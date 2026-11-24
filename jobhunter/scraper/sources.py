"""Builds the default set of scrapers from configuration."""

from __future__ import annotations

from typing import Any

from jobhunter.config.registry import build_sources

# Imported for re-export into ``globals()`` so ``build_sources`` can resolve them.
from jobhunter.scraper.ats import (  # noqa: F401
    AshbyScraper,
    RecruiteeScraper,
    SmartRecruitersScraper,
    WorkableScraper,
    WorkdayScraper,
)
from jobhunter.scraper.boards import (  # noqa: F401
    AdzunaScraper,
    JoobleScraper,
    RssFeedScraper,
    TheMuseScraper,
)
from jobhunter.scraper.collector import (
    ArbeitnowScraper,  # noqa: F401
    BaseScraper,
    CompanyCareerPageScraper,  # noqa: F401
    GreenhouseScraper,  # noqa: F401
    JobicyScraper,  # noqa: F401
    JobSpyScraper,  # noqa: F401
    LeverScraper,  # noqa: F401
    RemotiveScraper,  # noqa: F401
)


def build_default_scrapers() -> list[BaseScraper]:
    """Construct each configured source from the shared scraper registry."""
    return build_sources(globals())



def describe_sources(scrapers: list[BaseScraper]) -> dict[str, Any]:
    return {type(scraper).__name__: 1 for scraper in scrapers}
