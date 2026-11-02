"""Additional job boards and feeds: The Muse, Adzuna, Jooble and generic RSS/Atom.

* The Muse - free public API, location-filterable (Montreal).
* Adzuna / Jooble - aggregators with free API keys; skipped silently without a key.
* RSS/Atom - any job feed you point it at (``RSS_FEEDS`` in ``.env``).

Aggregator results often carry only a snippet; ``scraper.enrich.enrich_descriptions``
fetches fuller text for the few postings that survive the cheap filters.
"""

from __future__ import annotations

import logging
from typing import Any

from bs4 import BeautifulSoup

try:
    from jobhunter.config import settings as _settings
    from jobhunter.scraper.collector import (
        DEFAULT_SEARCH_TERMS,
        JOB_SEARCH_LOCATION,
        JOB_SEARCH_TERMS,
        BaseScraper,
        ScraperFactory,
        _polite_sleep,
        _request_get,
        _request_post,
        normalize_job,
    )
except ModuleNotFoundError:  # pragma: no cover
    from config import settings as _settings
    from scraper.collector import (
        DEFAULT_SEARCH_TERMS,
        JOB_SEARCH_LOCATION,
        JOB_SEARCH_TERMS,
        BaseScraper,
        ScraperFactory,
        _polite_sleep,
        _request_get,
        _request_post,
        normalize_job,
    )

LOGGER = logging.getLogger(__name__)

MUSE_API = "https://www.themuse.com/api/public/jobs"
ADZUNA_API = "https://api.adzuna.com/v1/api/jobs/ca/search/{page}"
JOOBLE_API = "https://jooble.org/api/{key}"


def _text(html: Any) -> str:
    return BeautifulSoup(str(html or ""), "html.parser").get_text(" ", strip=True)


def _terms(search_terms: list[str] | None) -> list[str]:
    return list(search_terms or JOB_SEARCH_TERMS or DEFAULT_SEARCH_TERMS)


