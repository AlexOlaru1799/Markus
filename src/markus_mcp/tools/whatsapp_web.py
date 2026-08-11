from __future__ import annotations

import atexit
import os
import queue
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar
from urllib.parse import quote

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


DATA_DIR = Path(os.getenv("MARKUS_DATA_DIR", "/data"))
HOST_DATA_DIR = Path(os.getenv("MARKUS_HOST_DATA_DIR", str(DATA_DIR)))
SESSION_DIR = DATA_DIR / "whatsapp-session"
SCREENSHOT_DIR = DATA_DIR / "screenshots"
LATEST_QR_PATH = SCREENSHOT_DIR / "whatsapp-qr-latest.png"
HEADLESS = os.getenv("WHATSAPP_HEADLESS", "true").lower() not in {"0", "false", "no"}
WHATSAPP_URL = "https://web.whatsapp.com"
CHROME_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
QR_WAIT_TIMEOUT_MS = int(os.getenv("WHATSAPP_QR_WAIT_TIMEOUT_MS", "60000"))
PAIR_DEFAULT_TIMEOUT_SEC = int(os.getenv("WHATSAPP_PAIR_TIMEOUT_SEC", "180"))
QR_REFRESH_INTERVAL_SEC = int(os.getenv("WHATSAPP_QR_REFRESH_INTERVAL_SEC", "15"))

T = TypeVar("T")

_playwright = None
_context = None
_jobs: queue.Queue[tuple[Callable[[], Any], threading.Event, dict[str, Any]] | None] = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()
_keepalive_stop = threading.Event()
_keepalive_thread: threading.Thread | None = None
_keepalive_lock = threading.Lock()


@dataclass(frozen=True)
class WhatsAppPageState:
    paired: bool
    needs_pairing: bool
    details: str


def _host_path(container_path: Path) -> str:
    try:
        relative_path = container_path.relative_to(DATA_DIR)
    except ValueError:
        return str(container_path)
    return str(HOST_DATA_DIR / relative_path)


def _ensure_dirs() -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def _normalize_name(name: str) -> str:
    return " ".join(name.strip().split()).casefold()


def _launch_context(playwright):
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(SESSION_DIR),
        headless=HEADLESS,
        user_agent=CHROME_USER_AGENT,
        viewport={"width": 1280, "height": 720},
        locale="en-US",
        args=[
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled",
        ],
    )


def _first_page(context):
    return context.pages[0] if context.pages else context.new_page()


def _close_browser() -> None:
    global _playwright, _context
    if _context is not None:
        try:
            _context.close()
        except Exception:
            pass
        _context = None
    if _playwright is not None:
        try:
            _playwright.stop()
        except Exception:
            pass
        _playwright = None


def _clear_stale_profile_locks() -> None:
    """Remove leftover Chromium singleton locks after container restarts."""
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        path = SESSION_DIR / name
        try:
            if path.is_symlink() or path.exists():
                path.unlink()
        except OSError:
            pass


def _ensure_browser():
    global _playwright, _context
    _ensure_dirs()

    if _context is not None:
        try:
            _ = _context.pages
            return _first_page(_context)
        except Exception:
            _close_browser()

    _clear_stale_profile_locks()
    _playwright = sync_playwright().start()
    _context = _launch_context(_playwright)
    return _first_page(_context)


def _worker_loop() -> None:
    while True:
        item = _jobs.get()
        if item is None:
            _close_browser()
            return
        fn, done, box = item
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001 - surface to caller
            box["error"] = exc
        finally:
            done.set()


def _ensure_worker() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        thread = threading.Thread(target=_worker_loop, name="whatsapp-browser", daemon=True)
        thread.start()
        _worker_started = True


def _run_on_browser_thread(fn: Callable[[], T]) -> T:
    _ensure_worker()
    done = threading.Event()
    box: dict[str, Any] = {}
    _jobs.put((fn, done, box))
    done.wait()
    if "error" in box:
        raise box["error"]
    return box["value"]


