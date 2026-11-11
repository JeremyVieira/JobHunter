"""Direct company job boards through the public APIs of common applicant-tracking systems.

These are the employer's *own* postings (the ATS hosts the application flow but the
board belongs to the company), so they are usually fresher and fuller than aggregator
copies. Every adapter uses an unauthenticated, publicly documented endpoint that the
vendor's own career widgets call - no login, scraping of protected pages, or API key.

Supported: Ashby, Workable, SmartRecruiters, Recruitee, Workday (Greenhouse and Lever
live in ``collector.py``). ``detect_ats`` recognizes any of them (plus Greenhouse and
Lever) from a company careers page so you only need to paste the careers URL.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from jobhunter.config import settings as _settings
from jobhunter.filter import (
    MONTREAL_AREA_TERMS,
    _title_matches_target,
    is_montreal_area_or_remote,
)
from jobhunter.scraper.collector import (
    BaseScraper,
    GreenhouseScraper,
    LeverScraper,
    ScraperFactory,
    _polite_sleep,
    _request_get,
    _request_post,
    is_excluded_title,
    normalize_job,
)
from jobhunter.textutils import contains_any_term, normalize_text, parse_posting_date

LOGGER = logging.getLogger(__name__)

ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"
WORKABLE_API = "https://apply.workable.com/api/v1/widget/accounts/{token}?details=true"
SMARTRECRUITERS_LIST_API = "https://api.smartrecruiters.com/v1/companies/{token}/postings"
SMARTRECRUITERS_DETAIL_API = (
    "https://api.smartrecruiters.com/v1/companies/{token}/postings/{posting_id}"
)
RECRUITEE_API = "https://{token}.recruitee.com/api/offers/"
WORKDAY_BASE = "https://{tenant}.{dc}.myworkdayjobs.com"

DEFAULT_WORKDAY_TERMS = (
    "software",
    "developer",
    "engineer",
    "data",
    "analyst",
    "python",
    "automation",
)


def _text(html: Any) -> str:
    return BeautifulSoup(str(html or ""), "html.parser").get_text(" ", strip=True)


def _best_location(primary: str, *others: str) -> str:
    """Prefer a Montreal-area location when a posting lists several offices."""
    candidates = [primary, *others]
    for candidate in candidates:
        if candidate and contains_any_term(normalize_text(candidate), MONTREAL_AREA_TERMS):
            return candidate
    return primary or "Unknown"


def _worth_detail_fetch(title: str, location: str) -> bool:
    """Cheap pre-check so we only spend a request on postings that could pass the filters."""
    if not title or is_excluded_title(title) or not _title_matches_target(title):
        return False
    if not location or normalize_text(location) in {"unknown", ""}:
        return True
    if re.search(r"\b\d+\s+locations?\b", location.lower()):  # Workday: "2 Locations"
        return True
    return is_montreal_area_or_remote(location)


class _BoardScraper(BaseScraper):
    """Shared plumbing: iterate companies, isolate failures, and add polite delays."""

    source = "ats"

    def __init__(self, companies: list[tuple[str, ...]] | None = None, timeout: int = 20):
        self.companies = list(companies) if companies is not None else self.default_companies()
        self.timeout = timeout

    @classmethod
    def default_companies(cls) -> list[tuple[str, ...]]:
        return []

    def scrape(self) -> list[dict[str, Any]]:
        if not self.companies:
            LOGGER.info(
                "%s skipped: no boards configured (set the matching *_COMPANIES env var).",
                self.source,
            )
            return []
        jobs: list[dict[str, Any]] = []
        for entry in self.companies:
            try:
                jobs.extend(self.scrape_company(*entry))
            except Exception:
                LOGGER.exception("%s scrape failed for %s.", self.source, entry[0])
            _polite_sleep()
        return jobs

    def scrape_company(self, *entry: str) -> list[dict[str, Any]]:  # pragma: no cover - abstract
        raise NotImplementedError


class AshbyScraper(_BoardScraper):
    """Ashby public job-board API (``api.ashbyhq.com/posting-api/job-board/<token>``)."""

    source = "ashby"

    @classmethod
    def default_companies(cls):
        return list(getattr(_settings, "ASHBY_BOARDS", []))

    def scrape_company(self, company: str, token: str) -> list[dict[str, Any]]:
        payload = _request_get(ASHBY_API.format(token=token), timeout=self.timeout).json()
        jobs = []
        for item in payload.get("jobs", []):
            if item.get("isListed") is False:
                continue
            secondary = [
                str(entry.get("location") or "")
                for entry in item.get("secondaryLocations") or []
                if isinstance(entry, dict)
            ]
            location = _best_location(str(item.get("location") or ""), *secondary)
            is_remote = bool(item.get("isRemote")) or "remote" in location.lower()
            compensation = item.get("compensation") or {}
            jobs.append(
                normalize_job(
                    {
                        "title": item.get("title"),
                        "company": company,
                        "location": location,
                        "remote_status": "Remote" if is_remote else "On-site",
                        "salary": compensation.get("compensationTierSummary") or "Not disclosed",
                        "description": item.get("descriptionPlain")
                        or _text(item.get("descriptionHtml")),
                        "posting_date": str(item.get("publishedAt") or "Unknown")[:10],
                        "url": item.get("jobUrl") or item.get("applyUrl"),
                        "source": self.source,
                    }
                )
            )
        return [job for job in jobs if job["url"]]


class WorkableScraper(_BoardScraper):
    """Workable widget API (``apply.workable.com/api/v1/widget/accounts/<token>``)."""

    source = "workable"

    @classmethod
    def default_companies(cls):
        return list(getattr(_settings, "WORKABLE_BOARDS", []))

    def scrape_company(self, company: str, token: str) -> list[dict[str, Any]]:
        payload = _request_get(WORKABLE_API.format(token=token), timeout=self.timeout).json()
        jobs = []
        for item in payload.get("jobs", []):
            location = ", ".join(
                str(part).strip()
                for part in (item.get("city"), item.get("state"), item.get("country"))
                if part
            )
            remote = bool(item.get("telecommuting"))
            if remote and not location:
                location = "Remote"
            jobs.append(
                normalize_job(
                    {
                        "title": item.get("title"),
                        "company": payload.get("name") or company,
                        "location": location or "Unknown",
                        "remote_status": "Remote" if remote else "On-site",
                        "description": _text(item.get("description")),
                        "posting_date": str(
                            item.get("published_on") or item.get("created_at") or "Unknown"
                        )[:10],
                        "url": item.get("url")
                        or item.get("shortlink")
                        or item.get("application_url"),
                        "source": self.source,
                    }
                )
            )
        return [job for job in jobs if job["url"]]


class SmartRecruitersScraper(_BoardScraper):
    """SmartRecruiters Posting API; fetches full detail only for plausible titles."""

    source = "smartrecruiters"
    MAX_PAGES = 5
    MAX_DETAILS = 40

    @classmethod
    def default_companies(cls):
        return list(getattr(_settings, "SMARTRECRUITERS_BOARDS", []))

    def scrape_company(self, company: str, token: str) -> list[dict[str, Any]]:
        postings: list[dict[str, Any]] = []
        offset = 0
        for _ in range(self.MAX_PAGES):
            payload = _request_get(
                SMARTRECRUITERS_LIST_API.format(token=token),
                params={"limit": 100, "offset": offset, "country": "ca"},
                timeout=self.timeout,
            ).json()
            content = payload.get("content", [])
            postings.extend(content)
            offset += len(content)
            if not content or offset >= int(payload.get("totalFound", 0) or 0):
                break

        jobs = []
        detail_calls = 0
        for item in postings:
            location_data = item.get("location") or {}
            location = ", ".join(
                str(location_data.get(key)).strip()
                for key in ("city", "region", "country")
                if location_data.get(key)
            )
            if location_data.get("remote"):
                location = f"Remote - {location}" if location else "Remote"
            title = str(item.get("name") or "")
            if not _worth_detail_fetch(title, location) or detail_calls >= self.MAX_DETAILS:
                continue
            detail_calls += 1
            description, url = "", ""
            try:
                _polite_sleep()
                detail = _request_get(
                    SMARTRECRUITERS_DETAIL_API.format(token=token, posting_id=item.get("id")),
                    timeout=self.timeout,
                ).json()
                sections = (detail.get("jobAd") or {}).get("sections") or {}
                description = " ".join(
                    _text((sections.get(name) or {}).get("text"))
                    for name in (
                        "companyDescription",
                        "jobDescription",
                        "qualifications",
                        "additionalInformation",
                    )
                )
                url = detail.get("postingUrl") or detail.get("applyUrl") or ""
            except Exception:
                LOGGER.debug(
                    "SmartRecruiters detail failed for %s/%s", token, item.get("id"), exc_info=True
                )
            if not url:
                url = f"https://jobs.smartrecruiters.com/{token}/{item.get('id')}"
            jobs.append(
                normalize_job(
                    {
                        "title": title,
                        "company": (item.get("company") or {}).get("name") or company,
                        "location": location or "Unknown",
                        "remote_status": "Remote" if location_data.get("remote") else "On-site",
                        "description": description,
                        "posting_date": str(item.get("releasedDate") or "Unknown")[:10],
                        "url": url,
                        "source": self.source,
                    }
                )
            )
        return jobs


class RecruiteeScraper(_BoardScraper):
    """Recruitee careers-site API (``<token>.recruitee.com/api/offers/``)."""

    source = "recruitee"

    @classmethod
    def default_companies(cls):
        return list(getattr(_settings, "RECRUITEE_BOARDS", []))

    def scrape_company(self, company: str, token: str) -> list[dict[str, Any]]:
        payload = _request_get(RECRUITEE_API.format(token=token), timeout=self.timeout).json()
        jobs = []
        for item in payload.get("offers", []):
            location = str(item.get("location") or "").strip() or ", ".join(
                str(part) for part in (item.get("city"), item.get("country")) if part
            )
            remote = bool(item.get("remote"))
            if remote and not location:
                location = "Remote"
            jobs.append(
                normalize_job(
                    {
                        "title": item.get("title"),
                        "company": item.get("company_name") or company,
                        "location": location or "Unknown",
                        "remote_status": "Remote" if remote else "On-site",
                        "description": f"{_text(item.get('description'))} {_text(item.get('requirements'))}",
                        "posting_date": str(
                            item.get("published_at") or item.get("created_at") or "Unknown"
                        )[:10],
                        "url": item.get("careers_url") or item.get("url"),
                        "source": self.source,
                    }
                )
            )
        return [job for job in jobs if job["url"]]


class WorkdayScraper(_BoardScraper):
    """Workday career sites (``<tenant>.<wdN>.myworkdayjobs.com``) via their CxS JSON API.

    Many Montreal enterprises (banks, insurers, aerospace) post here. Entries are
    ``(display name, tenant, datacenter, site)`` e.g. ``("RBC", "rbc", "wd3", "RBCGLOBAL1")``.
    Search is by keyword; detail pages are fetched only for plausible local titles.
    """

    source = "workday"
    PAGE_SIZE = 20
    MAX_PAGES_PER_TERM = 2
    MAX_DETAILS = 40

    def __init__(
        self,
        companies: list[tuple[str, ...]] | None = None,
        timeout: int = 20,
        search_terms: tuple[str, ...] | list[str] | None = None,
    ):
        super().__init__(companies, timeout)
        self.search_terms = tuple(search_terms) if search_terms else DEFAULT_WORKDAY_TERMS

    @classmethod
    def default_companies(cls):
        return list(getattr(_settings, "WORKDAY_BOARDS", []))

    def scrape_company(self, company: str, tenant: str, dc: str, site: str) -> list[dict[str, Any]]:
        base = WORKDAY_BASE.format(tenant=tenant, dc=dc)
        search_url = f"{base}/wday/cxs/{tenant}/{site}/jobs"
        postings: dict[str, dict[str, Any]] = {}
        for term in self.search_terms:
            for page in range(self.MAX_PAGES_PER_TERM):
                payload = _request_post(
                    search_url,
                    json={
                        "appliedFacets": {},
                        "limit": self.PAGE_SIZE,
                        "offset": page * self.PAGE_SIZE,
                        "searchText": term,
                    },
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                    timeout=self.timeout,
                ).json()
                batch = payload.get("jobPostings", [])
                for item in batch:
                    path = item.get("externalPath")
                    if path:
                        postings.setdefault(path, item)
                if len(batch) < self.PAGE_SIZE:
                    break
                _polite_sleep()

        jobs = []
        details = 0
        for path, item in postings.items():
            title = str(item.get("title") or "")
            listing_location = str(item.get("locationsText") or "")
            if not _worth_detail_fetch(title, listing_location) or details >= self.MAX_DETAILS:
                continue
            details += 1
            info: dict[str, Any] = {}
            try:
                _polite_sleep()
                detail = _request_get(
                    f"{base}/wday/cxs/{tenant}/{site}{path}",
                    headers={"Accept": "application/json"},
                    timeout=self.timeout,
                ).json()
                info = detail.get("jobPostingInfo") or {}
            except Exception:
                LOGGER.debug("Workday detail failed for %s%s", site, path, exc_info=True)
            location = str(info.get("location") or listing_location or "Unknown")
            extra = [str(x) for x in info.get("additionalLocations") or []]
            location = _best_location(location, *extra)
            posted = info.get("startDate") or ""
            if not posted:
                parsed = parse_posting_date(str(item.get("postedOn") or ""))
                posted = parsed.isoformat() if parsed else "Unknown"
            remote = (
                "remote" in str(info.get("remoteType") or "").lower()
                or "remote" in location.lower()
            )
            jobs.append(
                normalize_job(
                    {
                        "title": info.get("title") or title,
                        "company": company,
                        "location": location,
                        "remote_status": "Remote" if remote else "On-site",
                        "description": _text(info.get("jobDescription")),
                        "posting_date": str(posted)[:10],
                        "url": info.get("externalUrl") or f"{base}/{site}{path}",
                        "source": self.source,
                    }
                )
            )
        return jobs


# --------------------------------------------------------------------------
# Detecting a company's ATS from its careers page
# --------------------------------------------------------------------------
_RESERVED_TOKENS = {
    "embed",
    "careers",
    "jobs",
    "job",
    "api",
    "www",
    "static",
    "assets",
    "v1",
    "boards",
}

_ATS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "greenhouse",
        re.compile(
            r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board(?:/js)?\?for=)?([A-Za-z0-9_-]+)"
        ),
    ),
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_board(?:/js)?\?for=([A-Za-z0-9_-]+)")),
    ("lever", re.compile(r"jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9_.-]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)")),
    ("workable", re.compile(r"apply\.workable\.com/([A-Za-z0-9_-]+)")),
    ("smartrecruiters", re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_-]+)")),
    ("recruitee", re.compile(r"([a-z0-9-]+)\.recruitee\.com")),
    (
        "workday",
        re.compile(
            r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Za-z]{2}/)?([A-Za-z0-9_-]+)"
        ),
    ),
)


def detect_ats(html: str, page_url: str = "") -> list[dict[str, Any]]:
    """Find ATS boards referenced by a careers page (links, iframes, scripts, the URL itself).

    Returns dicts like ``{"ats": "greenhouse", "token": "acme", "key": "acme"}``; Workday
    entries also carry ``tenant``/``dc``/``site``. Duplicates are removed.
    """
    haystack = f"{page_url}\n{html or ''}"
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for ats, pattern in _ATS_PATTERNS:
        for match in pattern.finditer(haystack):
            if ats == "workday":
                tenant, dc, site = match.group(1), match.group(2), match.group(3)
                # Workday site names are often literally "Careers"; only skip bare locale segments.
                if re.fullmatch(r"[a-z]{2}-[A-Za-z]{2}", site):
                    continue
                key = f"{tenant}|{dc}|{site}"
                entry = {
                    "ats": ats,
                    "token": tenant,
                    "tenant": tenant,
                    "dc": dc,
                    "site": site,
                    "key": key,
                }
            else:
                token = match.group(1).rstrip(".")
                if not token or token.lower() in _RESERVED_TOKENS:
                    continue
                entry = {"ats": ats, "token": token, "key": token}
            marker = (ats, entry["key"])
            if marker not in seen:
                seen.add(marker)
                found.append(entry)
    return found


def scrapers_for_detections(company: str, detections: list[dict[str, Any]]) -> list[BaseScraper]:
    """Build one scraper per detected board for ``company``."""
    scrapers: list[BaseScraper] = []
    for detection in detections:
        ats, token = detection["ats"], detection["token"]
        if ats == "greenhouse":
            scrapers.append(GreenhouseScraper(companies=[(company, token)]))
        elif ats == "lever":
            scrapers.append(LeverScraper(companies=[(company, token)]))
        elif ats == "ashby":
            scrapers.append(AshbyScraper(companies=[(company, token)]))
        elif ats == "workable":
            scrapers.append(WorkableScraper(companies=[(company, token)]))
        elif ats == "smartrecruiters":
            scrapers.append(SmartRecruitersScraper(companies=[(company, token)]))
        elif ats == "recruitee":
            scrapers.append(RecruiteeScraper(companies=[(company, token)]))
        elif ats == "workday":
            scrapers.append(
                WorkdayScraper(
                    companies=[(company, detection["tenant"], detection["dc"], detection["site"])]
                )
            )
    return scrapers


def detection_from_url(url: str) -> list[dict[str, Any]]:
    """Convenience: detect an ATS purely from a URL such as ``https://jobs.lever.co/acme``."""
    return detect_ats("", url) if urlparse(url).netloc else []


for _name, _cls in (
    ("ashby", AshbyScraper),
    ("workable", WorkableScraper),
    ("smartrecruiters", SmartRecruitersScraper),
    ("recruitee", RecruiteeScraper),
    ("workday", WorkdayScraper),
):
    ScraperFactory.register(_name, _cls)
