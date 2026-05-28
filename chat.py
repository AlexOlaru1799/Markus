"""
Interactive chat interface for Markus.

Provides three modes:
1. **Normal chat** — forwards every message to the LLM and returns the response,
   maintaining a rolling conversation history.
2. **/Markus command** — when the user's prompt starts with ``/Markus``, the
   natural-language request is parsed for search keywords, then the full 6-phase
   Markus pipeline (job search → company extraction → LinkedIn discovery →
   executive identification → CSV output) is executed instead.
3. **Email sending** — after a pipeline completes, the user can optionally send
   results via email. Embedded email addresses in the ``/Markus`` prompt
   (e.g. ``/Markus find jobs and send to office@company.ro``) trigger automatic
   email delivery on completion.

Inspired by the ``/Marian`` agent routing pattern in Agent Demo.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os as _os
import re
import sys
from datetime import datetime
from typing import Any

from agent import run_agent
from config import config
from llm import llm
from main import _setup_logging
from state import AgentState
from tools import get_browser, close_browser, send_results_email

logger = logging.getLogger(__name__)

# ── Terminal colours ────────────────────────────────────────────────────────
C_USER = "\033[1;34m"    # bold blue
C_MARKUS = "\033[1;33m"  # bold yellow
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_GREEN = "\033[1;32m"
C_RED = "\033[1;31m"
C_CYAN = "\033[1;36m"    # bold cyan

# ── Help text ───────────────────────────────────────────────────────────────

HELP_TEXT = f"""  {C_BOLD}Available commands:{C_RESET}

  {C_BOLD}/Markus <prompt>{C_RESET}       — Run the job search + executive discovery pipeline
  {C_BOLD}/Markus send to <email>{C_RESET}  — Resend last pipeline results via email
  {C_BOLD}/help{C_RESET}              — Show this help message
  {C_BOLD}/quit{C_RESET}              — Exit the chat interface

  {C_DIM}Anything else  — Normal chat with the LLM{C_RESET}

  {C_DIM}Email:{C_RESET}
    {C_DIM}After a pipeline completes, you will be asked if you want to email results.{C_RESET}
    {C_DIM}Add "send to email@example.com" in your /Markus prompt to auto-send.{C_RESET}

  {C_DIM}Examples:{C_RESET}
    {C_DIM}/Markus find software engineer jobs and get me the executives{C_RESET}
    {C_DIM}/Markus caută posturi de contabil și găsește directorii{C_RESET}
    {C_DIM}/Markus get accountant jobs and retrieve executives{C_RESET}
    {C_DIM}/Markus find Java developer jobs and send to hr@company.ro{C_RESET}
    {C_DIM}/Markus send to office@company.ro{C_RESET}
