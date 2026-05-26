"""
Job board scraper and Google search utility using crawl4AI.

Provides two main capabilities:
1. `search_jobs()` — scrape ejobs.ro and bestjobs.eu for job listings
2. `search_google()` — generic Google search used for LinkedIn lookups

Both functions use the async crawl4ai library which handles JS rendering,
respects robots.txt, rotates user-agents, and manages delays.
"""

from __future__ import annotations

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
        "job_link_selector": "a.job-title, a[data-job-id], h2 a, .job-item a",
    },
    {
        "name": "bestjobs",
        "search_url": "https://www.bestjobs.eu/locuri-de-munca/{keyword}",
        "job_link_selector": "a.job-title, a[data-job-id], h2 a, .job-item a",
    },
]

# CAPTCHA page heuristics — if any of these substrings appear in the HTML
# we assume a CAPTCHA challenge is blocking us.
CAPTCHA_INDICATORS: list[str] = [
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


def detect_captcha(html: str) -> bool:
    """Return True if *html* appears to contain a CAPTCHA challenge page."""
    lower = html.lower()
    for indicator in CAPTCHA_INDICATORS:
        if indicator in lower:
            logger.warning("CAPTCHA indicator detected: '%s'", indicator)
            return True
    return False


async def fetch_page_text(url: str) -> str | None:
    """
    Use crawl4ai to fetch *url* and return its text/markdown content.

    Returns ``None`` if the request fails or a CAPTCHA is detected
    (detection is done on the raw HTML internally).

    The caller gets the full crawl result, with CAPTCHA filtering applied.
    """
    try:
        from crawl4ai import AsyncWebCrawler
        from crawl4ai.async_configs import CrawlerRunConfig

        crawl_config = CrawlerRunConfig(verbose=True)
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url, crawl_config)
            if result.success:
                # Check the raw HTML for CAPTCHA first
                html = result.html or ""
                if html and detect_captcha(html):
                    logger.warning("CAPTCHA detected on %s", url)
                    return None  # Signal CAPTCHA to the caller

                if result.markdown:
                    return result.markdown
                # Fallback: strip HTML tags for rough text
                if html:
                    logger.debug("No markdown for %s, falling back to raw HTML", url)
                    text = re.sub(r"<[^>]+>", " ", html)
                    text = re.sub(r"\s+", " ", text).strip()
                    return text[:10000] if len(text) > 10000 else text

            logger.warning("crawl4ai failed for %s (status=%s)", url, getattr(result, "status_code", "?"))
            return None
    except Exception as exc:
        logger.error("Exception fetching %s: %s", url, exc)
        return None


async def search_google(query: str, max_results: int = 5) -> list[str]:
    """
    Perform a Google search via crawl4AI and return a list of result URLs.

    Uses a standard ``google.com/search`` with crawl4AI's JS rendering.
    """
    urls: list[str] = []

    search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}&num={max_results}"
    html = await fetch_page_text(search_url)
    if not html:
        return urls

    if detect_captcha(html):
        logger.warning("Google search blocked by CAPTCHA for query: %s", query)
        return []  # caller will try next fallback

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


async def scrape_board(board: dict[str, Any], keyword: str) -> list[dict[str, Any]]:
    """
    Scrape a single job board for *keyword*.

    Returns a list of dicts:
        ``{"title": str, "url": str, "content": str}``

    The ``content`` field is the full markdown of the job detail page.
    """
    name = board["name"]
    search_url_template = board["search_url"]
    url = search_url_template.format(keyword=keyword.replace(" ", "+"))

    logger.info("Scraping %s for keyword '%s': %s", name, keyword, url)

    results: list[dict[str, Any]] = []
    search_html = await fetch_page_text(url)
    if not search_html:
        logger.warning("No content returned from %s", name)
        return results

    if detect_captcha(search_html):
        logger.warning("CAPTCHA on %s search page for '%s'", name, keyword)
        return [{"captcha": True, "board": name, "keyword": keyword, "url": url}]

    # Extract job links from the markdown/text — crawl4AI markdown usually
    # contains URLs inline. We look for patterns that look like job links.
    job_urls: list[str] = []
    for match in re.finditer(r"https?://[^\s\"'>]*?(?:jobs?|post|job-detail|job)[^\s\"'>]*", search_html):
        job_url = match.group().rstrip(".,;:)\"'")
        # Filter to same-domain URLs
        if ("ejobs" in job_url or "bestjobs" in job_url) and job_url not in job_urls:
            job_urls.append(job_url)

    # If no URLs found via regex, mark it for LLM parsing
    if not job_urls:
        logger.info("No job URLs extracted from %s via regex; content available for LLM", name)
        # Return the page content itself - the agent can use LLM to parse it
        return [{"title": f"Search results for {keyword}", "url": url, "content": search_html[:15000]}]

    # Fetch details for each job link
    for job_url in job_urls[:15]:  # Limit to first 15 to avoid rate limiting
        logger.info("  Fetching job detail: %s", job_url)
        content = await fetch_page_text(job_url)
        if content and not detect_captcha(content):
            # Extract a rough title from the content (first line or heading)
            title = _guess_title(content) or f"Job at {job_url}"
            results.append({"title": title, "url": job_url, "content": content[:15000]})
        else:
            logger.warning("  Could not fetch detail for %s", job_url)

    logger.info("  %s returned %d job entries", name, len(results))
    return results


def _guess_title(content: str) -> str | None:
    """Try to extract a job title from the first few lines of markdown content."""
    lines = content.strip().split("\n")
    for line in lines[:10]:
        line = line.strip().strip("#").strip("*").strip()
        if line and len(line) > 5 and len(line) < 200:
            return line
    return None


async def search_jobs(keywords: list[str]) -> list[dict[str, Any]]:
    """
    Orchestrate scraping across all boards for all keywords.

    Returns a flat list of job entries deduplicated by URL.
    """
    all_jobs: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for keyword in keywords:
        logger.info("=" * 50)
        logger.info("Searching for keyword: '%s'", keyword)
        logger.info("=" * 50)

        for board in BOARDS:
            entries = await scrape_board(board, keyword)
            for entry in entries:
                if "captcha" in entry:
                    # Return CAPTCHA signals immediately so the agent loop can pause
                    return [entry]
                url = entry.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    entry["search_keyword"] = keyword
                    all_jobs.append(entry)

    logger.info("Total unique jobs collected: %d", len(all_jobs))
    return all_jobs
