import pytest


@pytest.fixture(autouse=True)
def _no_request_delay(monkeypatch):
    """Scrapers pause politely between requests; tests should not."""
    from jobhunter.scraper import collector

    monkeypatch.setattr(collector, "REQUEST_DELAY_SECONDS", 0.0)
    # Retry backoff would also stall tests; never actually sleep.
    monkeypatch.setattr(collector.time, "sleep", lambda delay: None)


@pytest.fixture(scope="session", autouse=True)
def _database_schema_exists():
    """A fresh clone has no database yet; the app creates it on first run, so do the same.

    Several pipeline tests call the real purge/save helpers, which need the tables.
    """
    from jobhunter.tracker.db import ensure_database

    ensure_database()
