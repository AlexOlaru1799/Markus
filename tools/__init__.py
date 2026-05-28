"""
Tools package for the Job Search Agent.

Each module encapsulates a distinct capability:
- scraper:             crawl4AI-based job board scraping
- company_extractor:   LLM-based company name extraction
- linkedin_finder:     LinkedIn company URL finder (fallback chain)
- people_name_finder:  Internet search for C-suite names
- people_profile_finder: LinkedIn profile finder (fallback chain)
- writer:              CSV output
- browser_manager:     Persistent headed Playwright browser singleton
"""

from .scraper import search_jobs
from .company_extractor import extract_company_name
from .linkedin_finder import find_linkedin_company
from .people_name_finder import find_people_names
from .people_profile_finder import find_people_profiles
from .writer import write_spreadsheet
from .browser_manager import get_browser, close_browser
from .email_sender import send_results_email

__all__ = [
    "search_jobs",
    "extract_company_name",
    "find_linkedin_company",
    "find_people_names",
    "find_people_profiles",
    "write_spreadsheet",
    "get_browser",
    "close_browser",
    "send_results_email",
]
