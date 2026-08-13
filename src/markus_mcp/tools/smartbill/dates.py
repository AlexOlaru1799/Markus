from __future__ import annotations

from datetime import date, timedelta


def resolve_range(
    date_from: str | None = None,
    date_to: str | None = None,
    period: str | None = None,
) -> tuple[str, str]:
    """Return YYYY-MM-DD bounds. ``period`` is this_month / last_month."""
    today = date.today()
    preset = (period or "").strip().lower().replace("-", "_").replace(" ", "_")
    if preset in {"this_month", "luna_curenta", "luna_asta"}:
        return today.replace(day=1).isoformat(), today.isoformat()
    if preset in {"last_month", "luna_trecuta"}:
        last_prev = today.replace(day=1) - timedelta(days=1)
        return last_prev.replace(day=1).isoformat(), last_prev.isoformat()
    start = (date_from or "").strip()
    end = (date_to or "").strip()
    if not start:
        raise ValueError(
            "Provide date_from and date_to (YYYY-MM-DD), or period='this_month' / 'last_month'."
        )
    if not end:
        end = today.isoformat()
    return start, end
