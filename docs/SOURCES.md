# Job sources

Everything is optional and configured in `.env` (formats in [CONFIGURATION.md](CONFIGURATION.md)).
Employers' own boards are usually fresher and fuller than aggregator copies, so prefer them where
you can. A source that fails is logged and skipped; it never stops a run.

| Source | How it works | Needs |
| --- | --- | --- |
| JobSpy boards (Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google) | Scraped through the `python-jobspy` library | `JOB_SEARCH_TERMS`, `JOBSPY_SITES` |
| Greenhouse, Lever | Public board APIs | `GREENHOUSE_COMPANIES`, `LEVER_COMPANIES` (`Name|token`) |
| Ashby, Workable, SmartRecruiters, Recruitee | Public posting / widget APIs | `ASHBY_COMPANIES`, `WORKABLE_COMPANIES`, `SMARTRECRUITERS_COMPANIES`, `RECRUITEE_COMPANIES` |
| Workday (banks, insurers, aerospace...) | The career site's public JSON search | `WORKDAY_COMPANIES` (`Name|tenant|wd3|Site`) |
| Company career pages | `JobPosting` JSON-LD on the page; the employer's ATS is **detected automatically** from its links and embeds and queried through its API; otherwise job links are followed | `COMPANY_CAREER_URLS` |
| The Muse | Public API filtered to Montreal | On by default (`MUSE_ENABLED`) |
| Adzuna, Jooble | Free-tier aggregator APIs | `ADZUNA_APP_ID` / `ADZUNA_APP_KEY`, `JOOBLE_API_KEY` |
| Jobicy, Remotive, Arbeitnow | Public remote-job feeds | On by default |
| Any RSS / Atom feed | Generic parser | `RSS_FEEDS` (`Name|url`) |

## Finding a company's board settings

```bash
python -m jobhunter discover "Acme|https://acme.com/careers" --count
```

It detects the applicant-tracking system behind the page, prints the ready-to-paste `.env` line,
and with `--count` checks that the board answers.

## What happens after collection

- The same opening listed on several boards is merged; the employer's own copy wins and the longest
  description is kept.
- Roles you already applied to or dismissed are recognised by company and title, even when they
  reappear under a new URL.
- Short snippets (common from aggregators) are replaced with the full description from the posting
  page's own `JobPosting` data. LinkedIn, Indeed, Glassdoor, ZipRecruiter and Google pages are never
  fetched for enrichment.

## Being a good citizen

- Requests are paced (`REQUEST_DELAY_SECONDS`) and retried with back-off.
- Scraped boards can block you or change without notice. Check each site's terms, keep volumes
  modest, and use proxies only where you are authorised to.
- Provider endpoints are public but can change; if a source stops answering, check the logs.
