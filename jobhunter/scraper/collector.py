"""Job scrapers and the collection pipeline.

HTTP plumbing lives in :mod:`jobhunter.scraper.http`, quality filters in
:mod:`jobhunter.scraper.quality`, and normalization helpers in
:mod:`jobhunter.scraper.normalize`; the names imported below are re-exported
(via ``__all__``) so existing ``from jobhunter.scraper.collector import ...``
callers keep working unchanged.
"""

from __future__ import annotations

import importlib
import json
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from jobspy import scrape_jobs

from jobhunter.config import settings as _settings
from jobhunter.config.defaults import DEFAULT_SEARCH_TERMS
from jobhunter.config.settings import (
    COMPANY_CAREER_URLS,
    GREENHOUSE_BOARDS,
    JOB_SEARCH_LOCATION,
    JOB_SEARCH_TERMS,
    JOBSPY_PROXIES,
    JOBSPY_SITES,
    LEVER_BOARDS,
)
from jobhunter.textutils import days_since

from .http import DEFAULT_HEADERS, _request_get, _request_post
from .normalize import MAX_DESCRIPTION_CHARS, canonical_job_url, normalize_job
from .normalize import jobspy_text as _jobspy_text
from .quality import (
    MIN_DESCRIPTION_LENGTH,
    SHADY_COMPANY_NAME_TERMS,
    SHADY_DESCRIPTION_TERMS,
    _normalize_for_filter,
    filter_relevant_jobs,
    is_excluded_title,
    is_likely_tiny_startup,
    is_shady_posting,
)

__all__ = [
    "DEFAULT_HEADERS",
    "MAX_DESCRIPTION_CHARS",
    "MIN_DESCRIPTION_LENGTH",
    "SHADY_COMPANY_NAME_TERMS",
    "SHADY_DESCRIPTION_TERMS",
    "_normalize_for_filter",
    "_request_get",
    "_request_post",
    "canonical_job_url",
    "filter_relevant_jobs",
    "is_excluded_title",
    "is_likely_tiny_startup",
    "is_shady_posting",
    "normalize_job",
]


def _setting(name: str, default: Any) -> Any:
    return getattr(_settings, name, default) if _settings is not None else default


JOBICY_API_URL = "https://jobicy.com/api/v2/remote-jobs?count=50"
REMOTIVE_API_URL = "https://remotive.com/api/remote-jobs?limit=50"
ARBEITNOW_API_URL = "https://www.arbeitnow.com/api/job-board-api"

LOGGER = logging.getLogger(__name__)

REQUEST_DELAY_SECONDS = float(_setting("REQUEST_DELAY_SECONDS", 0.3))


def _polite_sleep() -> None:
    """Small pause between requests to the same provider (tests set the delay to 0)."""
    if REQUEST_DELAY_SECONDS > 0:
        time.sleep(REQUEST_DELAY_SECONDS)


class BaseScraper(ABC):
    """Abstract base class for all job scrapers."""

    @abstractmethod
    def scrape(self) -> list[dict[str, Any]]:
        """Fetch and return normalized job listings."""
        ...


def _career_url_configs(values: list[str]) -> list[tuple[str, str]]:
    configs = []
    for value in values:
        company, separator, url = value.partition("|")
        if separator and company.strip() and url.strip():
            configs.append((company.strip(), url.strip()))
    return configs


