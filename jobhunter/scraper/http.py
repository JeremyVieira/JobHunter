"""HTTP plumbing shared by every scraper: default headers, retry/backoff policy."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)
MAX_GET_ATTEMPTS = 3
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Some sites (e.g. The Muse) reject the default python-requests User-Agent with a
# 403, so every request goes out with a browser-like identity unless overridden.
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _with_default_headers(kwargs: dict) -> dict:
    headers = dict(DEFAULT_HEADERS)
    headers.update(kwargs.pop("headers", {}) or {})
    kwargs["headers"] = headers
    return kwargs


def _request_with_retries(method: str, url: str, *, timeout: int = 20, **kwargs):  # noqa: ANN001, ANN201
    """GET/POST with the same retry/backoff policy; honours ``Retry-After``."""
    kwargs = _with_default_headers(kwargs)
    request = requests.get if method == "get" else requests.post
    for attempt in range(1, MAX_GET_ATTEMPTS + 1):
        try:
            response = request(url, timeout=timeout, **kwargs)
        except (requests.ConnectionError, requests.Timeout):
            if attempt == MAX_GET_ATTEMPTS:
                raise
            LOGGER.warning(
                "%s request failed on attempt %s/%s: %s",
                method.upper(),
                attempt,
                MAX_GET_ATTEMPTS,
                url,
                exc_info=True,
            )
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
                "%s request received HTTP %s on attempt %s/%s: %s",
                method.upper(),
                status_code,
                attempt,
                MAX_GET_ATTEMPTS,
                url,
            )
            time.sleep(delay)
            continue
        response.raise_for_status()
        return response
    raise RuntimeError(
        f"{method.upper()} request failed after {MAX_GET_ATTEMPTS} attempts: {url}"
    )


def _request_get(url: str, *, timeout: int = 20, **kwargs):  # noqa: ANN001, ANN201
    return _request_with_retries("get", url, timeout=timeout, **kwargs)


def _request_post(url: str, *, timeout: int = 20, **kwargs):  # noqa: ANN001, ANN201
    return _request_with_retries("post", url, timeout=timeout, **kwargs)


def setting(name: str, default: Any) -> Any:
    """Read a runtime-tunable setting from the config module."""
    from jobhunter.config import settings as _settings

    return getattr(_settings, name, default) if _settings is not None else default
