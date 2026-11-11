"""Builds the default set of scrapers from configuration."""

from __future__ import annotations

from typing import Any

from jobhunter.config import settings as _settings
from jobhunter.scraper.ats import (
    AshbyScraper,
    RecruiteeScraper,
    SmartRecruitersScraper,
    WorkableScraper,
    WorkdayScraper,
)
from jobhunter.scraper.boards import (
    AdzunaScraper,
    JoobleScraper,
    RssFeedScraper,
    TheMuseScraper,
)
from jobhunter.scraper.collector import (
    ArbeitnowScraper,
    BaseScraper,
    CompanyCareerPageScraper,
    GreenhouseScraper,
    JobicyScraper,
    JobSpyScraper,
    LeverScraper,
    RemotiveScraper,
)


def build_default_scrapers() -> list[BaseScraper]:
    """Every source that is configured. Keyed APIs and empty board lists add nothing.

    Aggregators (JobSpy, The Muse, Adzuna, Jooble, remote boards) give breadth; the
    ATS adapters and company career pages give the employer's own, fresher postings.
    """
    scrapers: list[BaseScraper] = [
        JobSpyScraper(),
        TheMuseScraper(),
        JobicyScraper(),
        RemotiveScraper(),
        ArbeitnowScraper(),
        GreenhouseScraper(),
        LeverScraper(),
        AshbyScraper(),
        WorkableScraper(),
        SmartRecruitersScraper(),
        RecruiteeScraper(),
        WorkdayScraper(),
        CompanyCareerPageScraper(),
    ]
    if getattr(_settings, "ADZUNA_APP_ID", "") and getattr(_settings, "ADZUNA_APP_KEY", ""):
        scrapers.append(AdzunaScraper())
    if getattr(_settings, "JOOBLE_API_KEY", ""):
        scrapers.append(JoobleScraper())
    if getattr(_settings, "RSS_FEEDS", []):
        scrapers.append(RssFeedScraper())
    return scrapers


def describe_sources(scrapers: list[BaseScraper]) -> dict[str, Any]:
    return {type(scraper).__name__: 1 for scraper in scrapers}
