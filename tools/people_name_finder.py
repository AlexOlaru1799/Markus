"""
People name finder — determine C-suite names by company using Linkup + LLM.

Fallback order (no Google — always triggers CAPTCHA):
1. Linkup API (enterprise people search)
2. LLM direct knowledge: ask DeepSeek who the CEO/CFO/Director General is

ARCHITECTURE NOTE — Hallucination guard:
The LLM knowledge fallback was previously hallucinating executive names for
small/obscure companies (e.g. assigning "Ryan Roslansky" — LinkedIn's CEO — to
"Skilld", a Romanian company). The fix uses a three-stage gate:
  Stage 1 — Confidence check: LLM must assert it has specific knowledge
  Stage 2 — Name extraction: only if Stage 1 passes
  Stage 3 — Verification: cross-check name with a fresh LLM call
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config import config
from llm import llm

logger = logging.getLogger(__name__)

# Roles we look for
ROLES: dict[str, str] = {
    "ceo": "CEO (Chief Executive Officer) or Director General",
    "cfo": "CFO (Chief Financial Officer) or Director Financiar",
    "director_general": "Director General (General Manager)",
}


async def find_people_names(
    company_name: str,
    company_linkedin_url: str = "",
) -> dict[str, str]:
    """
    Determine the names of C-suite executives at *company_name*.

    Parameters
    ----------
    company_name : str
        The company name to search for.
    company_linkedin_url : str
        The company's LinkedIn page URL from Phase 3 (used to improve LinkUp
        search queries). Pass empty string if unavailable.

    Returns
    -------
    dict[str, str]
        ``{"ceo": "Name or empty", "cfo": "Name or empty", "director_general": "Name or empty"}``
    """
    logger.info("=" * 60)
    logger.info("Finding people names for: '%s'", company_name)
    if company_linkedin_url:
        logger.info("  LinkedIn URL context: %s", company_linkedin_url)
    logger.info("=" * 60)

    result: dict[str, str] = {"ceo": "", "cfo": "", "director_general": ""}

    for role_key, role_desc in ROLES.items():
        name = await _find_single_name(company_name, role_key, role_desc, company_linkedin_url)
        if name:
            result[role_key] = name
            logger.info("  [%s] Found: '%s'", role_key.upper(), name)
        else:
            logger.info("  [%s] Not found", role_key.upper())

    return result


async def _find_single_name(
    company_name: str,
    role_key: str,
    role_desc: str,
    company_linkedin_url: str = "",
) -> str:
    """Try Linkup then LLM for a single role."""

    # ── Fallback 1: Linkup API ──────────────────────────────────────────────
    name = await _fallback_linkup(company_name, role_key, role_desc, company_linkedin_url)
    if name:
        return name

    # ── Fallback 2: LLM direct knowledge ────────────────────────────────────
    name = await _fallback_llm_knowledge(company_name, role_key, role_desc)
    if name:
        return name

    return ""


async def _fallback_linkup(
    company_name: str,
    role_key: str,
    role_desc: str,
    company_linkedin_url: str = "",
) -> str | None:
    """Call LinkUp API to find the person's name.

    Searches for LinkedIn profiles matching the company and role,
    then extracts the person name from LinkUp's ``name`` field.

    When *company_linkedin_url* is available, also tries a second query
    scoped to the company's LinkedIn slug (e.g. ``"skilld"`` instead of
    the full company name ``"Skilld by eJobs"``).
    """
    logger.info("  Fallback 1 [LinkUp]: %s for '%s'", role_key.upper(), company_name)
    if not config.linkup_api_key:
        logger.warning("    LINKUP_API_KEY not set, skipping")
        return None

    # Build the list of queries to try (most specific first)
    queries: list[str] = [
        f'site:linkedin.com/in "{company_name}" "{role_desc}"',
    ]

    # Query: extract LinkedIn slug if URL is available
    if company_linkedin_url and "/company/" in company_linkedin_url:
        slug = company_linkedin_url.split("/company/")[-1].split("/")[0].split("?")[0]
        if slug and slug != company_name.lower().replace(" ", "-"):
            queries.append(f'site:linkedin.com/in "{slug}" "{role_desc}"')

    # Query: try short role keyword (CEO/CFO) instead of long description
    short_role = role_key.upper()
    queries.append(f'site:linkedin.com/in "{company_name}" "{short_role}"')

    # Query: try without LinkedIn site restriction as last resort
    queries.append(f'"{company_name}" "{short_role}" linkedin.com/in')

    for q_idx, query in enumerate(queries):
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
                    logger.warning("    LinkUp query %d returned status %d", q_idx + 1, resp.status_code)
                    continue

                data = resp.json()
                results = data.get("results", [])
                for item in results:
                    raw_name = (item.get("name") or "").strip()
                    url = (item.get("url") or "").strip()
                    if not raw_name or not url or "/in/" not in url:
                        continue
                    # Clean LinkedIn page titles like "Name - Title | Company | LinkedIn"
                    # Handle en-dash, em-dash, and regular hyphen
                    name = raw_name.split(" | ")[0]
                    for sep in (" \u2013 ", " \u2014 ", " - "):
                        name = name.split(sep)[0]
                    name = name.strip()
                    if name and len(name) <= 60:
                        logger.info("    LinkUp query %d returned: '%s' (from '%s')", q_idx + 1, name, raw_name)
                        return name
                logger.info("    LinkUp query %d returned no matching profile", q_idx + 1)
        except Exception as exc:
            logger.warning("    LinkUp query %d failed: %s", q_idx + 1, exc)
            continue

    return None


async def _fallback_llm_knowledge(company_name: str, role_key: str, role_desc: str) -> str | None:
    """Ask the LLM directly — with a three-stage hallucination guard.

    Stage 1 — Confidence check: LLM must assert it has specific knowledge.
    Stage 2 — Name extraction: only if Stage 1 passes.
    Stage 3 — Verification: cross-check name with a fresh LLM call.

    This prevents the LLM from fabricating executive names for companies it
    does not actually know about (e.g. assigning LinkedIn's CEO to a small
    Romanian company).
    """
    logger.info("  Fallback 2 [LLM knowledge]: %s for '%s'", role_key.upper(), company_name)

    # Stage 1: Confidence check
    check_prompt = (
        f"Company: '{company_name}'\n"
        f"Role: {role_desc}\n\n"
        f"Does your training data contain specific, verifiable information about "
        f"who the {role_desc} is at '{company_name}'? "
        f"This is a company that may be small, medium, or located in Romania. "
        f"ONLY answer YES if you are absolutely certain and have specific knowledge "
        f"of this specific executive at this specific company. "
        f"Answer NO if you are unsure, would be guessing, or only know about "
        f"a similarly-named company.\n\n"
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

    # Stage 2: Name extraction
    name_prompt = (
        f"Who is the {role_desc} of '{company_name}'? "
        f"Return ONLY the person's full name, nothing else."
    )
    try:
        result = await llm.ask_async(name_prompt)
        result = result.strip().strip('"').strip("'")
    except Exception as exc:
        logger.warning("    Stage 2 [extraction] failed: %s", exc)
        return None

    # Basic sanity: name should be at least 2 words and not too long
    words = result.split()
    if len(words) < 2 or len(result) >= 100:
        logger.info("    Stage 2 [extraction]: invalid name '%s' — rejected", result)
        return None

    # Stage 3: Verification (cross-check with fresh LLM call)
    verify_prompt = (
        f"Is '{result}' actually the real, current {role_desc} of "
        f"'{company_name}'? Do NOT just repeat what you said before — "
        f"think carefully. Answer ONLY YES or NO."
    )
    try:
        stage3 = await llm.ask_async(verify_prompt)
        if stage3.strip().upper().startswith("YES"):
            logger.info("    Stage 3 [verify]: '%s' verified at '%s'", result, company_name)
            return result
        logger.info("    Stage 3 [verify]: '%s' rejected for '%s'", result, company_name)
        return None
    except Exception as exc:
        logger.warning("    Stage 3 [verify] failed, accepting name by default: %s", exc)
        return result
