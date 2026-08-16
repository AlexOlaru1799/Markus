from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from markus_mcp.paths import data_dir, host_data_dir
from markus_mcp.tools.saga import iesiri_valuta as fx
from markus_mcp.tools.saga import session as saga_session


DATA_DIR = data_dir()
HOST_DATA_DIR = host_data_dir()

CURRENCY_CODES = (
    "EUR",
    "USD",
    "GBP",
    "CHF",
    "RON",
    "HUF",
    "PLN",
    "CZK",
    "SEK",
    "NOK",
    "DKK",
    "BGN",
    "TRY",
    "CAD",
    "AUD",
)

_INVOICE_NO_RE = re.compile(
    r"(?i)\b(?:invoice\s*(?:no\.?|number|#)|factura\s*(?:nr\.?|number)|nr\.?\s*(?:factura|doc(?:ument)?)"
    r"|rechnungsnr\.?|num[eé]ro\s*(?:de\s*)?facture|document\s*(?:no\.?|number))\s*[:#]?\s*"
    r"([A-Z0-9][A-Z0-9\-/\.]{1,40})"
)
_DATE_LABEL_RE = re.compile(
    r"(?i)\b(?:invoice\s*date|date\s*(?:of\s*)?invoice|data\s*(?:facturii|document)|issue\s*date|"
    r"rechnungsdatum|date\s*facture|dated?)\s*[:#]?\s*([0-9]{1,4}[.\-/][0-9]{1,2}[.\-/][0-9]{1,4})"
)
_DUE_LABEL_RE = re.compile(
    r"(?i)\b(?:due\s*date|payment\s*due|scadent(?:a|ă)?|data\s*scadent|"
    r"fälligkeitsdatum|date\s*d['’]?échéance)\s*[:#]?\s*"
    r"([0-9]{1,4}[.\-/][0-9]{1,2}[.\-/][0-9]{1,4})"
)
_CURRENCY_RE = re.compile(
    r"(?i)\b(?:currency|valuta|moned[aă]|deviza|währung|devise)\s*[:#]?\s*([A-Z]{3})\b"
    r"|(?<![A-Z])(EUR|USD|GBP|CHF|RON|HUF|PLN|CZK)(?![A-Z])"
)
_VAT_RATE_RE = re.compile(
    r"(?i)\b(?:vat|tva|mwst|ust|t\.?\s*v\.?\s*a\.?)\s*(?:rate|procent|%)?\s*[:#]?\s*(\d{1,2}(?:[.,]\d{1,2})?)\s*%?"
)
_CUSTOMER_RE = re.compile(
    r"(?i)\b(?:bill\s*to|sold\s*to|customer|client|buyer|cump[aă]r[aă]tor|destinatar|"
    r"rechnungsempfänger|facturé\s*à)\s*[:#]?\s*\n?\s*([A-Z0-9][^\n]{2,80})"
)
_LINE_ROW_RE = re.compile(
    r"(?m)^\s*(?:(\d+)\s*[.)]\s+)?"
    r"(.+?)\s+"
    r"(\d+(?:[.,]\d+)?)\s+"
    r"([A-Za-z]{1,6}|BUC|PCS?|HRS?|KG|M|L|SET|EA)\s+"
    r"(\d+(?:[.,]\d+)?)"
    r"(?:\s+(\d+(?:[.,]\d+)?))?"
    r"\s*(%)?\s*$"
)
_LINE_ROW_LOOSE_RE = re.compile(
    r"(?m)^\s*(?:(\d+)\s*[.)]\s+)?(.+?)\s+(\d+(?:[.,]\d+)?)\s+"
    r"(BUC|PCS?|HRS?|KG|M|L|SET|EA|Hour|Hours|pcs|buc)\s+"
    r"(\d+(?:[.,]\d+)?)"
    r"(?:\s+(\d+(?:[.,]\d+)?))?"
    r"\s*(%)?\s*$",
    re.I,
)
_SIMPLE_AMOUNT_LINE_RE = re.compile(
    r"(?m)^\s*(.+?)\s+(\d+(?:[.,]\d+)?)\s+(\d+(?:[.,]\d{2}))\s+(\d+(?:[.,]\d{2}))\s*$"
)


