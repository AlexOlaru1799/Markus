"""
LinkedIn people profile finder — given a person's name + company, find their
LinkedIn profile URL using a fallback chain with LLM validation.

Fallback order:
1. Google search via crawl4AI (site:linkedin.com/in "{name}" "{company}")
2. linkedin-scraper-no-selenium — uses LinkedIn's internal GraphQL API with
   your session cookies to find all employees, then filters for target names.
3. Linkup API
4. LLM direct knowledge (final fallback)

CREDENTIALS (set in .env):
  LINKEDIN_LI_AT       — Your LinkedIn session cookie (li_at)
  LINKEDIN_JSESSIONID  — Your LinkedIn JSESSIONID value
  LINKUP_API_KEY       — Linkup API key

After each successful result, the candidate URL is validated by the LLM.
"""

from __future__ import annotations

import csv
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import httpx

from config import config
from llm import llm
from tools.scraper import search_google

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

    # ── Phase 5a: Bulk employee lookup (linkedin-scraper) ──────────────────
    # If we have the LinkedIn company URL and credentials, try to fetch all
    # employees at once via linkedin-scraper-no-selenium.  This builds a
    # lookup dict {name_lower: profile_url} so individual lookups below can
    # use it.
    employee_lookup: dict[str, str] = {}
    if company_linkedin_url and "linkedin.com/company/" in company_linkedin_url.lower():
        try:
            logger.info("Bulk employee lookup via linkedin-scraper for %s", company_linkedin_url)
            employee_lookup = await _fetch_employees_bulk(company_linkedin_url)
            logger.info("  Found %d employees via bulk lookup", len(employee_lookup))
        except Exception as exc:
            logger.warning("  Bulk employee lookup failed: %s", exc)

    # ── Phase 5b: Individual profile lookups ───────────────────────────────
    result: dict[str, dict[str, str]] = {}

    for role_key, person_name in people_names.items():
        if not person_name:
            logger.info("  [%s] No name provided, skipping", role_key.upper())
            result[role_key] = {"name": "", "url": ""}
            continue

        role_label = ROLE_LABELS.get(role_key, role_key.upper())
        logger.info("  Looking up: %s (%s) at %s", person_name, role_label, company_name)

        # Check bulk lookup first (fastest path)
        person_key = person_name.strip().lower()
        if person_key in employee_lookup:
            profile_url = employee_lookup[person_key]
            logger.info("    [OK] Found in bulk employee results: %s", profile_url)
            result[role_key] = {"name": person_name, "url": profile_url}
            continue

        # Fall through to individual fallback chain
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
    Use linkedin-scraper-no-selenium's logic to fetch all employees of a
    company, returning ``{lowercased_name: profile_url}``.

    This clones the repo if not already present, writes a temporary script
    with the correct configuration, runs it, and parses the CSV output.
    """
    # Step 1: Ensure the linkedin-scraper repo is cloned
    if not LINKEDIN_SCRAPER_SCRIPT.exists():
        logger.info("  Cloning linkedin-scraper repo to %s ...", LINKEDIN_SCRAPER_DIR)
        try:
            subprocess.run(
                ["git", "clone", LINKEDIN_SCRAPER_REPO, str(LINKEDIN_SCRAPER_DIR)],
                check=True,
                capture_output=True,
                timeout=60,
            )
            logger.info("  Clone successful")
        except Exception as exc:
            logger.warning("  Failed to clone linkedin-scraper repo: %s", exc)
            return {}

    # Step 2: Check we have LinkedIn credentials
    if not config.linkedin_li_at or not config.linkedin_jsessionid:
        logger.warning("  LINKEDIN_LI_AT or LINKEDIN_JSESSIONID not set, skipping bulk lookup")
        logger.warning("  See .env.example for instructions on getting these values")
        return {}

    # Step 3: Create a temporary CSV output path
    tmp_csv = tempfile.mktemp(suffix=".csv", prefix="linkedin_leads_")

    # Step 4: Write a temporary runner script with the correct configuration.
    scraper_path_repr = repr(str(LINKEDIN_SCRAPER_DIR))
    runner_code = f"""import sys
sys.path.insert(0, {scraper_path_repr})

import __main__
__main__.company_link = {company_linkedin_url!r}
__main__.cookies = {config.linkedin_cookie_string!r}
__main__.output_file_name = {tmp_csv!r}

from Leade_generation import LinkedIn

company_id = LinkedIn.getCompanyID()
if company_id:
    linkedin = LinkedIn()
    linkedin.paginateResults(company_id)