class CompanyCareerPageScraper(BaseScraper):
    """Fetch public company career pages containing static JobPosting data.

    Many enterprise career sites publish schema.org JobPosting JSON-LD even
    when their search UI is rendered by JavaScript. This connector handles the
    static portion without login, browser automation, or an API key.
    """

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/127.0 Safari/537.36"
        ),
        "Accept-Language": "en-CA,en;q=0.9",
    }

    def __init__(
        self,
        pages: list[tuple[str, str]] | None = None,
        timeout: int = 20,
        max_detail_pages: int | None = None,
    ):
        self.pages = pages if pages is not None else _career_url_configs(COMPANY_CAREER_URLS)
        self.timeout = timeout
        self.max_detail_pages = (
            max_detail_pages
            if max_detail_pages is not None
            else int(_setting("CAREER_PAGE_MAX_DETAIL_PAGES", 15))
        )
        self.detected_boards: list[tuple[str, str, str]] = []  # (company, ats, token) for logging

    def scrape(self) -> list[dict[str, Any]]:
        """Collect postings from each career page.

        Strategy per page: (1) JobPosting JSON-LD on the page itself; (2) detect the
        employer's applicant-tracking system (Greenhouse, Lever, Ashby, Workable,
        SmartRecruiters, Recruitee, Workday) from links/embeds and use its public job
        API; (3) otherwise follow job-looking links and read their JSON-LD.
        """
        from jobhunter.scraper.ats import detect_ats, scrapers_for_detections

        jobs: list[dict[str, Any]] = []
        seen_boards: set[tuple[str, str]] = set()
        for company, page_url in self.pages:
            try:
                response = _request_get(page_url, headers=self.HEADERS, timeout=self.timeout)
                html = response.text
                page_jobs = self._parse_page(html, company, page_url)
                jobs.extend(page_jobs)

                ats_jobs: list[dict[str, Any]] = []
                detections = [
                    d for d in detect_ats(html, page_url) if (d["ats"], d["key"]) not in seen_boards
                ]
                for detection in detections:
                    seen_boards.add((detection["ats"], detection["key"]))
                    self.detected_boards.append((company, detection["ats"], detection["key"]))
                    LOGGER.info(
                        "Detected %s board %r for %s.", detection["ats"], detection["key"], company
                    )
                for scraper in scrapers_for_detections(company, detections):
                    try:
                        ats_jobs.extend(scraper.scrape())
                    except Exception:
                        LOGGER.exception("Detected ATS scrape failed for %s.", company)
                jobs.extend(ats_jobs)

                if not page_jobs and not ats_jobs:
                    jobs.extend(self._follow_detail_links(html, company, page_url))
            except Exception:
                LOGGER.exception("Company career page request failed for %s.", company)
        return jobs

    _JOB_LINK_HINTS = (
        "/job/",
        "/jobs/",
        "/careers/",
        "/career/",
        "/emploi",
        "/emplois/",
        "/posting",
        "/position",
        "/opening",
        "/requisition",
        "/vacancy",
        "/offre",
    )

    def _follow_detail_links(self, html: str, company: str, page_url: str) -> list[dict[str, Any]]:
        """Fetch job-looking links from a listing page and read each one's JSON-LD."""
        from urllib.parse import urljoin

        base_host = urlparse(page_url).netloc.lower().removeprefix("www.")
        base_domain = ".".join(base_host.split(".")[-2:])
        soup = BeautifulSoup(html, "html.parser")
        links: list[str] = []
        for anchor in soup.find_all("a", href=True):
            href = urljoin(page_url, anchor["href"].strip())
            parsed = urlparse(href)
            if parsed.scheme not in {"http", "https"} or href.lower().endswith(
                (".pdf", ".jpg", ".png")
            ):
                continue
            host = parsed.netloc.lower().removeprefix("www.")
            if not host.endswith(base_domain):
                continue
            path = parsed.path.lower() + "/"
            if not any(hint in path for hint in self._JOB_LINK_HINTS):
                continue
            canonical = canonical_job_url(href)
            if canonical == canonical_job_url(page_url) or canonical in links:
                continue
            links.append(canonical)
            if len(links) >= self.max_detail_pages:
                break

        jobs: list[dict[str, Any]] = []
        for link in links:
            try:
                _polite_sleep()
                detail = _request_get(link, headers=self.HEADERS, timeout=self.timeout)
                for job in self._parse_page(detail.text, company, link):
                    job["url"] = job["url"] or link
                    jobs.append(job)
            except Exception:
                LOGGER.debug("Detail page failed for %s: %s", company, link, exc_info=True)
        return jobs

    @staticmethod
    def _parse_page(html: str, company: str, page_url: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[dict[str, Any]] = []
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                payload = json.loads(script.string or script.get_text())
            except (TypeError, json.JSONDecodeError):
                LOGGER.debug("Invalid JSON-LD skipped on %s.", page_url)
                continue
            records = payload if isinstance(payload, list) else [payload]
            for item in records:
                if not isinstance(item, dict):
                    continue
                if item.get("@type") == "ItemList":
                    for element in item.get("itemListElement", []):
                        item_data = (
                            element.get("item", element) if isinstance(element, dict) else {}
                        )
                        if isinstance(item_data, dict) and item_data.get("@type") == "JobPosting":
                            jobs.append(
                                CompanyCareerPageScraper._normalize_job_posting(
                                    item_data, company, page_url
                                )
                            )
                elif item.get("@type") == "JobPosting":
                    jobs.append(
                        CompanyCareerPageScraper._normalize_job_posting(item, company, page_url)
                    )
        return [job for job in jobs if job["url"]]

    @staticmethod
    def _normalize_job_posting(item: dict[str, Any], company: str, page_url: str) -> dict[str, Any]:
        location_data = item.get("jobLocation") or {}
        if isinstance(location_data, list):
            location_data = location_data[0] if location_data else {}
        address = location_data.get("address", {}) if isinstance(location_data, dict) else {}
        location = ", ".join(
            str(value).strip()
            for value in (
                address.get("addressLocality"),
                address.get("addressRegion"),
                address.get("addressCountry"),
            )
            if value
        ) or ("Remote" if item.get("jobLocationType") == "TELECOMMUTE" else "Unknown")
        description = BeautifulSoup(str(item.get("description") or ""), "html.parser").get_text(
            " ", strip=True
        )
        return normalize_job(
            {
                "title": item.get("title"),
                "company": company,
                "location": location,
                "remote_status": "Remote"
                if item.get("jobLocationType") == "TELECOMMUTE"
                else "On-site",
                "salary": "Not disclosed",
                "description": description,
                "posting_date": str(item.get("datePosted") or "Unknown")[:10],
                "url": item.get("url") or page_url,
                "source": "company-career-page",
            }
        )


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
        results_wanted_per_term: int | None = None,
        proxies: list[str] | str | None = None,
        location: str | None = None,
        sites: list[str] | None = None,
        hours_old: int | None = None,
        fetch_linkedin_descriptions: bool | None = None,
    ):
        self.search_terms = search_terms or JOB_SEARCH_TERMS or list(DEFAULT_SEARCH_TERMS)
        self.results_wanted_per_term = (
            results_wanted_per_term
            if results_wanted_per_term is not None
            else int(_setting("JOBSPY_RESULTS_PER_TERM", 15))
        )
        # Fresh postings get disproportionate attention; default window is 72 hours.
        self.hours_old = (
            hours_old if hours_old is not None else int(_setting("JOBSPY_HOURS_OLD", 72))
        )
        # LinkedIn's search results only carry a snippet unless descriptions are fetched.
        self.fetch_linkedin_descriptions = (
            fetch_linkedin_descriptions
            if fetch_linkedin_descriptions is not None
            else bool(_setting("JOBSPY_FETCH_LINKEDIN_DESCRIPTIONS", True))
        )
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
                    hours_old=self.hours_old,
                    linkedin_fetch_description=self.fetch_linkedin_descriptions,
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
                                "location": _jobspy_text(item.get("location"), "Unknown"),
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
# Override with GREENHOUSE_COMPANIES / LEVER_COMPANIES in .env ("Name|token,Name|token").
GREENHOUSE_COMPANIES: list[tuple[str, str]] = list(GREENHOUSE_BOARDS)

