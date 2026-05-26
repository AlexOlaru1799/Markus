"""
State management — AgentState dataclass and helpers for the ReAct loop.

The agent maintains a single state dictionary that tracks progress through
all six phases: search, extract, find_company, find_names, find_profiles, write.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentState:
    """
    Mutable state container for the agent loop.

    Each field represents accumulated data from a phase of execution.
    Errors are accumulated non-fatally so the agent can report them in the
    final summary.
    """

    # ── Input ───────────────────────────────────────────────────────────────
    keywords: list[str] = field(default_factory=list)

    # ── Phase 1: scraped job entries ────────────────────────────────────────
    # Each entry: {"title": str, "url": str, "content": str}
    jobs: list[dict[str, Any]] = field(default_factory=list)

    # ── Phase 2: deduplicated company names ─────────────────────────────────
    companies: list[str] = field(default_factory=list)

    # ── Phase 3: company -> LinkedIn company URL ────────────────────────────
    linkedin_companies: dict[str, str] = field(default_factory=dict)

    # ── Phase 4: company -> role -> person name ─────────────────────────────
    # {company_name: {ceo: str, cfo: str, director_general: str}}
    people_names: dict[str, dict[str, str]] = field(default_factory=dict)

    # ── Phase 5: final spreadsheet records ──────────────────────────────────
    # Each record is a dict with columns:
    #   company_name, ceo_name, ceo_linkedin_url, cfo_name, cfo_linkedin_url,
    #   director_general_name, director_general_linkedin_url,
    #   job_source_url, search_keyword
    people_profiles: list[dict[str, str]] = field(default_factory=list)

    # ── Non-fatal errors ────────────────────────────────────────────────────
    errors: list[dict[str, str]] = field(default_factory=list)

    # ── Control ─────────────────────────────────────────────────────────────
    done: bool = False
    phase: str = "init"  # init | search | extract | find_company | find_names | find_profiles | write | done

    # ── Helpers ─────────────────────────────────────────────────────────────

    def add_error(self, step: str, context: str, detail: str) -> None:
        """Record a non-fatal error with timestamp context."""
        self.errors.append({
            "step": step,
            "context": context,
            "detail": detail,
        })

    def snapshot(self) -> dict[str, Any]:
        """Return a shallow copy of the state as a plain dict for LLM context."""
        return {
            "keywords": list(self.keywords),
            "jobs_count": len(self.jobs),
            "companies": list(self.companies),
            "linkedin_companies_found": len(self.linkedin_companies),
            "people_names": dict(self.people_names),
            "people_profiles_count": len(self.people_profiles),
            "errors_count": len(self.errors),
            "phase": self.phase,
            "done": self.done,
        }

    def summary(self) -> str:
        """Return a human-readable summary of all work done."""
        lines: list[str] = [
            "=" * 60,
            "AGENT EXECUTION SUMMARY",
            "=" * 60,
            f"Keywords searched: {', '.join(self.keywords)}",
            f"Jobs scraped:      {len(self.jobs)}",
            f"Companies found:   {len(self.companies)}",
            f"LinkedIn companies: {len(self.linkedin_companies)} found, "
            f"{len(self.companies) - len(self.linkedin_companies)} not found",
            f"Records written:   {len(self.people_profiles)}",
            f"Errors encountered: {len(self.errors)}",
            "-" * 60,
        ]
        if self.errors:
            lines.append("ERROR LOG:")
            for err in self.errors:
                lines.append(f"  [{err['step']}] {err['context']}: {err['detail']}")
            lines.append("-" * 60)
        lines.append("=" * 60)
        return "\n".join(lines)
