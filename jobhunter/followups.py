"""Follow-up reminders for applications that have gone quiet, with a plain draft message.

The draft only restates facts you already hold (role, company, date applied); it never
invents a reason, a contact or an achievement.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

from jobhunter.textutils import parse_posting_date

DEFAULT_FOLLOW_UP_DAYS = 7
MAX_FOLLOW_UPS = 2  # after two polite nudges, move on
_FOLLOWED_RE = re.compile(r"Followed up (\d{4}-\d{2}-\d{2})")


def follow_up_dates(notes: str | None) -> list[date]:
    found = []
    for match in _FOLLOWED_RE.finditer(notes or ""):
        parsed = parse_posting_date(match.group(1))
        if parsed:
            found.append(parsed)
    return found


def due_followups(
    applications: Iterable[dict[str, Any]],
    today: date | None = None,
    days: int = DEFAULT_FOLLOW_UP_DAYS,
) -> list[dict[str, Any]]:
    """Applications still at "applied" with no reply and no recent nudge.

    Each returned row gains ``days_waiting`` (since the last contact) and ``follow_ups_sent``.
    Oldest first, so the longest-waiting application leads.
    """
    today = today or date.today()
    due: list[dict[str, Any]] = []
    for app in applications:
        if str(app.get("status") or "").lower() != "applied" or app.get("response_date"):
            continue
        applied_on = parse_posting_date(str(app.get("application_date") or ""))
        if applied_on is None:
            continue
        nudges = follow_up_dates(app.get("notes"))
        if len(nudges) >= MAX_FOLLOW_UPS:
            continue
        last_contact = max([applied_on, *nudges])
        waiting = (today - last_contact).days
        if waiting >= days:
            due.append({**app, "days_waiting": waiting, "follow_ups_sent": len(nudges)})
    return sorted(due, key=lambda row: -row["days_waiting"])


def next_follow_up_on(app: dict[str, Any], days: int = DEFAULT_FOLLOW_UP_DAYS) -> date | None:
    applied_on = parse_posting_date(str(app.get("application_date") or ""))
    if applied_on is None:
        return None
    return max([applied_on, *follow_up_dates(app.get("notes"))]) + timedelta(days=days)


def draft_followup(
    role: str,
    company: str,
    applied_on: str,
    *,
    language: str = "en",
    name: str = "",
    follow_ups_sent: int = 0,
) -> str:
    role = role or "the position"
    company = company or "your company"
    applied = applied_on or "recently"
    if language == "fr":
        subject = f"Suivi de ma candidature - {role}"
        lead = (
            "Je me permets de vous relancer au sujet de ma candidature au poste de "
            f"{role} chez {company}, soumise le {applied}. Mon intérêt pour ce poste demeure entier."
            if follow_ups_sent == 0
            else f"Je me permets une dernière relance au sujet de ma candidature au poste de {role} "
            f"chez {company}, soumise le {applied}."
        )
        body = (
            f"Bonjour,\n\n{lead}\n\nSi je peux vous transmettre d'autres renseignements, "
            "je le ferai avec plaisir.\n\nMerci de votre temps et de votre considération.\n\n"
            f"Cordialement,\n{name}"
        )
    else:
        subject = f"Following up on my {role} application"
        lead = (
            f"I wanted to follow up on my application for the {role} position at {company}, "
            f"submitted on {applied}. I remain very interested in the role."
            if follow_ups_sent == 0
            else f"I am sending one last note about my application for the {role} position at "
            f"{company}, submitted on {applied}."
        )
        body = (
            f"Hello,\n\n{lead}\n\nIf there is any additional information I can provide, I would be "
            f"glad to share it.\n\nThank you for your time and consideration.\n\nBest regards,\n{name}"
        )
    return f"Subject: {subject}\n\n{body}"
