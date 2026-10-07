from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from jobspy import scrape_jobs

try:
    from jobhunter.config.settings import (
        JOB_SEARCH_LOCATION,
        JOB_SEARCH_TERMS,
        JOBSPY_PROXIES,
        JOBSPY_SITES,
    )
    from jobhunter.models import JobListing
except ModuleNotFoundError:  # pragma: no cover
    try:
        from config.settings import (
            JOB_SEARCH_LOCATION,
            JOB_SEARCH_TERMS,
            JOBSPY_PROXIES,
            JOBSPY_SITES,
        )
        from models import JobListing
    except ModuleNotFoundError:
        JOB_SEARCH_LOCATION = "Montreal, QC"
        JOB_SEARCH_TERMS = []
        JOBSPY_PROXIES = None
        JOBSPY_SITES = ["indeed", "linkedin", "zip_recruiter", "glassdoor", "google"]

        @dataclass
        class JobListing:  # type: ignore[no-redef]
            title: str
            company: str
            location: str
            remote_status: str
            salary: str
            description: str
            posting_date: str
            url: str
            source: str = "manual"

            def to_dict(self):
                return asdict(self)


JOBICY_API_URL = "https://jobicy.com/api/v2/remote-jobs?count=50"
REMOTIVE_API_URL = "https://remotive.com/api/remote-jobs?limit=50"
ARBEITNOW_API_URL = "https://www.arbeitnow.com/api/job-board-api"
# All 5 major search boards supported by JobSpy
JOBSPY_LOCATION = JOB_SEARCH_LOCATION
DEFAULT_SEARCH_TERMS = [
    "Junior Software Engineer",
    "Software Engineer I",
    "Associate Software Engineer",
    "Graduate Software Engineer",
    "New Grad Software Engineer",
    "Software Engineer",
    "Junior Software Developer",
    "Software Developer",
    "Python Developer",
    "Junior Python Developer",
    "Backend Developer",
    "Backend Engineer",
    "Junior Backend Developer",
    "Full Stack Developer",
    "Full Stack Engineer",
    "Automation Engineer",
    "Junior Automation Engineer",
    "Test Automation Engineer",
    "QA Automation Engineer",
    "Machine Learning Engineer",
    "Junior Machine Learning Engineer",
    "ML Engineer",
    "AI Engineer",
    "Junior AI Engineer",
    "Data Scientist",
    "Junior Data Scientist",
    "Data Engineer",
    "Junior Data Engineer",
    "DevOps Engineer",
    "Junior DevOps Engineer",
    "Cloud Engineer",
    "Site Reliability Engineer",

    "Développeur Python junior",
]

# Titles that are never a fit for a new-grad IC engineering search, no matter which
# board or search term surfaced them (job boards frequently mix "related" postings
# like Engineering Manager or Director of Engineering into results for "Software
# Engineer" searches). Kept in sync with scoring.MANAGEMENT_TITLE_TERMS.
EXCLUDED_TITLE_TERMS = (
    "manager",
    "director",
    "vp ",
    "vice president",
    "head of",
    "chief",
    "president",
    "executive",
    "general manager",
)

# Company-name fragments that signal the poster is hiding who they are, which
# correlates strongly with low-quality or scammy postings (fake "confidential"
# listings, resume-harvesting, recruiting-agency spam with no real employer named).
SHADY_COMPANY_NAME_TERMS = (
    "confidential",
    "undisclosed",
    "anonymous",
    "stealth",
    "various clients",
    "a client of",
    "our client",
)

# Description-level red flags for scams / pyramid-scheme-adjacent postings and
# postings that aren't real jobs (unpaid, pay-to-apply, "guaranteed income" spam).
SHADY_DESCRIPTION_TERMS = (
    "unpaid position",
    "no salary",
    "equity only",
    "must pay",
    "training fee",
    "pay to apply",
    "registration fee",
    "guaranteed income",
    "be your own boss",
    "unlimited earning potential",
    "wire transfer",
    "processing fee",
    "send your bank details",
)

