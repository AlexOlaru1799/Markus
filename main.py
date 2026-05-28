"""
Entry point for the Job Search Agent.

Loads environment variables, validates configuration,
initialises the agent state, and runs the full workflow.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from config import config
from state import AgentState
from agent import run_agent
from tools import get_browser, close_browser


# ── Coloured logging formatter ────────────────────────────────────────────

_LOG_COLORS: dict[int, str] = {
    logging.DEBUG:    "\033[2m",       # dim
    logging.INFO:     "\033[1;32m",    # bold green
    logging.WARNING:  "\033[1;33m",    # bold yellow
    logging.ERROR:    "\033[1;31m",    # bold red
    logging.CRITICAL: "\033[1;41m",    # white-on-red
}
_C_RESET = "\033[0m"


class _ColoredFormatter(logging.Formatter):
    """Log formatter that wraps each line in ANSI colour according to its level."""

    def format(self, record: logging.LogRecord) -> str:
        colour = _LOG_COLORS.get(record.levelno, "")
        plain = super().format(record)
        return f"{colour}{plain}{_C_RESET}"


def _setup_logging() -> None:
    """Configure root logger to output INFO+ to stderr with timestamps + colours."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_ColoredFormatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    # Remove any existing handlers and attach ours
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    # Suppress noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("crawl4ai").setLevel(logging.WARNING)


async def main() -> None:
    """Application entry point."""
    _setup_logging()

    print("=" * 60, file=sys.stderr)
    print("  JOB SEARCH AGENT", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # ── Validate configuration ──────────────────────────────────────────────
    missing = config.validate()
    if missing:
        print(
            f"ERROR: Missing required environment variables: {', '.join(missing)}",
            file=sys.stderr,
        )
        print("Please set them in a .env file or export them in your shell.", file=sys.stderr)
        sys.exit(1)

    # ── Default keywords and output ────────────────────────────────────────
    default_keywords = ["call center", "operator introducere date"]

    # Auto-generate timestamped output path in outputs/ folder
    import os as _os
    _os.makedirs("outputs", exist_ok=True)
    from datetime import datetime
    _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_output = f"outputs/agent_run_{_ts}.csv"

    import argparse
    parser = argparse.ArgumentParser(
        description="Job Search Agent — find executives at Romanian companies hiring on ejobs.ro / bestjobs.eu"
    )
    parser.add_argument(
        "--keywords", "-k",
        nargs="+",
        default=default_keywords,
        help="Search keywords for job boards (default: call center, operator introducere date)",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output CSV file path (default: outputs/agent_run_<timestamp>.csv)",
    )
    parser.add_argument(
        "--chat", "-c",
        action="store_true",
        help="Start interactive chat interface instead of running a single pipeline",
    )
    args = parser.parse_args()

    # ── Chat mode ──────────────────────────────────────────────────────────
    if args.chat:
        from chat import run_chat
        print("  Starting chat interface ...", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(file=sys.stderr)
        await run_chat()
        return

    output_path = args.output or default_output
    _os.environ["OUTPUT_SHEET"] = output_path
    # Re-load config with the override
    from config import config as cfg
    cfg.output_sheet = output_path

    keywords = args.keywords
    print(f"  Keywords: {keywords}", file=sys.stderr)
    print(f"  Output:   {output_path}", file=sys.stderr)
    print(f"  LLM:      {config.llm_model}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(file=sys.stderr)

    # ── Start persistent headed browser ────────────────────────────────────
    # The browser window opens now and stays visible for the entire run.
    # The user can solve any CAPTCHAs that appear in this same window.
    print("  Starting persistent browser (visible window)...", file=sys.stderr)
    _ = await get_browser()
    logger = logging.getLogger(__name__)

    # ── Run agent ───────────────────────────────────────────────────────────
    try:
        final_state: AgentState = await run_agent(keywords)
        print(file=sys.stderr)
        print(final_state.summary(), file=sys.stderr)

        # Also print the summary to stdout so it can be captured
        print("\n" + final_state.summary())
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"\nFATAL ERROR: {exc}", file=sys.stderr)
        logger.exception("Fatal error in agent execution")
        sys.exit(1)
    finally:
        # ── Close persistent browser ──────────────────────────────────────────
        logger.info("Shutting down persistent browser ...")
        await close_browser()


if __name__ == "__main__":
    asyncio.run(main())
