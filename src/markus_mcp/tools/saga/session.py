from __future__ import annotations

import atexit
import json
import os
import queue
import re
import shutil
import signal
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar
from urllib.parse import urljoin

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from markus_mcp.paths import data_dir, host_data_dir
from markus_mcp.tools.saga.credentials import load_credentials


DATA_DIR = data_dir()
HOST_DATA_DIR = host_data_dir()
SESSION_DIR = DATA_DIR / "saga-session"
ARTIFACT_DIR = DATA_DIR / "saga"
BASE_URL = os.getenv("SAGA_BASE_URL", "https://web.sagasoft.ro").rstrip("/")
DEFAULT_APP_BASE_URL = os.getenv("SAGA_APP_BASE_URL", "https://web2.sagasoft.ro/sagac").rstrip("/")
HEADLESS = os.getenv("SAGA_HEADLESS", "true").lower() not in {"0", "false", "no"}
CHROME_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def app_base_url(page=None) -> str:
    """Return the SAGA C app origin (web2 .../sagac) when available."""
    if page is not None:
        url = page.url or ""
        match = re.match(r"(https?://[^/]+/sagac)", url, flags=re.IGNORECASE)
        if match:
            return match.group(1).rstrip("/")
    return DEFAULT_APP_BASE_URL

T = TypeVar("T")

_playwright = None
_context = None
_jobs: queue.Queue[tuple[Callable[[], Any], threading.Event, dict[str, Any]] | None] = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()
_captured_requests: list[dict[str, Any]] = []
_capture_lock = threading.Lock()


@dataclass(frozen=True)
class SagaSessionState:
    logged_in: bool
    firm_selected: bool
    needs_otp: bool
    needs_browser_authorization: bool
    details: str
    url: str


def _host_path(path: Path) -> str:
    try:
        relative_path = path.relative_to(DATA_DIR)
    except ValueError:
        return str(path)
    return str(HOST_DATA_DIR / relative_path)


def _ensure_dirs() -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def _clear_stale_profile_locks() -> None:
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        path = SESSION_DIR / name
        try:
            if path.is_symlink() or path.exists():
                path.unlink()
        except OSError:
            pass


def _launch_context(playwright):
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(SESSION_DIR),
        headless=HEADLESS,
        user_agent=CHROME_USER_AGENT,
        viewport={"width": 1440, "height": 900},
        locale="ro-RO",
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


def _redact_secrets(value: str | None) -> str | None:
    if not value:
        return value
    redacted = value
    for key in ("Password", "password", "passwd", "Pwd", "otp"):
        redacted = re.sub(rf"({key}=)[^&]*", rf"\1***", redacted, flags=re.IGNORECASE)
    return redacted


def _on_request(request) -> None:
    try:
        url = request.url
        if "sagasoft" not in url.casefold():
            return
        entry = {
            "method": request.method,
            "url": url,
            "resource_type": request.resource_type,
            "post_data": _redact_secrets(request.post_data),
        }
        with _capture_lock:
            _captured_requests.append(entry)
    except Exception:
        return


def _on_response(response) -> None:
    try:
        request = response.request
        url = request.url
        if "sagasoft" not in url.casefold():
            return
        content_type = (response.headers or {}).get("content-type", "")
        body_preview = None
        if "json" in content_type or "/Home/" in url or "Partener" in url:
            try:
                text = response.text()
                body_preview = _redact_secrets(text[:4000])
            except Exception:
                body_preview = None
        with _capture_lock:
            for item in reversed(_captured_requests[-100:]):
                if item.get("url") == url and item.get("method") == request.method and "status" not in item:
                    item["status"] = response.status
                    item["content_type"] = content_type
                    if body_preview is not None:
                        item["body_preview"] = body_preview
                    break
    except Exception:
        return


def _ensure_browser():
    global _playwright, _context
    _ensure_dirs()
    if _context is not None:
        try:
            _ = _context.pages
            page = _first_page(_context)
            return page
        except Exception:
            _close_browser()

    _clear_stale_profile_locks()
    _playwright = sync_playwright().start()
    _context = _launch_context(_playwright)
    page = _first_page(_context)
    page.on("request", _on_request)
    page.on("response", _on_response)
    return page