# No confirmed-working Lever boards to ship as defaults (Figma left Lever, so its
# token 404s) — set LEVER_COMPANIES="Name|token,..." in .env to enable this scraper.
LEVER_COMPANIES: list[tuple[str, str]] = list(LEVER_BOARDS)


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
        "company-career-page": CompanyCareerPageScraper,
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
    response = _request_get(url, timeout=timeout)
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


def _suppress_jobspy_loggers() -> None:
    """Mute noisy error logs from third-party scrapers that hit anti-bot defenses."""
    for module_name in ["jobspy.glassdoor", "jobspy.ziprecruiter"]:
        try:
            mod = importlib.import_module(module_name)
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


AGGREGATOR_SOURCES = frozenset(
    {
        "adzuna",
        "arbeitnow",
        "glassdoor",
        "google",
        "indeed",
        "jobicy",
        "jobspy",
        "jooble",
        "linkedin",
        "remotive",
        "rss",
        "themuse",
        "zip_recruiter",
    }
)
FIRST_PARTY_SOURCES = frozenset(
    {
        "ashby",
        "company-career-page",
        "greenhouse",
        "lever",
        "recruitee",
        "smartrecruiters",
        "workable",
        "workday",
    }
)


def filter_stale_jobs(
    jobs: Iterable[dict[str, Any]],
    *,
    max_age_days: int | None = None,
) -> list[dict[str, Any]]:
    """Remove aggregated postings older than the configured recency window."""
    limit = (
        int(_setting("MAX_JOB_AGE_DAYS", 14))
        if max_age_days is None
        else max(0, int(max_age_days))
    )
    kept: list[dict[str, Any]] = []
    for job in jobs:
        source = str(job.get("source") or "").lower().split(":")[0]
        if source not in AGGREGATOR_SOURCES:
            kept.append(job)
            continue
        age = days_since(str(job.get("posting_date") or ""))
        if age is not None and age > limit:
            continue
        kept.append(job)
    return kept


