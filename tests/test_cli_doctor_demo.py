"""CLI routing, setup diagnostics, demo workspace and path overrides."""

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from jobhunter import cli, demo, doctor
from jobhunter.tracker.db import (
    SQLiteApplicationRepository,
    SQLiteJobRepository,
    compute_funnel,
)

# ---- CLI ---------------------------------------------------------------------


def test_version_and_help(capsys):
    assert cli.main(["version"]) == 0
    assert capsys.readouterr().out.startswith("jobhunter ")
    assert cli.main([]) == 0
    help_text = capsys.readouterr().out
    for command in cli.COMMANDS:
        assert command in help_text


@pytest.mark.parametrize(
    "argv, patch_target",
    [
        (["doctor"], "jobhunter.doctor.main"),
        (["discover", "Acme|https://acme.com/careers"], "jobhunter.scraper.discover.main"),
        (["run"], "jobhunter.app.main"),
    ],
)
def test_commands_route_to_their_implementations(monkeypatch, argv, patch_target):
    calls = []
    monkeypatch.setattr(patch_target, lambda *a, **k: calls.append(a) or 0)
    assert cli.main(argv) == 0
    assert len(calls) == 1


def test_discover_forwards_arguments(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "jobhunter.scraper.discover.main", lambda args=None: seen.setdefault("args", args) and 0
    )
    cli.main(["discover", "Acme|https://acme.com/careers", "--count"])
    assert seen["args"] == ["Acme|https://acme.com/careers", "--count"]


def test_demo_seed_only_does_not_launch_a_server(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(demo, "seed_demo", lambda *a, **k: {"dir": tmp_path})
    launched = []
    monkeypatch.setattr(demo, "run_demo", lambda **k: launched.append(k) or 0)
    assert cli.main(["demo", "--seed-only"]) == 0
    assert not launched and str(tmp_path) in capsys.readouterr().out


def test_demo_command_passes_port_and_browser_flag(monkeypatch):
    seen = {}
    monkeypatch.setattr(demo, "run_demo", lambda **k: seen.update(k) or 0)
    cli.main(["demo", "--port", "9000", "--host", "0.0.0.0", "--no-open"])
    assert seen == {"host": "0.0.0.0", "port": 9000, "open_browser": False}


def test_collect_prints_a_summary(monkeypatch, capsys):
    jobs = [{"fit_score": 91.5, "title": "Dev", "company": "Acme"}]
    monkeypatch.setattr(
        "jobhunter.scheduler.run_daily_jobs_and_report", lambda: (jobs, "report.html")
    )
    assert cli.main(["collect"]) == 0
    out = capsys.readouterr().out
    assert "Collected and kept 1 postings" in out and "Dev @ Acme" in out


# ---- doctor ------------------------------------------------------------------


def _by_name(checks):
    return {c.name: c for c in checks}


def test_doctor_fails_without_a_master_resume_and_passes_with_one(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor.settings, "RESUME_SOURCE_DIR", tmp_path)
    missing = _by_name(doctor.run_checks())["Master resume (EN)"]
    assert missing.status == doctor.FAIL and "master_resume.template.txt" in missing.fix

    (tmp_path / "master_resume.txt").write_text("Name\n", encoding="utf-8")
    assert _by_name(doctor.run_checks())["Master resume (EN)"].status == doctor.OK


def test_doctor_exit_code_and_report_format(monkeypatch, capsys):
    ok = [doctor.Check("A", doctor.OK, "fine"), doctor.Check("B", doctor.WARN, "meh", "do this")]
    monkeypatch.setattr(doctor, "run_checks", lambda: ok)
    assert doctor.main() == 0
    out = capsys.readouterr().out
    assert "0 problem(s), 1 suggestion(s)" in out and "-> do this" in out

    monkeypatch.setattr(
        doctor, "run_checks", lambda: [*ok, doctor.Check("C", doctor.FAIL, "broken", "fix it")]
    )
    assert doctor.main() == 1


def test_doctor_reports_unwritable_database_and_configured_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor.settings, "ASHBY_BOARDS", [("A", "a")])
    monkeypatch.setattr(doctor.settings, "ADZUNA_APP_ID", "id")
    monkeypatch.setattr(doctor.settings, "ADZUNA_APP_KEY", "key")
    checks = _by_name(doctor.run_checks())
    assert "Ashby x1" in checks["Job sources"].detail and "Adzuna" in checks["Job sources"].detail
    monkeypatch.setattr(doctor.os, "access", lambda *a, **k: False)
    assert _by_name(doctor.run_checks())["Database location"].status == doctor.FAIL


