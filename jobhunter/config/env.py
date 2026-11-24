"""Typed environment-variable parsing used only by :mod:`jobhunter.config.settings`."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

FALSE_VALUES = {"0", "false", "no", "off"}


def text(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def string(name: str, default: str = "") -> str:
    return text(name, default).strip()


def integer(name: str, default: int) -> int:
    return int(string(name) or default)


def number(name: str, default: float) -> float:
    return float(string(name) or default)


def boolean(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() not in FALSE_VALUES


def true_only(name: str, default: bool = False) -> bool:
    return text(name, str(default)).lower() == "true"


def string_list(name: str, default: tuple[str, ...] = ()) -> list[str]:
    raw = string(name)
    return [item.strip() for item in raw.split(",") if item.strip()] if raw else list(default)


def path(name: str, default: Path) -> Path:
    raw = string(name)
    return Path(raw).expanduser() if raw else default


def tuples(name: str, size: int, default: tuple[tuple[str, ...], ...] = ()) -> list[tuple[str, ...]]:
    raw = os.getenv(name)
    if raw is None:
        return list(default)
    entries = (
        tuple(part.strip() for part in entry.split("|"))
        for entry in raw.split(",")
    )
    return [entry for entry in entries if len(entry) == size and all(entry)]


def declare(schema: dict[str, tuple[str, Callable[[str, Any], Any], Any]]) -> dict[str, Any]:
    """Resolve a declarative ``setting: (environment key, parser, default)`` schema."""
    return {name: parser(env, default) for name, (env, parser, default) in schema.items()}
