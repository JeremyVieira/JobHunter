"""Build the candidate's skill inventory from their own local master resume."""

from __future__ import annotations

from pathlib import Path

from jobhunter.matching.skills import get_matcher


def resume_skill_ids(*resume_paths: Path | str) -> list[str]:
    """Skill ids found in the given resume files (missing files are skipped).

    Only real master resumes are read - never the ``*.template.txt`` examples,
    whose placeholder content must not inflate a candidate's skill inventory.
    """
    matcher = get_matcher()
    found: set[str] = set()
    for raw_path in resume_paths:
        path = Path(raw_path)
        if ".template" in path.name or not path.exists():
            continue
        try:
            found.update(matcher.extract(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
    return sorted(found)
