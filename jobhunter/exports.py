"""Data export: CSV for spreadsheets and a consistent SQLite backup."""

from __future__ import annotations

import csv
import io
import sqlite3
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

JOB_COLUMNS = (
    "title",
    "company",
    "location",
    "remote_status",
    "salary",
    "fit_score",
    "skills_match",
    "title_match",
    "experience_match",
    "source",
    "posting_date",
    "url",
)
APPLICATION_COLUMNS = (
    "company",
    "role",
    "status",
    "fit_score",
    "application_date",
    "interview_date",
    "response_date",
    "source",
    "language",
    "url",
    "notes",
)

# Spreadsheet apps treat cells starting with these characters as formulas.
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _safe_cell(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def rows_to_csv(rows: Iterable[dict[str, Any]], columns: Sequence[str]) -> str:
    """CSV text with only the requested columns. Formula-like text is neutralised so a
    hostile posting title cannot execute when the file is opened in Excel/Sheets."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_safe_cell(row.get(column, "")) for column in columns])
    return buffer.getvalue()


def backup_database_bytes(db_path: Path | str) -> bytes:
    """A consistent copy of the database (safe while the app is writing)."""
    source = sqlite3.connect(str(db_path))
    try:
        with tempfile.TemporaryDirectory() as tmp:
            target_path = Path(tmp) / "backup.db"
            target = sqlite3.connect(str(target_path))
            try:
                source.backup(target)
            finally:
                target.close()
            return target_path.read_bytes()
    finally:
        source.close()
