"""Rapoarte two-step download: SetDataRaport<X> then CreateRaport<X> on data-api."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from markus_mcp.paths import data_dir, host_data_dir
from markus_mcp.tools.saga import context as saga_context
from markus_mcp.tools.saga import exports as saga_exports
from markus_mcp.tools.saga import grid as saga_grid
from markus_mcp.tools.saga import protocol as saga_protocol
from markus_mcp.tools.saga import schema as saga_schema
from markus_mcp.tools.saga import session as saga_session


PERIOD_PACK = ("balanta", "jurnal_cumparari", "jurnal_vanzari")


def reports_dir() -> Path:
    path = data_dir() / "saga" / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _host(path: Path) -> str:
    try:
        return str(host_data_dir() / path.relative_to(data_dir()))
    except ValueError:
        return str(path)


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def saga_date(value: str) -> str:
    text = (value or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        year, month, day = text[:10].split("-")
        return f"{day}.{month}.{year}"
    return text


def resolve_report(name: str) -> tuple[str, dict[str, Any]] | None:
    wanted = saga_schema.normalize_key(name)
    if not wanted:
        return None
    if wanted in {"period_pack", "period-pack", "pachet", "pachet_perioada"}:
        return "period_pack", {"title": "Period pack", "period_pack_bundle": True}
    catalog = saga_schema.reports_catalog()
    for report_id, entry in catalog.items():
        if not isinstance(entry, dict):
            continue
        aliases = {saga_schema.normalize_key(report_id), saga_schema.normalize_key(str(entry.get("title") or ""))}
        for alias in entry.get("aliases") or ():
            aliases.add(saga_schema.normalize_key(str(alias)))
        if wanted in aliases:
            return report_id, entry
    return None


def list_reports() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for report_id, entry in saga_schema.reports_catalog().items():
        if not isinstance(entry, dict):
            continue
        items.append(
            {
                "name": report_id,
                "title": entry.get("title") or report_id,
                "captured": entry.get("captured") is not False,
                "provisional": bool(entry.get("provisional")),
                "period_pack": bool(entry.get("period_pack")),
                "usage": entry.get("usage") or "",
                "filters": saga_schema.exposed_columns(f"report:{report_id}") if entry.get("captured") is not False else [],
            }
        )
    items.sort(key=lambda item: str(item.get("name") or ""))
    return {
        "ok": True,
        "count": len(items),
        "reports": items,
        "period_pack": list(PERIOD_PACK),
        "details": (
            "Call saga_run_report(name, filters) with a report id. "
            "name=period_pack runs balanță + jurnale for the working interval. "
            "captured=false reports need a print-modal auxiliar capture before they can run."
        ),
    }


def report_api_origin(page) -> str:
    raw = ""
    try:
        raw = page.evaluate(
            """() => {
              const body = document.body;
              if (!body) return "";
              const ds = body.dataset || {};
              return ds.api || body.getAttribute("data-api") || "";
            }"""
        ) or ""
    except Exception:
        raw = ""
    text = str(raw).strip()
    app = saga_session.app_base_url(page).rstrip("/")
    if not text:
        return app
    if text.startswith("http://") or text.startswith("https://"):
        return text.rstrip("/")
    return urljoin(app + "/", text.lstrip("/")).rstrip("/")


def _filename_from_headers(headers: dict[str, Any], fallback: str) -> str:
    blob = str(headers.get("content-disposition") or headers.get("Content-Disposition") or "")
    match = re.search(r"filename\*?=(?:UTF-8''|\"')?([^\";]+)", blob, flags=re.I)
    if match:
        name = match.group(1).strip().strip("\"'")
        if name:
            return Path(name).name
    return fallback


def _fill_period(fields: dict[str, str], snapshot: dict[str, Any]) -> dict[str, str]:
    out = dict(fields)
    start = snapshot.get("interval_start")
    end = snapshot.get("interval_end")
    if start and "DataStart" not in out:
        out["DataStart"] = saga_date(str(start))
    if end and "DataStop" not in out:
        out["DataStop"] = saga_date(str(end))
    for key, value in list(out.items()):
        out[key] = saga_date(value) if key.casefold().startswith("data") or "date" in key.casefold() else value
    return out


def run_report(
    name: str,
    *,
    filters: dict[str, Any] | str | None = None,
    format: str = "pdf",
    accounts: str | None = None,
) -> dict[str, Any]:
    wanted = (name or "").strip()
    if not wanted:
        return list_reports()
    resolved = resolve_report(wanted)
    if resolved is None:
        listed = list_reports()
        return {
            "ok": False,
            "error": f"Unknown report '{name}'.",
            "reports": listed.get("reports"),
        }
    report_id, spec = resolved
    if report_id == "period_pack":
        return run_period_pack(filters=filters, format=format, accounts=accounts)
    if spec.get("captured") is False:
        return {
            "ok": False,
            "error": (
                f"Report '{report_id}' has no captured auxiliar/setter yet (U6). "
                "A print-modal probe must be reviewed before this name can download a file."
            ),
            "report": report_id,
            "title": spec.get("title"),
            "usage": spec.get("usage"),
        }

    user_filters = _as_dict(filters)
    kind = (format or "pdf").strip().casefold()
    if kind in {"excel", "xls"}:
        kind = "xlsx"
    if kind not in {"pdf", "xlsx"}:
        kind = "pdf"

    def _run(browser_page):
        from markus_mcp.tools.saga import partners as saga_partners

        page = saga_partners._ready(browser_page)
        snapshot = saga_context.snapshot(page)
        mapped = saga_schema.map_fields(f"report:{report_id}", user_filters)
        fields = _fill_period(mapped.fields, snapshot)
        if accounts and "Cont" not in fields:
            fields["Cont"] = str(accounts).strip()
        warning = snapshot.get("closed_period_warning")
        opened = saga_grid.open_screen(page, str(spec.get("route") or "Rapoarte"))
        if not opened.get("ok"):
            return {"ok": False, "report": report_id, **opened}
        saga_session.clear_capture()
        origin = report_api_origin(page)
        title = fields.get("Titlu") or str(spec.get("title") or report_id)
        creators = spec.get("creators") if isinstance(spec.get("creators"), dict) else {}
        creator = str(creators.get(kind) or creators.get("pdf") or spec.get("creator") or "").strip()
        if not creator:
            return {
                "ok": False,
                "error": f"Report '{report_id}' has no creator URL for format={kind}.",
                "report": report_id,
            }
        mode = str(spec.get("mode") or "set_then_create")
        setter_result: dict[str, Any] | None = None
        if mode != "direct":
            setter = str(spec.get("setter") or "").strip()
            if not setter:
                return {"ok": False, "error": f"Report '{report_id}' has no setter URL.", "report": report_id}
            form = {
                "Filtru": json.dumps(fields, ensure_ascii=False, separators=(",", ":")),
                "Titlu": title,
                "Tip": "Export",
                "SortColumn": user_filters.get("SortColumn") or "",
                "SortMode": user_filters.get("SortMode") or "",
            }
            setter_result = saga_protocol.ajax(page, "POST", setter, form=form, timeout=120_000)
            if not setter_result.get("ok_http"):
                return {
                    "ok": False,
                    "error": (
                        f"SetDataRaport failed HTTP {setter_result.get('status')} "
                        f"on {setter_result.get('endpoint')}."
                    ),
                    "report": report_id,
                    "setter": setter_result,
                    "mapped_filters": fields,
                    "unknown_filters": mapped.unknown,
                    "api_origin": origin,
                    "closed_period_warning": warning,
                    "url": page.url,
                    "screenshot_path": saga_session._save_screenshot(page, "saga-report-setter-failed.png"),
                    "capture_path": saga_session._dump_capture("network-run-report.json"),
                }
        raw = saga_protocol.fetch_raw(
            page,
            "GET",
            creator,
            params={"Filtru": "Export", "Descarca": "true"},
            origin=origin,
            timeout=180_000,
        )
        sniffed = saga_exports.sniff_bytes(raw.get("body") or b"")
        if sniffed not in {"pdf", "xlsx", "xls"}:
            preview = (raw.get("body") or b"")[:300]
            try:
                preview_text = preview.decode("utf-8", errors="replace")
            except Exception:
                preview_text = str(preview)
            return {
                "ok": False,
                "error": (
                    "CreateRaport did not return a real PDF/XLS file "
                    f"(sniffed {sniffed or 'unknown'}). HTML error pages are not saved."
                ),
                "report": report_id,
                "creator": raw.get("endpoint"),
                "status": raw.get("status"),
                "content_type": raw.get("content_type"),
                "sniffed": sniffed,
                "preview": preview_text,
                "setter": setter_result,
                "mapped_filters": fields,
                "unknown_filters": mapped.unknown,
                "api_origin": origin,
                "closed_period_warning": warning,
                "url": page.url,
                "screenshot_path": saga_session._save_screenshot(page, "saga-report-create-failed.png"),
                "capture_path": saga_session._dump_capture("network-run-report.json"),
            }
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        fallback = f"{report_id}-{stamp}.{sniffed}"
        filename = _filename_from_headers(raw.get("headers") or {}, fallback)
        if "." not in filename:
            filename = f"{filename}.{sniffed}"
        dest = reports_dir() / filename
        if dest.exists():
            dest = reports_dir() / fallback
        dest.write_bytes(raw["body"])
        return {
            "ok": True,
            "report": report_id,
            "title": spec.get("title") or report_id,
            "path": _host(dest),
            "resolved_path": str(dest),
            "filename": dest.name,
            "kind": sniffed,
            "size_bytes": dest.stat().st_size,
            "format_requested": kind,
            "provisional": bool(spec.get("provisional")),
            "mapped_filters": fields,
            "unknown_filters": mapped.unknown,
            "api_origin": origin,
            "setter": (setter_result or {}).get("endpoint") if setter_result else None,
            "creator": raw.get("endpoint"),
            "closed_period_warning": warning,
            "interval_start": snapshot.get("interval_start"),
            "interval_end": snapshot.get("interval_end"),
            "url": page.url,
            "capture_path": saga_session._dump_capture("network-run-report.json"),
        }

    return saga_session.run_in_session(_run)


def run_period_pack(
    *,
    filters: dict[str, Any] | str | None = None,
    format: str = "pdf",
    accounts: str | None = None,
) -> dict[str, Any]:
    names = list(PERIOD_PACK)
    extra = [part.strip() for part in str(accounts or "").split(",") if part.strip()]
    results: list[dict[str, Any]] = []
    for report_id in names:
        results.append(run_report(report_id, filters=filters, format=format))
    for account in extra:
        results.append(run_report("fise_conturi", filters=filters, format=format, accounts=account))
    ok = all(item.get("ok") for item in results) if results else False
    return {
        "ok": ok,
        "report": "period_pack",
        "count": len(results),
        "results": results,
        "paths": [item.get("path") for item in results if item.get("ok") and item.get("path")],
        "details": (
            "Period pack runs balanță + jurnal cumpărări + jurnal vânzări. "
            "Pass accounts=401,4111,… to also pull fișe conturi. "
            "Per-report PDF/XLS success on a test firm is still required before ticking §13.4 feature boxes."
        ),
    }
