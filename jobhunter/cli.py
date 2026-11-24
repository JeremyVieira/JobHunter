"""Command-line entry point: ``python -m jobhunter <command>``."""

from __future__ import annotations

import argparse
import subprocess

from jobhunter import __version__

COMMANDS = {
    "run": "start the dashboard and the daily collection schedule",
    "collect": "collect and score jobs once, then exit",
    "dashboard": "open the dashboard only (no collection)",
    "demo": "explore everything with synthetic data (your data is untouched)",
    "doctor": "check your setup and tell you what to fix",
    "outreach": "private recruiter-contact discovery and draft workflow",
    "resume-audit": "audit your master resume: structure, privacy, missing results, weak bullets",
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
            from jobhunter.config.settings import DASHBOARD_HOST

            sp.add_argument("--host", default=DASHBOARD_HOST)
            sp.add_argument("--no-open", action="store_true", help="do not open a browser tab")
            sp.add_argument("--seed-only", action="store_true", help="build the demo data and exit")
        if name == "resume-audit":
            sp.add_argument("--file", help="resume file to audit (default: your master resume)")
            sp.add_argument("--lang", choices=["en", "fr"], help="audit the French master resume")
            sp.add_argument("--markdown", action="store_true", help="wrap the report for pasting into Markdown")
        if name == "dashboard":
            sp.add_argument("--port", type=int, default=8501)
        if name == "discover":
            sp.add_argument(
                "args", nargs=argparse.REMAINDER, help="arguments for the discover tool"
            )
        if name == "outreach":
            sp.add_argument("--job-id", default="", help="tracked job database ID")
            sp.add_argument("--job-url", default="", help="exact tracked posting URL")
            sp.add_argument("--list", action="store_true", help="list tracked jobs and exit")
            sp.add_argument("--recruiter-name", default="")
            sp.add_argument("--recruiter-role", default="")
            sp.add_argument("--email", default="")
            sp.add_argument("--linkedin", default="")
            sp.add_argument("--source-url", default="")
            sp.add_argument("--verified", action="store_true")
            sp.add_argument(
                "--status",
                choices=["identified", "drafted", "contacted", "replied", "not_interested"],
                default="identified",
            )
    return parser


def _dashboard(port: int) -> int:
    from jobhunter.config.dashboard import dashboard_command
    from jobhunter.config.settings import BASE_DIR, DASHBOARD_HEADLESS, DASHBOARD_HOST

    return subprocess.call(
        dashboard_command(
            BASE_DIR,
            host=DASHBOARD_HOST,
            port=port,
            headless=DASHBOARD_HEADLESS,
        ),
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
    if args.command == "resume-audit":
        from jobhunter.resume.audit import main as audit_main

        return audit_main(args.file, args.lang, args.markdown)
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
    if args.command == "outreach":
        try:
            from private.outreach.cli import main as outreach_main
        except ModuleNotFoundError:
            print(
                "Private outreach is not installed on this workstation. "
                "No recruiter data or message was sent."
            )
            return 1
        return outreach_main(
            [
                "--job-id",
                args.job_id,
                "--job-url",
                args.job_url,
                *(["--list"] if args.list else []),
                "--recruiter-name",
                args.recruiter_name,
                "--recruiter-role",
                args.recruiter_role,
                "--email",
                args.email,
                "--linkedin",
                args.linkedin,
                "--source-url",
                args.source_url,
                *(["--verified"] if args.verified else []),
                "--status",
                args.status,
            ]
        )
    if args.command == "dashboard":
        return _dashboard(args.port)
    if args.command == "collect":
        return _collect()
    if args.command == "run":
        from jobhunter.app import main as run_main

        run_main()
        return 0
    return 1  # pragma: no cover
