"""
People name finder — search the internet for C-suite names by company.

For each company, performs Google searches to discover the names of:
- CEO (or Romanian equivalent "Director General")
- CFO (or Romanian equivalent "Director Financiar")
- Director General

Results from Google are passed to the LLM to parse the actual person names.
"""

from __future__ import annotations

import logging
from typing import Any

from llm import llm
from tools.scraper import search_google

logger = logging.getLogger(__name__)

# Role titles to search for — both English and Romanian
ROLE_QUERIES: dict[str, list[str]] = {
    "ceo": [
        "CEO of {company}",
        "Chief Executive Officer {company}",
        "Director General {company}",
        "{company} CEO",
    ],
    "cfo": [
        "CFO of {company}",
        "Chief Financial Officer {company}",
        "Director Financiar {company}",
        "{company} CFO",
    ],
    "director_general": [
        "Director General {company}",
        "{company} director general",
        "General Manager {company}",
        "{company} conducere",
    ],
}


async def find_people_names(company_name: str) -> dict[str, str]:
    """
    Search the internet for the names of C-suite executives at *company_name*.

    Returns
    -------
    dict[str, str]
        ``{"ceo": "Name or empty", "cfo": "Name or empty", "director_general": "Name or empty"}``
    """
    logger.info("=" * 60)
    logger.info("Finding people names for: '%s'", company_name)
    logger.info("=" * 60)

    result: dict[str, str] = {"ceo": "", "cfo": "", "director_general": ""}

    for role_key, queries in ROLE_QUERIES.items():
        name = await _search_for_role(company_name, role_key, queries)
        if name:
            result[role_key] = name
            logger.info("  [%s] Found: '%s'", role_key.upper(), name)
        else:
            logger.info("  [%s] Not found", role_key.upper())

    return result


async def _search_for_role(company_name: str, role_key: str, queries: list[str]) -> str:
    """Try multiple search queries for a single role and return the first name found."""
    for query_template in queries:
        query = query_template.format(company=company_name)
        logger.info("  Searching: '%s'", query)

        urls = await search_google(query, max_results=5)
        if not urls:
            logger.info("    No results for query")
            continue

        # Fetch the top result page and ask LLM to extract the name
        # We use the Google snippet text rather than fetching each page
        # to keep things fast.  We'll fetch the first result page for detail.
        for url in urls[:2]:  # Check top 2 results
            if "linkedin.com" in url or "facebook.com" in url:
                continue  # Skip social media pages
            name = await _extract_name_from_url(url, company_name, role_key)
            if name:
                return name

    return ""


async def _extract_name_from_url(url: str, company: str, role_key: str) -> str | None:
    """
    Fetch *url* and ask the LLM to extract the person's name for *role_key*
    at *company*.
    """
    from tools.scraper import fetch_page_text

    logger.debug("    Fetching %s for name extraction ...", url)
    content = await fetch_page_text(url)
    if not content:
        return None

    # Truncate to avoid excessive token usage
    content = content[:5000]

    role_display = role_key.replace("_", " ").upper()
    prompt = (
        f"From the following web page content, find the name of the {role_display} "
        f"of '{company}'. Return ONLY the person's full name, nothing else. "
        f"If you cannot find it, return 'UNKNOWN'.\n\n"
        f"Page content:\n{content}"
    )

    try:
        result = await llm.ask_async(prompt)
        result = result.strip().strip('"').strip("'")
        if result.upper() == "UNKNOWN" or not result:
            return None
        # Basic sanity: name should be at least 2 words
        words = result.split()
        if len(words) >= 2 and len(result) < 100:
            return result
        return None
    except Exception as exc:
        logger.warning("    LLM name extraction failed: %s", exc)
        return None