def verify_live_listings(
    jobs: Iterable[dict[str, Any]],
    *,
    timeout: float | None = None,
    max_checks: int | None = None,
) -> list[dict[str, Any]]:
    """Drop listings with explicit HTTP 404/410 responses.

    403, 429, timeouts and anti-bot pages remain unverified but are kept: a blocked
    listing cannot be proven stale, and false negatives are safer than hiding a real job.
    """
    if not bool(_setting("VERIFY_LISTING_URLS", True)):
        return list(jobs)

    request_timeout = (
        float(_setting("LISTING_URL_TIMEOUT_SECONDS", 8))
        if timeout is None
        else timeout
    )
    check_limit = (
        int(_setting("MAX_LISTING_URL_CHECKS", 40))
        if max_checks is None
        else max(0, int(max_checks))
    )
    kept: list[dict[str, Any]] = []
    checks = 0
    headers = dict(DEFAULT_HEADERS)
    for job in jobs:
        url = str(job.get("url") or "").strip()
        source = str(job.get("source") or "").lower().split(":")[0]
        if (
            not url
            or source in FIRST_PARTY_SOURCES
            or source not in AGGREGATOR_SOURCES
            or checks >= check_limit
        ):
            kept.append(job)
            continue

        checks += 1
        try:
            response = requests.head(
                url,
                headers=headers,
                allow_redirects=True,
                timeout=request_timeout,
            )
            if response.status_code in {405, 501}:
                response = requests.get(
                    url,
                    headers=headers,
                    allow_redirects=True,
                    timeout=request_timeout,
                    stream=True,
                )
            if response.status_code in {404, 410}:
                continue
        except (requests.ConnectionError, requests.Timeout):
            pass
        except requests.RequestException:
            pass
        kept.append(job)

    return kept


def freshen_jobs(jobs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    recency_filtered = filter_stale_jobs(jobs)
    return verify_live_listings(recency_filtered)


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
            "salary": "$70,000 - $85,000 CAD/yr",
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
            "salary": "$75,000 - $95,000 CAD/yr",
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
            "salary": "$95,000 - $115,000 CAD/yr",
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
            "salary": "$90,000 - $110,000 CAD/yr",
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
            "salary": "$120,000 - $150,000 CAD/yr",
            "description": "Heavy software engineering role with strong Python back-end and system design responsibilities.",
            "posting_date": "2026-08-27",
            "url": "https://example.com/job/startup",
            "source": "demo",
        },
    ]