"""

    runner_path = tempfile.mktemp(suffix=".py", prefix="linkedin_runner_")
    try:
        with open(runner_path, "w") as f:
            f.write(runner_code)

        logger.info("  Running linkedin-scraper for %s ...", company_linkedin_url)
        result = subprocess.run(
            [sys.executable, runner_path],
            capture_output=True,
            timeout=120,
        )

        if result.returncode != 0:
            logger.warning("  linkedin-scraper exited with code %d", result.returncode)
            stderr = result.stderr.decode("utf-8", errors="replace")[:500]
            if stderr:
                logger.warning("  stderr: %s", stderr)
            return {}

        # Step 5: Parse the CSV output
        if not os.path.exists(tmp_csv):
            logger.warning("  linkedin-scraper produced no output file")
            stdout = result.stdout.decode("utf-8", errors="replace")[:500]
            if stdout:
                logger.info("  stdout: %s", stdout)
            return {}

        employee_map: dict[str, str] = {}
        with open(tmp_csv, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = (row.get("Name") or "").strip()
                profile_link = (row.get("Profile Link") or "").strip()
                if name and profile_link:
                    employee_map[name.lower()] = profile_link

        logger.info("  Parsed %d employees from CSV", len(employee_map))
        return employee_map

    except subprocess.TimeoutExpired:
        logger.warning("  linkedin-scraper timed out after 120s")
        return {}
    except Exception as exc:
        logger.warning("  linkedin-scraper bulk lookup failed: %s", exc)
        return {}
    finally:
        # Clean up temp files
        for tmp in [tmp_csv, runner_path]:
            try:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            except Exception:
                pass


# ── Individual fallback chain ────────────────────────────────────────────────

async def _find_single_profile(
    person_name: str,
    company_name: str,
    role_label: str,
) -> str | None:
    """Try all fallbacks for a single person and return the validated LinkedIn URL."""

    # ── Fallback 1: Google search ───────────────────────────────────────────
    candidate = await _fallback_google_profile(person_name, company_name)
    if candidate and await _validate_profile_url(candidate, person_name, company_name):
        return candidate

    # ── Fallback 2: Linkup API ──────────────────────────────────────────────
    candidate = await _fallback_linkup_profile(person_name, company_name)
    if candidate and await _validate_profile_url(candidate, person_name, company_name):
        return candidate

    # ── Fallback 3: LLM direct knowledge ────────────────────────────────────
    candidate = await _fallback_llm_knowledge_profile(person_name, company_name)
    if candidate and await _validate_profile_url(candidate, person_name, company_name):
        return candidate

    return None


# ── Fallback implementations ────────────────────────────────────────────────

async def _fallback_google_profile(person_name: str, company_name: str) -> str | None:
    """Search ``site:linkedin.com/in "{name}" "{company}"``."""
    query = f'site:linkedin.com/in "{person_name}" "{company_name}"'
    logger.info("  Fallback 1 [Google]: %s", query)
    urls = await search_google(query, max_results=5)
    for url in urls:
        if "linkedin.com/in/" in url:
            clean = url.split("?")[0].rstrip("/")
            logger.info("    Google returned: %s", clean)
            return clean
    return None


async def _fallback_linkup_profile(person_name: str, company_name: str) -> str | None:
    """Call Linkup API to find the person's LinkedIn profile."""
    logger.info("  Fallback 2 [Linkup]: %s / %s", person_name, company_name)
    if not config.linkup_api_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.linkup.com/v1/people/search",
                headers={
                    "Authorization": f"Bearer {config.linkup_api_key}",
                    "Content-Type": "application/json",
                },
                json={"name": person_name, "company": company_name},
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            url = data.get("linkedin_url") or data.get("profile", {}).get("linkedin_url")
            if url:
                clean = url.split("?")[0].rstrip("/")
                logger.info("    Linkup returned: %s", clean)
                return clean
            return None
    except Exception as exc:
        logger.warning("    Linkup API call failed: %s", exc)
        return None


async def _fallback_llm_knowledge_profile(person_name: str, company_name: str) -> str | None:
    """Ask the LLM directly if it knows the LinkedIn profile URL."""
    logger.info("  Fallback 3 [LLM knowledge]: %s / %s", person_name, company_name)
    prompt = (
        f"What is the LinkedIn profile URL for {person_name} who works at "
        f"{company_name}? Return ONLY the full URL starting with https://, "
        f"nothing else. If you don't know, return 'UNKNOWN'."
    )
    try:
        result = await llm.ask_async(prompt)
        result = result.strip().strip('"').strip("'")
        if result.upper() == "UNKNOWN" or "linkedin.com/in/" not in result:
            return None
        clean = result.split("?")[0].rstrip("/")
        logger.info("    LLM knowledge returned: %s", clean)
        return clean
    except Exception as exc:
        logger.warning("    LLM knowledge call failed: %s", exc)
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
