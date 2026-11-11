# Changelog

## 2.0.0 - 2026-11-11

### Changed
- Salaries are now stored in one canonical format everywhere (`$70,000 - $85,000 CAD/yr`, `$95,000 USD/yr`, `$30 CAD/hr`, `Not disclosed`) via a new `normalize_salary()` canonicalizer applied to every scraped posting in `normalize_job()`. Hourly postings are converted to an annual estimate (×2080) when scored.
- Job descriptions are cleaned of leftover HTML and markdown (`**`, `*`, `` ` ``, `#`) with collapsed whitespace, so scraped text renders as readable plain text in the dashboard and reports.

### Fixed
- The Muse source was failing with HTTP 403: all scraper requests now send browser-like default headers (`User-Agent`, `Accept`, `Accept-Language`), overridable per call.
- Removed the dead `Figma` Lever board default (its API token now 404s); set `LEVER_COMPANIES="Name|token"` in `.env` to enable Lever.
- ATS scrapers with no boards configured (Ashby, Workable, SmartRecruiters, Recruitee, Workday) now log "skipped: no boards configured" instead of a misleading "returned 0 postings".
- Test suite runs in ~10s instead of ~5 minutes: network-dependent scrapers are mocked in tests and CI uses `pytest -n auto` (xdist), with coverage isolated to a single matrix leg.
- Import fallbacks (`try/except ModuleNotFoundError` + `sys.path` hacks) removed across the package — the project is installed with `pip install -e .`.
- `purge_placeholders()` no longer deletes real senior/lead/manager postings via overly broad LIKE patterns.

### Changed
- README setup instructions use `python -m pip` throughout, with a Windows note explaining that the venv's `pip.exe` launcher hardcodes its original path and breaks after the project folder is renamed/moved (fix: recreate the venv).

### Removed
- Docker support: `Dockerfile`, `docker-compose.yml`, `.dockerignore`, the CI `docker` job and all Docker references in the docs. The app runs locally with a plain virtualenv (`python -m jobhunter run`).

## 0.2.0 - Product polish

### Added
- `python -m jobhunter` command (`run`, `collect`, `dashboard`, `demo`, `doctor`, `discover`, `version`) and `pip install -e .` packaging.
- **Demo mode**: an isolated workspace with a fictional candidate and invented postings, so anyone can explore the full dashboard without scraping or personal data.
- **`doctor`**: a setup check that lists what is missing and how to fix it (also shown in the dashboard sidebar).
- CI for Linux and Windows on Python 3.10-3.12 with a coverage gate, plus wheel and weekly dependency-audit workflows, Dependabot and an optional pre-commit config.
- Docs: architecture, scoring and configuration guides, contributing and security notes.
- Dashboard: first-run welcome and setup checklist, search/minimum-fit/source filters, richer job cards, structured profile tab, version footer, theme.
- Environment overrides for data, output, log, database and resume locations.

### Changed
- The dashboard now opens immediately and the first collection runs in the background (it used to block start-up for minutes).
- Scores soft-saturate above 88 so several strong postings no longer tie at exactly 100.
- Dependencies updated to versions without known advisories (requests, streamlit, python-dotenv, lxml, pyarrow) and verified together; `use_container_width` replaced with `width`.
- Streamlit usage telemetry disabled; the dashboard host is configurable (loopback by default).

### Removed
- Unused dependencies: `openai`, `scikit-learn`, `openpyxl`, `sqlite-utils` (and the unused `OPENAI_API_KEY` entry in `.env.example`).

### Fixed
- Built packages could have included private `master_resume*.txt` files; package data is now limited to template files and CI checks the wheel.

## Matching, tailoring and sources upgrade

### Fixed
- Skill keywords containing punctuation (`CI/CD`, `scikit-learn`) never matched because the posting was normalized but the keywords were not.
- Substring matching produced false hits: "excellent" counted as Excel, "digital" as Git, "International" as an internship, "Bilingual" as BI, and the established-company bonus fired for Honeywell/Disney (`ey`) and Sapient (`sap`). All checks are now whole-word (`textutils.contains_term`).
- A missing years-of-experience figure scored as the best case (90); the first "N years" anywhere (even company age) was used; `5+` never matched. Years are now parsed from experience context, ranges use their lower bound, and silence scores a neutral 80.
- A posting with no location was silently treated as "Remote" (JobSpy) or "Montreal, QC" (`normalize_job`). It is now "Unknown" and kept only if the text places it in Greater Montreal.
- Remote postings restricted to another country (US-only, UK-only...) are no longer accepted.
- Applications with a status past `applied` (interview, rejected, ...) reappeared in the new-opportunities lists.
- French "j'ai" was read as the skill "AI".

### Changed
- Skill score is requirement coverage: required vs. nice-to-have skills from the posting compared with what your profile and resume show; hard-stack gaps (Java, C#, ...) cost points. Scoring weights rebalanced so near-constant dimensions no longer flatten the score range.
- New adjustments: bilingual bonus, language mismatch penalty, freshness/stale, preference learning from applied vs. dismissed.
- Score explanations (`match_details`) are stored and shown in the dashboard. "Interview Chance" is relabelled "Match strength" (a heuristic, not a probability).
- Resume tailoring is generic: bullets and projects are ranked by evidence from their own text/tags; skill groups and items are reordered; optional user-written summary variants. The hardcoded project dictionary is gone.
- Cover letters are built from matching resume bullets (plus an optional user-written company line) instead of pasting the summary. Honest gap statements, bilingual line only when supported.
- Documents are generated in the posting's language by default in the dashboard.
- `ats_analysis` separates "skills you have but did not show" from "skills you have no record of (do not claim)".
- Postings are collected for 72 hours by default (was 7 days), descriptions kept up to 12,000 characters, up to 40 jobs persisted per run (was 25). All configurable.

### Added
- Sources: Ashby, Workable, SmartRecruiters, Recruitee, Workday, The Muse, Adzuna, Jooble, RSS/Atom; ATS auto-detection and job-link following on company career pages; `python -m jobhunter.scraper.discover`.
- Cross-board de-duplication, applied/dismissed matching by company+title, description enrichment for short snippets.
- Fabrication checks (`resume/verify.py`) and a `verification_report.txt` per application pack.
- Application lifecycle statuses, outcome recording and a Funnel view (rates by score band, source, language).
- `summary_variants.template.json`, optional `[tags: ...]` on resume bullets.