# A real posting almost always runs longer than this; a description this thin is
# usually a stub/spam listing rather than an actual job ad worth reading.
MIN_DESCRIPTION_LENGTH = 80
LOGGER = logging.getLogger(__name__)
MAX_GET_ATTEMPTS = 3
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _request_get(url: str, *, timeout: int = 20, **kwargs):
    for attempt in range(1, MAX_GET_ATTEMPTS + 1):
        try:
            response = requests.get(url, timeout=timeout, **kwargs)
        except (requests.ConnectionError, requests.Timeout):
            if attempt == MAX_GET_ATTEMPTS:
                raise
            LOGGER.warning("GET request failed on attempt %s/%s: %s", attempt, MAX_GET_ATTEMPTS, url, exc_info=True)
            time.sleep(0.25 * 2 ** (attempt - 1))
            continue

        status_code = getattr(response, "status_code", 200)
        if status_code in RETRYABLE_STATUS_CODES and attempt < MAX_GET_ATTEMPTS:
            retry_after = getattr(response, "headers", {}).get("Retry-After", "")
            try:
                delay = min(float(retry_after), 30.0)
            except (TypeError, ValueError):
                delay = 0.25 * 2 ** (attempt - 1)
            LOGGER.warning(
                "GET request received HTTP %s on attempt %s/%s: %s",
                status_code,
                attempt,
                MAX_GET_ATTEMPTS,
                url,
            )
            time.sleep(delay)
            continue

        response.raise_for_status()
        return response

    raise RuntimeError(f"GET request failed after {MAX_GET_ATTEMPTS} attempts: {url}")

# Companies large/stable enough that startup-culture language in their own JD (e.g.
# "fast-paced") shouldn't count against them. Kept loosely in sync with
# scoring.CompositeScorer.KNOWN_ESTABLISHED_COMPANIES; duplicated here so this file
# has no import dependency on scoring.py.
KNOWN_ESTABLISHED_COMPANIES = (
    "rbc", "royal bank", "td bank", "td canada trust", "scotiabank", "bmo",
    "bank of montreal", "national bank", "desjardins", "sun life", "manulife",
    "intact", "cgi", "cae", "bombardier", "air canada", "hydro quebec",
    "loto quebec", "caisse de depot", "bell canada", "rogers", "telus",
    "videotron", "shopify", "lightspeed", "nuvei", "ubisoft", "ericsson", "ibm",
    "microsoft", "google", "amazon", "meta", "salesforce", "sap", "oracle",
    "cisco", "deloitte", "pwc", "ey", "kpmg", "accenture", "loblaw",
    "metro inc", "canadian tire", "stripe", "gitlab", "databricks", "figma",
    "datadog", "airbnb", "spotify",
)

# Self-described early-stage/tiny-team language. Free job-board APIs don't expose
# employee counts, so this is a best-effort proxy, not a real headcount check —
# it only catches companies that describe themselves this way in the posting.
TINY_STARTUP_SIGNAL_TERMS = (
    "pre-seed",
    "seed stage",
    "seed-stage",
    "early stage startup",
    "early-stage startup",
    "small but mighty",
    "wear many hats",
    "founding engineer",
    "founding team",
    "series a startup",
    "bootstrapped",
    "small scrappy team",
    "fast paced startup environment",
    "we're a small team",
    "we are a small team",
)


def _normalize_for_filter(value: str) -> str:
    return (value or "").lower()


def is_excluded_title(title: str) -> bool:
    """True if a title is a structural mismatch (management/executive) regardless
    of how well the rest of the posting reads."""
    text = _normalize_for_filter(title)
    return any(term in text for term in EXCLUDED_TITLE_TERMS)