def _detect_state(page) -> WhatsAppPageState:
    try:
        page_text = page.locator("body").inner_text(timeout=5_000)
    except Exception:
        page_text = ""

    lowered = page_text.casefold()

    if "works with google chrome" in lowered or "update google chrome" in lowered:
        return WhatsAppPageState(
            paired=False,
            needs_pairing=False,
            details="WhatsApp Web rejected the browser as unsupported.",
        )

    # Strict paired signals only — generic contenteditables cause false positives on load screens.
    chat_list = page.locator('div[data-testid="chat-list"]')
    search = page.locator('div[contenteditable="true"][data-tab="3"]')
    side = page.locator("#side, #pane-side")
    if chat_list.count() > 0 or (search.count() > 0 and side.count() > 0):
        return WhatsAppPageState(
            paired=True,
            needs_pairing=False,
            details="WhatsApp Web appears to be paired and ready.",
        )

    qr_markers = (
        "scan to log in" in lowered
        or "scan qr code" in lowered
        or "log in with phone number" in lowered
    )
    if qr_markers:
        return WhatsAppPageState(
            paired=False,
            needs_pairing=True,
            details="WhatsApp Web is showing a QR code. Keep this session open and scan it with your phone.",
        )

    if "end-to-end encrypted" in lowered:
        return WhatsAppPageState(
            paired=False,
            needs_pairing=False,
            details="WhatsApp Web is still loading the chat list after login.",
        )

    return WhatsAppPageState(
        paired=False,
        needs_pairing=False,
        details="WhatsApp Web opened, but readiness could not be determined yet.",
    )


def _wait_for_ready_state(page, timeout_ms: int = QR_WAIT_TIMEOUT_MS) -> WhatsAppPageState:
    deadline = time.monotonic() + (timeout_ms / 1000)
    last_state = WhatsAppPageState(
        paired=False,
        needs_pairing=False,
        details="Waiting for WhatsApp Web to finish loading.",
    )

    while time.monotonic() < deadline:
        last_state = _detect_state(page)
        if last_state.paired or last_state.needs_pairing or "unsupported" in last_state.details:
            return last_state
        page.wait_for_timeout(1_000)

    return last_state


def _wait_for_chat_ui(page, timeout_ms: int = 120_000) -> WhatsAppPageState:
    """Wait through the post-login splash until the chat sidebar is usable."""
    deadline = time.monotonic() + (timeout_ms / 1000)
    last_state = _detect_state(page)
    while time.monotonic() < deadline:
        last_state = _detect_state(page)
        if last_state.paired or last_state.needs_pairing or "unsupported" in last_state.details:
            return last_state
        page.wait_for_timeout(1_000)
    return last_state


def _save_debug_screenshot(page, name: str = "whatsapp-debug.png") -> str:
    _ensure_dirs()
    path = SCREENSHOT_DIR / name
    page.screenshot(path=str(path), full_page=True)
    return _host_path(path)


def _save_qr_screenshot(page) -> str:
    _ensure_dirs()
    page.screenshot(path=str(LATEST_QR_PATH), full_page=True)
    return _host_path(LATEST_QR_PATH)


def _state_payload(state: WhatsAppPageState, **extra: Any) -> dict[str, object]:
    payload: dict[str, object] = {
        "paired": state.paired,
        "needs_pairing": state.needs_pairing,
        "details": state.details,
        "headless": HEADLESS,
    }
    payload.update(extra)
    return payload


def _stop_keepalive() -> None:
    global _keepalive_thread
    with _keepalive_lock:
        _keepalive_stop.set()
        _keepalive_thread = None
    # Do not join: keepalive may be blocked waiting for the browser worker.


def _keepalive_tick() -> dict[str, object]:
    if _context is None:
        return {"active": False, "reason": "no_browser"}
    page = _first_page(_context)
    if "web.whatsapp.com" not in (page.url or ""):
        page.goto(WHATSAPP_URL, wait_until="domcontentloaded", timeout=60_000)
        state = _wait_for_ready_state(page)
    else:
        state = _detect_state(page)

    if state.paired:
        return {"active": False, "paired": True}

    if state.needs_pairing:
        return {
            "active": True,
            "paired": False,
            "screenshot_path": _save_qr_screenshot(page),
        }

    return {"active": True, "paired": False, "details": state.details}


