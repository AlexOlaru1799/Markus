"""
Configuration module — loads environment variables with sensible defaults.

All API keys and configuration values are loaded from environment variables
at runtime. A .env file can be used for local development.
"""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Typed configuration container with all environment-driven settings."""

    # ── LLM (DeepSeek) ──────────────────────────────────────────────────────
    llm_api_key: str = field(default_factory=lambda: os.environ.get("LLM_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", "deepseek-chat"))
    llm_base_url: str = field(default_factory=lambda: os.environ.get(
        "LLM_BASE_URL", "https://api.deepseek.com/v1"
    ))

    # ── External APIs ───────────────────────────────────────────────────────
    linkup_api_key: str = field(default_factory=lambda: (
        os.environ.get("LINKUP_API_KEY") or os.environ.get("LINKUP_API_TOKEN") or ""
    ))

    # ── LinkedIn session credentials ────────────────────────────────────────
    # These are needed by the linkedin-scraper-no-selenium library.
    # Get your li_at cookie value from browser DevTools (Application > Cookies).
    linkedin_li_at: str = field(default_factory=lambda: os.environ.get("LINKEDIN_LI_AT", ""))
    linkedin_jsessionid: str = field(default_factory=lambda: os.environ.get("LINKEDIN_JSESSIONID", ""))

    @property
    def linkedin_cookie_string(self) -> str:
        """Build the full cookie string required by linkedin-scraper-no-selenium."""
        parts = []
        if self.linkedin_li_at:
            parts.append(f"li_at={self.linkedin_li_at}")
        if self.linkedin_jsessionid:
            parts.append(f"JSESSIONID=\\\"{self.linkedin_jsessionid}\\\"")
        return "; ".join(parts)

    @property
    def linkedin_csrf_token(self) -> str:
        """Return the JSESSIONID value for use as CSRF token."""
        return self.linkedin_jsessionid

    # ── Output ──────────────────────────────────────────────────────────────
    output_sheet: str = field(default_factory=lambda: os.environ.get("OUTPUT_SHEET", "output.csv"))

    # ── Scraping ────────────────────────────────────────────────────────────
    crawl4ai_delay: float = field(default_factory=lambda: float(
        os.environ.get("CRAWL4AI_DELAY", "1.0")
    ))

    # ── Validation ──────────────────────────────────────────────────────────
    def validate(self) -> list[str]:
        """Return a list of missing required configuration keys."""
        missing: list[str] = []
        if not self.llm_api_key:
            missing.append("LLM_API_KEY")
        if not self.linkup_api_key:
            missing.append("LINKUP_API_KEY")
        # LinkedIn credentials are optional — no warning if missing
        return missing


# Module-level singleton for convenience.
config = Config()
