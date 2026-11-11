"""Safe, minimal editing of the ``.env`` file from the dashboard.

Existing comments, ordering and unrelated settings are preserved; only the keys you change are
rewritten (or appended). A ``.env.bak`` copy is kept, and the write is atomic.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

_KEY_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def _unquote(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        inner = value[1:-1]
        return inner.replace('\\"', '"').replace("\\\\", "\\") if value[0] == '"' else inner
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def read_env_values(path: Path | str) -> dict[str, str]:
    path = Path(path)
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _KEY_LINE.match(line)
        if match and not line.lstrip().startswith("#"):
            values[match.group(1)] = _unquote(match.group(2))
    return values


def _format_value(value: str) -> str:
    value = str(value).replace("\r", " ").replace("\n", " ").strip()
    if value == "" or not re.search(r"[\s,#\"'\\]", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def update_env_file(path: Path | str, updates: dict[str, str], *, backup: bool = True) -> None:
    """Set ``updates`` in the file, keeping everything else exactly as it was."""
    path = Path(path)
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    newline = "\r\n" if "\r\n" in original else "\n"
    lines = original.splitlines()
    remaining = dict(updates)

    for index, line in enumerate(lines):
        match = _KEY_LINE.match(line)
        if match and not line.lstrip().startswith("#") and match.group(1) in remaining:
            key = match.group(1)
            lines[index] = f"{key}={_format_value(remaining.pop(key))}"
    if remaining:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(f"{key}={_format_value(value)}" for key, value in remaining.items())

    if backup and path.exists():
        shutil.copyfile(path, path.with_name(path.name + ".bak"))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(newline.join(lines) + newline)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