class TheMuseScraper(BaseScraper):
    """The Muse public jobs API, filtered to Montreal and early-career levels."""

    MAX_PAGES = 3

    def __init__(
        self,
        location: str = "Montreal, Canada",
        levels: tuple[str, ...] = ("Entry Level", "Internship", "Mid Level"),
        timeout: int = 20,
        enabled: bool | None = None,
    ):
        self.location = location
        self.levels = levels
        self.timeout = timeout
        self.enabled = bool(getattr(_settings, "MUSE_ENABLED", True)) if enabled is None else enabled

    def scrape(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        jobs: list[dict[str, Any]] = []
        for page in range(1, self.MAX_PAGES + 1):
            payload = _request_get(
                MUSE_API,
                params=[("page", page), ("location", self.location), *[("level", lvl) for lvl in self.levels]],
                timeout=self.timeout,
            ).json()
            for item in payload.get("results", []):
                locations = [str(loc.get("name") or "") for loc in item.get("locations") or [] if isinstance(loc, dict)]
                location = next((loc for loc in locations if "montr" in loc.lower()), locations[0] if locations else "")
                jobs.append(
                    normalize_job(
                        {
                            "title": item.get("name"),
                            "company": (item.get("company") or {}).get("name"),
                            "location": location or "Unknown",
                            "remote_status": "Remote" if "flexible" in location.lower() or "remote" in location.lower() else "On-site",
                            "description": _text(item.get("contents")),
                            "posting_date": str(item.get("publication_date") or "Unknown")[:10],
                            "url": (item.get("refs") or {}).get("landing_page"),
                            "source": "themuse",
                        }
                    )
                )
            if page >= int(payload.get("page_count", 1) or 1):
                break
            _polite_sleep()
        return [job for job in jobs if job["url"]]


class AdzunaScraper(BaseScraper):
    """Adzuna Canada search API (free key from developer.adzuna.com)."""

    def __init__(
        self,
        app_id: str | None = None,
        app_key: str | None = None,
        search_terms: list[str] | None = None,
        where: str | None = None,
        max_days_old: int = 3,
        results_per_term: int = 30,
        timeout: int = 20,
    ):
        self.app_id = app_id if app_id is not None else getattr(_settings, "ADZUNA_APP_ID", "")
        self.app_key = app_key if app_key is not None else getattr(_settings, "ADZUNA_APP_KEY", "")
        self.search_terms = _terms(search_terms)
        self.where = where or JOB_SEARCH_LOCATION.split(",")[0]
        self.max_days_old = max_days_old
        self.results_per_term = results_per_term
        self.timeout = timeout

    def scrape(self) -> list[dict[str, Any]]:
        if not (self.app_id and self.app_key):
            return []
        jobs: list[dict[str, Any]] = []
        for term in self.search_terms:
            try:
                payload = _request_get(
                    ADZUNA_API.format(page=1),
                    params={
                        "app_id": self.app_id,
                        "app_key": self.app_key,
                        "what": term,
                        "where": self.where,
                        "max_days_old": self.max_days_old,
                        "results_per_page": self.results_per_term,
                        "content-type": "application/json",
                    },
                    timeout=self.timeout,
                ).json()
            except Exception:
                LOGGER.exception("Adzuna search failed for %r.", term)
                continue
            for item in payload.get("results", []):
                low, high = item.get("salary_min"), item.get("salary_max")
                salary = f"${int(low):,} - ${int(high):,}" if low and high else "Not disclosed"
                jobs.append(
                    normalize_job(
                        {
                            "title": item.get("title"),
                            "company": (item.get("company") or {}).get("display_name"),
                            "location": (item.get("location") or {}).get("display_name"),
                            "salary": salary,
                            "description": _text(item.get("description")),
                            "posting_date": str(item.get("created") or "Unknown")[:10],
                            "url": item.get("redirect_url"),
                            "source": "adzuna",
                        }
                    )
                )
            _polite_sleep()
        return [job for job in jobs if job["url"]]


class JoobleScraper(BaseScraper):
    """Jooble search API (free key from jooble.org/api/about)."""

    def __init__(
        self,
        api_key: str | None = None,
        search_terms: list[str] | None = None,
        location: str | None = None,
        timeout: int = 20,
    ):
        self.api_key = api_key if api_key is not None else getattr(_settings, "JOOBLE_API_KEY", "")
        self.search_terms = _terms(search_terms)
        self.location = location or JOB_SEARCH_LOCATION
        self.timeout = timeout

    def scrape(self) -> list[dict[str, Any]]:
        if not self.api_key:
            return []
        jobs: list[dict[str, Any]] = []
        for term in self.search_terms:
            try:
                payload = _request_post(
                    JOOBLE_API.format(key=self.api_key),
                    json={"keywords": term, "location": self.location, "page": 1},
                    timeout=self.timeout,
                ).json()
            except Exception:
                LOGGER.exception("Jooble search failed for %r.", term)
                continue
            for item in payload.get("jobs", []):
                jobs.append(
                    normalize_job(
                        {
                            "title": item.get("title"),
                            "company": item.get("company"),
                            "location": item.get("location"),
                            "salary": item.get("salary") or "Not disclosed",
                            "description": _text(item.get("snippet")),
                            "posting_date": str(item.get("updated") or "Unknown")[:10],
                            "url": item.get("link"),
                            "source": "jooble",
                        }
                    )
                )
            _polite_sleep()
        return [job for job in jobs if job["url"]]


class RssFeedScraper(BaseScraper):
    """Generic RSS 2.0 / Atom job feeds. Entries are ``(feed name, feed url)``."""

    def __init__(self, feeds: list[tuple[str, ...]] | None = None, timeout: int = 20):
        self.feeds = list(feeds) if feeds is not None else list(getattr(_settings, "RSS_FEEDS", []))
        self.timeout = timeout

    @staticmethod
    def parse_feed(xml: str, feed_name: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(xml, "xml")
        jobs = []
        for item in soup.find_all(["item", "entry"]):
            title = item.find("title")
            link_tag = item.find("link")
            link = ""
            if link_tag is not None:
                link = link_tag.get("href") or link_tag.get_text(strip=True)
            body = item.find("description") or item.find("content") or item.find("summary")
            date_tag = item.find("pubDate") or item.find("published") or item.find("updated")
            author = item.find("author") or item.find("creator")
            company = author.get_text(strip=True) if author is not None else feed_name
            location_tag = item.find("location")
            jobs.append(
                normalize_job(
                    {
                        "title": title.get_text(strip=True) if title else "",
                        "company": company or feed_name,
                        "location": location_tag.get_text(strip=True) if location_tag else "",
                        "description": _text(body.get_text() if body else ""),
                        "posting_date": (date_tag.get_text(strip=True) if date_tag else "Unknown")[:25],
                        "url": link,
                        "source": f"rss:{feed_name}",
                    }
                )
            )
        return [job for job in jobs if job["url"] and job["title"] != "Unknown role"]

    def scrape(self) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        for entry in self.feeds:
            name, url = entry[0], entry[1]
            try:
                response = _request_get(url, timeout=self.timeout)
                jobs.extend(self.parse_feed(response.text, name))
            except Exception:
                LOGGER.exception("RSS feed failed: %s", name)
            _polite_sleep()
        return jobs


for _name, _cls in (
    ("themuse", TheMuseScraper),
    ("adzuna", AdzunaScraper),
    ("jooble", JoobleScraper),
    ("rss", RssFeedScraper),
):
    ScraperFactory.register(_name, _cls)
