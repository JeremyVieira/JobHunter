# JobHunter

JobHunter is a configurable job-search and application-tracking tool. It collects postings from supported job-board sources, scores them against a candidate profile, and provides a Streamlit dashboard for reviewing, tracking, and preparing application documents.

It can be configured for technical roles, business and data analysis, operations, administration, customer support, project coordination, and other job families. The default profile is only an example: customize target titles and keywords to match your own search.

## How It Works

1. **Collect:** modular adapters collect job postings from supported sources, including JobSpy-backed sources and public feeds such as Jobicy, Remotive, and Arbeitnow. Source availability and fields vary. Respect each site's terms and access limits.
2. **Score:** postings are evaluated for title fit, experience, education, skills, salary, location, and work arrangement using the candidate profile and scoring weights.
3. **Filter:** unrelated, unsuitable-level, location-mismatched, low-scoring, and selected company-risk postings can be filtered out.
4. **Review and track:** the dashboard shows matches and lets you record applied or dismissed opportunities. Local SQLite storage preserves the tracker between runs.
5. **Prepare application documents:** on request, the app creates English and French resume and cover-letter files for a selected posting. Resume content comes from your local master-resume files; tailoring emphasizes relevant skills and projects already in that source material. The app does not submit applications or send email.

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
- `USER_TARGET_ROLES`: comma-separated titles used for profile matching and role filtering; this does not itself change collection queries.
- `USER_PRIORITY_TARGET_ROLES`: titles that should score as the strongest role matches.
- `USER_KEYWORDS`: comma-separated skills, tools, credentials, or domain terms used for profile matching.
- `USER_EXPERIENCE_SUMMARY`, `USER_EXPERIENCE_YEARS`, and `USER_DEGREE`: profile details used by scoring and dashboard views.
- `JOBHUNTER_COLLECTION_HOUR` and `JOBHUNTER_COLLECTION_MINUTE`: daily collection schedule.
- `JOBHUNTER_DASHBOARD_PORT`: local dashboard port.

The example `.env` starts with business/data analysis, operations, and project-coordination searches. Replace both search terms and target roles with any combination that fits your search. For example, a hospitality profile could set both `JOB_SEARCH_TERMS` and `USER_TARGET_ROLES` to `Front Desk Supervisor, Event Coordinator, Guest Services Representative`, then use keywords such as `reservation systems, scheduling, customer service, conflict resolution`. Role titles and keywords are configurable; scoring rules and hard filters are in `jobhunter/config/settings.py` and `jobhunter/filter.py` if you want to adapt the logic further.

For application documents, create your own local `jobhunter/resume/master_resume.txt` and, optionally, `jobhunter/resume/master_resume_fr.txt`. The repository includes `.template.txt` examples; use them as structure references and replace all sample content with accurate details. The actual master-resume paths are ignored by Git. Review every generated document before sending it to an employer.

Optional proxy configuration is available through `JOBSPY_PROXIES`. Only configure services and access methods you are authorized to use. Keep proxy credentials in `.env`, never in source code.

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