def _keepalive_loop() -> None:
    while not _keepalive_stop.wait(QR_REFRESH_INTERVAL_SEC):
        try:
            result = _run_on_browser_thread(_keepalive_tick)
            if result.get("paired"):
                _keepalive_stop.set()
                return
        except Exception:
            continue


def _start_keepalive() -> None:
    global _keepalive_thread
    with _keepalive_lock:
        if _keepalive_thread is not None and _keepalive_thread.is_alive():
            return
        _keepalive_stop.clear()
        _keepalive_thread = threading.Thread(
            target=_keepalive_loop,
            name="whatsapp-qr-keepalive",
            daemon=True,
        )
        _keepalive_thread.start()


def _status_impl() -> dict[str, object]:
    page = _ensure_browser()
    if "web.whatsapp.com" not in (page.url or ""):
        page.goto(WHATSAPP_URL, wait_until="domcontentloaded", timeout=60_000)
    state = _wait_for_chat_ui(page, timeout_ms=90_000)

    screenshot_path = None
    if state.needs_pairing:
        screenshot_path = _save_qr_screenshot(page)
        _start_keepalive()
    elif not state.paired:
        screenshot_path = _save_debug_screenshot(page, "whatsapp-status.png")
    else:
        _stop_keepalive()

    return _state_payload(state, screenshot_path=screenshot_path)


def status() -> dict[str, object]:
    return _run_on_browser_thread(_status_impl)


def _pair_impl() -> dict[str, object]:
    """Open WhatsApp Web, save a live QR screenshot, return immediately; browser stays open."""
    page = _ensure_browser()
    page.goto(WHATSAPP_URL, wait_until="domcontentloaded", timeout=60_000)
    state = _wait_for_ready_state(page)
    screenshot_path = None

    if state.paired:
        _stop_keepalive()
        return _state_payload(
            state,
            screenshot_path=None,
            browser_kept_open=True,
            next_step="Already paired. You can send messages.",
        )

    screenshot_path = _save_qr_screenshot(page)
    if state.needs_pairing or "unsupported" not in state.details:
        _start_keepalive()

    return _state_payload(
        state,
        screenshot_path=screenshot_path,
        browser_kept_open=True,
        qr_refresh_interval_sec=QR_REFRESH_INTERVAL_SEC,
        next_step=(
            "Open screenshot_path now and scan the QR with your phone. "
            "The browser session stays open in the background and the screenshot "
            "refreshes automatically. Then call whatsapp_web_status until paired=true."
        ),
    )


def pair(timeout_sec: int = PAIR_DEFAULT_TIMEOUT_SEC) -> dict[str, object]:
    """Start live pairing and return the QR path immediately (does not block for scan)."""
    del timeout_sec  # kept for API compatibility; pairing no longer blocks
    return _run_on_browser_thread(_pair_impl)


def pairing_screenshot() -> dict[str, object]:
    """Deprecated wrapper around the non-blocking pair flow."""
    result = pair()
    result["deprecated"] = "Use whatsapp_web_pair instead."
    return result


def _reset_session_impl(delete_profile: bool) -> dict[str, object]:
    _stop_keepalive()
    _close_browser()
    deleted = False
    if delete_profile and SESSION_DIR.exists():
        shutil.rmtree(SESSION_DIR, ignore_errors=True)
        deleted = True
    _ensure_dirs()
    return {
        "reset": True,
        "profile_deleted": deleted,
        "session_dir": _host_path(SESSION_DIR),
        "details": "Browser session closed"
        + (" and profile deleted." if deleted else ". Profile kept for next launch."),
    }


def reset_session(delete_profile: bool = False) -> dict[str, object]:
    return _run_on_browser_thread(lambda: _reset_session_impl(delete_profile))


