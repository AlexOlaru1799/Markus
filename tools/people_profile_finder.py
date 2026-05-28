"""
LinkedIn people profile finder — given a person's name + company, find their
LinkedIn profile URL using a fallback chain with LLM validation.

Fallback order:
1. linkedin-scraper-no-selenium — uses LinkedIn's internal GraphQL API with
   your session cookies to find all employees, then filters for target names.
2. Linkup API
3. LLM direct knowledge (final fallback)

CREDENTIALS (set in .env):
  LINKEDIN_LI_AT       — Your LinkedIn session cookie (li_at)
  LINKEDIN_JSESSIONID  — Your LinkedIn JSESSIONID value
  LINKUP_API_KEY       — Linkup API key

After each successful result, the candidate URL is validated by the LLM.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx

from config import config
from llm import llm

logger = logging.getLogger(__name__)

# Roles we care about
ROLE_LABELS: dict[str, str] = {
    "ceo": "CEO",
    "cfo": "CFO",
    "director_general": "Director General",
}

# ── Path where we clone the linkedin-scraper-no-selenium repo ──────────────
LINKEDIN_SCRAPER_DIR = Path(__file__).resolve().parent.parent / "linkedin-scraper"
LINKEDIN_SCRAPER_REPO = "https://github.com/Mahdi-hasan-shuvo/linkedin-scraper.git"
LINKEDIN_SCRAPER_SCRIPT = LINKEDIN_SCRAPER_DIR / "Leade_generation.py"


# ── Public entry point ──────────────────────────────────────────────────────

async def find_people_profiles(
    company_name: str,
    people_names: dict[str, str],
    company_linkedin_url: str = "",
) -> dict[str, dict[str, str]]:
    """
    Find LinkedIn profile URLs for each named person at *company_name*.

    Parameters
    ----------
    company_name : str
        The company the person works for.
    people_names : dict[str, str]
        Mapping of role keys to person names, e.g.
        ``{"ceo": "John Doe", "cfo": "", "director_general": "Jane Smith"}``
    company_linkedin_url : str
        The company's LinkedIn page URL (needed for Fallback 2).

    Returns
    -------
    dict[str, dict[str, str]]
        ``{"ceo": {"name": "John Doe", "url": "https://..."}, ...}``
    """
    logger.info("=" * 60)
    logger.info("Finding LinkedIn profiles for %s", company_name)
    logger.info("=" * 60)

    # ── Individual profile lookups ─────────────────────────────────────────
    # Bulk employee lookup (linkedin-scraper-no-selenium) was removed — it
    # always failed 100% of the time (unauthenticated request → login page).
    # LinkUp API per-person fallback works in 2-3 seconds.
    result: dict[str, dict[str, str]] = {}

    for role_key, person_name in people_names.items():
        if not person_name:
            logger.info("  [%s] No name provided, skipping", role_key.upper())
            result[role_key] = {"name": "", "url": ""}
            continue

        role_label = ROLE_LABELS.get(role_key, role_key.upper())
        logger.info("  Looking up: %s (%s) at %s", person_name, role_label, company_name)

        # Fallback chain: LinkUp → LLM knowledge
        profile_url = await _find_single_profile(person_name, company_name, role_label)
        result[role_key] = {"name": person_name, "url": profile_url or ""}

        if profile_url:
            logger.info("    [OK] %s -> %s", person_name, profile_url)
        else:
            logger.info("    [FAIL] No LinkedIn profile found for %s", person_name)

    return result


# ── Bulk employee lookup via linkedin-scraper-no-selenium ────────────────────

async def _fetch_employees_bulk(company_linkedin_url: str) -> dict[str, str]:
    """
    Bulk employee lookup — **disabled**.
    
    linkedin-scraper-no-selenium's ``getCompanyID()`` makes an unauthenticated
    request (no cookies), so LinkedIn returns a login-wall page and the
    ``objectUrn`` regex never matches → always "Company ID not found" or
    120-second timeout.
    
    The LinkUp API fallback (called per-person below) works in 2-3 seconds, so
    we skip this entirely to save ~120s × 38 companies ≈ 76 minutes per run.
    
    To re-enable: restore the original implementation (git log for details).
    """
    logger.info("  Bulk employee lookup disabled — skipping (will use LinkUp per-person fallback)")
    return {}


# ── Individual fallback chain ────────────────────────────────────────────────

async def _find_single_profile(
    person_name: str,
    company_name: str,
    role_label: str,
) -> str | None:
    """Try all fallbacks for a single person and return the validated LinkedIn URL."""

    # ── Fallback 1: Linkup API ──────────────────────────────────────────────
    candidate = await _fallback_linkup_profile(person_name, company_name)
    if candidate and await _validate_profile_url(candidate, person_name, company_name):
        return candidate

    # ── Fallback 2: LLM direct knowledge ────────────────────────────────────
    candidate = await _fallback_llm_knowledge_profile(person_name, company_name)
    if candidate and await _validate_profile_url(candidate, person_name, company_name):
        return candidate

    return None


# ── Fallback implementations ────────────────────────────────────────────────


async def _fallback_linkup_profile(person_name: str, company_name: str) -> str | None:
    """Call LinkUp API to find the person's LinkedIn profile.

    Uses ``site:linkedin.com/in`` search operator to find the profile URL.
    """
    logger.info("  Fallback 1 [LinkUp]: %s / %s", person_name, company_name)
    if not config.linkup_api_key:
        return None

    query = f'site:linkedin.com/in "{person_name}" "{company_name}"'
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
                return None

            data = resp.json()
            results = data.get("results", [])
            for item in results:
                url = (item.get("url") or "").strip()
                if url and "/in/" in url:
                    clean = url.split("?")[0].rstrip("/")
                    # Normalise country subdomain → www (e.g. ca.linkedin.com → www.linkedin.com)
                    if clean.startswith("https://") and ".linkedin.com" in clean:
                        subdomain = clean.split("://", 1)[1].split(".linkedin.com")[0]
                        if subdomain != "www" and "." not in subdomain:
                            clean = clean.replace(f"https://{subdomain}.linkedin.com", "https://www.linkedin.com")
                    logger.info("    LinkUp returned: %s", clean)
                    return clean
            logger.info("    LinkUp returned no matching profile")
            return None
    except Exception as exc:
        logger.warning("    LinkUp API call failed: %s", exc)
        return None


async def _fallback_llm_knowledge_profile(person_name: str, company_name: str) -> str | None:
    """Ask the LLM directly — with a two-stage hallucination guard.

    Stage 1 — Confidence check: LLM must assert it knows this person's profile.
    Stage 2 — URL extraction: only if Stage 1 passes.
    """
    logger.info("  Fallback 2 [LLM knowledge]: %s / %s", person_name, company_name)

    # Stage 1: Confidence check
    check_prompt = (
        f"Do you actually know the specific LinkedIn profile URL for "
        f"'{person_name}' who works at '{company_name}'? "
        f"ONLY answer YES if you are absolutely certain and can provide "
        f"the exact URL. Answer NO if you would be guessing.\n\n"
        f"Answer (YES/NO):"
    )
    try:
        stage1 = await llm.ask_async(check_prompt)
        if not stage1.strip().upper().startswith("YES"):
            logger.info("    Stage 1 [confidence]: LLM is not confident — skipping")
            return None
        logger.info("    Stage 1 [confidence]: passed")
    except Exception as exc:
        logger.warning("    Stage 1 [confidence] failed: %s", exc)
        return None

    # Stage 2: URL extraction
    prompt = (
        f"What is the LinkedIn profile URL for {person_name} who works at "
        f"{company_name}? Return ONLY the full URL starting with https://, "
        f"nothing else. If you don't know, return 'UNKNOWN'."
    )
    try:
        result = await llm.ask_async(prompt)
        result = result.strip().strip('"').strip("'")
        if result.upper() == "UNKNOWN" or "linkedin.com/in/" not in result:
            logger.info("    Stage 2 [extraction]: no valid URL returned")
            return None
        clean = result.split("?")[0].rstrip("/")
        logger.info("    Stage 2 [extraction]: %s", clean)
        return clean
    except Exception as exc:
        logger.warning("    Stage 2 [extraction] failed: %s", exc)
        return None


# ── LLM Validation ──────────────────────────────────────────────────────────

async def _validate_profile_url(
    candidate_url: str,
    person_name: str,
    company_name: str,
) -> bool:
    """Ask the LLM to validate the candidate profile URL."""
    prompt = (
        f"Does this LinkedIn profile URL '{candidate_url}' appear to belong to "
        f"'{person_name}' who works at '{company_name}'? "
        f"Answer with exactly YES or NO, then optionally a short explanation."
    )
    try:
        result = await llm.ask_async(prompt)
        if result.strip().upper().startswith("YES"):
            logger.info("    LLM Validation: YES for %s -> %s", person_name, candidate_url)
            return True
        logger.info("    LLM Validation: NO for %s -> %s", person_name, candidate_url)
        return False
    except Exception as exc:
        logger.warning("    LLM validation failed, accepting URL by default: %s", exc)
        return True
