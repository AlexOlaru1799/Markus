"""
Tools package for the Job Search Agent.

Each module encapsulates a distinct capability:
- scraper:             crawl4AI-based job board + Google search
- company_extractor:   LLM-based company name extraction
- linkedin_finder:     LinkedIn company URL finder (fallback chain)
- people_name_finder:  Internet search for C-suite names
- people_profile_finder: LinkedIn profile finder (fallback chain)
- writer:              CSV output
"""

from .scraper import search_jobs, search_google
from .company_extractor import extract_company_name
from .linkedin_finder import find_linkedin_company
from .people_name_finder import find_people_names
from .people_profile_finder import find_people_profiles
from .writer import write_spreadsheet

__all__ = [
    "search_jobs",
    "search_google",
    "extract_company_name",
    "find_linkedin_company",
    "find_people_names",
    "find_people_profiles",
    "write_spreadsheet",
]
