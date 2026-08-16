"""Live probe of a SAGA AdvancedControls screen (`tableModel` / toolbar / sample rows)."""

from __future__ import annotations

from typing import Any

from markus_mcp.tools.saga import grid as saga_grid
from markus_mcp.tools.saga import protocol as saga_protocol
from markus_mcp.tools.saga import registry as saga_registry
from markus_mcp.tools.saga import session as saga_session


_PROBE_JS = """(wanted) => {
  const out = {
    tables: [],
    tableName: wanted || null,
    hasGetTable: typeof getTable === 'function',
    tabID: (typeof tabID !== 'undefined' && tabID != null) ? String(tabID) : null,
  };
  const names = [];
  for (const el of document.querySelectorAll('[id^="containerAdvancedTable_"]')) {
    names.push(el.id.replace('containerAdvancedTable_', ''));
  }
  for (const el of document.querySelectorAll('[id^="tableMain_"]')) {
    const name = el.id.replace('tableMain_', '');
    if (!names.includes(name)) names.push(name);
  }
  out.domTables = names;
  const pick = wanted && names.includes(wanted) ? wanted : (wanted || names[0] || null);
  out.picked = pick;

  const dumpTable = (name) => {
    const info = { name, hasTable: false };
    let table = null;
    try {
      table = (typeof getTable === 'function') ? getTable(name) : null;
    } catch (e) {
      info.error = String(e);
      return info;
    }
    info.hasTable = !!table;
    if (!table) return info;
    const model = table.tableModel || table.TableModel || table.model || null;
    if (model) {
      info.tableModel = {
        tableName: model.tableName || model.TableName || name,
        controllerName: model.controllerName || model.ControllerName || null,
        primaryKey: model.primaryKey || model.PrimaryKey || null,
        detailSetup: model.detailSetup || model.DetailSetup || null,
        actionsURLs: (model.tableConfig && model.tableConfig.actionsURLs)
          || (model.actionsURLs) || null,
        columns: (model.tableColumns || []).map((col) => ({
          name: col.name || col.Name,
          inputType: col.inputType || col.InputType,
          selectModel: col.selectModel || col.SelectModel,
          defaultValue: col.defaultValue,
          hidden: !!col.hidden,
          lock: !!col.lock,
          caption: col.caption || col.Caption || null,
        })),
      };
    }
    try {
      if (table.GetRequestSetup) info.requestSetup = table.GetRequestSetup();
    } catch (e) {}
    try {
      if (table.GetVirtualData) {
        const rows = table.GetVirtualData() || [];
        info.rowCount = rows.length;
        info.sample = rows[0] || null;
        info.sampleKeys = rows[0] ? Object.keys(rows[0]) : [];
      }
    } catch (e) {}
    const inputs = [...document.querySelectorAll(
      `#containerAdvancedTable_${name} input[class*="rowField"], #tableMain_${name} input[class*="rowField"]`
    )].map((el) => {
      const cls = [...el.classList].find((c) => c.startsWith('rowFieldInput_'));
      return cls ? cls.replace('rowFieldInput_', '') : null;
    }).filter(Boolean);
    info.inputFields = [...new Set(inputs)];
    info.toolbar = {
      add: !!document.querySelector(`.buttonOperationAdd_${name}`),
      save: !!document.querySelector(`.buttonOperationSave_${name}`),
      edit: !!document.querySelector(`.buttonOperationEdit_${name}`),
      delete: !!document.querySelector(`.buttonOperationDelete_${name}`),
    };
    return info;
  };

  if (pick) out.primary = dumpTable(pick);
  out.tables = names.map(dumpTable);
  return out;
}"""


def probe_screen(page, route: str, table: str | None = None) -> dict[str, Any]:
    """Navigate to `route` and capture tableModel / sample keys. Developer onboarding only."""
    saga_session.clear_capture()
    opened = saga_grid.open_screen(page, route)
    if not opened.get("ok"):
        return {"ok": False, **opened}

    wanted = table
    if not wanted:
        spec = saga_registry.get_screen(route)
        if spec is not None:
            wanted = spec.table
    try:
        live = page.evaluate(_PROBE_JS, wanted)
    except Exception as exc:
        live = {"error": str(exc)}

    get_data_sample = None
    spec = saga_registry.get_screen(route) or saga_registry.get_screen(wanted or "")
    if spec and spec.get_data:
        probed = saga_protocol.get_json(
            page,
            spec.get_data[0],
            params={"RequestSetup": saga_protocol.request_setup(skip=0, batch_size=3)},
        )
        if probed and probed.get("ok"):
            rows = saga_protocol.rows_from_payload(probed.get("body"))
            get_data_sample = {
                "endpoint": probed.get("endpoint"),
                "status": probed.get("status"),
                "row_count": len(rows),
                "sample": rows[0] if rows else None,
                "sample_keys": sorted((rows[0] or {}).keys()) if rows else [],
            }

    return {
        "ok": True,
        "route": route,
        "url": page.url,
        "live": live,
        "get_data": get_data_sample,
        "screenshot_path": saga_session._save_screenshot(page, f"saga-probe-{route.lower()}.png"),
        "capture_path": saga_session._dump_capture(f"network-probe-{route.lower()}.json"),
        "note": (
            "Writes still use the committed schemas/*.json catalog until a human reviews "
            "this probe and updates the snapshot."
        ),
    }


def probe_registered(page, operation: str) -> dict[str, Any]:
    spec = saga_registry.get_screen(operation)
    if spec is None:
        return {
            "ok": False,
            "error": f"Unknown screen '{operation}'.",
            "screens": saga_registry.list_operation_ids(),
        }
    return probe_screen(page, spec.route, table=spec.table)


def live_column_names(probe: dict[str, Any]) -> list[str]:
    live = probe.get("live") if isinstance(probe.get("live"), dict) else probe
    primary = live.get("primary") if isinstance((live or {}).get("primary"), dict) else {}
    model = primary.get("tableModel") if isinstance(primary.get("tableModel"), dict) else {}
    names: list[str] = []
    for column in model.get("columns") or []:
        if not isinstance(column, dict):
            continue
        name = str(column.get("name") or column.get("Name") or "").strip()
        if name:
            names.append(name)
    if not names:
        for key in primary.get("sampleKeys") or live.get("sampleKeys") or []:
            text = str(key).strip()
            if text:
                names.append(text)
    return names


def diff_probe(operation: str, probe: dict[str, Any]) -> dict[str, Any]:
    """Compare a saved probe (or live dump) to schemas/<operation>.json. No Playwright."""
    from markus_mcp.tools.saga import schema as saga_schema

    catalog = set(saga_schema.column_map(operation))
    live = set(live_column_names(probe))
    missing_in_catalog = sorted(live - catalog)
    extra_in_catalog = sorted(catalog - live)
    return {
        "ok": not missing_in_catalog,
        "operation": operation,
        "matched": sorted(live & catalog),
        "missing_in_catalog": missing_in_catalog,
        "extra_in_catalog": extra_in_catalog,
        "details": (
            "Live columns missing from schemas/*.json must be reviewed before writes. "
            "Extra catalog columns are allowed (hidden/lock fields, aliases)."
        ),
    }