# ---- demo --------------------------------------------------------------------


def test_demo_workspace_is_isolated_fictional_and_realistic(tmp_path):
    paths = demo.seed_demo(tmp_path)
    assert paths["db"].parent == tmp_path and (paths["resume_dir"] / "master_resume.txt").exists()

    jobs = SQLiteJobRepository(paths["db"]).find_top(50)
    assert len(jobs) >= 6
    assert all(j["url"].startswith("https://example.com/") for j in jobs)
    # the pipeline's own filter ran: nothing senior/low-fit made it in, scores are distinct
    assert not any("Senior" in j["title"] for j in jobs)
    scores = [j["fit_score"] for j in jobs]
    assert len(set(scores)) == len(scores) and max(scores) < 100

    stats = compute_funnel(SQLiteApplicationRepository(paths["db"]).funnel_rows())
    assert stats["overall"]["applied"] == len(demo._SAMPLE_APPLICATIONS)
    assert stats["overall"]["interviews"] == 2 and stats["overall"]["ghosted"] == 2


def test_demo_seeding_is_repeatable(tmp_path):
    demo.seed_demo(tmp_path)
    first = len(SQLiteJobRepository(tmp_path / "demo.db").find_top(50))
    demo.seed_demo(tmp_path)
    assert len(SQLiteJobRepository(tmp_path / "demo.db").find_top(50)) == first


def test_demo_environment_replaces_the_real_profile_and_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_NAME", "Real Person")
    env = demo.demo_environment(demo.seed_demo(tmp_path))
    assert env["USER_NAME"] == "Alex Example" and env["JOBHUNTER_DEMO"] == "1"
    assert Path(env["JOBHUNTER_DB_PATH"]).parent == tmp_path
    assert Path(env["JOBHUNTER_RESUME_DIR"]) == tmp_path / "resume"


def test_demo_dashboard_renders_without_errors(tmp_path):
    """Run the real Streamlit script against the demo workspace in a clean interpreter."""
    env = demo.demo_environment(demo.seed_demo(tmp_path))
    code = (
        "from streamlit.testing.v1 import AppTest\n"
        "at = AppTest.from_file('jobhunter/dashboard/app.py', default_timeout=120); at.run()\n"
        "assert not at.exception, [e.value for e in at.exception]\n"
        "labels = [m.label for m in at.metric]\n"
        "assert 'Total Jobs' in labels and 'Match strength' in labels, labels\n"
        "assert len(at.dataframe) >= 1, 'funnel tables missing'\n"
        "print('OK')\n"
    )
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, cwd=root, capture_output=True, text=True
    )
    assert result.returncode == 0 and "OK" in result.stdout, result.stdout + result.stderr[-1500:]


# ---- path overrides ----------------------------------------------------------


def test_path_overrides_are_honoured_and_defaults_unchanged(monkeypatch, tmp_path):
    from jobhunter.config import settings

    monkeypatch.setenv("JOBHUNTER_DB_PATH", str(tmp_path / "custom.db"))
    monkeypatch.setenv("JOBHUNTER_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("JOBHUNTER_RESUME_DIR", str(tmp_path / "private"))
    reloaded = importlib.reload(settings)
    try:
        assert reloaded.DB_PATH == tmp_path / "custom.db"
        assert reloaded.RESUME_DIR == tmp_path / "out" / "resumes"
        assert reloaded.RESUME_SOURCE_DIR == tmp_path / "private"
    finally:
        for name in ("JOBHUNTER_DB_PATH", "JOBHUNTER_OUTPUT_DIR", "JOBHUNTER_RESUME_DIR"):
            monkeypatch.delenv(name)
        restored = importlib.reload(settings)
    assert restored.DB_PATH.name == "jobhunter.db" and restored.RESUME_SOURCE_DIR.name == "resume"
    assert os.environ.get("JOBHUNTER_DB_PATH") is None
