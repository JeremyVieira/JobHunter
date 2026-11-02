# JobHunter

JobHunter is a configurable job-search and application-tracking tool. It collects postings from supported job-board sources, scores them against a candidate profile, and provides a Streamlit dashboard for reviewing, tracking, and preparing application documents.

It can be configured for technical roles, business and data analysis, operations, administration, customer support, project coordination, and other job families. The default profile is only an example: customize target titles and keywords to match your own search.

## How It Works

1. **Collect:** modular adapters collect job postings from supported sources, including JobSpy-backed sources, public feeds such as Jobicy, Remotive, and Arbeitnow, ATS feeds such as Greenhouse and Lever, and configured company career pages. Source availability and fields vary. Respect each site's terms and access limits.
2. **Score:** postings are evaluated for title fit, experience, requirement coverage (which skills the posting asks for, required vs. nice-to-have, and which of them you can truthfully claim), education, salary, location, language, and freshness. Every score comes with a "why this score" explanation in the dashboard.
3. **Filter:** unrelated, unsuitable-level, location-mismatched, low-scoring, and selected company-risk postings can be filtered out.
4. **Review and track:** the dashboard shows matches and lets you record applied or dismissed opportunities. Local SQLite storage preserves the tracker between runs.
5. **Prepare application documents:** on request, the app creates resume and cover-letter files for a selected posting, in the language the posting is written in. Resume content comes from your local master-resume files; tailoring only *selects and orders* what is already there (see "Tailoring and honesty" below). The app does not submit applications or send email.
6. **Learn from outcomes:** record what happens after you apply (screening, interview, rejected, ghosted). The tracker's Funnel shows interview rates by score band, source, and document language, and your applied/dismissed history gently adjusts future scores.

Generated files, collected posting data, the SQLite database, and personal resume files may contain sensitive information. They are excluded from Git by default.

## Requirements

- Python 3.10, 3.11, or 3.12
- Internet access for job collection
- A modern browser for the Streamlit dashboard

## Setup

Clone the repository and create a virtual environment.

**Windows PowerShell**

```powershell
git clone https://github.com/JeremyVieira/JobHunter.git
cd JobHunter
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r jobhunter\requirements.txt
Copy-Item .env.example .env
```

If PowerShell blocks activation, you can skip activation and use `.venv\Scripts\python.exe -m pip ...` and `.venv\Scripts\python.exe -m jobhunter.app` instead.

**macOS or Linux**

```bash
git clone https://github.com/JeremyVieira/JobHunter.git
cd JobHunter
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r jobhunter/requirements.txt
cp .env.example .env
```

## Configure Your Search

Edit the local `.env` file. It is ignored by Git. Set your contact details and customize:

- `JOB_SEARCH_TERMS`: comma-separated JobSpy search queries. These drive searches on its supported boards.
- `JOB_SEARCH_LOCATION`: location passed to JobSpy searches.
- `JOBSPY_SITES`: comma-separated JobSpy sources to query; remove any source you do not intend to use.
- `COMPANY_CAREER_URLS`: optional comma-separated `Company Name|career URL` entries for additional public employer career pages.
- `USER_TARGET_ROLES`: comma-separated titles used for profile matching and role filtering; this does not itself change collection queries.
- `USER_PRIORITY_TARGET_ROLES`: titles that should score as the strongest role matches.
- `USER_KEYWORDS`: comma-separated skills, tools, credentials, or domain terms used for profile matching.
- `USER_EXPERIENCE_SUMMARY`, `USER_EXPERIENCE_YEARS`, and `USER_DEGREE`: profile details used by scoring and dashboard views.
- `USER_LANGUAGES`: languages you work in (default `en,fr`); drives the bilingual bonus and the penalty for postings in a language you do not speak.
- `JOBSPY_HOURS_OLD` (default 72), `JOBSPY_RESULTS_PER_TERM`, `MAX_PERSISTED_JOBS`: how fresh and how many postings to collect and keep per run.
- `JOBHUNTER_COLLECTION_HOUR` and `JOBHUNTER_COLLECTION_MINUTE`: daily collection schedule.
- `JOBHUNTER_DASHBOARD_PORT`: local dashboard port.

The example `.env` starts with business/data analysis, operations, and project-coordination searches. Replace both search terms and target roles with any combination that fits your search. For example, a hospitality profile could set both `JOB_SEARCH_TERMS` and `USER_TARGET_ROLES` to `Front Desk Supervisor, Event Coordinator, Guest Services Representative`, then use keywords such as `reservation systems, scheduling, customer service, conflict resolution`. Role titles and keywords are configurable; scoring rules and hard filters are in `jobhunter/config/settings.py` and `jobhunter/filter.py` if you want to adapt the logic further. The default location filter accepts Montreal and nearby municipalities (such as Laval, Longueuil, and Brossard) plus generic remote postings; it rejects explicit non-local locations such as Seattle or Toronto, even if the description mentions remote work. Postings with no location are kept only if the posting text places them in Greater Montreal, and generic "remote" postings are rejected when they are explicitly limited to another region (for example "must be authorized to work in the US").

For application documents, create your own local `jobhunter/resume/master_resume.txt` and, optionally, `jobhunter/resume/master_resume_fr.txt`. The repository includes `.template.txt` examples; use them as structure references and replace all sample content with accurate details. The actual master-resume paths are ignored by Git. Review every generated document before sending it to an employer.

Optional proxy configuration is available through `JOBSPY_PROXIES`. Only configure services and access methods you are authorized to use. Keep proxy credentials in `.env`, never in source code.

