"""Shared Streamlit dashboard launch configuration and command construction."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jobhunter.config import settings

DASHBOARD_SCRIPT = "dashboard/app.py"


def dashboard_command(
    base_dir: Path,
    *,
    host: str,
    port: int | str,
    headless: bool,
) -> list[str]:
    """Build the canonical ``python -m streamlit run ...`` command."""
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(base_dir / DASHBOARD_SCRIPT),
        "--server.address",
        host,
        "--server.port",
        str(port),
        "--browser.gatherUsageStats",
        "false",
    ]
    if headless:
        command += ["--server.headless", "true"]
    return command


def configured_command(
    base_dir: Path,
    settings: "settings",  # noqa: UP037
    *,
    port: int | None = None,
    host: str | None = None,
) -> list[str]:
    """Build the command from parsed settings, with optional CLI overrides."""
    return dashboard_command(
        base_dir,
        host=host or settings.DASHBOARD_HOST,  # type: ignore[attr-defined]
        port=port if port is not None else settings.DASHBOARD_PORT,  # type: ignore[attr-defined]
        headless=settings.DASHBOARD_HEADLESS,  # type: ignore[attr-defined]
    )
