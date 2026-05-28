"""
Persistent headed Playwright browser manager.

Maintains a **single** visible Chromium window throughout the entire agent
run.  All page fetches go through this browser so that:

* The user can always see what the agent is doing.
* CAPTCHA challenges appear in the SAME window — the user solves them
  directly, and the agent detects the resolution by polling the page HTML.
* Cookies / session are preserved across requests (no repeated CAPTCHAs
  for the same domain once solved).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

# How often (seconds) to poll the page for CAPTCHA resolution.
CAPTCHA_POLL_INTERVAL: float = 2.0


class BrowserManager:
    """
    Manager for a single persistent headed Playwright browser.

    Usage::

        browser_mgr = await BrowserManager.create()
        try:
            content = await browser_mgr.fetch_page("https://example.com")
            # ... work ...
        finally:
            await browser_mgr.close()
    """

    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._captcha_indicators: list[str] = [
            "captcha",
            "cf-challenge",
            "cf-browser-verification",
            "challenge-platform",
            "g-recaptcha",
            "hcaptcha",
            "turnstile",
            "verify you are human",
            "please enable javascript",
        ]

    # ── Lifecycle ──────────────────────────────────────────────────────────

    @classmethod
    async def create(cls) -> "BrowserManager":
        """Factory: launch the persistent headless browser."""
        self = cls()
        await self._start()
        return self

    async def _start(self) -> None:
        """Launch Playwright + Chromium in headless mode."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("playwright not installed — cannot launch browser")
            raise

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        self._page = await self._context.new_page()
        logger.info("Persistent headless browser started")

    async def close(self) -> None:
        """Shut down the browser and Playwright."""
        try:
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        logger.info("Persistent headed browser closed")

    # ── Page fetching ──────────────────────────────────────────────────────

    async def fetch_page(
        self,
        url: str,
        *,
        context_label: str = "",
        max_wait_for_captcha: float = 300.0,
        return_html: bool = False,
        scroll: bool = False,
        scroll_steps: int = 5,
    ) -> str | None:
        """
        Navigate the persistent browser to *url* and return page content.

        If a CAPTCHA is detected, the browser stays open and visible — the
        user can solve it directly.  This method polls the page until the
        CAPTCHA indicators disappear, then returns the content.

        Parameters
        ----------
        url : str
            The URL to navigate to.
        context_label : str
            Short description for logging (e.g. ``"Google search"``).
        max_wait_for_captcha : float
            Max seconds to wait for CAPTCHA resolution (default 5 min).
        return_html : bool
            If ``True`` return the full raw HTML; otherwise return extracted
            visible text (default ``False``).
        scroll : bool
            If ``True``, scroll the page in steps to trigger lazy-loaded
            content (e.g. infinite-scroll job cards) before capturing.
        scroll_steps : int
            Number of scroll steps (default 5).  Ignored when ``scroll=False``.

        Returns the page content, or ``None`` on failure.
        """
        page = self._page
        label = context_label or url

        try:
            logger.info("  [browser] Navigating to: %s", url)
            await page.goto(url, timeout=30000, wait_until="networkidle")
        except Exception as exc:
            logger.warning("  [browser] Navigation failed for %s: %s", label, exc)
            return None

        # Small delay to let JS finish rendering
        await asyncio.sleep(1.0)

        # Scroll the page to trigger lazy-loaded content (e.g. Nuxt SPA cards)
        if scroll:
            await self._scroll_page(page, steps=scroll_steps)

        # Check for CAPTCHA and wait if needed
        html = await page.content()
        if self._detect_captcha(html):
            logger.warning("  [browser] CAPTCHA detected on %s — user must solve it", label)
            self._print_banner(url, label)
            content = await self._wait_for_captcha_resolution(page, max_wait_for_captcha, return_html)
            if content is None:
                return None
            return content

        # No CAPTCHA — extract content
        if return_html:
            return await page.content()
        return await self._extract_text(page)

    # ── Page scrolling (for lazy-loaded SPA content) ───────────────────────

    async def _scroll_page(self, page: Any, steps: int = 5) -> None:
        """Scroll the page in *steps* increments to trigger lazy-loaded cards.

        Many job boards (e.g. eJobs) render job cards only when they enter the
        viewport.  Scrolling down forces the Nuxt/React SPA to render
        additional cards so they become available in ``page.content()``.
        """
        logger.info("  [browser] Scrolling page in %d steps to trigger lazy-loaded content ...", steps)
        for i in range(1, steps + 1):
            try:
                await page.evaluate(
                    f"window.scrollTo(0, document.body.scrollHeight * {i} / {steps})"
                )
                await asyncio.sleep(0.5)
            except Exception:
                break
        # Scroll back to top so the page is in a predictable state
        try:
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(0.3)
        except Exception:
            pass

    # ── CAPTCHA detection ──────────────────────────────────────────────────

    def _detect_captcha(self, html: str) -> bool:
        """
        Return ``True`` if *html* looks like a CAPTCHA challenge page.

        Uses a two-tier check:
        1. Quickly scan for strong indicators (challenge-stage, g-recaptcha,
           hcaptcha, cf-browser-verification).
        2. For weaker indicators (e.g. *turnstile* which appears in the widget
           div even after solving), only flag if the page also lacks meaningful
           content (fewer than ~200 chars of visible body text).
        """
        lower = html.lower()

        # ── Strong indicators — always block ─────────────────────────────
        strong_indicators = [
            "cf-challenge",
            "cf-browser-verification",
            "challenge-platform",
            "g-recaptcha",
            "hcaptcha",
            "verify you are human",
            "please enable javascript",
        ]
        for indicator in strong_indicators:
            if indicator in lower:
                logger.warning("  [browser] CAPTCHA strong indicator: '%s'", indicator)
                return True

        # ── Weak indicators — only block if page has negligible content ───
        weak_indicators = ["turnstile", "captcha"]
        for indicator in weak_indicators:
            if indicator in lower:
                # Count visible body text length as a heuristic for
                # "is the actual page content rendered?"
                body_match = re.search(r"<body[^>]*>(.*?)</body>", html, re.IGNORECASE | re.DOTALL)
                body_text = body_match.group(1) if body_match else ""
                visible = re.sub(r"<[^>]+>", "", body_text).strip()
                # If body has very little visible text the page is still
                # showing a challenge overlay.
                if len(visible) < 200:
                    logger.warning(
                        "  [browser] CAPTCHA weak indicator '%s' + short body (%d chars) → blocking",
                        indicator,
                        len(visible),
                    )
                    return True
                logger.info(
                    "  [browser] CAPTCHA weak indicator '%s' but body has %d chars → assuming solved",
                    indicator,
                    len(visible),
                )
                return False

        return False

    def _print_banner(self, url: str, context: str) -> None:
        """Print a prominent banner telling the user to solve the CAPTCHA."""
        banner = f"""
{'=' * 72}
🚨  CAPTCHA DETECTED — Solve in the open browser window
{'=' * 72}

A CAPTCHA challenge has appeared in the **visible browser window**.

  1. Look at the Chromium window that's open on your screen.
  2. **Solve the CAPTCHA / Turnstile / reCAPTCHA** there.
  3. The agent will detect the solution **automatically** and continue.

Context: {context}
URL: {url}

{'=' * 72}
"""
        print(banner, flush=True)

    async def _wait_for_captcha_resolution(
        self,
        page: Any,
        max_wait: float = 300.0,
        return_html: bool = False,
    ) -> str | None:
        """
        Poll the page until CAPTCHA is resolved (no page reloads).

        Uses a **debounce** of 3 consecutive clean polls (~6 s) before
        declaring the CAPTCHA solved — this prevents transient widget
        states (e.g. user clicking the reCAPTCHA checkbox but not yet
        completing the image challenge) from falsely triggering resolution.

        Parameters
        ----------
        page : playwright.Page
            The page to poll.
        max_wait : float
            Maximum seconds to wait before giving up (default 5 min).
        return_html : bool
            If ``True`` return full HTML; otherwise return visible text.

        Returns the page content, or ``None`` if waiting times out.
        """
        DEBOUNCE_COUNT = 3  # Require 3 consecutive clean polls
        start = time.monotonic()
        last_log = 0.0
        clean_count = 0

        while time.monotonic() - start < max_wait:
            await asyncio.sleep(CAPTCHA_POLL_INTERVAL)
            try:
                html = await page.content()
            except Exception:
                continue

            if not self._detect_captcha(html):
                clean_count += 1
                if clean_count >= DEBOUNCE_COUNT:
                    logger.info(
                        "  [browser] CAPTCHA resolved! (%d consecutive clean polls) Extracting content ...",
                        clean_count,
                    )
                    if return_html:
                        return html
                    return await self._extract_text(page)
                # Still accumulating clean polls — wait for next cycle
                continue
            else:
                # CAPTCHA still present — reset clean counter
                if clean_count > 0:
                    logger.debug("  [browser] CAPTCHA re-appeared, resetting clean counter (was %d)", clean_count)
                clean_count = 0

            elapsed = time.monotonic() - start

            # Log progress every 30 s
            if elapsed - last_log >= 30.0:
                remaining = max_wait - elapsed
                logger.info(
                    "  [browser] Still waiting for CAPTCHA solve ... (%.0fs remaining)",
                    remaining,
                )
                last_log = elapsed

        logger.error("  [browser] CAPTCHA not solved within %.0f seconds — skipping", max_wait)
        print(
            f"\n{'=' * 72}\n"
            f"⏰  CAPTCHA not solved within {max_wait:.0f} seconds — skipping.\n"
            f"{'=' * 72}\n",
            flush=True,
        )
        return None

    # ── Content extraction ─────────────────────────────────────────────────

    async def _extract_text(self, page: Any) -> str | None:
        """Extract visible text from the current page."""
        try:
            text = await page.inner_text("body")
            if text and text.strip():
                return text
        except Exception:
            pass
        # Fallback via JavaScript
        try:
            text = await page.evaluate("document.body.innerText")
            return text
        except Exception:
            pass
        # Last resort: strip HTML
        try:
            html = await page.content()
            text = re.sub(r"<[^>]+>", " ", html)
            return re.sub(r"\s+", " ", text).strip()[:20000]
        except Exception:
            return None


# ── Module-level singleton ──────────────────────────────────────────────────

_shared_browser: BrowserManager | None = None


async def get_browser() -> BrowserManager:
    """Return the shared persistent browser (lazily created on first call)."""
    global _shared_browser
    if _shared_browser is None:
        _shared_browser = await BrowserManager.create()
    return _shared_browser


async def close_browser() -> None:
    """Close the shared persistent browser (if open)."""
    global _shared_browser
    if _shared_browser:
        await _shared_browser.close()
        _shared_browser = None