def _resolve_under_data_dir(path: Path) -> Path:
    """If path is under HOST_DATA_DIR, also try the equivalent under DATA_DIR."""
    try:
        relative = path.resolve().relative_to(HOST_DATA_DIR.resolve())
        return DATA_DIR / relative
    except Exception:
        return path


def resolve_pdf_path(pdf_path: str) -> dict[str, Any]:
    """Resolve a PDF path on the local filesystem."""
    raw = (pdf_path or "").strip()
    if not raw:
        return {
            "ok": False,
            "error": "pdf_path is required.",
            "hint": "Pass an absolute PDF path, or place the file under ~/.markus/data/invoices/.",
        }

    candidates: list[Path] = []
    given = Path(raw).expanduser()
    candidates.append(given)
    candidates.append(_resolve_under_data_dir(given))
    if not given.is_absolute():
        candidates.append(DATA_DIR / given)
        candidates.append(DATA_DIR / "invoices" / given.name)
        candidates.append(HOST_DATA_DIR / given)
        candidates.append(HOST_DATA_DIR / "invoices" / given.name)

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            if candidate.suffix.casefold() != ".pdf":
                return {"ok": False, "error": f"File is not a PDF: {candidate}"}
            return {"ok": True, "path": candidate, "path_str": str(candidate)}

    return {
        "ok": False,
        "error": f"PDF not found: {raw}",
        "tried": [str(p) for p in candidates[:8]],
        "hint": (
            "Pass an absolute path to the PDF, or copy it into ~/.markus/data/invoices/ "
            "and pass the filename or that path."
        ),
    }


def extract_pdf_text(path: Path) -> dict[str, Any]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        return {
            "ok": False,
            "error": f"pypdf is not installed: {exc}",
            "hint": "Rebuild the Markus image so pypdf is available.",
        }

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        return {"ok": False, "error": f"Could not open PDF: {exc}"}

    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    text = "\n".join(pages).strip()
    return {
        "ok": True,
        "page_count": len(reader.pages),
        "char_count": len(text),
        "text": text,
        "empty": len(text) < 40,
    }