def _worker_loop() -> None:
    while True:
        item = _jobs.get()
        if item is None:
            _close_browser()
            return
        fn, done, box = item
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc
        finally:
            done.set()


def _ensure_worker() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        thread = threading.Thread(target=_worker_loop, name="saga-browser", daemon=True)
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


def _save_screenshot(page, name: str) -> str:
    _ensure_dirs()
    path = ARTIFACT_DIR / name
    page.screenshot(path=str(path), full_page=True)
    return _host_path(path)


def _dump_capture(name: str = "network-capture.json") -> str:
    _ensure_dirs()
    path = ARTIFACT_DIR / name
    with _capture_lock:
        payload = list(_captured_requests)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return _host_path(path)


def clear_capture() -> None:
    with _capture_lock:
        _captured_requests.clear()


def get_capture() -> list[dict[str, Any]]:
    with _capture_lock:
        return list(_captured_requests)


def _saga_token(page) -> str | None:
    for cookie in page.context.cookies():
        if cookie.get("name") == "SAGA-Valid-Token-JS":
            return cookie.get("value")
    try:
        return page.evaluate(
            """() => {
                const t = '; ' + document.cookie;
                const n = t.split('; SAGA-Valid-Token-JS=');
                if (n.length === 2) return n.pop().split(';').shift();
                return null;
            }"""
        )
    except Exception:
        return None


def _auth_headers(page) -> dict[str, str]:
    token = _saga_token(page)
    headers = {"X-Requested-With": "XMLHttpRequest"}
    if token:
        headers["X-SAGA-Valid-Token"] = token
    return headers


def _detect_state(page) -> SagaSessionState:
    url = page.url or ""
    lowered = url.casefold()
    needs_otp = "/otp" in lowered
    needs_browser_authorization = "unauthorizedbrowser" in lowered
    logged_out = any(token in lowered for token in ("/login", "autentificare", "forgotpassword"))
    firm_page = "/firme" in lowered
    app_shell_url = "web2.sagasoft.ro" in lowered or "/sagac/" in lowered

    body = ""
    try:
        body = page.locator("body").inner_text(timeout=3_000)
    except Exception:
        pass
    body_l = body.casefold()

    if needs_otp or "introduceti codul primit pe mail" in body_l:
        return SagaSessionState(
            logged_in=False,
            firm_selected=False,
            needs_otp=True,
            needs_browser_authorization=False,
            details="SAGA is waiting for the 6-digit email OTP. Call saga_submit_otp with the code.",
            url=url,
        )

    if needs_browser_authorization or "browser nu este autorizat" in body_l:
        return SagaSessionState(
            logged_in=False,
            firm_selected=False,
            needs_otp=False,
            needs_browser_authorization=True,
            details=(
                "SAGA requires authorizing this browser via the email link "
                "'Autorizează browser' (~3 months). Avoid 'Autentificare fără autorizare' "
                "(one-time OTP every login)."
            ),
            url=url,
        )

    menu_markers = (
        "parteneri",
        "nomenclatoare",
        "rapoarte",
        "documente",
        "iesire",
        "ieșire",
        "clienti",
        "clienți",
        "fisiere",
        "fișiere",
        "operatii",
        "operații",
        "situatii",
        "situații",
        "administrare",
        "adaug",
        "modific",
    )
    has_app_shell = any(marker in body_l for marker in menu_markers) or app_shell_url
    logged_in = (
        (not logged_out and has_app_shell)
        or firm_page
        or app_shell_url
        or ("/home" in lowered and "login" not in lowered)
    )
    firm_selected = logged_in and not firm_page and (has_app_shell or app_shell_url)

    if firm_page:
        details = "Logged in; select a firm on /Firme."
    elif firm_selected:
        details = "SAGA WEB session appears logged in with a firm selected."
    elif logged_in:
        details = "Logged in, but firm selection may still be required."
    else:
        details = "Not logged in to SAGA WEB."

    return SagaSessionState(
        logged_in=logged_in,
        firm_selected=firm_selected,
        needs_otp=False,
        needs_browser_authorization=False,
        details=details,
        url=url,
    )


