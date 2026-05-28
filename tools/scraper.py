"""
Job board scraper utility.

Provides:
- ``search_jobs()`` — scrape ejobs.ro and bestjobs.eu for job listings

All page fetches go through the **persistent visible browser** so the user can
see exactly what the agent is doing at all times.  If a CAPTCHA challenge
appears, solve it directly in the open browser window — the agent polls
automatically and continues once the challenge is gone.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from config import config

logger = logging.getLogger(__name__)

# ── Board configuration ─────────────────────────────────────────────────────

BOARDS: list[dict[str, Any]] = [
    {
        "name": "ejobs",
        "search_url": "https://www.ejobs.ro/locuri-de-munca/{keyword}",
    },
    {
        "name": "bestjobs",
        "search_url": "https://www.bestjobs.eu/locuri-de-munca/{keyword}",
    },
]

# ── Page fetching (always uses visible persistent browser) ─────────────────
# ── Page fetching (always uses visible persistent browser) ─────────────────


async def fetch_page_text(url: str, *, anti_bot: bool = False, captcha_context: str = "", scroll: bool = False, scroll_steps: int = 5) -> str | None:
    """
    Fetch *url* using the **persistent visible browser** and return the
    **raw HTML** content.

    The browser window stays open at all times so you can see exactly what
    the agent is doing.  If a CAPTCHA challenge appears, solve it directly
    in the browser window — the agent polls automatically (with debounce)
    and continues once the challenge is gone.

    Returns raw HTML so that URL-extraction regexes (e.g.
    ``_extract_job_urls``) can find hyperlinks in ``href`` attributes.
    Callers that need only visible text can strip tags themselves.

    Parameters
    ----------
    url : str
        The URL to fetch.
    anti_bot : bool
        Ignored (the persistent browser handles all anti-bot measures).
        Kept for API compatibility.
    captcha_context : str
        Optional description (e.g. ``"ejobs search"``).  Displayed in the
        CAPTCHA banner to help the user understand the context.
    scroll : bool
        If ``True``, scroll the page in steps to trigger lazy-loaded
        content (e.g. infinite-scroll job cards).
    scroll_steps : int
        Number of scroll steps (default 5).  Ignored when ``scroll=False``.

    Returns the raw page HTML, or ``None`` on failure.
    """
    from .browser_manager import get_browser

    browser_mgr = await get_browser()
    return await browser_mgr.fetch_page(
        url,
        context_label=captcha_context or "Automated fetch",
        max_wait_for_captcha=300.0,
        return_html=True,
        scroll=scroll,
        scroll_steps=scroll_steps,
    )


# ── Google search ───────────────────────────────────────────────────────────


async def search_google(query: str, max_results: int = 5) -> list[str]:
    """
    Perform a Google search via crawl4AI and return a list of result URLs.

    Uses a standard ``google.com/search`` with crawl4AI's JS rendering.
    If Google presents a CAPTCHA, the headed browser will open for you to
    solve it — once solved, the search results are extracted automatically.
    """
    urls: list[str] = []

    search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}&num={max_results}"
    html = await fetch_page_text(search_url, captcha_context=f"Google search: {query[:60]}")
    if not html:
        return urls

    # Naive link extraction — crawl4AI's markdown usually contains bare URLs.
    for match in re.finditer(r"https?://[^\s\"'>]+", html):
        url = match.group().rstrip(".,;:)\"'")
        urls.append(url)

    # Filter to unique, likely-relevant URLs
    seen: set[str] = set()
    unique: list[str] = []
    for u in urls:
        if u not in seen and "google" not in u:
            seen.add(u)
            unique.append(u)

    logger.info("Google search for '%s' returned %d URLs", query, len(unique))
    return unique[:max_results]


# ── Board scraping ──────────────────────────────────────────────────────────


async def scrape_board(
    board: dict[str, Any],
    keyword: str,
    max_results: int | None = None,
) -> list[dict[str, Any]]:
    """
    Scrape a single job board for *keyword*.

    Parameters
    ----------
    board : dict
        Board configuration (name, search_url).
    keyword : str
        Search term.
    max_results : int or None
        Maximum number of job entries to return from this board
        (default: no limit).

    Returns a list of dicts:
        ``{"title": str, "url": str, "content": str}``

    The ``content`` field is the full markdown of the search results page,
    which typically contains job titles and company names in the rendered text.
    """
    name = board["name"]
    search_url_template = board["search_url"]
    url = search_url_template.format(keyword=keyword.replace(" ", "+"))

    logger.info("Scraping %s for keyword '%s': %s", name, keyword, url)

    # ── Fetch the keyword-filtered listing page ──────────────────────────
    # For both boards we scroll to trigger lazy-loaded (Nuxt SPA) cards.
    # eJobs in particular hides most cards behind infinite-scroll rendering.
    search_html = await fetch_page_text(
        url,
        anti_bot=True,
        captcha_context=f"{name} search for '{keyword}'",
        scroll=True,
        scroll_steps=6,
    )
    if not search_html:
        logger.warning("No content returned from %s", name)
        return []

    # ── Extract individual job detail URLs ───────────────────────────────
    job_urls: list[str] = _extract_job_urls(name, search_html)

    if not job_urls:
        logger.info("No job URLs extracted from %s via regex; using page content for LLM", name)
        return [{"title": f"Search results for {keyword} on {name}", "url": url, "content": search_html[:20000]}]

    # ── eJobs: extract companies from listing page cards ─────────────────
    # eJobs individual job detail pages ALWAYS redirect (HTTP 307 →
    # /locuri-de-munca) to the unfiltered main listing page, making them
    # useless for company extraction.  Instead we parse company names
    # directly from the (now-scrolled) listing page HTML.
    if name == "ejobs":
        entries = _build_ejobs_entries(search_html, job_urls, keyword)
        if max_results is not None:
            entries = entries[:max_results]
        return entries

    # ── bestjobs: fetch each job detail page (they work fine) ──────────
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for job_url in job_urls:
        if job_url in seen:
            continue
        seen.add(job_url)
        if max_results is not None and len(results) >= max_results:
            break
        if max_results is None and len(results) >= 10:
            break

        if results:
            delay = config.crawl4ai_delay
            logger.debug("  Waiting %.1fs before next job detail fetch ...", delay)
            await asyncio.sleep(delay)

        logger.info("  Fetching job detail: %s", job_url)
        content = await fetch_page_text(job_url, anti_bot=True, captcha_context=f"{name} job detail")
        if content:
            title = _guess_title(content) or f"Job at {job_url}"
            results.append({"title": title, "url": job_url, "content": content[:15000]})
        else:
            logger.warning("  Could not fetch detail for %s", job_url)

    logger.info("  %s returned %d job entries", name, len(results))
    return results


def _build_ejobs_entries(search_html: str, job_urls: list[str], keyword: str) -> list[dict[str, Any]]:
    """Parse eJobs company names from the scrolled listing page HTML.

    Individual eJobs detail pages always redirect (HTTP 307 → /locuri-de-munca),
    so we extract company names and job titles from the **keyword-filtered
    listing page** cards (rendered by Playwright after scrolling).

    Returns up to 10 entries with the company name embedded in the ``content``
    field so that ``extract_company_name()`` can pick it up trivially.
    """
    # ── Parse rendered cards with BeautifulSoup ──────────────────────────
    # The Nuxt SPA renders job cards as <div class="job-card"> only when
    # they enter the viewport.  Scrolling (scroll_steps=6) should have
    # triggered most of them.
    card_map: dict[str, dict[str, str]] = {}

    try:
        from bs4 import BeautifulSoup  # type: ignore[import-untyped]
        soup = BeautifulSoup(search_html, "html.parser")
        cards = soup.select(".job-card")

        for card in cards:
            # Job title (inside <a> → <span>)
            title_el = card.select_one(".job-card-content-middle__title a span")
            title = title_el.get_text(strip=True) if title_el else ""

            # Job detail URL (inside <a> href)
            url_el = card.select_one(".job-card-content-middle__title a")
            rel_url: str = ""
            if url_el and url_el.get("href"):
                rel_url = str(url_el["href"])
                if not rel_url.startswith("http"):
                    rel_url = "https://www.ejobs.ro" + rel_url

            # Company name (<h3 class="...--darker">)
            company_el = card.select_one("h3.job-card-content-middle__info--darker")
            if not company_el:
                company_el = card.select_one("[class*='job-card-content-middle__info']")
            company = company_el.get_text(strip=True) if company_el else ""

            if rel_url and company:
                # Card URLs have /user/locuri-de-munca/... (which works when clicked).
                # Regex-extracted URLs use /locuri-de-munca/... (which 307-redirects).
                # Store both: key by the normalised form (for lookup matching job_urls),
                # but keep the original card URL to use in the result.
                card_map[rel_url.replace("/user/locuri-de-munca/", "/locuri-de-munca/")] = {
                    "title": title, "company": company, "card_url": rel_url,
                }

        logger.info(
            "  [ejobs] BeautifulSoup found %d cards with company names (of %d URLs)",
            len(card_map),
            len(job_urls),
        )
    except ImportError:
        logger.warning("  [ejobs] BeautifulSoup not installed — falling back to LLM-only extraction")

    # ── Build entries ────────────────────────────────────────────────────
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    # First pass: entries where we have the company name
    for job_url in job_urls:
        if job_url in seen:
            continue
        card_info = card_map.get(job_url)
        if not card_info:
            continue
        seen.add(job_url)

        company = card_info["company"]
        title = card_info["title"]
        # Use the card URL (with /user/) which works when clicked,
        # rather than the regex-extracted URL which 307-redirects.
        actual_url = card_info.get("card_url", job_url)

        # Embed the company name prominently so LLM extraction is trivial
        content = (
            f"JOB TITLE: {title}\n"
            f"COMPANY NAME: {company}\n"
            f"RECRUITER: eJobs\n\n"
            f"{search_html[:10000]}"
        )
        results.append({"title": title, "url": actual_url, "content": content})

        if len(results) >= 10:
            break

    # Second pass: fill remaining slots with listing-page content for LLM
    if len(results) < 10:
        for job_url in job_urls:
            if job_url in seen:
                continue
            seen.add(job_url)
            if len(results) >= 10:
                break

            # Try to extract title from JSON-LD or <a> tag
            title = _extract_ejobs_title(search_html, job_url)

            content = (
                f"JOB URL: {job_url}\n"
                f"JOB TITLE: {title or 'ejobs job'}\n\n"
                f"{search_html[:15000]}"
            )
            results.append({"title": title or f"ejobs job", "url": job_url, "content": content})

    logger.info("  [ejobs] Returning %d job entries (listing-page extraction)", len(results))
    return results


def _extract_ejobs_title(html: str, job_url: str) -> str | None:
    """Extract a job title from the eJobs listing page HTML for *job_url*.

    Tries two sources:
    1. JSON‑LD structured data (``@type``: ``ListItem``) — always present,
       contains the canonical title.
    2. ``<a>`` tag with matching ``href`` — present for rendered cards only.
    """
    # Strategy 1: JSON-LD structured data
    rel_path = job_url.replace("https://www.ejobs.ro", "")
    # Match JSON-LD items: {"name":"Job Title","id":"https://www.ejobs.ro/user/..."}
    # Note: the JSON uses full URL with /user/ prefix
    user_path = "/user" + rel_path
    escaped_user = re.escape(user_path)
    # Build regex without f-string (to avoid }} escaping issues)
    pat = '"name"\\s*:\\s*"([^"]+)"[^}]*"id"\\s*:\\s*"[^"]*' + escaped_user + '"'
    m = re.search(pat, html, re.IGNORECASE)
    if m:
        return m.group(1)

    # Strategy 2: JSON-LD (alternative field order)
    pat2 = '"id"\\s*:\\s*"[^"]*' + escaped_user + '"[^}]*"name"\\s*:\\s*"([^"]+)"'
    m2 = re.search(pat2, html, re.IGNORECASE)
    if m2:
        return m2.group(1)

    # Strategy 3: <a> tag with matching href
    a_match = re.search(
        '<a[^>]*href="' + re.escape(rel_path) + '"[^>]*>(.*?)</a>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if a_match:
        text = re.sub(r"<[^>]+>", "", a_match.group(1)).strip()
        if text:
            return text

    return None


def _extract_job_urls(board_name: str, html: str) -> list[str]:
    """
    Extract actual job detail URLs from the search results page HTML.

    Uses board-specific patterns to distinguish job listings from
    navigation links, images, and other noise.  Both absolute and
    relative URLs are matched.

    Filters out:
    - Template placeholders containing ``{`` or ``}``
    - Pagination URLs (``/paginaN``)
    - Search query URLs (containing ``+`` in the path)
    """
    raw: list[str] = []

    if board_name == "bestjobs":
        # Bestjobs job URLs: /loc-de-munca/<job-slug>-<id>
        for match in re.finditer(
            r"/loc-de-munca/[a-z0-9\-]+-\d+",
            html,
        ):
            raw.append("https://www.bestjobs.eu" + match.group())
        logger.debug("  Extracted %d raw bestjobs job URLs", len(raw))

    elif board_name == "ejobs":
        # Ejobs job URLs: /locuri-de-munca/<job-slug>/<numeric-id>
        for match in re.finditer(
            r"/locuri-de-munca/[a-z0-9\-]+/\d+",
            html,
        ):
            raw.append("https://www.ejobs.ro" + match.group())
        logger.debug("  Extracted %d raw ejobs job URLs", len(raw))

    # ── Post-processing: filter + deduplicate ─────────────────────────────
    urls: list[str] = []
    seen: set[str] = set()
    for url in raw:
        # Skip template placeholders (e.g. {search_term_string})
        if "{" in url or "}" in url:
            continue
        # Skip pagination URLs
        if "/pagina" in url.lower():
            continue
        # Skip search query URLs (contain + in path — indicates keyword search, not job)
        # Normalise: strip trailing slash and common punctuation
        clean = url.rstrip("/.,;:)\"'")
        if clean not in seen:
            seen.add(clean)
            urls.append(clean)

    logger.debug("  After filtering: %d job detail URLs for %s", len(urls), board_name)
    return urls


def _guess_title(content: str) -> str | None:
    """Try to extract a job title from the first few lines of markdown content."""
    lines = content.strip().split("\n")
    for line in lines[:10]:
        line = line.strip().strip("#").strip("*").strip()
        if line and len(line) > 5 and len(line) < 200:
            return line
    return None


async def search_jobs(
    keywords: list[str],
    max_results: int | None = None,
) -> list[dict[str, Any]]:
    """
    Orchestrate scraping across all boards for all keywords.

    Parameters
    ----------
    keywords : list[str]
        Search terms for job boards.
    max_results : int or None
        Maximum number of unique job entries to collect.
        Stops early once this many have been gathered.

    Returns a flat list of job entries deduplicated by URL.
    """
    all_jobs: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for keyword in keywords:
        logger.info("=" * 50)
        logger.info("Searching for keyword: '%s'", keyword)
        logger.info("=" * 50)

        for idx, board in enumerate(BOARDS):
            if max_results is not None and len(all_jobs) >= max_results:
                logger.info("Reached max_results (%d) — stopping early", max_results)
                break

            if idx > 0:
                delay = config.crawl4ai_delay
                logger.info("Waiting %.1fs before next board to avoid triggering CAPTCHA ...", delay)
                await asyncio.sleep(delay)

            # Calculate how many more entries we need from this board
            remaining = None if max_results is None else max_results - len(all_jobs)
            entries = await scrape_board(board, keyword, max_results=remaining)
            for entry in entries:
                url = entry.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    entry["search_keyword"] = keyword
                    all_jobs.append(entry)
                    if max_results is not None and len(all_jobs) >= max_results:
                        logger.info("Reached max_results (%d) — stopping early", max_results)
                        break

        if max_results is not None and len(all_jobs) >= max_results:
            break

    logger.info("Total unique jobs collected: %d", len(all_jobs))
    return all_jobs