def _dismiss_blocking_ui(page) -> None:
    """Close WhatsApp intro/update modals that block search and chat."""
    candidates = [
        'button:has-text("Continue")',
        'div[role="button"]:has-text("Continue")',
        'button[aria-label="Close"]',
        'div[role="button"][aria-label="Close"]',
        '[data-testid="popup-controls-ok"]',
        '[data-testid="modal-close"]',
        'span[data-icon="x-alt"]',
        'span[data-icon="x"]',
    ]
    for selector in candidates:
        locator = page.locator(selector)
        try:
            count = min(locator.count(), 3)
            for index in range(count):
                target = locator.nth(index)
                if target.is_visible():
                    target.click(timeout=2_000)
                    page.wait_for_timeout(400)
        except Exception:
            continue


def _find_search_box(page):
    _dismiss_blocking_ui(page)

    candidates = [
        'div[contenteditable="true"][data-tab="3"]',
        '#side div[contenteditable="true"]',
        'div[contenteditable="true"][role="textbox"][data-tab="3"]',
        '[data-testid="chat-list-search"] div[contenteditable="true"]',
        'div[title="Search input textbox"]',
        'div[aria-label="Search input textbox"]',
        'div[aria-label="Search or start a new chat"]',
        'div[aria-label*="Search"][contenteditable="true"]',
        '#side [role="textbox"]',
        '[role="textbox"][contenteditable="true"]',
    ]
    for selector in candidates:
        locator = page.locator(selector)
        if locator.count() > 0 and locator.first.is_visible():
            return locator.first

    # New WhatsApp UI: activate search by clicking the placeholder label first.
    placeholders = [
        page.get_by_text("Search or start a new chat", exact=False),
        page.get_by_text("Search", exact=False),
    ]
    for placeholder in placeholders:
        try:
            if placeholder.count() == 0:
                continue
            placeholder.first.click(timeout=3_000)
            page.wait_for_timeout(600)
            focused = page.locator('[contenteditable="true"]:focus, [role="textbox"]:focus')
            if focused.count() > 0:
                return focused.first
            editable = page.locator('#side [contenteditable="true"], #side [role="textbox"]')
            if editable.count() > 0:
                return editable.first
        except Exception:
            continue

    return page.locator('div[contenteditable="true"][data-tab="3"]').first


def _open_chat_by_exact_name(page, to_name: str) -> dict[str, object]:
    requested = to_name.strip()
    if not requested:
        return {"ok": False, "error": "to_name cannot be empty."}

    normalized = _normalize_name(requested)
    search = _find_search_box(page)
    try:
        search.wait_for(state="visible", timeout=30_000)
    except PlaywrightTimeoutError:
        state = _detect_state(page)
        return {
            "ok": False,
            "needs_pairing": state.needs_pairing,
            "error": "WhatsApp search box did not become available.",
            "details": state.details,
            "debug_screenshot": _save_debug_screenshot(page, "whatsapp-search-missing.png"),
        }

    search.click()
    page.keyboard.press("Meta+A")
    page.keyboard.press("Control+A")
    page.keyboard.press("Backspace")
    page.keyboard.type(requested, delay=40)
    page.wait_for_timeout(2_500)

    titles = page.locator("#pane-side span[title], #side span[title]")
    exact_indexes: list[tuple[int, str]] = []
    seen_titles: set[str] = set()

    count = titles.count()
    for index in range(count):
        title = titles.nth(index).get_attribute("title") or ""
        if _normalize_name(title) != normalized:
            continue
        if title in seen_titles:
            continue
        seen_titles.add(title)
        exact_indexes.append((index, title))

    if not exact_indexes:
        return {
            "ok": False,
            "error": f"No exact chat/contact match for '{requested}'. Nothing was sent.",
            "requested_name": requested,
            "debug_screenshot": _save_debug_screenshot(page, "whatsapp-no-match.png"),
        }

    if len(exact_indexes) > 1:
        return {
            "ok": False,
            "error": (
                f"Multiple exact matches for '{requested}'. "
                "Nothing was sent; use a more specific name or to_phone_number."
            ),
            "requested_name": requested,
            "matches": [title for _, title in exact_indexes],
        }

    index, matched_name = exact_indexes[0]
    titles.nth(index).click()
    page.wait_for_timeout(1_000)
    return {"ok": True, "matched_name": matched_name, "requested_name": requested}


