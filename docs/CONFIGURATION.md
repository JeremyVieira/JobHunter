# Configuration

Everything is configured through a local `.env` file (copy `.env.example`). It is ignored by Git.
Run `python -m jobhunter doctor` at any time to see what is set, what is missing, and why it matters.

## You

| Variable | Purpose |
| --- | --- |
| `USER_NAME`, `USER_LOCATION`, `USER_EMAIL`, `USER_PHONE`, `USER_GITHUB` | Contact details used on generated documents. |
| `USER_DEGREE`, `USER_EXPERIENCE_YEARS`, `USER_EXPERIENCE_SUMMARY` | Profile used by scoring and the dashboard. Use your real years of relevant experience. |
| `USER_LANGUAGES` | Languages you work in (default `en,fr`). Drives the bilingual bonus and the penalty for postings in a language you do not speak. |
| `USER_TARGET_ROLES`, `USER_PRIORITY_TARGET_ROLES` | Titles used for matching/filtering. Priority roles score highest. |
| `USER_KEYWORDS` | Skills and tools you can truthfully claim. Unknown terms are matched as written. |

## What to search

| Variable | Purpose |
| --- | --- |
| `JOB_SEARCH_TERMS`, `JOB_SEARCH_LOCATION` | Queries and location for the JobSpy-backed boards. |
| `JOBSPY_SITES` | Which JobSpy boards to query. Remove any you do not intend to use. |
| `JOBSPY_HOURS_OLD` (72), `JOBSPY_RESULTS_PER_TERM` (15), `JOBSPY_FETCH_LINKEDIN_DESCRIPTIONS` (true), `JOBSPY_PROXIES` | Freshness window, volume, full LinkedIn descriptions, optional proxies (only where you are authorised to use them). |
| `COMPANY_CAREER_URLS` | `Name|careers URL`, comma-separated. The employer's ATS is detected automatically. |
| `GREENHOUSE_COMPANIES`, `LEVER_COMPANIES`, `ASHBY_COMPANIES`, `WORKABLE_COMPANIES`, `SMARTRECRUITERS_COMPANIES`, `RECRUITEE_COMPANIES` | `Name|token`, comma-separated. |
| `WORKDAY_COMPANIES` | `Name|tenant|wdN|Site`, comma-separated. |
| `RSS_FEEDS` | `Name|url`, comma-separated. |
| `MUSE_ENABLED`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `JOOBLE_API_KEY` | Extra boards; keyed ones are skipped without a key. |

`python -m jobhunter discover "Company|https://company.com/careers" --count` finds the right board
settings for a company and prints the `.env` line.

## How much to keep

| Variable | Default | Purpose |
| --- | --- | --- |
| `MAX_PERSISTED_JOBS` | 40 | Postings saved per run. |
| `ENRICH_MAX_FETCHES` | 40 | Pages fetched per run to replace short snippets with full descriptions. |
| `CAREER_PAGE_MAX_DETAIL_PAGES` | 15 | Job links followed per career page that has no ATS. |
| `REQUEST_DELAY_SECONDS` | 0.3 | Pause between requests to the same provider. |
| `JOBHUNTER_COLLECTION_HOUR`, `JOBHUNTER_COLLECTION_MINUTE` | 8:00 | Daily collection time (local). |

## Where things live

Defaults keep everything inside the repository. These overrides exist for custom installs and demo mode.

| Variable | Default | Purpose |
| --- | --- | --- |
| `JOBHUNTER_DATA_DIR` | `jobhunter/data` | Database folder. |
| `JOBHUNTER_DB_PATH` | `<data dir>/jobhunter.db` | Database file. |
| `JOBHUNTER_OUTPUT_DIR` | `jobhunter/outputs` | Reports and generated application packs. |
| `JOBHUNTER_RESUME_DIR` | `jobhunter/resume` | Folder with your private `master_resume.txt`, `master_resume_fr.txt`, `summary_variants.json`. |
| `JOBHUNTER_LOG_DIR` | `jobhunter/logs` | Logs. |
| `JOBHUNTER_DASHBOARD_HOST` / `_PORT` / `_HEADLESS` | `127.0.0.1` / `8501` / off | Dashboard binding. Keep the host on loopback unless you add your own access control: the dashboard has no login. |

## Your resume

Create `jobhunter/resume/master_resume.txt` (and optionally `master_resume_fr.txt`) from the
`.template.txt` examples and replace all sample content with accurate details. A bullet may end with
`[tags: gcp, terraform]` to help ranking; tags are never rendered. Optionally copy
`summary_variants.template.json` to `summary_variants.json` and write your own summaries per role
family. Review every generated document before sending it.

## Location rules

The default filter accepts Greater Montreal and generic remote postings and rejects explicit
non-local locations. Postings with no location are kept only if their text places them in the
Montreal area; "remote" postings limited to another country are rejected. Adapt
`MONTREAL_AREA_TERMS` in `jobhunter/filter.py` for another city.