def _normalize_number(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(" ", "").replace("\u00a0", "")
    if "," in text and "." in text:
        # 1.234,56 → 1234.56 ; 1,234.56 → 1234.56
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        text = text.replace(",", ".") if len(parts[-1]) in (1, 2) else text.replace(",", "")
    try:
        number = float(text)
    except ValueError:
        return None
    if number.is_integer():
        return str(int(number))
    return f"{number:.4f}".rstrip("0").rstrip(".")


def _to_saga_date(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip()
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%Y.%m.%d", "%d.%m.%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%d.%m.%Y")
        except ValueError:
            continue
    # 9.8.2026
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", raw)
    if m:
        d, mo, y = m.groups()
        return f"{int(d):02d}.{int(mo):02d}.{y}"
    return None


def _pick_currency(text: str) -> str | None:
    m = _CURRENCY_RE.search(text)
    if m:
        code = (m.group(1) or m.group(2) or "").upper()
        if code in CURRENCY_CODES and code != "RON":
            return code
        if code in CURRENCY_CODES:
            return code
    counts = {code: len(re.findall(rf"\b{code}\b", text)) for code in CURRENCY_CODES}
    ranked = sorted(((n, code) for code, n in counts.items() if n > 0), reverse=True)
    if not ranked:
        return None
    # Prefer non-RON for FX invoices when both appear.
    for _, code in ranked:
        if code != "RON":
            return code
    return ranked[0][1]


def _heuristic_lines(text: str) -> list[dict[str, str]]:
    lines: list[dict[str, str]] = []

    def _append(denumire: str, qty: str | None, um: str, price: str | None, vat: str | None) -> None:
        if not denumire or not qty or not price:
            return
        if any(token in denumire.casefold() for token in ("total", "subtotal", "tva", "vat", "amount due")):
            return
        unit = (um or "BUC").upper()
        if unit in {"PC", "PCS", "EA", "EACH", "HOUR", "HOURS"}:
            unit = "BUC" if unit in {"PC", "PCS", "EA", "EACH"} else "ORA"
        item: dict[str, str] = {
            "Denumire": denumire[:200],
            "Cantitate": qty,
            "UM": unit,
            "PretUnitarValuta": price,
        }
        if vat is not None:
            item["TVA_ART"] = vat
        lines.append(item)

    for match in _LINE_ROW_RE.finditer(text):
        extra = _normalize_number(match.group(6)) if match.group(6) else None
        vat = extra if match.group(7) else None
        _append(
            (match.group(2) or "").strip(" -|\t"),
            _normalize_number(match.group(3)),
            match.group(4) or "BUC",
            _normalize_number(match.group(5)),
            vat,
        )

    if not lines:
        for match in _LINE_ROW_LOOSE_RE.finditer(text):
            extra = _normalize_number(match.group(6)) if match.group(6) else None
            vat = extra if match.group(7) else None
            _append(
                (match.group(2) or "").strip(" -|\t"),
                _normalize_number(match.group(3)),
                match.group(4) or "BUC",
                _normalize_number(match.group(5)),
                vat,
            )

    if lines:
        return lines

    # Fallback: description + qty + unit price + line total
    for match in _SIMPLE_AMOUNT_LINE_RE.finditer(text):
        denumire = (match.group(1) or "").strip(" -|\t")
        qty = _normalize_number(match.group(2))
        price = _normalize_number(match.group(3))
        if not denumire or not qty or not price:
            continue
        low = denumire.casefold()
        if any(token in low for token in ("total", "subtotal", "invoice", "factura", "vat", "tva")):
            continue
        if len(denumire) < 3:
            continue
        lines.append(
            {
                "Denumire": denumire[:200],
                "Cantitate": qty,
                "UM": "BUC",
                "PretUnitarValuta": price,
            }
        )
        if len(lines) >= 20:
            break
    return lines


def parse_invoice_text_heuristic(text: str) -> dict[str, Any]:
    header: dict[str, str] = {}
    warnings: list[str] = []

    inv = _INVOICE_NO_RE.search(text)
    if inv:
        header["NrDoc"] = inv.group(1).strip()

    date_m = _DATE_LABEL_RE.search(text)
    saga_date = _to_saga_date(date_m.group(1) if date_m else None)
    if saga_date:
        header["Data"] = saga_date
    else:
        # first date-looking token
        loose = re.search(r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{2}-\d{2})\b", text)
        saga_date = _to_saga_date(loose.group(1) if loose else None)
        if saga_date:
            header["Data"] = saga_date
            warnings.append("Invoice date inferred from first date-like token.")

    due_m = _DUE_LABEL_RE.search(text)
    due = _to_saga_date(due_m.group(1) if due_m else None)
    if due:
        header["Scadent"] = due

    currency = _pick_currency(text)
    if currency:
        header["Valuta"] = currency
    else:
        warnings.append("Currency not found in PDF text.")

    customer = _CUSTOMER_RE.search(text)
    if customer:
        name = re.sub(r"\s+", " ", customer.group(1)).strip(" ,;")
        if name:
            header["Client"] = name[:120]

    vat_m = _VAT_RATE_RE.search(text)
    default_vat = _normalize_number(vat_m.group(1) if vat_m else None)

    lines = _heuristic_lines(text)
    if default_vat:
        for line in lines:
            line.setdefault("TVA_ART", default_vat)
    if not lines:
        warnings.append("No line items detected by heuristics; fill lines manually or enable LLM extraction.")

    return {
        "ok": True,
        "method": "heuristic",
        "header": header,
        "lines": lines,
        "warnings": warnings,
        "default_vat": default_vat,
    }


def _llm_enabled() -> bool:
    return bool(os.getenv("MARKUS_LLM_API_KEY") or os.getenv("OPENAI_API_KEY"))


def _llm_extract(text: str) -> dict[str, Any]:
    api_key = os.getenv("MARKUS_LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    base = (os.getenv("MARKUS_LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("MARKUS_LLM_MODEL") or "gpt-4o-mini"
    if not api_key:
        return {"ok": False, "error": "No MARKUS_LLM_API_KEY / OPENAI_API_KEY configured."}

    schema_hint = {
        "header": {
            "NrDoc": "invoice number",
            "Data": "dd.mm.yyyy",
            "Scadent": "dd.mm.yyyy or null",
            "Client": "customer name",
            "Cod": "customer code if present else null",
            "Valuta": "ISO currency e.g. EUR",
            "InformatiiSuplimentare": "optional notes",
        },
        "lines": [
            {
                "Denumire": "item name",
                "Cod": "sku optional",
                "Cantitate": "number as string",
                "UM": "unit",
                "PretUnitarValuta": "unit price FX",
                "TVA_ART": "vat percent",
            }
        ],
        "warnings": ["string"],
    }
    system = (
        "Extract a foreign-currency sales invoice into JSON for Romanian SAGA IesiriValuta. "
        "Return ONLY valid JSON matching the schema. Dates must be dd.mm.yyyy. "
        "Use decimal point for numbers as strings. Ignore RON totals if a foreign currency is present. "
        "Do not invent line items that are not in the text."
    )
    user = (
        "Schema example:\n"
        f"{json.dumps(schema_hint, ensure_ascii=False)}\n\n"
        "Invoice text:\n"
        f"{text[:12000]}"
    )
    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        return {"ok": False, "error": f"LLM HTTP {exc.code}: {detail}"}
    except Exception as exc:
        return {"ok": False, "error": f"LLM request failed: {exc}"}

    try:
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except Exception as exc:
        return {"ok": False, "error": f"LLM returned unparseable content: {exc}", "raw": body}

    header_raw = parsed.get("header") if isinstance(parsed, dict) else {}
    lines_raw = parsed.get("lines") if isinstance(parsed, dict) else []
    warnings = list(parsed.get("warnings") or []) if isinstance(parsed, dict) else []

    header: dict[str, str] = {}
    if isinstance(header_raw, dict):
        mapped, unknown = fx._map_fields(header_raw, "iesiri_valuta")
        header = mapped
        if unknown:
            warnings.append(f"LLM unknown header fields ignored: {', '.join(unknown)}")
        if header.get("Data"):
            normalized = _to_saga_date(header["Data"])
            if normalized:
                header["Data"] = normalized
        if header.get("Scadent"):
            normalized = _to_saga_date(header["Scadent"])
            if normalized:
                header["Scadent"] = normalized

    lines: list[dict[str, str]] = []
    if isinstance(lines_raw, list):
        for idx, line in enumerate(lines_raw):
            if not isinstance(line, dict):
                continue
            mapped, unknown = fx._map_fields(line, "iesiri_valuta_detalii")
            if unknown:
                warnings.append(f"LLM unknown line[{idx}] fields ignored: {', '.join(unknown)}")
            for key in ("Cantitate", "PretUnitarValuta", "TVA_ART", "ValoareValuta"):
                if key in mapped:
                    num = _normalize_number(mapped[key])
                    if num is not None:
                        mapped[key] = num
            if mapped:
                lines.append(mapped)

    return {
        "ok": True,
        "method": "llm",
        "model": model,
        "header": header,
        "lines": lines,
        "warnings": warnings,
    }


def _apply_defaults(
    header: dict[str, str],
    lines: list[dict[str, str]],
    defaults: dict[str, Any] | None,
) -> tuple[dict[str, str], list[dict[str, str]], list[str]]:
    warnings: list[str] = []
    defaults = defaults or {}
    header_out = dict(header)
    lines_out = [dict(line) for line in lines]

    header_defaults, unknown_h = fx._map_fields(
        {k: v for k, v in defaults.items() if k.casefold() not in {"cont", "um", "tva_art", "tva", "cod_art"}},
        "iesiri_valuta",
    )
    for key, value in header_defaults.items():
        if key not in header_out or not header_out[key]:
            header_out[key] = value
            warnings.append(f"Applied default header.{key}={value}")

    cont = str(defaults.get("Cont") or defaults.get("cont") or "").strip()
    um = str(defaults.get("UM") or defaults.get("um") or "").strip()
    tva = _normalize_number(str(defaults.get("TVA_ART") or defaults.get("tva_art") or defaults.get("tva") or ""))
    for line in lines_out:
        if cont and not line.get("Cont"):
            line["Cont"] = cont
        if um and not line.get("UM"):
            line["UM"] = um
        if tva and not line.get("TVA_ART"):
            line["TVA_ART"] = tva

    if cont and lines_out:
        warnings.append(f"Applied default Cont={cont} on lines missing Cont.")
    if unknown_h:
        warnings.append(f"Unknown defaults ignored: {', '.join(unknown_h)}")
    return header_out, lines_out, warnings


def _missing_for_create(header: dict[str, str], lines: list[dict[str, str]]) -> list[str]:
    missing: list[str] = []
    if not header.get("Client") and not header.get("Cod"):
        missing.append("header.Client or header.Cod")
    if not header.get("Valuta"):
        missing.append("header.Valuta")
    if not header.get("Data"):
        missing.append("header.Data")
    if not lines:
        missing.append("lines")
    for idx, line in enumerate(lines):
        if not line.get("Cont"):
            missing.append(f"lines[{idx}].Cont")
        if not line.get("PretUnitarValuta") and not line.get("ValoareValuta"):
            missing.append(f"lines[{idx}].PretUnitarValuta")
        if not line.get("Denumire") and not line.get("Cod") and not line.get("Cod_Art"):
            missing.append(f"lines[{idx}].Denumire")
    return missing


def parse_fx_invoice_pdf(
    pdf_path: str,
    *,
    defaults: dict[str, Any] | None = None,
    use_llm: bool | None = None,
) -> dict[str, Any]:
    """
    Read a PDF invoice and map it to saga_add_iesiri_valuta header/lines.

    defaults: optional values applied when PDF omits them (especially Cont, Cod, Client, TVA_ART, UM).
    use_llm: True/False to force; default auto when MARKUS_LLM_API_KEY/OPENAI_API_KEY is set.
    """
    resolved = resolve_pdf_path(pdf_path)
    if not resolved.get("ok"):
        return resolved

    path: Path = resolved["path"]
    extracted = extract_pdf_text(path)
    if not extracted.get("ok"):
        return extracted
    if extracted.get("empty"):
        return {
            "ok": False,
            "error": "PDF has little or no extractable text (likely scanned). OCR is not enabled.",
            "pdf_path": str(path),
            "host_pdf_path": saga_session._host_path(path),
            "page_count": extracted.get("page_count"),
            "hint": "Use a text-based PDF, or paste/override fields manually.",
        }

    text = extracted["text"]
    want_llm = _llm_enabled() if use_llm is None else bool(use_llm)

    heuristic = parse_invoice_text_heuristic(text)
    llm_result: dict[str, Any] | None = None
    chosen = heuristic
    if want_llm:
        llm_result = _llm_extract(text)
        if llm_result.get("ok") and (llm_result.get("header") or llm_result.get("lines")):
            # Prefer LLM fields; fill gaps from heuristics.
            header = dict(heuristic.get("header") or {})
            header.update({k: v for k, v in (llm_result.get("header") or {}).items() if v})
            lines = llm_result.get("lines") or heuristic.get("lines") or []
            if not lines:
                lines = heuristic.get("lines") or []
            warnings = list(heuristic.get("warnings") or []) + list(llm_result.get("warnings") or [])
            chosen = {
                "ok": True,
                "method": "llm+heuristic",
                "header": header,
                "lines": lines,
                "warnings": warnings,
                "llm_model": llm_result.get("model"),
            }
        else:
            chosen = {
                **heuristic,
                "warnings": list(heuristic.get("warnings") or [])
                + [f"LLM extraction skipped/failed: {(llm_result or {}).get('error')}"],
            }

    header, lines, default_warnings = _apply_defaults(
        dict(chosen.get("header") or {}),
        list(chosen.get("lines") or []),
        defaults,
    )
    warnings = list(chosen.get("warnings") or []) + default_warnings
    missing = _missing_for_create(header, lines)
    create_args = {
        "header": header,
        "lines": lines,
        "confirm_write": False,
    }
    host_path = saga_session._host_path(path)

    return {
        "ok": True,
        "pdf_path": str(path),
        "host_pdf_path": host_path,
        "page_count": extracted.get("page_count"),
        "extraction_method": chosen.get("method"),
        "header": header,
        "lines": lines,
        "create_args": create_args,
        "missing_required": missing,
        "ready_for_preview": len(missing) == 0,
        "warnings": warnings,
        "next_step": (
            "Call saga_add_iesiri_valuta(**create_args) with confirm_write=false, show the user the "
            "preview, then confirm_write=true after explicit OK."
            if not missing
            else "Fill missing_required (especially Cont/Cod/Client) via defaults or overrides, then create."
        ),
        "text_preview": text[:2500],
        "llm": {
            "requested": want_llm,
            "ok": bool(llm_result and llm_result.get("ok")) if want_llm else None,
            "error": (llm_result or {}).get("error") if want_llm else None,
            "model": (llm_result or {}).get("model") if want_llm else None,
        },
    }