def is_shady_posting(job: dict[str, Any]) -> bool:
    """True for postings that look like spam, scams, or resume-harvesting rather
    than a real job: an unnamed employer, pay-to-apply / unpaid-position language,
    or a description too thin to be a genuine ad."""
    company = _normalize_for_filter(job.get("company", ""))
    description = _normalize_for_filter(job.get("description", ""))

    if any(term in company for term in SHADY_COMPANY_NAME_TERMS):
        return True
    if any(term in description for term in SHADY_DESCRIPTION_TERMS):
        return True
    if description and len(description) < MIN_DESCRIPTION_LENGTH:
        return True
    return False


def is_likely_tiny_startup(job: dict[str, Any]) -> bool:
    """Best-effort proxy for 'tiny/very early-stage company'. Free scraping APIs
    don't expose employee counts or funding data, so this only catches companies
    whose own name or job description self-identifies as small/early-stage. It
    will under-flag (a real tiny startup that doesn't say so in the JD slips
    through) but should rarely over-flag a genuinely established employer."""
    company = _normalize_for_filter(job.get("company", ""))
    if any(name in company for name in KNOWN_ESTABLISHED_COMPANIES):
        return False
    if any(term in company for term in ("labs", "forge", "ventures", "startup")):
        return True
    description = _normalize_for_filter(job.get("description", ""))
    if any(term in description for term in TINY_STARTUP_SIGNAL_TERMS):
        return True
    return False


def filter_relevant_jobs(
    jobs: Iterable[dict[str, Any]],
    exclude_tiny_startups: bool = True,
) -> list[dict[str, Any]]:
    """Drop management/executive titles, shady/spammy postings, and (optionally)
    self-described tiny/early-stage startups from a combined jobs list.

    Call this once, after merging results from all scrapers and before handing the
    list to scoring.score_jobs() (which also filters management titles by default)
    or to save_jobs_to_json(), so mismatched/low-quality postings don't clutter
    storage either. Set exclude_tiny_startups=False if you'd rather see small
    companies ranked normally instead of removed — the signal is best-effort, so
    over-filtering is possible.
    """
    filtered = [job for job in jobs if not is_excluded_title(job.get("title", ""))]
    filtered = [job for job in filtered if not is_shady_posting(job)]
    if exclude_tiny_startups:
        filtered = [job for job in filtered if not is_likely_tiny_startup(job)]
    return filtered


class BaseScraper(ABC):
    """Abstract base class for all job scrapers."""

    @abstractmethod
    def scrape(self) -> list[dict[str, Any]]:
        """Fetch and return normalized job listings."""
        pass


class JobicyScraper(BaseScraper):
    """Scraper adapter for Jobicy public remote jobs API."""

    def __init__(self, api_url: str = JOBICY_API_URL, timeout: int = 20):
        self.api_url = api_url
        self.timeout = timeout

    def scrape(self) -> list[dict[str, Any]]:
        response = _request_get(self.api_url, timeout=self.timeout)
        payload = response.json()
        jobs: list[dict[str, Any]] = []

        for item in payload.get("jobs", []):
            title = (item.get("jobTitle") or "").strip()
            company = (item.get("companyName") or "").strip()
            url = (item.get("url") or "").strip()
            if not title or not company or not url:
                continue

            description = BeautifulSoup(
                item.get("jobDescription") or item.get("jobExcerpt") or "", "html.parser"
            ).get_text(" ", strip=True)
            salary_minimum = item.get("salaryMin")
            salary = (
                f"{item.get('salaryCurrency', '$')}{salary_minimum}"
                if salary_minimum
                else "Not disclosed"
            )
            jobs.append(
                normalize_job(
                    {
                        "title": title,
                        "company": company,
                        "location": item.get("jobGeo") or "Remote",
                        "remote_status": "Remote",
                        "salary": salary,
                        "description": description,
                        "posting_date": item.get("pubDate") or "Unknown",
                        "url": url,
                        "source": "jobicy",
                    }
                )
            )
        return jobs


