# Job Search Agent

An AI-powered agentic system that automates searching Romanian job boards, extracting hiring companies, finding their LinkedIn profiles, identifying key executives (CEO, CFO, Director General), and writing the results to a CSV spreadsheet.

## Architecture

```
                        ┌──────────────────────┐
                        │   DeepSeek LLM Agent  │
                        │   (ReAct Loop)        │
                        └──────┬───────┬───────┘
                               │       │
            ┌──────────────────┘       └──────────────────┐
            ▼                                               ▼
    ┌───────────────┐                               ┌───────────────┐
    │  crawl4AI      │                               │  External APIs │
    │  (scraping)    │                               │  Linkup        │
    │  - ejobs.ro    │                               │  linkedin-     │
    │  - bestjobs.eu │                               │  scraper-no-   │
    │  - Google      │                               │  selenium      │
    └───────────────┘                               └───────────────┘
                                                           │
                                                           ▼
                                                  ┌───────────────┐
                                                  │  output.csv   │
                                                  └───────────────┘
```

### 6-Phase Decision Graph

1. **SEARCH** — Scrape ejobs.ro and bestjobs.eu for job listings matching keywords
2. **EXTRACT COMPANY** — Use LLM to extract hiring company names from job content
3. **FIND LINKEDIN COMPANY** — Fallback chain: Google → Linkup → LLM knowledge
4. **FIND PEOPLE NAMES** — Search internet for CEO/CFO/Director General names per company
5. **FIND PEOPLE PROFILES** — Fallback chain: Google → linkedin-scraper-no-selenium (bulk employee lookup) → Linkup → LLM knowledge
6. **WRITE** — Append all results to CSV

Each successful result in phases 3 and 5 is **validated by the LLM** before being accepted. If validation fails, the next fallback method is tried.

## Features

- **Automated job board scraping** — ejobs.ro and bestjobs.eu via crawl4AI
- **Intelligent company extraction** — DeepSeek LLM parses job postings
- **Multi-layered LinkedIn search** — Fallback chains for finding company pages and people profiles
- **LLM validation** — every candidate URL is verified before acceptance
- **LLM direct knowledge fallback** — LLM may know URLs from training data
- **Verbose logging** — all decisions logged with timestamps and full context
- **CAPTCHA handling** — pauses and requests human input when detected
- **CSV output** — structured results ready for analysis

## Requirements

- Python 3.10+
- DeepSeek API key (or any OpenAI-compatible LLM API)
- Linkup API key
- LinkedIn session cookies (for linkedin-scraper-no-selenium employee lookups):
  - `li_at` cookie value
  - `JSESSIONID` cookie value

## Installation

```bash
# Clone the repository
cd /path/to/project

# Create a virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env` and fill in your API keys and credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```ini
# Required
LLM_API_KEY=sk-your-deepseek-api-key
LINKUP_API_KEY=your-linkup-api-key

# LinkedIn session cookies (for employee lookups via linkedin-scraper-no-selenium)
# How to get these:
# 1. Log in to https://www.linkedin.com in Chrome
# 2. Open DevTools → Application → Storage → Cookies → linkedin.com
# 3. Copy the "li_at" value → paste below
# 4. Copy the "JSESSIONID" value → paste below
LINKEDIN_LI_AT=
LINKEDIN_JSESSIONID=

# Optional (shown with defaults)
# LLM_MODEL=deepseek-chat
# LLM_BASE_URL=https://api.deepseek.com/v1
# OUTPUT_SHEET=output.csv
# CRAWL4AI_DELAY=1.0
```

## Usage

### Basic usage

```bash
python main.py
```

This searches for _"call center"_ and _"operator introducere date"_ on both job boards.

### Custom keywords

```bash
python main.py --keywords "software developer" "data entry"
```

### Custom output file

```bash
python main.py --output results.csv
```

### Full options

```bash
python main.py --help
```

## Output Format

The CSV contains the following columns:

