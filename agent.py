"""
ReAct-style agent loop with verbose logging.

The agent progresses through 6 sequential phases:
1. Search jobs on Romanian job boards
2. Extract company names from job content
3. Find LinkedIn company pages
4. Find people names (CEO, CFO, Director General)
5. Find LinkedIn profiles for those people
6. Write results to CSV

Every step is logged with timestamps for full traceability.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from typing import Any

from config import config
from llm import llm
from state import AgentState
from tools import (
    search_jobs,
    extract_company_name,
    find_linkedin_company,
    find_people_names,
    find_people_profiles,
    write_spreadsheet,
)

logger = logging.getLogger(__name__)


# ── Logging helper ──────────────────────────────────────────────────────────

def _log(level: str, message: str, *args: Any) -> None:
    """Print a timestamped log line to stderr."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    formatted = message % args if args else message
    print(f"[{ts}] [{level}] {formatted}", file=sys.stderr, flush=True)


def _log_phase(phase_name: str) -> None:
    """Print a prominent phase header."""
    _log("INFO", "")
    _log("INFO", "=" * 70)
    _log("INFO", f"  PHASE: {phase_name}")
    _log("INFO", "=" * 70)


# ── Agent loop ──────────────────────────────────────────────────────────────

async def run_agent(keywords: list[str]) -> AgentState:
    """
    Run the full agentic workflow.

    Parameters
    ----------
    keywords : list[str]
        Search terms for job boards.

    Returns
    -------
    AgentState
        The final state containing all results, errors, and the summary.
    """
    state = AgentState(keywords=keywords)

    _log("INFO", "Agent started with keywords: %s", keywords)
    _log("INFO", "LLM model: %s", config.llm_model)
    _log("INFO", "Output file: %s", config.output_sheet)

    # ── Phase 1: Search jobs ────────────────────────────────────────────────
    _log_phase("Phase 1: Job Search")
    state.phase = "search"

    try:
        _log("INFO", "Scraping job boards for keywords: %s", keywords)
        jobs = await search_jobs(keywords)

        # Check for CAPTCHA signal
        if jobs and isinstance(jobs, list) and len(jobs) == 1 and jobs[0].get("captcha"):
            captcha_info = jobs[0]
            _log("WARN", "CAPTCHA detected on board '%s' for keyword '%s'",
                 captcha_info.get("board", "?"), captcha_info.get("keyword", "?"))
            _log("WARN", "Please solve the CAPTCHA in your browser, then press Enter to continue...")
            input("CAPTCHA detected. Solve it in your browser, then press Enter to continue...")
            _log("INFO", "Human confirmed CAPTCHA solved. Retrying...")
            jobs = await search_jobs(keywords)

        if jobs and isinstance(jobs, list) and len(jobs) == 1 and jobs[0].get("captcha"):
            _log("ERROR", "CAPTCHA still present after human confirmation. Skipping.")
            state.add_error("search", "CAPTCHA", "CAPTCHA persisted after human intervention")
            jobs = []

        state.jobs = [j for j in (jobs or []) if not j.get("captcha")]
        _log("INFO", "Phase 1 complete: %d job entries collected", len(state.jobs))

    except Exception as exc:
        _log("ERROR", "Job search failed: %s", exc)
        state.add_error("search", "all", str(exc))

    # ── Phase 2: Extract company names ──────────────────────────────────────
    _log_phase("Phase 2: Company Name Extraction")
    state.phase = "extract"

    # Store a mapping from company -> list of jobs (to preserve job-source links)
    company_jobs_map: dict[str, list[dict[str, Any]]] = {}

    for idx, job in enumerate(state.jobs):
        job_title = job.get("title", "?")
        job_url = job.get("url", "?")
        _log("INFO", "  [%d/%d] Extracting company from: %s", idx + 1, len(state.jobs), job_title)

        try:
            company = await extract_company_name(job.get("content", ""))
            if company and company != "UNKNOWN":
                # Store the company name directly in the job for later matching
                job["company"] = company
                if company not in company_jobs_map:
                    company_jobs_map[company] = []
                company_jobs_map[company].append(job)
                _log("INFO", "    -> Company: '%s'", company)
            else:
                _log("WARN", "    -> Could not extract company name")
                state.add_error("extract", job_url, "Unknown company")
        except Exception as exc:
            _log("ERROR", "    -> Extraction failed: %s", exc)
            state.add_error("extract", job_url, str(exc))

    companies = list(company_jobs_map.keys())
    state.companies = companies
    _log("INFO", "Phase 2 complete: %d unique companies found", len(companies))
    for c in companies:
        _log("INFO", "  - %s (%d job(s))", c, len(company_jobs_map[c]))

    # ── Phase 3: Find LinkedIn company pages ────────────────────────────────
    _log_phase("Phase 3: LinkedIn Company Search")
    state.phase = "find_company"

    linkedin_companies: dict[str, str] = {}
    for idx, company in enumerate(companies):
        _log("INFO", "  [%d/%d] Finding LinkedIn for: '%s'", idx + 1, len(companies), company)

        try:
            url = await find_linkedin_company(company)
            linkedin_companies[company] = url
            if url != "LinkedIn not found" and "linkedin.com/company" in url.lower():
                _log("INFO", "    -> LinkedIn URL: %s", url)
            else:
                _log("WARN", "    -> LinkedIn not found")
        except Exception as exc:
            _log("ERROR", "    -> Search failed: %s", exc)
            linkedin_companies[company] = "LinkedIn not found"
            state.add_error("find_company", company, str(exc))

    state.linkedin_companies = linkedin_companies
    found_count = sum(1 for v in linkedin_companies.values() if "linkedin.com" in v.lower())
    _log("INFO", "Phase 3 complete: %d/%d companies have LinkedIn pages", found_count, len(companies))

    # ── Phase 4: Find people names ──────────────────────────────────────────
    _log_phase("Phase 4: People Name Discovery")
    state.phase = "find_names"

    people_names: dict[str, dict[str, str]] = {}
    for idx, company in enumerate(companies):
        _log("INFO", "  [%d/%d] Searching for executives at: '%s'", idx + 1, len(companies), company)

        try:
            names = await find_people_names(company)
            people_names[company] = names
            _log("INFO", "    -> CEO: %s", names.get("ceo") or "(not found)")
            _log("INFO", "    -> CFO: %s", names.get("cfo") or "(not found)")
            _log("INFO", "    -> Director General: %s", names.get("director_general") or "(not found)")
        except Exception as exc:
            _log("ERROR", "    -> Name search failed: %s", exc)
            people_names[company] = {"ceo": "", "cfo": "", "director_general": ""}
            state.add_error("find_names", company, str(exc))

    state.people_names = people_names

    # ── Phase 5: Find LinkedIn profiles ─────────────────────────────────────
    _log_phase("Phase 5: LinkedIn Profile Discovery")
    state.phase = "find_profiles"

    all_records: list[dict[str, str]] = []
    for company in companies:
        names = people_names.get(company, {"ceo": "", "cfo": "", "director_general": ""})
        jobs_for_company = company_jobs_map.get(company, [])
        linkedin_company_url = linkedin_companies.get(company, "")

        _log("INFO", "  Processing profiles for: '%s' (%d job source(s))", company, len(jobs_for_company))
        if linkedin_company_url and "linkedin.com/company" in linkedin_company_url.lower():
            _log("INFO", "    LinkedIn company URL: %s", linkedin_company_url)

        try:
            profiles = await find_people_profiles(company, names, linkedin_company_url)
            _log("INFO", "    -> CEO profile: %s", profiles.get("ceo", {}).get("url") or "(not found)")
            _log("INFO", "    -> CFO profile: %s", profiles.get("cfo", {}).get("url") or "(not found)")
            _log("INFO", "    -> Director General profile: %s", profiles.get("director_general", {}).get("url") or "(not found)")

            # Build one record per job source URL for this company
            if not jobs_for_company:
                record = _build_record(company, profiles, "", keywords[0] if keywords else "")
                all_records.append(record)
            else:
                for job in jobs_for_company:
                    record = _build_record(
                        company,
                        profiles,
                        job.get("url", ""),
                        job.get("search_keyword", keywords[0] if keywords else ""),
                    )
                    all_records.append(record)

        except Exception as exc:
            _log("ERROR", "    -> Profile search failed: %s", exc)
            state.add_error("find_profiles", company, str(exc))

    state.people_profiles = all_records
    _log("INFO", "Phase 5 complete: %d records built", len(all_records))

    # ── Phase 6: Write to spreadsheet ───────────────────────────────────────
    _log_phase("Phase 6: Writing to Spreadsheet")
    state.phase = "write"

    if all_records:
        try:
            confirmation = await write_spreadsheet(all_records)
            _log("INFO", "Write result: %s", confirmation)
        except Exception as exc:
            _log("ERROR", "Write failed: %s", exc)
            state.add_error("write", config.output_sheet, str(exc))
    else:
        _log("WARN", "No records to write — skipping spreadsheet output.")

    # ── Done ────────────────────────────────────────────────────────────────
    state.phase = "done"
    state.done = True

    _log_phase("EXECUTION COMPLETE")
    _log("INFO", "Summary:")
    _log("INFO", "  Jobs scraped:      %d", len(state.jobs))
    _log("INFO", "  Companies found:   %d", len(state.companies))
    _log("INFO", "  LinkedIn found:    %d", found_count)
    _log("INFO", "  Records written:   %d", len(all_records))
    _log("INFO", "  Errors:            %d", len(state.errors))

    if state.errors:
        _log("WARN", "Error log:")
        for err in state.errors:
            _log("WARN", "  [%s] %s: %s", err["step"], err["context"], err["detail"])

    return state


# ── Helpers ─────────────────────────────────────────────────────────────────

def _build_record(
    company: str,
    profiles: dict[str, dict[str, str]],
    job_url: str,
    keyword: str,
) -> dict[str, str]:
    """Build a single CSV record dict from the available data."""
    ceo = profiles.get("ceo", {})
    cfo = profiles.get("cfo", {})
    dg = profiles.get("director_general", {})

    return {
        "company_name": company,
        "ceo_name": ceo.get("name", ""),
        "ceo_linkedin_url": ceo.get("url", ""),
        "cfo_name": cfo.get("name", ""),
        "cfo_linkedin_url": cfo.get("url", ""),
        "director_general_name": dg.get("name", ""),
        "director_general_linkedin_url": dg.get("url", ""),
        "job_source_url": job_url,
        "search_keyword": keyword,
    }
