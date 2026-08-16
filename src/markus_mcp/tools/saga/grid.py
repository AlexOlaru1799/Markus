"""Generic AdvancedControls grid client. Not exposed as employee write MCP."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from markus_mcp.tools.saga import protocol as saga_protocol
from markus_mcp.tools.saga import registry as saga_registry
from markus_mcp.tools.saga import schema as saga_schema
from markus_mcp.tools.saga import session as saga_session


WriteStyle = Literal["classic", "ex"]
Risk = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class GridColumn:
    name: str
    kind: str = "text"
    required: bool = False
    hidden: bool = False
    default_value: Any = None
    aliases: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class GridModel:
    table_name: str
    controller: str
    primary_key: str
    get_data_urls: tuple[str, ...]
    create_urls: tuple[str, ...]
    edit_urls: tuple[str, ...]
    delete_urls: tuple[str, ...]
    next_index_urls: tuple[str, ...] = ()
    is_master: bool = True
    is_detail: bool = False
    master_table: str | None = None
    selection_key: str | None = None
    columns: tuple[GridColumn, ...] = ()
    write_style: WriteStyle = "classic"
    risk: Risk = "medium"
    operation: str = ""

    @property
    def column_names(self) -> set[str]:
        return {column.name for column in self.columns}


def model_for(operation: str) -> GridModel:
    spec = saga_registry.require_screen(operation)
    catalog = saga_schema.catalog_for(spec.schema_id)
    columns: list[GridColumn] = []
    for item in catalog.get("columns") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        columns.append(
            GridColumn(
                name=name,
                kind=str(item.get("kind") or item.get("inputType") or "text"),
                required=bool(item.get("required") or item.get("required_on_create")),
                hidden=bool(item.get("hidden")),
                default_value=item.get("defaultValue"),
                aliases=tuple(item.get("aliases") or ()),
                description=str(item.get("description") or ""),
            )
        )
    controller = str(catalog.get("controller") or spec.route)
    is_detail = spec.operation.endswith("_detalii") or bool(catalog.get("is_detail"))
    return GridModel(
        table_name=spec.table,
        controller=controller,
        primary_key=spec.pk,
        get_data_urls=spec.get_data or tuple(catalog.get("actions", {}).get("get_data") or ()),
        create_urls=spec.create or tuple(catalog.get("actions", {}).get("create") or ()),
        edit_urls=spec.edit or tuple(catalog.get("actions", {}).get("edit") or ()),
        delete_urls=spec.delete or tuple(catalog.get("actions", {}).get("delete") or ()),
        next_index_urls=spec.next_index,
        is_master=not is_detail,
        is_detail=is_detail,
        master_table=catalog.get("master_table"),
        selection_key=catalog.get("selection_key") or spec.pk,
        columns=tuple(columns),
        write_style=spec.write_style,
        risk=spec.risk,
        operation=spec.operation,
    )


IDENTITY_FIELDS = ("Id", "ID", "Cod", "PK", "NrDoc")


def row_matches_pk(row: dict[str, Any], pk: str, *, primary_key: str) -> bool:
    """Match identity columns only — never Denumire / CodFiscal."""
    needle = str(pk or "").strip().casefold()
    if not needle or not isinstance(row, dict):
        return False
    names = (primary_key,) + IDENTITY_FIELDS
    seen: set[str] = set()
    for name in names:
        if not name or name in seen:
            continue
        seen.add(name)
        value = saga_protocol.row_get(row, name)
        if value and str(value).strip().casefold() == needle:
            return True
    return False


class SagaGrid:
    def __init__(self, model: GridModel):
        self.model = model

    @classmethod
    def for_operation(cls, operation: str) -> "SagaGrid":
        return cls(model_for(operation))

    def _preflight(self, page) -> dict[str, Any] | None:
        from markus_mcp.tools.saga import context as saga_context

        return saga_context.assert_writable(page, screen=self.model.operation)

    def _unknown(self, row: dict[str, Any]) -> list[str]:
        allowed = self.model.column_names
        if not allowed:
            return []
        return [str(key) for key in row if str(key) not in allowed]

    def list(
        self,
        page,
        *,
        skip: int = 0,
        batch_size: int = 50,
        master_id: str | None = None,
        keyword: str | None = None,
    ) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        if keyword:
            names = [column.name for column in self.model.columns if not column.hidden][:12]
            if names:
                extra["FilterColumns"] = names
        params = {
            "RequestSetup": saga_protocol.request_setup(
                skip=skip,
                batch_size=batch_size,
                keyword=keyword,
                master_id=master_id,
                **extra,
            )
        }
        last: dict[str, Any] = {"ok": False, "rows": [], "error": "No getData URL."}
        for path in self.model.get_data_urls:
            probed = saga_protocol.get_json(page, path, params=params)
            if not probed or not probed.get("ok"):
                last = probed or last
                continue
            body = probed.get("body")
            if not isinstance(body, (dict, list)):
                last = {**(probed or {}), "ok": False, "error": "GetData did not return JSON."}
                continue
            rows = saga_protocol.rows_from_payload(body)
            return {
                **probed,
                "rows": rows,
                "rows_count": saga_protocol.rows_count_from_payload(body),
                "ok": True,
            }
        return {**last, "rows": last.get("rows") or []}

    def get(self, page, pk: str) -> dict[str, Any] | None:
        key = str(pk or "").strip()
        if not key:
            return None
        attempts = (
            {"keyword": key, "batch_size": 50},
            {"keyword": None, "batch_size": 200},
        )
        for kwargs in attempts:
            fetched = self.list(page, skip=0, **kwargs)
            for row in fetched.get("rows") or []:
                if row_matches_pk(row, key, primary_key=self.model.primary_key):
                    return row
        return None

    def create(
        self,
        page,
        row: dict[str, Any],
        *,
        allow_choices: bool = False,
        uvf: Any = None,
    ) -> saga_protocol.SagaResponse:
        blocked = self._preflight(page)
        if blocked:
            return saga_protocol.SagaResponse(outcome="error", message=blocked["error"], raw=blocked)
        unknown = self._unknown(row)
        if unknown:
            return saga_protocol.SagaResponse(
                outcome="error",
                message=f"Unknown field(s): {', '.join(unknown)}",
                raw={"unknown_fields": unknown},
            )
        last = saga_protocol.SagaResponse(outcome="error", message="No create URL.")
        for path in self.model.create_urls:
            result = saga_protocol.post_with_handshake(
                page,
                path,
                row_data=row,
                style=self.model.write_style,
                allow_choices=allow_choices,
                operation="create",
                uvf=uvf,
            )
            last = result
            if result.ok:
                return result
            parsed = result.raw
            if isinstance(parsed, dict) and parsed.get("type") in ("Warning", "Choice", "Error"):
                break
        return last

    def update(
        self,
        page,
        pk: str,
        row: dict[str, Any],
        *,
        allow_choices: bool = False,
        uvf: Any = None,
    ) -> saga_protocol.SagaResponse:
        blocked = self._preflight(page)
        if blocked:
            return saga_protocol.SagaResponse(outcome="error", message=blocked["error"], raw=blocked)
        unknown = self._unknown(row)
        if unknown:
            return saga_protocol.SagaResponse(
                outcome="error",
                message=f"Unknown field(s): {', '.join(unknown)}",
                raw={"unknown_fields": unknown},
            )
        payload = dict(row)
        payload.setdefault(self.model.primary_key, pk)
        last = saga_protocol.SagaResponse(outcome="error", message="No edit URL.")
        for path in self.model.edit_urls:
            result = saga_protocol.post_with_handshake(
                page,
                path,
                row_data=payload,
                style=self.model.write_style,
                allow_choices=allow_choices,
                operation="edit",
                uvf=uvf,
            )
            last = result
            if result.ok:
                return result
        return last

    def delete(self, page, pk: str, *, allow_choices: bool = False) -> dict[str, Any]:
        blocked = self._preflight(page)
        if blocked:
            return blocked
        last: dict[str, Any] = {"ok": False, "error": "No delete URL."}
        for path in self.model.delete_urls:
            result = saga_protocol.delete_with_handshake(page, path, pk, allow_choices=allow_choices)
            last = result
            if result.get("ok"):
                return result
        return last

    def next_index(self, page, *, params: dict[str, str] | None = None) -> str:
        last_body: Any = None
        for path in self.model.next_index_urls:
            probed = saga_protocol.get_json(page, path, params=params)
            if not probed or not probed.get("ok"):
                continue
            body = probed.get("body")
            last_body = body
            if isinstance(body, (int, float)):
                return str(int(body)) if float(body).is_integer() else str(body)
            if isinstance(body, str) and body.strip():
                return body.strip()
            if isinstance(body, dict):
                for key in ("Cod", "cod", "status", "Status", "value", "Value", "nr", "NrDoc"):
                    value = body.get(key)
                    if value not in (None, ""):
                        return str(value).strip()
        return str(last_body).strip() if last_body not in (None, "") else ""

    def details(self, page, master_pk: str, detail_operation: str) -> dict[str, Any]:
        detail = SagaGrid.for_operation(detail_operation)
        return detail.list(page, skip=0, batch_size=200, master_id=master_pk)

    def create_detail(
        self,
        page,
        detail_operation: str,
        row: dict[str, Any],
        *,
        allow_choices: bool = False,
    ) -> saga_protocol.SagaResponse:
        return SagaGrid.for_operation(detail_operation).create(page, row, allow_choices=allow_choices)


def open_screen(page, route: str, *, markers: tuple[str, ...] = ()) -> dict[str, Any]:
    from urllib.parse import urljoin

    app_base = saga_session.app_base_url(page)
    url = urljoin(app_base.rstrip("/") + "/", route.lstrip("/"))
    current = (page.url or "").casefold()
    want = f"/sagac/{route.casefold()}"
    if want in current:
        return {"ok": True, "url": page.url, "via": "current"}
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    except Exception:
        try:
            page.goto(url, wait_until="commit", timeout=60_000)
        except Exception as exc:
            return {
                "ok": False,
                "error": f"Could not open {route}: {exc}",
                "url": page.url,
                "screenshot_path": saga_session._save_screenshot(page, f"saga-{route.lower()}-missing.png"),
            }
    page.wait_for_timeout(1_200)
    if markers:
        body = ""
        try:
            body = page.locator("body").inner_text(timeout=3_000)
        except Exception:
            pass
        blob = f"{body} {page.url or ''}".casefold()
        if not any(token.casefold() in blob for token in markers) and want not in (page.url or "").casefold():
            return {
                "ok": False,
                "error": f"Opened a page but {route} markers were not found.",
                "url": page.url,
                "screenshot_path": saga_session._save_screenshot(page, f"saga-{route.lower()}-missing.png"),
            }
    return {"ok": True, "url": page.url, "via": "route"}