| Column | Description |
|---|---|
| `company_name` | Hiring company name |
| `ceo_name` | CEO's full name |
| `ceo_linkedin_url` | CEO's LinkedIn profile URL |
| `cfo_name` | CFO's full name |
| `cfo_linkedin_url` | CFO's LinkedIn profile URL |
| `director_general_name` | Director General's full name |
| `director_general_linkedin_url` | Director General's LinkedIn profile URL |
| `job_source_url` | Original job posting URL |
| `search_keyword` | Keyword used to find the job |

## Fallback Chains

### LinkedIn Company Search (Phase 3)

> linkedin-scraper-no-selenium is NOT used here — it requires a LinkedIn company URL
> as input, so it cannot help find one.

1. **Google search** — `site:linkedin.com/company "{company_name}"` via crawl4AI
2. **Linkup API** — enterprise API for company data
3. **LLM direct knowledge** — ask the DeepSeek LLM directly

After each successful result → **LLM Validation** → If rejected, try next fallback.

### LinkedIn Profile Search (Phase 5)

**Bulk employee lookup** runs FIRST if the LinkedIn company URL was found in Phase 3:
1. **linkedin-scraper-no-selenium** — clones the GitHub repo and runs it as a
   subprocess with your LinkedIn session cookies to fetch ALL employees.
   The results are filtered to match the target names (CEO, CFO, Director General).

If the bulk lookup doesn't find a match, individual fallbacks are tried:
1. **Google search** — `site:linkedin.com/in "{name}" "{company}"` via crawl4AI
2. **Linkup API** — enterprise API for people data
3. **LLM direct knowledge** — ask the DeepSeek LLM directly

After each successful result → **LLM Validation** → If rejected, try next fallback.

## Project Structure

```
├── main.py                   # Entry point
├── agent.py                  # ReAct agent loop with verbose logging
├── config.py                 # Environment variable loading
├── state.py                  # AgentState dataclass
├── llm.py                    # DeepSeek LLM client wrapper
├── tools/
│   ├── scraper.py            # crawl4AI job board + Google search
│   ├── company_extractor.py  # LLM-based company name extraction
│   ├── linkedin_finder.py    # LinkedIn company URL finder
│   ├── people_name_finder.py # Internet search for executive names
│   ├── people_profile_finder.py  # LinkedIn profile URL finder
│   └── writer.py             # CSV output
├── .env.example              # Environment variable template
├── requirements.txt          # Python dependencies
└── README.md                 # This file
```

## Logging

The agent provides verbose, real-time logging of all operations:

```
[2026-05-26 21:30:01] [INFO] ======================================================================
[2026-05-26 21:30:01] [INFO]   PHASE: Phase 1: Job Search
[2026-05-26 21:30:01] [INFO] ======================================================================
[2026-05-26 21:30:01] [INFO] Scraping job boards for keywords: ['call center', 'operator introducere date']
[2026-05-26 21:30:01] [INFO] ==================================================
[2026-05-26 21:30:01] [INFO] Searching for keyword: 'call center'
[2026-05-26 21:30:01] [INFO] ==================================================
[2026-05-26 21:30:01] [INFO] Scraping ejobs for keyword 'call center': https://www.ejobs.ro/locuri-de-munca/call+center
[2026-05-26 21:30:05] [INFO]   ejobs returned 12 job entries
[2026-05-26 21:30:05] [INFO] ===== Phase 2: Company Name Extraction =====
[2026-05-26 21:30:05] [INFO]   [1/12] Extracting company from: Customer Support Agent
[2026-05-26 21:30:06] [INFO]     -> New company: 'TechCorp SRL'
```

## Error Handling

- **Non-fatal errors** are logged and stored; the agent continues processing
- **Failed job boards** are skipped; other boards are still scraped
- **LinkedIn lookups** try all 4 fallbacks before marking as not found
- **LLM call failures** retry up to 3 times with exponential backoff
- **CAPTCHA detection** pauses for human intervention
- A **final summary** shows total companies processed, successes, failures, and all errors

## License

MIT