def _click_if_visible(page, *texts: str) -> bool:
    for text in texts:
        loc = page.get_by_text(text, exact=False)
        try:
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click(timeout=3_000)
                page.wait_for_timeout(1_000)
                return True
        except Exception:
            continue
    return False


def _is_unauthorized_browser_page(page) -> bool:
    url = (page.url or "").casefold()
    if "unauthorizedbrowser" in url:
        return True
    try:
        return page.locator("text=Acest browser nu este autorizat").count() > 0
    except Exception:
        return False


def _authorization_request_id(page) -> str | None:
    try:
        text = page.locator("body").inner_text(timeout=3_000)
    except Exception:
        return None
    match = re.search(r"AUTH-\d+", text or "")
    return match.group(0) if match else None


def _handle_unauthorized_browser(page, *, allow_otp_without_authorization: bool = False) -> None:
    """Stay on UnauthorizedBrowser unless the caller explicitly opts into one-time OTP.

    Clicking "Autentificare fără autorizare" skips the 3-month browser trust and forces
    a fresh OTP on every login. Prefer the email "Autorizează browser" link instead.
    """
    if not _is_unauthorized_browser_page(page):
        return
    if not allow_otp_without_authorization:
        return
    _click_if_visible(page, "Autentificare fara autorizare", "Autentificare fără autorizare")
    _click_if_visible(page, "Am Inteles", "Am Înțeles")


def _select_firm_if_needed(page) -> None:
    """Select a firm on /Firme and click Conectare (required before app routes work)."""
    if "/firme" not in (page.url or "").casefold():
        # Still try if the firm table / connect button is visible.
        if page.locator("text=Conectare").count() == 0 and page.locator("table tbody tr").count() == 0:
            return

    rows = page.locator("table tbody tr")
    if rows.count() > 0:
        try:
            rows.first.click(timeout=5_000)
            page.wait_for_timeout(500)
        except Exception:
            pass

    # SAGA requires an explicit Conectare after highlighting a firm.
    connected = _click_if_visible(page, "Conectare", "% Conectare")
    if not connected:
        # Fallback: button may include icons / whitespace.
        for selector in (
            'button:has-text("Conectare")',
            'a:has-text("Conectare")',
            '[role="button"]:has-text("Conectare")',
            "text=/Conectare/i",
        ):
            loc = page.locator(selector)
            if loc.count() == 0:
                continue
            try:
                loc.first.click(timeout=5_000)
                connected = True
                break
            except Exception:
                continue

    if connected:
        try:
            page.wait_for_url(
                re.compile(r"web2\.sagasoft\.ro|/sagac/|/Home|/Clienti", re.I),
                timeout=45_000,
            )
        except Exception:
            try:
                page.wait_for_url(lambda url: "/firme" not in (url or "").casefold(), timeout=30_000)
            except Exception:
                page.wait_for_timeout(3_000)
    else:
        _click_if_visible(page, "Selecteaza", "Selectează", "Deschide")


def _post_form(page, path: str, form: dict[str, str]) -> dict[str, Any]:
    absolute = urljoin(BASE_URL + "/", path.lstrip("/"))
    response = page.request.post(
        absolute,
        form=form,
        headers=_auth_headers(page),
        timeout=60_000,
    )
    content_type = response.headers.get("content-type", "")
    body: Any
    try:
        body = response.json() if "json" in content_type else response.text()
    except Exception:
        body = response.text()
    return {"ok": response.ok, "status": response.status, "url": response.url, "body": body}