class RemotiveScraper(BaseScraper):
    """Scraper adapter for Remotive public API."""

    def __init__(self, api_url: str = REMOTIVE_API_URL, timeout: int = 20):
        self.api_url = api_url
        self.timeout = timeout

    def scrape(self) -> list[dict[str, Any]]:
        try:
            response = _request_get(self.api_url, timeout=self.timeout)
            payload = response.json()
        except Exception:
            LOGGER.exception("Remotive source request failed.")
            return []

        jobs: list[dict[str, Any]] = []
        for item in payload.get("jobs", []):
            title = (item.get("title") or "").strip()
            company = (item.get("company_name") or "").strip()
            url = (item.get("url") or "").strip()
            if not title or not company or not url:
                continue

            raw_desc = item.get("description") or ""
            description = BeautifulSoup(raw_desc, "html.parser").get_text(" ", strip=True)
            salary = item.get("salary") or "Not disclosed"
            candidate_loc = item.get("candidate_required_location") or "Remote"

            jobs.append(
                normalize_job(
                    {
                        "title": title,
                        "company": company,
                        "location": candidate_loc,
                        "remote_status": "Remote",
                        "salary": salary,
                        "description": description,
                        "posting_date": str(item.get("publication_date", "Unknown"))[:10],
                        "url": url,
                        "source": "remotive",
                    }
                )
            )
        return jobs


class ArbeitnowScraper(BaseScraper):
    """Scraper adapter for Arbeitnow public API."""

    def __init__(self, api_url: str = ARBEITNOW_API_URL, timeout: int = 20):
        self.api_url = api_url
        self.timeout = timeout

    def scrape(self) -> list[dict[str, Any]]:
        try:
            response = _request_get(self.api_url, timeout=self.timeout)
            payload = response.json()
        except Exception:
            LOGGER.exception("Arbeitnow source request failed.")
            return []

        jobs: list[dict[str, Any]] = []
        for item in payload.get("data", []):
            title = (item.get("title") or "").strip()
            company = (item.get("company_name") or "").strip()
            url = (item.get("url") or "").strip()
            if not title or not company or not url:
                continue

            raw_desc = item.get("description") or ""
            description = BeautifulSoup(raw_desc, "html.parser").get_text(" ", strip=True)
            is_remote = bool(item.get("remote"))
            location = (item.get("location") or ("Remote" if is_remote else "Montreal, QC")).strip()

            jobs.append(
                normalize_job(
                    {
                        "title": title,
                        "company": company,
                        "location": location,
                        "remote_status": "Remote" if is_remote else "Hybrid/On-site",
                        "salary": "Not disclosed",
                        "description": description,
                        "posting_date": str(item.get("created_at", "Unknown"))[:10],
                        "url": url,
                        "source": "arbeitnow",
                    }
                )
            )
        return jobs


class JobSpyScraper(BaseScraper):
    """Scraper adapter for JobSpy multi-platform search."""

    def __init__(
        self,
        search_terms: list[str] | None = None,
        results_wanted_per_term: int = 15,
        proxies: list[str] | str | None = None,
        location: str | None = None,
        sites: list[str] | None = None,
    ):
        self.search_terms = search_terms or JOB_SEARCH_TERMS or DEFAULT_SEARCH_TERMS
        self.results_wanted_per_term = results_wanted_per_term
        self.proxies = proxies if proxies is not None else JOBSPY_PROXIES
        self.location = location or JOB_SEARCH_LOCATION
        self.sites = sites or JOBSPY_SITES

    def scrape(self) -> list[dict[str, Any]]:
        _suppress_jobspy_loggers()
        all_jobs: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for term in self.search_terms:
            try:
                listings = scrape_jobs(
                    site_name=self.sites,
                    search_term=term,
                    location=self.location,
                    results_wanted=self.results_wanted_per_term,
                    country_indeed="Canada",
                    hours_old=168,
                    proxies=self.proxies,
                )
                for item in listings.to_dict(orient="records"):
                    title = _jobspy_text(item.get("title"))
                    company = _jobspy_text(item.get("company"))
                    url = _jobspy_text(item.get("job_url_direct")) or _jobspy_text(
                        item.get("job_url")
                    )
                    if not title or not company or not url or url in seen_urls:
                        continue

                    seen_urls.add(url)
                    salary_minimum = item.get("min_amount")
                    salary_maximum = item.get("max_amount")
                    currency = _jobspy_text(item.get("currency"), "$")
                    if salary_minimum and salary_maximum:
                        salary = f"{currency}{salary_minimum} - {currency}{salary_maximum}"
                    elif salary_minimum:
                        salary = f"{currency}{salary_minimum}"
                    else:
                        salary = "Not disclosed"

                    all_jobs.append(
                        normalize_job(
                            {
                                "title": title,
                                "company": company,
                                "location": _jobspy_text(item.get("location"), "Remote"),
                                "remote_status": "Remote" if item.get("is_remote") else "On-site",
                                "salary": salary,
                                "description": _jobspy_text(item.get("description")),
                                "posting_date": _jobspy_text(item.get("date_posted"), "Unknown"),
                                "url": url,
                                "source": _jobspy_text(item.get("site"), "jobspy"),
                            }
                        )
                    )
            except Exception:
                LOGGER.exception(
                    "JobSpy search failed for term %r on sources %s.", term, self.sites
                )
                continue
        return all_jobs


