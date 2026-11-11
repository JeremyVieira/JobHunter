"""Find a company's job-board configuration from its careers page.

    python -m jobhunter.scraper.discover "Shopify|https://www.shopify.com/careers" https://jobs.lever.co/acme

For each page this reports which applicant-tracking system it uses and prints the
ready-to-paste ``.env`` line. With ``--count`` it also queries the detected board and
reports how many postings it returned, so you know the token works.
"""

from __future__ import annotations

import argparse
import sys
from urllib.parse import urlparse

from jobhunter.scraper.ats import detect_ats, scrapers_for_detections
from jobhunter.scraper.collector import CompanyCareerPageScraper, _request_get

ENV_VARS = {
    "greenhouse": "GREENHOUSE_COMPANIES",
    "lever": "LEVER_COMPANIES",
    "ashby": "ASHBY_COMPANIES",
    "workable": "WORKABLE_COMPANIES",
    "smartrecruiters": "SMARTRECRUITERS_COMPANIES",
    "recruitee": "RECRUITEE_COMPANIES",
    "workday": "WORKDAY_COMPANIES",
}


def env_entry(company: str, detection: dict) -> str:
    if detection["ats"] == "workday":
        return f"{company}|{detection['tenant']}|{detection['dc']}|{detection['site']}"
    return f"{company}|{detection['token']}"


def split_target(value: str) -> tuple[str, str]:
    name, sep, url = value.partition("|")
    if sep and url.startswith("http"):
        return name.strip(), url.strip()
    host = urlparse(value).netloc.removeprefix("www.")
    return (host.split(".")[0].title() or "Company"), value.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "targets", nargs="+", help="careers URLs, optionally 'Company Name|https://...'"
    )
    parser.add_argument(
        "--count", action="store_true", help="query each detected board and count postings"
    )
    args = parser.parse_args(argv)

    collected: dict[str, list[str]] = {}
    for target in args.targets:
        company, url = split_target(target)
        try:
            html = _request_get(url, headers=CompanyCareerPageScraper.HEADERS, timeout=20).text
        except Exception as exc:  # network errors are expected for some sites
            print(f"! {company}: could not fetch {url} ({exc})")
            html = ""
        detections = detect_ats(html, url)
        if not detections:
            jsonld = len(CompanyCareerPageScraper._parse_page(html, company, url)) if html else 0
            print(
                f"- {company}: no ATS detected; page has {jsonld} JSON-LD postings "
                f"(keep it in COMPANY_CAREER_URLS to follow job links)."
            )
            continue
        for detection in detections:
            entry = env_entry(company, detection)
            collected.setdefault(ENV_VARS[detection["ats"]], []).append(entry)
            suffix = ""
            if args.count:
                try:
                    count = sum(
                        len(s.scrape()) for s in scrapers_for_detections(company, [detection])
                    )
                    suffix = f"  [{count} postings]"
                except Exception as exc:
                    suffix = f"  [query failed: {exc}]"
            print(f"+ {company}: {detection['ats']} -> {entry}{suffix}")

    if collected:
        print("\nAdd to your .env (merge with existing values, comma-separated):")
        for var, entries in collected.items():
            print(f"{var}={','.join(entries)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