def _ajax_login(page, username: str, password: str) -> dict[str, Any]:
    login = _post_form(page, "/Home/Login", {"Email": username, "Password": password})
    body = login.get("body")
    if isinstance(body, dict) and body.get("success") is False:
        return {"ok": False, "stage": "Login", "result": login}

    complete = _post_form(page, "/Home/CompleteLogin", {})
    return {"ok": True, "stage": "CompleteLogin", "login": login, "complete": complete}


def _goto_after_auth(page, complete_body: Any) -> None:
    if isinstance(complete_body, dict):
        next_url = complete_body.get("url") or ""
        if next_url:
            page.goto(urljoin(BASE_URL + "/", str(next_url).lstrip("/")), wait_until="domcontentloaded", timeout=60_000)
            return
        if complete_body.get("firme") is not None:
            page.goto(f"{BASE_URL}/Firme", wait_until="domcontentloaded", timeout=60_000)
            return
    # Fallbacks.
    for path in ("/Firme", "/Home", "/"):
        page.goto(f"{BASE_URL}{path}", wait_until="domcontentloaded", timeout=60_000)
        state = _detect_state(page)
        if state.logged_in or state.needs_otp or state.needs_browser_authorization:
            return


def _browser_auth_required_result(page, credentials) -> dict[str, object]:
    request_id = _authorization_request_id(page)
    return {
        "logged_in": False,
        "firm_selected": False,
        "needs_otp": False,
        "needs_browser_authorization": True,
        "authorization_request_id": request_id,
        "details": (
            "SAGA detected a new/unauthorized browser. Click 'Autorizează browser' in the "
            "SAGA email (valid ~3 months for this persisted Chromium profile). Do not use "
            "'Autentificare fără autorizare' unless you want a one-time OTP every login. "
            "Then call saga_login again. Optional escape hatch: saga_login(allow_otp_without_authorization=true)."
        ),
        "url": page.url,
        "credentials_file": credentials.source_file,
        "session_dir": _host_path(SESSION_DIR),
        "screenshot_path": _save_screenshot(page, "saga-unauthorized-browser.png"),
        "network_capture_path": _dump_capture("network-unauthorized.json"),
    }


