"""
LinkedIn company URL finder with fallback chain and LLM validation.

Fallback order:
1. Google search via crawl4AI (site:linkedin.com/company "{name}")
2. Linkup API
3. LLM direct knowledge (final fallback)

After each successful result, the candidate URL is validated by the LLM.
If validation fails, the next fallback is tried.

NOTES for the user:
- linkedin-scraper-no-selenium is NOT used here because it requires a LinkedIn
  company URL as input — it cannot help find one.
- LinkedIn credentials are configured via LINKEDIN_LI_AT and LINKEDIN_JSESSIONID
  in the .env file (used later in Phase 5 for employee lookups).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config import config
from llm import llm
from tools.scraper import search_google

logger = logging.getLogger(__name__)


# ── Public entry point ──────────────────────────────────────────────────────

async def find_linkedin_company(company_name: str) -> str:
    """
    Find the LinkedIn company page URL for *company_name*.

    Returns the URL as a string, or ``"LinkedIn not found"`` if all fallbacks
    and validation fail.
    """
    logger.info("=" * 60)
    logger.info("Finding LinkedIn company page for: '%s'", company_name)
    logger.info("=" * 60)

    # ── Fallback 1: Google search ───────────────────────────────────────────
    candidate = await _fallback_google(company_name)
    if candidate and await _validate_company_url(candidate, company_name):
        logger.info("[OK] Google returned validated URL: %s", candidate)
        return candidate

    # ── Fallback 2: Linkup API ──────────────────────────────────────────────
    candidate = await _fallback_linkup(company_name)
    if candidate and await _validate_company_url(candidate, company_name):
        logger.info("[OK] Linkup returned validated URL: %s", candidate)
        return candidate

    # ── Fallback 3: LLM direct knowledge ────────────────────────────────────
    candidate = await _fallback_llm_knowledge(company_name)
    if candidate and await _validate_company_url(candidate, company_name):
        logger.info("[OK] LLM knowledge returned validated URL: %s", candidate)
        return candidate

    logger.warning("[FAIL] All fallbacks exhausted for '%s'", company_name)
    return "LinkedIn not found"


# ── Fallback implementations ────────────────────────────────────────────────

async def _fallback_google(company_name: str) -> str | None:
    """Search ``site:linkedin.com/company "{company}"`` via Google."""
    query = f'site:linkedin.com/company "{company_name}"'
    logger.info("Fallback 1 [Google]: searching for '%s'", query)
    urls = await search_google(query, max_results=5)
    for url in urls:
        if "linkedin.com/company/" in url:
            clean = url.split("?")[0].rstrip("/")
            logger.info("  Google returned: %s", clean)
            return clean
    logger.info("  Google found no LinkedIn company URLs")
    return None


async def _fallback_linkup(company_name: str) -> str | None:
    """Call the Linkup API to get the company's LinkedIn URL."""
    logger.info("Fallback 2 [Linkup]: looking up '%s'", company_name)
    if not config.linkup_api_key:
        logger.warning("  LINKUP_API_KEY not set, skipping")
        return None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Linkup API endpoint — adjust based on their actual spec
            resp = await client.post(
                "https://api.linkup.com/v1/company/search",
                headers={
                    "Authorization": f"Bearer {config.linkup_api_key}",
                    "Content-Type": "application/json",
                },
                json={"name": company_name, "include_linkedin": True},
            )
            if resp.status_code != 200:
                logger.warning("  Linkup returned status %d", resp.status_code)
                return None

            data = resp.json()
            url = data.get("linkedin_url") or data.get("company", {}).get("linkedin_url")
            if url:
                clean = url.split("?")[0].rstrip("/")
                logger.info("  Linkup returned: %s", clean)
                return clean
            logger.info("  Linkup returned no LinkedIn URL in response")
            return None
    except Exception as exc:
        logger.warning("  Linkup API call failed: %s", exc)
        return None


async def _fallback_llm_knowledge(company_name: str) -> str | None:
    """Ask the LLM directly if it knows the LinkedIn company URL."""
    logger.info("Fallback 3 [LLM knowledge]: asking about '%s'", company_name)
    prompt = (
        f"What is the LinkedIn company page URL for '{company_name}'? "
        f"Return ONLY the full URL starting with https://, nothing else. "
        f"If you don't know, return 'UNKNOWN'."
    )
    try:
        result = await llm.ask_async(prompt)
        result = result.strip().strip('"').strip("'")
        if result.upper() == "UNKNOWN" or "linkedin.com/company/" not in result:
            logger.info("  LLM does not know the LinkedIn URL")
            return None
        clean = result.split("?")[0].rstrip("/")
        logger.info("  LLM knowledge returned: %s", clean)
        return clean
    except Exception as exc:
        logger.warning("  LLM knowledge call failed: %s", exc)
        return None


# ── LLM Validation ──────────────────────────────────────────────────────────

async def _validate_company_url(candidate_url: str, company_name: str) -> bool:
    """
    Ask the LLM to validate that *candidate_url* is the correct LinkedIn
    company page for *company_name*.
    """
    prompt = (
        f"Does this LinkedIn URL '{candidate_url}' appear to be the correct "
        f"company page for '{company_name}'? Answer with exactly YES or NO, "
        f"then optionally a short explanation on the next line."
    )
    try:
        result = await llm.ask_async(prompt)
        result_upper = result.strip().upper()
        if result_upper.startswith("YES"):
            logger.info("  LLM Validation: YES for %s -> %s", company_name, candidate_url)
            return True
        logger.info("  LLM Validation: NO for %s -> %s (reason: %s)", company_name, candidate_url, result[:100])
        return False
    except Exception as exc:
        logger.warning("  LLM validation call failed, accepting URL by default: %s", exc)
        return True  # Default to accepting on validation failure
