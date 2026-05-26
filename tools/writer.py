"""
CSV writer — appends records to a CSV file.

Each record contains the columns specified in the requirements:
company_name, ceo_name, ceo_linkedin_url, cfo_name, cfo_linkedin_url,
director_general_name, director_general_linkedin_url, job_source_url, search_keyword

If the file doesn't exist, a header row is written first.
"""

from __future__ import annotations

import csv
import logging
import os
from typing import Any

from config import config

logger = logging.getLogger(__name__)

# Column order (must match requirements exactly)
COLUMNS: list[str] = [
    "company_name",
    "ceo_name",
    "ceo_linkedin_url",
    "cfo_name",
    "cfo_linkedin_url",
    "director_general_name",
    "director_general_linkedin_url",
    "job_source_url",
    "search_keyword",
]


async def write_spreadsheet(records: list[dict[str, str]]) -> str:
    """
    Append *records* to the CSV file specified by ``OUTPUT_SHEET``.

    Parameters
    ----------
    records : list[dict[str, str]]
        Each dict must contain all keys listed in :data:`COLUMNS`.

    Returns
    -------
    str
        A confirmation message with the file path and record count.
    """
    filepath = config.output_sheet
    file_exists = os.path.isfile(filepath)

    try:
        with open(filepath, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)

            if not file_exists:
                writer.writeheader()
                logger.info("Created new CSV file: %s", filepath)

            for record in records:
                # Ensure all columns are present (fill missing with empty string)
                row = {col: record.get(col, "") for col in COLUMNS}
                writer.writerow(row)

        logger.info("Appended %d records to %s", len(records), filepath)
        return f"Successfully wrote {len(records)} records to {filepath}"

    except Exception as exc:
        logger.error("Failed to write to CSV %s: %s", filepath, exc)
        raise
