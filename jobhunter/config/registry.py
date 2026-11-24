"""Declarative bindings between scraper implementations and their settings."""

from collections.abc import Callable

from jobhunter.config import settings as _settings

BOARD_SETTINGS = {
    "AshbyScraper": "ASHBY_BOARDS",
    "GreenhouseScraper": "GREENHOUSE_BOARDS",
    "LeverScraper": "LEVER_BOARDS",
    "RecruiteeScraper": "RECRUITEE_BOARDS",
    "SmartRecruitersScraper": "SMARTRECRUITERS_BOARDS",
    "WorkableScraper": "WORKABLE_BOARDS",
    "WorkdayScraper": "WORKDAY_BOARDS",
}
SCRAPER_SETTINGS = {
    "AdzunaScraper": {
        "app_id": "ADZUNA_APP_ID", "app_key": "ADZUNA_APP_KEY",
        "search_terms": "JOB_SEARCH_TERMS", "where": "JOB_SEARCH_LOCATION",
    },
    "ArbeitnowScraper": {},
    "AshbyScraper": {"companies": "ASHBY_BOARDS"},
    "CompanyCareerPageScraper": {"max_detail_pages": "CAREER_PAGE_MAX_DETAIL_PAGES"},
    "GreenhouseScraper": {"companies": "GREENHOUSE_BOARDS"},
    "JobSpyScraper": {
        "search_terms": "JOB_SEARCH_TERMS", "results_wanted_per_term": "JOBSPY_RESULTS_PER_TERM",
        "proxies": "JOBSPY_PROXIES", "location": "JOB_SEARCH_LOCATION", "sites": "JOBSPY_SITES",
        "hours_old": "JOBSPY_HOURS_OLD",
        "fetch_linkedin_descriptions": "JOBSPY_FETCH_LINKEDIN_DESCRIPTIONS",
    },
    "JobicyScraper": {},
    "JoobleScraper": {
        "api_key": "JOOBLE_API_KEY", "search_terms": "JOB_SEARCH_TERMS", "location": "JOB_SEARCH_LOCATION",
    },
    "LeverScraper": {"companies": "LEVER_BOARDS"},
    "RecruiteeScraper": {"companies": "RECRUITEE_BOARDS"},
    "RemotiveScraper": {},
    "RssFeedScraper": {"feeds": "RSS_FEEDS"},
    "SmartRecruitersScraper": {"companies": "SMARTRECRUITERS_BOARDS"},
    "TheMuseScraper": {"enabled": "MUSE_ENABLED"},
    "WorkableScraper": {"companies": "WORKABLE_BOARDS"},
    "WorkdayScraper": {"companies": "WORKDAY_BOARDS"},
}
SOURCE_ORDER = (
    "JobSpyScraper", "TheMuseScraper", "JobicyScraper", "RemotiveScraper", "ArbeitnowScraper",
    "GreenhouseScraper", "LeverScraper", "AshbyScraper", "WorkableScraper",
    "SmartRecruitersScraper", "RecruiteeScraper", "WorkdayScraper", "CompanyCareerPageScraper",
    "AdzunaScraper", "JoobleScraper", "RssFeedScraper",
)


def setting(name: str, default=None):
    return getattr(_settings, name, default)


def scraper_options(cls: type | Callable) -> dict:
    """Only inject options understood by the concrete scraper constructor."""
    import inspect

    parameters = inspect.signature(cls).parameters
    if any(parameter.kind == parameter.VAR_KEYWORD for parameter in parameters.values()):
        known_arguments = SCRAPER_SETTINGS.get(cls.__name__, {})
    else:
        known_arguments = {
            argument: setting_name
            for argument, setting_name in SCRAPER_SETTINGS.get(cls.__name__, {}).items()
            if argument in parameters
        }
    return {
        argument: setting(setting_name)
        for argument, setting_name in known_arguments.items()
    }


def is_enabled(name: str) -> bool:
    if name == "AdzunaScraper":
        return bool(setting("ADZUNA_APP_ID") and setting("ADZUNA_APP_KEY"))
    if name == "JoobleScraper":
        return bool(setting("JOOBLE_API_KEY"))
    if name == "RssFeedScraper":
        return bool(setting("RSS_FEEDS"))
    return True


def build_sources(factories: dict[str, Callable]) -> list:
    return [
        factories[name](**scraper_options(factories[name]))
        for name in SOURCE_ORDER
        if is_enabled(name)
    ]