## More job sources

Beyond the JobSpy-backed boards, JobHunter can read employers' own postings (usually fresher and fuller than aggregator copies) and extra boards. Everything is optional and configured in `.env`; see `.env.example` for the exact formats.

| Source | How it works | Needs |
| --- | --- | --- |
| Greenhouse, Lever | public board APIs | `GREENHOUSE_COMPANIES`, `LEVER_COMPANIES` (`Name\|token`) |
| Ashby, Workable, SmartRecruiters, Recruitee | public posting/widget APIs | `ASHBY_COMPANIES`, `WORKABLE_COMPANIES`, `SMARTRECRUITERS_COMPANIES`, `RECRUITEE_COMPANIES` |
| Workday (banks, insurers, aerospace...) | the career site's public JSON search | `WORKDAY_COMPANIES` (`Name\|tenant\|wd3\|Site`) |
| Company career pages | JSON-LD `JobPosting` on the page; **auto-detects the employer's ATS** from the page's links and uses its API; otherwise follows job links | `COMPANY_CAREER_URLS` |
| The Muse | public API filtered to Montreal | on by default (`MUSE_ENABLED`) |
| Adzuna, Jooble | free-tier aggregator APIs | `ADZUNA_APP_ID/KEY`, `JOOBLE_API_KEY` |
| Any RSS/Atom feed | generic parser | `RSS_FEEDS` (`Name\|url`) |

**Find the right token for a company** instead of guessing:

```bash
python -m jobhunter.scraper.discover "Acme|https://acme.com/careers" --count
```

It detects the ATS behind the page, prints the ready-to-paste `.env` line, and with `--count` checks that the board answers.

Collection also de-duplicates the same opening across boards (the employer's own copy wins), recognises roles you already applied to or dismissed even when they reappear under a new URL, and fetches fuller descriptions (from the posting's own `JobPosting` data) for short aggregator snippets. LinkedIn, Indeed, Glassdoor, ZipRecruiter and Google pages are never fetched directly for enrichment. Requests are paced (`REQUEST_DELAY_SECONDS`); respect each provider's terms and rate limits. JSON-LD and ATS endpoints are public, but providers can change them without notice: a source that stops answering is logged and skipped, not fatal.

## Tailoring and honesty

Generated documents never add information:

- **Resume:** only ordering and selection change. Bullets within each job/project are ranked by how well they evidence what the posting asks for, the most relevant projects are chosen from *all* your projects (no hardcoded names), and skill groups and the items inside them are reordered. Nothing is reworded.
- **Optional tags:** a bullet may end with `[tags: gcp, terraform]` to help ranking. Tags are never rendered. Without tags, skills are detected from the bullet text.
- **Summary variants:** copy `jobhunter/resume/summary_variants.template.json` to `summary_variants.json` (git-ignored) and write your own summaries per role family (software, data/ML, DevOps/cloud, analyst, support). The matching one replaces the summary; otherwise your summary stays untouched.
- **Cover letter:** built from the master-resume bullets that match the posting's requirements, your education line, and (only for bilingual/French postings, and only if your resume supports it) a language line. A company-specific line appears **only if you type one** in the dashboard. If the posting names a hard-stack skill you lack (for example Java) and the taxonomy knows a related tool you do have, the letter says so plainly instead of claiming the skill. Set `mention_gaps=False` in `generate_cover_letter` to turn that off.
- **Verification:** every generated pack is checked mechanically. Resume lines must exist in the master resume (skill lists may be reordered, nothing else), and numbers or known skills in a letter must appear in your resume or the posting. Anything else is listed in `verification_report.txt` and in the dashboard before you send.

## Reading your results

- **Fit score** blends title, experience (years asked vs. your years, with one year of stretch), requirement coverage, and small location/salary signals, then adjusts for entry-level wording, bilingual postings, freshness, hard-stack gaps (Java, C#, ...), language mismatch, and learned preferences. Dimensions that barely vary carry little weight so the score spreads.
- **Match strength** (formerly "Interview Chance") is a heuristic, not a probability. Your real callback rates are in the tracker's **Funnel**, which only counts outcomes you record.
- **Preference learning** needs at least 30 applied/dismissed examples with 5+ of each kind and moves scores by at most 8 points.

## Run

Start collection and the dashboard together:

```powershell
python -m jobhunter.app
```

The dashboard is available at `http://127.0.0.1:8501` by default. Startup runs a collection once, then schedules daily runs at the configured local time while the app process remains open. This is not a Windows service and will not run after the app is closed or the computer is off. To collect once without starting the dashboard:

```powershell
python -c "from jobhunter.app import run_daily_collection; print(f'Collected {len(run_daily_collection())} jobs')"
```

To run only the dashboard:

```powershell
python -m streamlit run jobhunter/dashboard/app.py
```

The local database is stored at `jobhunter/data/jobhunter.db`. Reports and exports are written under `jobhunter/outputs/`, including per-posting application packs under `jobhunter/outputs/resumes/`.

## Tests and Lint

```bash
python -m pytest tests/ -v
python -m ruff check .
```

## Privacy Before Publishing

- Keep `.env`, local profile settings, master resumes, generated documents, databases, logs, and scraped/exported job data out of commits.
- The tracked `.env.example` contains placeholders only. Do not put real credentials or contact details in it.
- Review `git status` and `git diff --cached` before pushing. `.gitignore` does not remove a file Git already tracks; if a secret was committed, rotate or revoke it and remove it from repository history as appropriate.