def _login_impl(*, allow_otp_without_authorization: bool = False) -> dict[str, object]:
    clear_capture()
    credentials = load_credentials()
    page = _ensure_browser()
    page.goto(f"{BASE_URL}/", wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(2_000)
    _handle_unauthorized_browser(
        page, allow_otp_without_authorization=allow_otp_without_authorization
    )

    state = _detect_state(page)
    if state.logged_in and state.firm_selected:
        return {
            "logged_in": True,
            "firm_selected": True,
            "needs_otp": False,
            "needs_browser_authorization": False,
            "details": "Already logged in; session reused.",
            "url": state.url,
            "credentials_file": credentials.source_file,
            "session_dir": _host_path(SESSION_DIR),
            "screenshot_path": _save_screenshot(page, "saga-status.png"),
        }

    if state.needs_browser_authorization and not allow_otp_without_authorization:
        return _browser_auth_required_result(page, credentials)

    if state.needs_otp:
        return {
            "logged_in": False,
            "firm_selected": False,
            "needs_otp": True,
            "needs_browser_authorization": False,
            "details": state.details,
            "url": state.url,
            "credentials_file": credentials.source_file,
            "session_dir": _host_path(SESSION_DIR),
            "screenshot_path": _save_screenshot(page, "saga-otp.png"),
        }

    # Ensure login page cookies/token exist.
    if page.locator('input[type="password"]').count() == 0 and not state.logged_in:
        page.goto(f"{BASE_URL}/", wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(2_000)

    ajax = _ajax_login(page, credentials.username, credentials.password)
    complete_body = None
    if ajax.get("ok"):
        complete_body = (ajax.get("complete") or {}).get("body")
        _goto_after_auth(page, complete_body)
    else:
        # Fallback to classic form submit.
        user = page.locator('input[type="email"], input[type="text"]').first
        pwd = page.locator('input[type="password"]').first
        user.fill(credentials.username)
        pwd.fill(credentials.password)
        if page.locator('button[type="submit"]').count():
            page.locator('button[type="submit"]').first.click()
        else:
            pwd.press("Enter")
        page.wait_for_timeout(3_000)

    page.wait_for_timeout(2_000)
    _handle_unauthorized_browser(
        page, allow_otp_without_authorization=allow_otp_without_authorization
    )
    state = _detect_state(page)

    if state.needs_browser_authorization and not allow_otp_without_authorization:
        return _browser_auth_required_result(page, credentials)

    if state.needs_otp:
        return {
            "logged_in": False,
            "firm_selected": False,
            "needs_otp": True,
            "needs_browser_authorization": False,
            "details": state.details,
            "url": state.url,
            "credentials_file": credentials.source_file,
            "session_dir": _host_path(SESSION_DIR),
            "screenshot_path": _save_screenshot(page, "saga-otp.png"),
            "network_capture_path": _dump_capture("network-login.json"),
        }

    if "/firme" in (page.url or "").casefold():
        _select_firm_if_needed(page)
        page.wait_for_timeout(2_000)
        state = _detect_state(page)

    result: dict[str, object] = {
        "logged_in": state.logged_in,
        "firm_selected": state.firm_selected,
        "needs_otp": state.needs_otp,
        "needs_browser_authorization": state.needs_browser_authorization,
        "details": state.details,
        "url": state.url,
        "credentials_file": credentials.source_file,
        "screenshot_path": _save_screenshot(page, "saga-login.png"),
        "network_capture_path": _dump_capture("network-login.json"),
    }
    if not state.logged_in:
        result["error"] = "SAGA login did not reach an authenticated page."
        result["ajax"] = {
            "stage": ajax.get("stage"),
            "login_status": (ajax.get("login") or {}).get("status"),
            "complete_status": (ajax.get("complete") or {}).get("status"),
        }
    return result


def login(*, allow_otp_without_authorization: bool = False) -> dict[str, object]:
    return _run_on_browser_thread(
        lambda: _login_impl(allow_otp_without_authorization=allow_otp_without_authorization)
    )


def _submit_otp_impl(code: str) -> dict[str, object]:
    digits = re.sub(r"\D", "", code or "")
    if len(digits) != 6:
        return {"ok": False, "error": "OTP must be exactly 6 digits."}

    page = _ensure_browser()
    if "/otp" not in (page.url or "").casefold():
        page.goto(f"{BASE_URL}/OTP", wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1_000)

    # Prefer official AJAX endpoint used by OTP.min.js.
    validate = _post_form(page, "/Home/ValidateOTP", {"otp": digits})
    body = validate.get("body")
    if isinstance(body, dict):
        if body.get("url"):
            page.goto(urljoin(BASE_URL + "/", str(body["url"]).lstrip("/")), wait_until="domcontentloaded", timeout=60_000)
        elif body.get("success") is False:
            return {
                "ok": False,
                "error": body.get("message") or "OTP validation failed.",
                "screenshot_path": _save_screenshot(page, "saga-otp-failed.png"),
            }
        elif body.get("firme") is not None:
            page.goto(f"{BASE_URL}/Firme", wait_until="domcontentloaded", timeout=60_000)
        else:
            # UI fallback fill.
            inputs = page.locator(".otp-input, input[maxlength='1']")
            if inputs.count() >= 6:
                for i, ch in enumerate(digits):
                    inputs.nth(i).fill(ch)
                _click_if_visible(page, "Autentificare")
                page.wait_for_timeout(2_000)
    else:
        inputs = page.locator(".otp-input, input[maxlength='1']")
        if inputs.count() >= 6:
            for i, ch in enumerate(digits):
                inputs.nth(i).fill(ch)
            _click_if_visible(page, "Autentificare")
            page.wait_for_timeout(2_000)

    if "/firme" in (page.url or "").casefold():
        _select_firm_if_needed(page)
        page.wait_for_timeout(2_000)

    state = _detect_state(page)
    return {
        "ok": state.logged_in,
        "logged_in": state.logged_in,
        "firm_selected": state.firm_selected,
        "needs_otp": state.needs_otp,
        "details": state.details,
        "url": state.url,
        "screenshot_path": _save_screenshot(page, "saga-after-otp.png"),
        "validate_status": validate.get("status"),
    }


def submit_otp(code: str) -> dict[str, object]:
    return _run_on_browser_thread(lambda: _submit_otp_impl(code))


def _status_impl() -> dict[str, object]:
    page = _ensure_browser()
    if "sagasoft.ro" not in (page.url or ""):
        page.goto(f"{BASE_URL}/", wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(2_000)
    state = _detect_state(page)
    return {
        "logged_in": state.logged_in,
        "firm_selected": state.firm_selected,
        "needs_otp": state.needs_otp,
        "needs_browser_authorization": state.needs_browser_authorization,
        "details": state.details,
        "url": state.url,
        "headless": HEADLESS,
        "screenshot_path": _save_screenshot(page, "saga-status.png"),
    }


def status() -> dict[str, object]:
    return _run_on_browser_thread(_status_impl)


def _reset_impl(delete_profile: bool) -> dict[str, object]:
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
        "details": "SAGA browser session closed"
        + (" and profile deleted." if deleted else ". Profile kept."),
    }


def reset_session(delete_profile: bool = False) -> dict[str, object]:
    return _run_on_browser_thread(lambda: _reset_impl(delete_profile))


def run_in_session(fn: Callable[[Any], T]) -> T:
    def _wrapped() -> T:
        page = _ensure_browser()
        return fn(page)

    return _run_on_browser_thread(_wrapped)


def ensure_ready_page():
    def _ensure():
        page = _ensure_browser()
        state = _detect_state(page)
        if state.needs_otp:
            raise RuntimeError("SAGA OTP required. Call saga_submit_otp with the 6-digit email code.")
        if state.needs_browser_authorization:
            raise RuntimeError("SAGA browser authorization required. Authorize via email then saga_login.")
        if not state.logged_in:
            _login_impl()
            page = _ensure_browser()
            state = _detect_state(page)
        if state.needs_otp:
            raise RuntimeError("SAGA OTP required. Call saga_submit_otp with the 6-digit email code.")
        if not state.logged_in:
            raise RuntimeError("Unable to establish a logged-in SAGA WEB session.")
        if not state.firm_selected and "/firme" in (page.url or "").casefold():
            _select_firm_if_needed(page)
            state = _detect_state(page)
        return page

    return _run_on_browser_thread(_ensure)


def api_request(
    method: str,
    url: str,
    *,
    form: dict[str, Any] | None = None,
    data: Any = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    def _req():
        page = _ensure_browser()
        state = _detect_state(page)
        if not state.logged_in:
            _login_impl()
            page = _ensure_browser()
        absolute = url if url.startswith("http") else f"{BASE_URL}{url}"
        response = page.request.fetch(
            absolute,
            method=method.upper(),
            params=params,
            form=form,
            data=data,
            headers=_auth_headers(page),
            timeout=60_000,
        )
        content_type = response.headers.get("content-type", "")
        try:
            body = response.json() if "json" in content_type else response.text()
        except Exception:
            body = response.text()
        return {
            "ok": response.ok,
            "status": response.status,
            "url": response.url,
            "content_type": content_type,
            "body": body,
        }

    return _run_on_browser_thread(_req)


def shutdown() -> None:
    """Flush Chromium profile (cookies/device trust) before process exit."""
    try:
        _ensure_worker()
        done = threading.Event()
        box: dict[str, Any] = {}

        def _flush_close() -> None:
            _close_browser()

        _jobs.put((_flush_close, done, box))
        done.wait(timeout=15)
        _jobs.put(None)
    except Exception:
        try:
            _close_browser()
        except Exception:
            pass


def _install_signal_handlers() -> None:
    def _handle(signum, frame):  # noqa: ANN001, ARG001
        shutdown()
        raise SystemExit(0)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handle)
        except Exception:
            pass


atexit.register(shutdown)
_install_signal_handlers()
