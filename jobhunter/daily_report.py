from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

try:
    from jobhunter.config.settings import OUTPUT_DIR
except ModuleNotFoundError:  # pragma: no cover
    from config.settings import OUTPUT_DIR


def generate_email_summary(top_jobs: list[dict[str, Any]]) -> str:
    if not top_jobs:
        return "JobHunterAI Daily Job Summary\nNo matching opportunities found today."

    lines = ["JobHunterAI Daily Job Summary", "=============================", ""]
    for idx, job in enumerate(top_jobs[:10], start=1):
        company = job.get("company", "Unknown")
        title = job.get("title", "Unknown")
        salary = job.get("salary", "N/A")
        fit_score = job.get("fit_score", "N/A")
        location = job.get("location", "N/A")
        url = job.get("url", "N/A")
        lines.append(f"{idx}. {title} at {company}")
        lines.append(f"   Fit Score: {fit_score} | Salary: {salary} | Location: {location}")
        lines.append(f"   Link: {url}")
        lines.append("")
    return "\n".join(lines)


def generate_daily_report(
    top_jobs: list[dict[str, Any]], output_dir: Path | str | None = None
) -> str:
    target_dir = Path(output_dir) if output_dir is not None else OUTPUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    html_path = target_dir / "daily_report.html"

    rows = "\n".join(
        f"<tr><td>{escape(str(job.get('company', 'Unknown')))}</td>"
        f"<td>{escape(str(job.get('title', 'Unknown')))}</td>"
        f"<td>{escape(str(job.get('salary', 'Not disclosed')))}</td>"
        f"<td>{escape(str(job.get('fit_score', '0')))}</td>"
        f"<td>{escape(str(job.get('location', 'Unknown')))}</td>"
        f"<td><a href='{escape(str(job.get('url', '')))}' target='_blank'>link</a></td></tr>"
        for job in top_jobs[:10]
    )

    summary_text = escape(generate_email_summary(top_jobs[:10])).replace("\n", "<br>")

    html = f"""<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8">
    <title>JobHunterAI Daily Report</title>
    <style>
      body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 30px; background: #f8f9fa; color: #212529; }}
      h1 {{ color: #1f4e79; }}
      .summary {{ background: #fff; padding: 20px; border-radius: 8px; border: 1px solid #dee2e6; margin-bottom: 25px; line-height: 1.6; font-family: monospace; }}
      table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
      th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #dee2e6; }}
      th {{ background-color: #1f4e79; color: #ffffff; font-weight: 600; }}
      tr:hover {{ background-color: #f1f5f9; }}
      a {{ color: #0066cc; text-decoration: none; }}
      a:hover {{ text-decoration: underline; }}
    </style>
  </head>
  <body>
    <h1>JobHunterAI Daily Report</h1>
    <div class="summary">{summary_text}</div>
    <table>
      <thead>
        <tr><th>Company</th><th>Position</th><th>Salary</th><th>Fit Score</th><th>Location</th><th>Link</th></tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")
    return str(html_path)