"""


# ── Resend / email intent patterns ────────────────────────────────────────────

_RESEND_PATTERNS: tuple[str, ...] = (
    "send email", "send results", "trimite mail", "trimite rezultatele",
    "resend", "send to",
)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# ── Job-count patterns ───────────────────────────────────────────────────────
# Matches a number followed anywhere by a job-related word.
# This handles both:
#   "4 jobs"                     (number immediately before "jobs")
#   "4 software engineer jobs"   (number separated from "jobs" by the title)
#   "exactly 3 positions"        (with "exactly" prefix)
#   "find 5 posturi de contabil" (Romanian, number before "posturi")
_COUNT_RE = re.compile(
    r"(?i)"
    r"(?:exactly\s+)?"
    r"(\d{1,3})"
    r"(?=.*\b(?:job|posting|position|role|oferta|post(?:uri)?|"
    r"loc(?:uri)?|joburi|posturi|roluri|"
    r"anunț(?:uri)?|anunt(?:uri)?)"
    r"s?\b)"
)
# Fallback: leading number at start of prompt (e.g. "5 software engineering jobs")
_COUNT_LEADING_RE = re.compile(r"^\s*(\d{1,3})\b")


# ═══════════════════════════════════════════════════════════════════════════
# Keyword Extraction
# ═══════════════════════════════════════════════════════════════════════════


async def _extract_keywords(prompt: str) -> list[str]:
    """Use the LLM to extract search keywords from a natural-language prompt.

    Handles variations in phrasing, language (RO/EN), and removes noise words.

    Returns a list of 1–3 keyword strings, defaulting to
    ``["call center", "operator introducere date"]`` if parsing fails.
    """
    extraction_prompt = (
        "Extract search keywords from this recruitment request.\n\n"
        f"User request: {prompt}\n\n"
        "Return ONLY a JSON array of keyword strings, nothing else.\n\n"
        "Examples:\n"
        '- "find software engineer jobs" → ["software engineer"]\n'
        '- "get call center and operator jobs" → ["call center", "operator introducere date"]\n'
        '- "caută posturi de contabil" → ["contabil"]\n'
        '- "find me some accountant positions" → ["accountant"]\n'
        '- "help me find Java developer roles and get executives" → ["Java developer"]\n\n'
        "Rules:\n"
        "- Extract 1-3 keywords maximum\n"
        "- Remove noise words (find, get, jobs, please, help, me, some, retrieve, etc.)\n"
        "- Keep multi-word phrases intact (e.g. 'software engineer', 'call center', 'Java developer')\n"
        "- If the user mixes Romanian and English, prefer Romanian keywords\n"
        "- Default to [\"call center\", \"operator introducere date\"] if unclear"
    )

    try:
        response = await llm.ask_async(
            extraction_prompt,
            system=(
                "You are a keyword extraction assistant. "
                "Always respond with valid JSON only — a flat string array."
            ),
            temperature=0.0,
            max_tokens=256,
        )
        # Locate the JSON array in the response
        match = re.search(r"\[.*?\]", response, re.DOTALL)
        if match:
            keywords = json.loads(match.group(0))
            if isinstance(keywords, list) and keywords:
                cleaned = [str(k).strip() for k in keywords if str(k).strip()]
                if cleaned:
                    return cleaned
    except Exception as exc:
        logger.warning("Keyword extraction failed: %s", exc)

    return ["call center", "operator introducere date"]


# ═══════════════════════════════════════════════════════════════════════════
# Markus pipeline handler
# ═══════════════════════════════════════════════════════════════════════════


async def _handle_markus(
    prompt: str,
    last_state: AgentState | None = None,
) -> AgentState | None:
    """Execute the full Markus pipeline for a ``/Markus <prompt>`` command.

    Also handles:
    - **Resend** — if the prompt is a resend command (e.g. ``send to x@y.z``),
      the *last_state* results are emailed and ``None`` is returned.
    - **Embedded email** — if the prompt contains an email address
      (e.g. ``find jobs and send to x@y.z``), the pipeline runs and results
      are auto-emailed on success.
    - **Post-pipeline prompt** — after a successful pipeline run the user
      is asked whether they want to email the results.

    Parameters
    ----------
    prompt : str
        The natural-language request (the part after ``/Markus``).
    last_state : AgentState or None
        The state from the previous pipeline run (used for resends).

    Returns
    -------
    AgentState or None
        The final pipeline state, or ``None`` if this was a resend-only command.
    """
    print(f"  {C_MARKUS}🤖 Markus pipeline triggered{C_RESET}", file=sys.stderr)
    print(f"  {C_DIM}Prompt: {prompt}{C_RESET}", file=sys.stderr)
    print(file=sys.stderr)

    # ── Detect email in prompt ───────────────────────────────────────────
    email_match = _EMAIL_RE.search(prompt)
    to_email: str | None = email_match.group(0) if email_match else None

    # ── Check for resend-only command ────────────────────────────────────
    is_resend = any(prompt.lower().startswith(p) for p in _RESEND_PATTERNS)

    if is_resend:
        if not to_email:
            print(
                f"  {C_MARKUS}📧 Please specify an email address.\n"
                f"  Example: /Markus send to office@company.ro{C_RESET}",
                file=sys.stderr,
            )
            return None

        if last_state is None or not last_state.people_profiles:
            print(
                f"  {C_MARKUS}📧 No previous results to send.\n"
                f"  Run a pipeline first like /Markus find engineer jobs{C_RESET}",
                file=sys.stderr,
            )
            return None

        return _send_results_email_helper(last_state, to_email)

    # ── Strip email from prompt for keyword extraction ───────────────────
    search_prompt = prompt
    if to_email:
        # Remove "send to email@..." or "trimite la email@..." from the prompt
        search_prompt = _EMAIL_RE.sub("", search_prompt).strip()
        # Also strip dangling "send to" / "trimite la" fragments
        search_prompt = re.sub(
            r"(?i)\b(?:send|trimite)\s+(?:to|la|the\s+results\s+to)?\s*$",
            "",
            search_prompt,
        ).strip()

    # ── Detect job count in prompt ────────────────────────────────────────
    max_results: int | None = None
    count_match = _COUNT_RE.search(search_prompt)
    if not count_match:
        count_match = _COUNT_LEADING_RE.search(search_prompt)
    if count_match:
        max_results = int(count_match.group(1))
        search_prompt = _COUNT_RE.sub("", search_prompt, count=1).strip()
        search_prompt = _COUNT_LEADING_RE.sub("", search_prompt, count=1).strip()
        print(f"  {C_DIM}Max results: {max_results}{C_RESET}", file=sys.stderr)

    # ── Step 1: Extract keywords ──────────────────────────────────────────
    print(f"  {C_DIM}Extracting search keywords...{C_RESET}", file=sys.stderr)
    keywords = await _extract_keywords(search_prompt)
    print(f"  {C_GREEN}✅ Keywords: {keywords}{C_RESET}", file=sys.stderr)
    print(file=sys.stderr)

    # ── Step 2: Auto-generate output path ──────────────────────────────────
    _os.makedirs("outputs", exist_ok=True)
    _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = f"outputs/agent_run_{_ts}.csv"
    _os.environ["OUTPUT_SHEET"] = output_path
    config.output_sheet = output_path

    print(f"  Output: {output_path}", file=sys.stderr)
    print(f"  LLM:    {config.llm_model}", file=sys.stderr)
    print(file=sys.stderr)

    # ── Step 3: Run the full pipeline ─────────────────────────────────────
    final_state: AgentState | None = None
    try:
        final_state = await run_agent(keywords, max_results=max_results)
        print(file=sys.stderr)
        print(final_state.summary(), file=sys.stderr)
        print(f"\n{final_state.summary()}")

        if final_state and final_state.people_profiles:
            print(file=sys.stderr)
            _display_results_table(final_state)

    except Exception as exc:
        print(f"  {C_RED}❌ Pipeline failed: {exc}{C_RESET}", file=sys.stderr)
        logger.exception("Fatal error in Markus pipeline")
        print(f"\n❌ Pipeline failed: {exc}")
        return final_state

    # ── Post-pipeline email handling ─────────────────────────────────────
    if not final_state or not final_state.people_profiles:
        return final_state

    if to_email:
        # Auto-send because the user embedded an email in the prompt
        _send_results_email_helper(final_state, to_email)
    elif config.smtp_configured:
        # Ask the user interactively
        print(file=sys.stderr)
        answer = input(
            f"  {C_MARKUS}📧 Results saved to {config.output_sheet}. "
            f"Would you like to email them? (y/N) {C_RESET}"
        ).strip().lower()
        if answer in ("y", "yes", "da", "d"):
            email_input = input(
                f"  {C_MARKUS}📧 Enter recipient email: {C_RESET}"
            ).strip()
            if email_input:
                _send_results_email_helper(final_state, email_input)

    return final_state


# ── email helper ─────────────────────────────────────────────────────────

def _send_results_email_helper(
    state: AgentState,
    to_email: str,
) -> None:
    """Send pipeline results via email with user-friendly error handling."""
    if not config.smtp_configured:
        print(
            f"  {C_MARKUS}⚠️  SMTP not configured. Set SMTP_HOST, SMTP_USER, "
            f"SMTP_PASSWORD, and EMAIL_FROM in .env to send emails.{C_RESET}",
            file=sys.stderr,
        )
        return

    csv_path = config.output_sheet if _os.path.exists(config.output_sheet) else None
    subject = f"🤖 Markus — {len(state.people_profiles)} results"

    try:
        send_results_email(
            to_email=to_email,
            subject=subject,
            rows=state.people_profiles,
            csv_path=csv_path,
        )
        print(f"  {C_GREEN}✅ Email sent to {to_email}{C_RESET}", file=sys.stderr)
    except Exception as exc:
        print(
            f"  {C_RED}❌ Failed to send email: {exc}{C_RESET}",
            file=sys.stderr,
        )


# ── Results table display ──────────────────────────────────────────────────

_ANSI_HYPERLINK = "\033]8;;{}\033\\{}\033]8;;\033\\"


def _display_results_table(state: AgentState) -> None:
    """Print a terminal-formatted results table with clickable links.

    Uses ANSI hyperlink escapes (``\\033]8;;URL\\033\\\\TEXT\\033]8;;\\033\\\\``)
    so that LinkedIn profile URLs are clickable in modern terminals.
    """
    records = state.people_profiles
    if not records:
        return

    print(f"  {'═' * 56}", file=sys.stderr)
    print(f"  📋  RESULTS — {len(records)} record{'s' if len(records) != 1 else ''}", file=sys.stderr)
    print(f"  {'═' * 56}", file=sys.stderr)

    for i, rec in enumerate(records, 1):
        company = rec.get("company_name", "?")
        ceo_name = rec.get("ceo_name", "")
        ceo_url = rec.get("ceo_linkedin_url", "")
        cfo_name = rec.get("cfo_name", "")
        cfo_url = rec.get("cfo_linkedin_url", "")
        dg_name = rec.get("director_general_name", "")
        dg_url = rec.get("director_general_linkedin_url", "")

        print(f"  {C_CYAN}── [{i}] {company}{C_RESET}", file=sys.stderr)

        def _link(name: str, url: str) -> str:
            if url:
                return _ANSI_HYPERLINK.format(url, name or "🔗 link")
            return name or "—"

        if ceo_name or ceo_url:
            print(f"    👤 CEO:        {_link(ceo_name, ceo_url)}", file=sys.stderr)
        if cfo_name or cfo_url:
            print(f"    👤 CFO:        {_link(cfo_name, cfo_url)}", file=sys.stderr)
        if dg_name or dg_url:
            print(f"    👤 Dir. Gen.:  {_link(dg_name, dg_url)}", file=sys.stderr)

        job_url = rec.get("job_source_url", "")
        if job_url:
            print(f"    📎 Job:        {_ANSI_HYPERLINK.format(job_url, job_url[:80])}", file=sys.stderr)

        print(file=sys.stderr)

    print(f"  {'─' * 56}", file=sys.stderr)


# ═══════════════════════════════════════════════════════════════════════════
# Main Chat Loop
# ═══════════════════════════════════════════════════════════════════════════


async def run_chat() -> None:
    """Start the interactive chat interface.

    The user is prompted repeatedly. Each message is processed as:

    - ``/Markus <prompt>`` → extract keywords → run the 6-phase pipeline
    - ``/help``            → show available commands
    - ``/quit`` or EOF     → exit
    - everything else      → forward to the LLM with conversation history
    """
    _setup_logging()

    # ── Print banner ──────────────────────────────────────────────────────
    print(file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print("  MARKUS — Chat Interface", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(HELP_TEXT, file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # ── Conversation history for normal chat ──────────────────────────────
    chat_history: list[dict[str, str]] = []
    last_state: AgentState | None = None

    # ── Start persistent browser ─────────────────────────────────────────
    print("  Starting persistent browser (headless)...", file=sys.stderr)
    await get_browser()
    print(file=sys.stderr)

    try:
        while True:
            # ── Read user input ──────────────────────────────────────────
            try:
                user_input = input(f"\n{C_USER}You{C_RESET}> ").strip()
            except (EOFError, KeyboardInterrupt):
                print(file=sys.stderr)
                print("👋 Goodbye!", file=sys.stderr)
                break

            if not user_input:
                continue

            # ── /quit / /exit ────────────────────────────────────────────
            if user_input.lower() in ("/quit", "/exit", "quit", "exit"):
                print("👋 Goodbye!", file=sys.stderr)
                break

            # ── /help ────────────────────────────────────────────────────
            if user_input.lower() in ("/help", "/commands", "-h", "--help"):
                print(HELP_TEXT, file=sys.stderr)
                continue

            # ── /Markus <prompt> — trigger pipeline ──────────────────────
            markus_match = re.match(
                r"^/Markus\s+(.+)$", user_input, re.IGNORECASE | re.DOTALL
            )
            if markus_match:
                result = await _handle_markus(
                    markus_match.group(1).strip(),
                    last_state=last_state,
                )
                if result is not None:
                    last_state = result
                continue

            # ── Bare /Markus (no prompt) — show hint ─────────────────────
            if user_input.lower().strip() == "/markus":
                print(
                    f"  {C_MARKUS}Please provide a prompt after /Markus.\n"
                    f"  Example: /Markus find software engineer jobs{C_RESET}",
                    file=sys.stderr,
                )
                continue

            # ── Normal chat — forward to LLM with history ────────────────
            try:
                response = await llm.chat_async(
                    user_input,
                    system=(
                        "You are Markus, a general-purpose AI assistant. "
                        "Respond in Romanian or English based on the user's "
                        "language. Be concise and helpful.\n\n"
                        "Capabilities:\n"
                        "- General conversation, Q&A, explanations\n"
                        "- Use **/Markus <prompt>** to trigger specialised "
                        "workflows (e.g. job search, company research, "
                        "executive discovery)\n\n"
                        "Examples:\n"
                        "  /Markus find software engineer jobs and get the executives\n"
                        "  /Markus caută posturi de contabil și găsește directorii"
                    ),
                    history=chat_history,
                )
                print(f"  {response}")
                chat_history.append({"role": "user", "content": user_input})
                chat_history.append({"role": "assistant", "content": response})
                # Keep the last 40 messages to bound memory usage
                if len(chat_history) > 40:
                    chat_history = chat_history[-40:]
            except Exception as exc:
                print(f"  {C_RED}❌ Error: {exc}{C_RESET}", file=sys.stderr)

    finally:
        # ── Close persistent browser ──────────────────────────────────────
        logger.info("Shutting down persistent browser ...")
        await close_browser()
