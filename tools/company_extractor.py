"""
Company name extraction from job posting content.

Uses the DeepSeek LLM to extract the hiring company's name from the full text
of a job posting.  This is a simple extraction call — the LLM is prompted to
return only the company name.
"""

from __future__ import annotations

import logging

from llm import llm

logger = logging.getLogger(__name__)

EXTRACT_PROMPT = (
    "Extract the hiring company name from this job posting. "
    "Return ONLY the company name, nothing else. "
    "If you cannot find a company name, return 'UNKNOWN'.\n\n"
    "Job content:\n{content}"
)


async def extract_company_name(content: str) -> str:
    """
    Extract the hiring company name from *content* using the LLM.

    Parameters
    ----------
    content : str
        The full markdown/text content of a job posting.

    Returns
    -------
    str
        The company name, or ``"UNKNOWN"`` if extraction fails.
    """
    if not content or len(content.strip()) < 20:
        logger.warning("Job content too short (%d chars), cannot extract company", len(content or ""))
        return "UNKNOWN"

    prompt = EXTRACT_PROMPT.format(content=content[:12000])  # Safety trim
    logger.debug("Sending company extraction prompt to LLM (%d chars)", len(prompt))

    try:
        result = await llm.ask_async(prompt)
        result = result.strip().strip('"').strip("'")
        if result.upper() == "UNKNOWN" or not result:
            logger.info("LLM could not determine company name")
            return "UNKNOWN"
        logger.info("Extracted company: '%s'", result)
        return result
    except Exception as exc:
        logger.error("LLM extraction failed: %s", exc)
        return "UNKNOWN"
