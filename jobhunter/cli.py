"""Command-line entry point: ``python -m jobhunter <command>``."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from jobhunter import __version__

COMMANDS = {
    "run": "start the dashboard and the daily collection schedule",
    "collect": "collect and score jobs once, then exit",
    "dashboard": "open the dashboard only (no collection)",
    "demo": "explore everything with synthetic data (your data is untouched)",
    "doctor": "check your setup and tell you what to fix",
    "discover": "find a company's job-board settings from its careers page",
    "version": "print the version",
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jobhunter",
        description="JobHunter: collect, score and track job postings, and prepare honest application documents.",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    for name, helptext in COMMANDS.items():
        sp = sub.add_parser(name, help=helptext, description=helptext)
        if name == "demo":
            sp.add_argument("--port", type=int, default=8502)
            sp.add_argument("--host", default=os.getenv("JOBHUNTER_DASHBOARD_HOST", "127.0.0.1"))
            sp.add_argument("--no-open", action="store_true", help="do not open a browser tab")
            sp.add_argument("--seed-only", action="store_true", help="build the demo data and exit")
        if name == "dashboard":
            sp.add_argument("--port", type=int, default=8501)
        if name == "discover":
            sp.add_argument(
                "args", nargs=argparse.REMAINDER, help="arguments for the discover tool"
            )
    return parser


def _dashboard(port: int) -> int:
    from jobhunter.config.settings import BASE_DIR

    return subprocess.call(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(BASE_DIR / "dashboard" / "app.py"),
            "--server.address",
            "127.0.0.1",
            "--server.port",
            str(port),
            "--browser.gatherUsageStats",
            "false",
        ],
        cwd=BASE_DIR,
    )


def _collect() -> int:
    from jobhunter.scheduler import run_daily_jobs_and_report

    jobs, report = run_daily_jobs_and_report()
    print(f"Collected and kept {len(jobs)} postings. Report: {report}")
    for job in jobs[:5]:
        print(
            f"  {job.get('fit_score', 0):5.1f}  {job.get('title', '')} @ {job.get('company', '')}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    if args.command == "version":
        print(f"jobhunter {__version__}")
        return 0
    if args.command == "doctor":
        from jobhunter.doctor import main as doctor_main

        return doctor_main()
    if args.command == "demo":
        from jobhunter import demo

        if args.seed_only:
            paths = demo.seed_demo()
            print(f"Demo data written to {paths['dir']}")
            return 0
        return demo.run_demo(host=args.host, port=args.port, open_browser=not args.no_open)
    if args.command == "discover":
        from jobhunter.scraper.discover import main as discover_main

        return discover_main(args.args or None)
    if args.command == "dashboard":
        return _dashboard(args.port)
    if args.command == "collect":
        return _collect()
    if args.command == "run":
        from jobhunter.app import main as run_main

        run_main()
        return 0
    return 1  # pragma: no cover