def _submit_composed_message(page, message: str) -> dict[str, object]:
    trimmed = message.strip()
    try:
        box = page.locator('[contenteditable="true"][role="textbox"]').last
        box.wait_for(state="visible", timeout=60_000)
        box.click()
        page.keyboard.type(trimmed, delay=20)
        page.keyboard.press("Enter")
        page.wait_for_timeout(2_000)
        return {
            "sent": True,
            "details": "Message send action was submitted in WhatsApp Web.",
        }
    except PlaywrightTimeoutError:
        state = _detect_state(page)
        return {
            "sent": False,
            "needs_pairing": state.needs_pairing,
            "error": "WhatsApp message box did not become available.",
            "details": state.details,
        }


def _send_message_impl(
    message: str,
    to_name: str | None,
    to_phone_number: str | None,
    confirm_send: bool,
) -> dict[str, object]:
    trimmed_message = message.strip()
    name = (to_name or "").strip()
    phone_raw = (to_phone_number or "").strip()
    normalized_phone = "".join(ch for ch in phone_raw if ch.isdigit())

    if not trimmed_message:
        return {"sent": False, "error": "message cannot be empty."}
    if not name and not normalized_phone:
        return {
            "sent": False,
            "error": "Provide to_name (exact chat name) or to_phone_number with country code.",
        }

    page = _ensure_browser()
    if "web.whatsapp.com" not in (page.url or ""):
        page.goto(WHATSAPP_URL, wait_until="domcontentloaded", timeout=60_000)
    state = _wait_for_chat_ui(page, timeout_ms=120_000)
    _dismiss_blocking_ui(page)
    state = _detect_state(page)

    if not state.paired:
        return {
            "sent": False,
            "needs_pairing": state.needs_pairing,
            "error": "WhatsApp Web is not ready for messaging yet.",
            "details": state.details,
            "debug_screenshot": _save_debug_screenshot(page, "whatsapp-not-ready.png"),
        }

    matched_name: str | None = None
    if name:
        opened = _open_chat_by_exact_name(page, name)
        if not opened.get("ok"):
            return {"sent": False, **opened}
        matched_name = str(opened["matched_name"])

    if not confirm_send:
        preview: dict[str, object] = {
            "sent": False,
            "requires_confirmation": True,
            "preview": trimmed_message,
            "match_rule": "exact_name_only" if name else "phone_number",
            "details": (
                "Exact recipient resolved. Ask the user to confirm, then call again "
                "with the same arguments and confirm_send=true."
            ),
        }
        if matched_name is not None:
            preview["to_name"] = matched_name
            preview["requested_name"] = name
        if normalized_phone:
            preview["to_phone_number"] = normalized_phone
        return preview

    if name:
        result = _submit_composed_message(page, trimmed_message)
        if result.get("sent"):
            result["to_name"] = matched_name
            result["requested_name"] = name
        return result

    send_url = f"{WHATSAPP_URL}/send?phone={normalized_phone}&text={quote(trimmed_message)}"
    page.goto(send_url, wait_until="domcontentloaded", timeout=60_000)
    try:
        textbox = page.locator('[contenteditable="true"][role="textbox"]').last
        textbox.wait_for(state="visible", timeout=60_000)
    except PlaywrightTimeoutError:
        state = _detect_state(page)
        return {
            "sent": False,
            "needs_pairing": state.needs_pairing,
            "error": "WhatsApp message box did not become available.",
            "details": state.details,
        }

    page.keyboard.press("Enter")
    page.wait_for_timeout(2_000)
    return {
        "sent": True,
        "to_phone_number": normalized_phone,
        "details": "Message send action was submitted in WhatsApp Web.",
    }


def send_message(
    message: str,
    to_name: str | None = None,
    to_phone_number: str | None = None,
    confirm_send: bool = False,
) -> dict[str, object]:
    return _run_on_browser_thread(
        lambda: _send_message_impl(message, to_name, to_phone_number, confirm_send)
    )


def shutdown() -> None:
    _stop_keepalive()
    _ensure_worker()
    _jobs.put(None)


atexit.register(shutdown)
