"""
LinkedIn company URL finder with fallback chain and LLM validation.

Fallback order (no Google — always triggers CAPTCHA):
1. Linkup API
2. LLM direct knowledge (final fallback)

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

    # ── Fallback 1: Linkup API ──────────────────────────────────────────────
    candidate = await _fallback_linkup(company_name)
    if candidate and await _validate_company_url(candidate, company_name):
        logger.info("[OK] Linkup returned validated URL: %s", candidate)
        return candidate

    # ── Fallback 2: LLM direct knowledge ────────────────────────────────────
    candidate = await _fallback_llm_knowledge(company_name)
    if candidate and await _validate_company_url(candidate, company_name):
        logger.info("[OK] LLM knowledge returned validated URL: %s", candidate)
        return candidate

    logger.warning("[FAIL] All fallbacks exhausted for '%s'", company_name)
    return "LinkedIn not found"


# ── Fallback implementations ────────────────────────────────────────────────


async def _fallback_linkup(company_name: str) -> str | None:
    """Call the LinkUp API to get the company's LinkedIn URL.

    Uses ``site:linkedin.com/company`` search operator.
    """
    logger.info("Fallback 1 [LinkUp]: looking up '%s'", company_name)
    if not config.linkup_api_key:
        logger.warning("  LINKUP_API_KEY not set, skipping")
        return None

    query = f'site:linkedin.com/company "{company_name}"'
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.linkup.so/v1/search",
                headers={
                    "Authorization": f"Bearer {config.linkup_api_key}",
                    "Content-Type": "application/json",
                },
                json={"q": query, "depth": "fast", "outputType": "searchResults", "count": 5},
            )
            if resp.status_code != 200:
                logger.warning("  LinkUp returned status %d", resp.status_code)
                return None

            data = resp.json()
            results = data.get("results", [])
            for item in results:
                url = (item.get("url") or "").strip()
                if url and "/company/" in url:
                    clean = url.split("?")[0].rstrip("/")
                    # Normalise country subdomain → www (e.g. ro.linkedin.com → www.linkedin.com)
                    if clean.startswith("https://") and ".linkedin.com" in clean:
                        subdomain = clean.split("://", 1)[1].split(".linkedin.com")[0]
                        if subdomain != "www" and "." not in subdomain:
                            clean = clean.replace(f"https://{subdomain}.linkedin.com", "https://www.linkedin.com")
                    logger.info("  LinkUp returned: %s", clean)
                    return clean
            logger.info("  LinkUp returned no LinkedIn URL in response")
            return None
    except Exception as exc:
        logger.warning("  LinkUp API call failed: %s", exc)
        return None


async def _fallback_llm_knowledge(company_name: str) -> str | None:
    """Ask the LLM directly — with a confidence check to prevent hallucination."""
    logger.info("Fallback 2 [LLM knowledge]: asking about '%s'", company_name)

    # Stage 1: Confidence check
    check_prompt = (
        f"Do you actually know the specific LinkedIn company page URL for "
        f"'{company_name}'? ONLY answer YES if you are absolutely certain "
        f"and can provide the exact URL. Answer NO if you would be guessing "
        f"or are unsure.\n\nAnswer (YES/NO):"
    )
    try:
        stage1 = await llm.ask_async(check_prompt)
        if not stage1.strip().upper().startswith("YES"):
            logger.info("  Stage 1 [confidence]: LLM is not confident — skipping")
            return None
        logger.info("  Stage 1 [confidence]: passed")
    except Exception as exc:
        logger.warning("  Stage 1 [confidence] failed: %s", exc)
        return None

    # Stage 2: URL extraction
    prompt = (
        f"What is the LinkedIn company page URL for '{company_name}'? "
        f"Return ONLY the full URL starting with https://, nothing else. "
        f"If you don't know, return 'UNKNOWN'."
    )
    try:
        result = await llm.ask_async(prompt)
        result = result.strip().strip('"').strip("'")
        if result.upper() == "UNKNOWN" or "linkedin.com/company/" not in result:
            logger.info("  Stage 2 [extraction]: LLM does not know the LinkedIn URL")
            return None
        clean = result.split("?")[0].rstrip("/")
        logger.info("  Stage 2 [extraction]: %s", clean)
        return clean
    except Exception as exc:
        logger.warning("  Stage 2 [extraction] failed: %s", exc)
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