GREENHOUSE_API_TEMPLATE = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
LEVER_API_TEMPLATE = "https://api.lever.co/v0/postings/{token}?mode=json"

# Seed lists for the two ATS scrapers below: (display_name, board_token) pairs.
# These are the *company's own* career-page postings (Greenhouse/Lever host the
# application flow, but the board belongs to the employer) — this is how you get
# "straight from the company's website" instead of only aggregator sites.
#
# How to find a token for a company you care about: open their careers page.
#   Greenhouse URL looks like boards.greenhouse.io/<token> or job-boards.greenhouse.io/<token>
#   Lever URL looks like jobs.lever.co/<token>
# The handful below are just confirmed-working examples to show the shape of the
# list — replace/extend with the specific companies you're actually targeting
# (established employers you trust, ideally ones already on your radar).
GREENHOUSE_COMPANIES: list[tuple[str, str]] = [
    ("Stripe", "stripe"),
    ("GitLab", "gitlab"),
    ("Databricks", "databricks"),
]

LEVER_COMPANIES: list[tuple[str, str]] = [
    ("Figma", "figma"),
]


class GreenhouseScraper(BaseScraper):
    """Scraper adapter for Greenhouse's public, unauthenticated Job Board API —
    pulls postings directly from a company's own careers page/ATS rather than a
    third-party aggregator. One request per company, no login or API key needed."""

    def __init__(
        self,
        companies: list[tuple[str, str]] | None = None,
        timeout: int = 20,
    ):
        self.companies = companies if companies is not None else GREENHOUSE_COMPANIES
        self.timeout = timeout

    def scrape(self) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        for display_name, token in self.companies:
            try:
                url = GREENHOUSE_API_TEMPLATE.format(token=token)
                response = _request_get(url, timeout=self.timeout)
                payload = response.json()
            except Exception:
                LOGGER.exception("Greenhouse request failed for board %s.", display_name)
                continue

            for item in payload.get("jobs", []):
                title = (item.get("title") or "").strip()
                job_url = (item.get("absolute_url") or "").strip()
                if not title or not job_url:
                    continue

                location = ((item.get("location") or {}).get("name") or "Unknown").strip()
                description = BeautifulSoup(item.get("content") or "", "html.parser").get_text(
                    " ", strip=True
                )
                is_remote = "remote" in location.lower()

                jobs.append(
                    normalize_job(
                        {
                            "title": title,
                            "company": display_name,
                            "location": location or "Unknown",
                            "remote_status": "Remote" if is_remote else "On-site",
                            "salary": "Not disclosed",
                            "description": description,
                            "posting_date": (item.get("updated_at") or "Unknown")[:10],
                            "url": job_url,
                            "source": "greenhouse",
                        }
                    )
                )
        return jobs


