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


def _setup_logging() -> None:
    """Configure root logger to output INFO+ to stderr with timestamps."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )
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

    # ── Determine search keywords ───────────────────────────────────────────
    # Default keywords if none provided via env or CLI
    default_keywords = ["call center", "operator introducere date"]

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
        help="Override output CSV file path",
    )
    args = parser.parse_args()

    if args.output:
        import os as _os
        _os.environ["OUTPUT_SHEET"] = args.output
        # Re-load config with the override
        from config import config as cfg
        cfg.output_sheet = args.output

    keywords = args.keywords
    print(f"  Keywords: {keywords}", file=sys.stderr)
    print(f"  Output:   {config.output_sheet}", file=sys.stderr)
    print(f"  LLM:      {config.llm_model}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(file=sys.stderr)

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
        logging.getLogger(__name__).exception("Fatal error in agent execution")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