class LeverScraper(BaseScraper):
    """Scraper adapter for Lever's public, unauthenticated postings API — same idea
    as GreenhouseScraper but for companies whose careers page runs on Lever."""

    def __init__(
        self,
        companies: list[tuple[str, str]] | None = None,
        timeout: int = 20,
    ):
        self.companies = companies if companies is not None else LEVER_COMPANIES
        self.timeout = timeout

    def scrape(self) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        for display_name, token in self.companies:
            try:
                url = LEVER_API_TEMPLATE.format(token=token)
                response = _request_get(url, timeout=self.timeout)
                payload = response.json()
            except Exception:
                LOGGER.exception("Lever request failed for board %s.", display_name)
                continue

            if not isinstance(payload, list):
                continue

            for item in payload:
                title = (item.get("text") or "").strip()
                job_url = (item.get("hostedUrl") or "").strip()
                if not title or not job_url:
                    continue

                categories = item.get("categories") or {}
                location = (categories.get("location") or "Unknown").strip()
                workplace_type = (categories.get("workplaceType") or "").lower()
                is_remote = workplace_type == "remote" or "remote" in location.lower()
                description = BeautifulSoup(
                    item.get("descriptionPlain") or item.get("description") or "",
                    "html.parser",
                ).get_text(" ", strip=True)

                jobs.append(
                    normalize_job(
                        {
                            "title": title,
                            "company": display_name,
                            "location": location or "Unknown",
                            "remote_status": "Remote" if is_remote else "On-site",
                            "salary": "Not disclosed",
                            "description": description,
                            "posting_date": "Unknown",
                            "url": job_url,
                            "source": "lever",
                        }
                    )
                )
        return jobs


class ScraperFactory:
    """Factory to create registered job scrapers."""

    _registry: dict[str, type[BaseScraper]] = {
        "jobicy": JobicyScraper,
        "remotive": RemotiveScraper,
        "arbeitnow": ArbeitnowScraper,
        "jobspy": JobSpyScraper,
        "greenhouse": GreenhouseScraper,
        "lever": LeverScraper,
    }

    @classmethod
    def create(cls, scraper_type: str, **kwargs: Any) -> BaseScraper:
        scraper_cls = cls._registry.get(scraper_type.lower())
        if not scraper_cls:
            raise ValueError(
                f"Unknown scraper type: '{scraper_type}'. Available: {list(cls._registry.keys())}"
            )
        return scraper_cls(**kwargs)

    @classmethod
    def register(cls, scraper_type: str, scraper_cls: type[BaseScraper]) -> None:
        cls._registry[scraper_type.lower()] = scraper_cls


def fetch_job_page(url: str, timeout: int = 20) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    response = _request_get(url, headers=headers, timeout=timeout)
    return response.text


def fetch_jobicy_jobs(timeout: int = 20) -> list[dict]:
    return JobicyScraper(timeout=timeout).scrape()


def fetch_remotive_jobs(timeout: int = 20) -> list[dict]:
    return RemotiveScraper(timeout=timeout).scrape()


def fetch_arbeitnow_jobs(timeout: int = 20) -> list[dict]:
    return ArbeitnowScraper(timeout=timeout).scrape()


def fetch_greenhouse_jobs(
    companies: list[tuple[str, str]] | None = None, timeout: int = 20
) -> list[dict]:
    return GreenhouseScraper(companies=companies, timeout=timeout).scrape()


def fetch_lever_jobs(
    companies: list[tuple[str, str]] | None = None, timeout: int = 20
) -> list[dict]:
    return LeverScraper(companies=companies, timeout=timeout).scrape()


def fetch_all_jobs(
    jobspy_search_terms: list[str] | None = None,
    greenhouse_companies: list[tuple[str, str]] | None = None,
    lever_companies: list[tuple[str, str]] | None = None,
    exclude_tiny_startups: bool = True,
) -> list[dict]:
    """Run every scraper (job boards + direct-from-company-website ATS feeds),
    merge and de-dupe by URL, then apply filter_relevant_jobs(). This is the
    one-stop entry point for "scour everything, but keep it clean."
    """
    all_jobs: list[dict[str, Any]] = []
    all_jobs.extend(fetch_jobicy_jobs())
    all_jobs.extend(fetch_remotive_jobs())
    all_jobs.extend(fetch_arbeitnow_jobs())
    all_jobs.extend(fetch_jobspy_jobs(search_terms=jobspy_search_terms))
    all_jobs.extend(fetch_greenhouse_jobs(companies=greenhouse_companies))
    all_jobs.extend(fetch_lever_jobs(companies=lever_companies))

    seen_urls: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for job in all_jobs:
        url = job.get("url", "")
        if url and url in seen_urls:
            continue
        seen_urls.add(url)
        deduped.append(job)

    return filter_relevant_jobs(deduped, exclude_tiny_startups=exclude_tiny_startups)


def _jobspy_text(value, default: str = "") -> str:
    if value is None or str(value).lower() == "nan":
        return default
    return str(value).strip() or default


def _suppress_jobspy_loggers() -> None:
    """Mute noisy error logs from third-party scrapers that hit anti-bot defenses."""
    for module_name in ["jobspy.glassdoor", "jobspy.ziprecruiter"]:
        try:
            mod = __import__(module_name, fromlist=["log"])
            if hasattr(mod, "log"):
                mod.log.disabled = True
        except Exception:
            pass


def fetch_jobspy_jobs(
    search_terms: list[str] | None = None,
    results_wanted_per_term: int = 15,
    proxies: list[str] | str | None = None,
) -> list[dict]:
    return JobSpyScraper(
        search_terms=search_terms,
        results_wanted_per_term=results_wanted_per_term,
        proxies=proxies,
    ).scrape()


def parse_linkedin_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select("li.jobs-search-results__list-item") or soup.select(
        "div.job-card-container"
    ):
        title = card.select_one("h3, .job-card-list__title, .base-search-card__title")
        company = card.select_one(
            "h4, .job-card-container__company-name, .base-search-card__subtitle"
        )
        location = card.select_one(".job-search-card__location, .base-search-card__metadata")
        link = card.select_one("a")
        if title:
            jobs.append(
                {
                    "title": title.get_text(" ", strip=True),
                    "company": company.get_text(" ", strip=True) if company else "Unknown",
                    "location": location.get_text(" ", strip=True) if location else "Remote",
                    "remote_status": "Hybrid/Remote"
                    if "remote" in (location.get_text(" ", strip=True).lower() if location else "")
                    else "On-site",
                    "salary": "Not disclosed",
                    "description": card.get_text(" ", strip=True)[:1500],
                    "posting_date": "Unknown",
                    "url": link.get("href") if link else "",
                    "source": "linkedin",
                }
            )
    return jobs


def parse_indeed_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select("div.jobsearch-SerpJobCard"):
        title = card.select_one("h2.jobtitle a")
        company = card.select_one("span.companyName")
        location = card.select_one("div.companyLocation")
        salary = card.select_one("div.salary-snippet-container")
        link = card.select_one("h2.jobtitle a")
        if title:
            jobs.append(
                {
                    "title": title.get_text(" ", strip=True),
                    "company": company.get_text(" ", strip=True) if company else "Unknown",
                    "location": location.get_text(" ", strip=True) if location else "Montreal, QC",
                    "remote_status": "Hybrid/Remote"
                    if "remote" in (location.get_text(" ", strip=True).lower() if location else "")
                    else "On-site",
                    "salary": salary.get_text(" ", strip=True) if salary else "Not disclosed",
                    "description": card.get_text(" ", strip=True)[:1500],
                    "posting_date": "Unknown",
                    "url": "https://ca.indeed.com" + link.get("href")
                    if link and link.get("href", "").startswith("/")
                    else (link.get("href") if link else ""),
                    "source": "indeed",
                }
            )
    return jobs


def parse_generic_html(html: str, source: str) -> list[dict]:
    """Ignore pages that cannot be parsed into individual job listings."""
    return []


def normalize_job(job: dict) -> dict:
    normalized = {
        "title": (job.get("title") or "Unknown role").strip(),
        "company": (job.get("company") or "Unknown").strip(),
        "location": (job.get("location") or "Montreal, QC").strip(),
        "remote_status": (job.get("remote_status") or "Hybrid/Remote").strip(),
        "salary": (job.get("salary") or "Not disclosed").strip(),
        "description": (job.get("description") or "").strip()[:4000],
        "posting_date": (job.get("posting_date") or "Unknown").strip(),
        "url": (job.get("url") or "").strip(),
        "source": (job.get("source") or "manual").strip(),
    }
    return normalized


def canonical_job_url(url: str) -> str:
    parsed = urlsplit((url or "").strip())
    hostname = parsed.netloc.lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    ignored_parameters = {"fbclid", "gclid", "msclkid", "ref", "referrer"}
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in ignored_parameters
        )
    )
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), hostname, path, query, ""))


def collect_jobs_from_urls(urls: Iterable[str]) -> list[dict]:
    jobs = []
    for url in urls:
        if not url:
            continue
        hostname = urlparse(url).netloc.lower()
        try:
            html = fetch_job_page(url)
            parsed = None
            if "linkedin" in hostname:
                parsed = parse_linkedin_html(html)
            elif "indeed" in hostname:
                parsed = parse_indeed_html(html)
            else:
                parsed = parse_generic_html(html, hostname)
            jobs.extend(normalize_job(job) for job in parsed)
        except Exception:
            LOGGER.exception("Fallback page collection failed for host %s.", hostname)
            continue
    return jobs


def build_example_jobs() -> list[dict]:
    return [
        {
            "title": "Junior Python Developer",
            "company": "Nuvei",
            "location": "Montreal, QC",
            "remote_status": "Hybrid",
            "salary": "$70,000 - $85,000",
            "description": "Junior Python developer role building automation scripts, internal tooling, and REST APIs. Great fit for a new grad with Python and SQL experience.",
            "posting_date": "2026-08-30",
            "url": "https://example.com/job/pydev",
            "source": "demo",
        },
        {
            "title": "Machine Learning Engineer I",
            "company": "Lightspeed",
            "location": "Montreal, QC",
            "remote_status": "Hybrid",
            "salary": "$75,000 - $95,000",
            "description": "Entry-level machine learning engineer supporting model training pipelines, data preprocessing with pandas/numpy, and Python automation for the ML platform team.",
            "posting_date": "2026-08-30",
            "url": "https://example.com/job/mle1",
            "source": "demo",
        },
        {
            "title": "Business Systems Analyst",
            "company": "Bank of Montreal",
            "location": "Montreal, QC",
            "remote_status": "Hybrid",
            "salary": "$95,000 - $115,000",
            "description": "Business systems analyst role involving requirements gathering, process improvement, stakeholder communication, Excel, SQL, and backlog management.",
            "posting_date": "2026-08-29",
            "url": "https://example.com/job/bsa",
            "source": "demo",
        },
        {
            "title": "IT Business Analyst",
            "company": "Bell Canada",
            "location": "Montreal, QC",
            "remote_status": "Hybrid",
            "salary": "$90,000 - $110,000",
            "description": "IT business analyst supporting digital transformation, Jira, Confluence, requirement documentation, and business process mapping.",
            "posting_date": "2026-08-28",
            "url": "https://example.com/job/itba",
            "source": "demo",
        },
        {
            "title": "Senior Software Engineer",
            "company": "A startup",
            "location": "Montreal, QC",
            "remote_status": "Remote",
            "salary": "$120,000 - $150,000",
            "description": "Heavy software engineering role with strong Python back-end and system design responsibilities.",
            "posting_date": "2026-08-27",
            "url": "https://example.com/job/startup",
            "source": "demo",
        },
    ]


def save_jobs_to_json(jobs: list[dict], path: str):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(jobs, file, indent=2, ensure_ascii=False)
