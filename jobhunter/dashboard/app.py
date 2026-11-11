from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

import streamlit as st  # noqa: E402

from jobhunter import __version__
from jobhunter.app import run_daily_collection
from jobhunter.config.settings import USER_PROFILE
from jobhunter.doctor import FAIL, OK, run_checks
from jobhunter.matching.skills import label_for
from jobhunter.resume.tailor import (
    ats_analysis,
    build_master_resume,
    generate_application_pack,
    get_application_pack_files,
    read_verification_warnings,
    suggest_languages,
)
from jobhunter.scoring.engine import salary_comparison
from jobhunter.tracker.db import (
    ALL_STATUSES,
    dismiss_job,
    ensure_database,
    funnel_stats,
    get_connection,
    get_job_stats,
    get_top_jobs,
    parse_match_details,
    save_application,
    update_application_status,
)

st.set_page_config(page_title="JobHunter", page_icon="💼", layout="wide")

ensure_database()


def as_job_dict(job):
    """Normalize SQLite row objects and dict-like records to a plain dict."""
    if job is None:
        return {}
    if hasattr(job, "keys"):
        return dict(job)
    return dict(job)


_MARKDOWN_SPECIAL_CHARS = re.compile(r"([\\`*_{}\[\]()#+.!|>~$-])")


def _escape_markdown(value: str) -> str:
    plain_text = " ".join((value or "").splitlines())
    return _MARKDOWN_SPECIAL_CHARS.sub(lambda match: "\\" + match.group(1), plain_text)


st.title("💼 JobHunter")
if os.getenv("JOBHUNTER_DEMO") == "1":
    st.info(
        "Demo mode: every company, posting and person here is fictional, and nothing touches "
        "your real data. Stop it with Ctrl+C and run `python -m jobhunter run` for the real thing."
    )
st.caption(
    f"Your job search for {_escape_markdown(USER_PROFILE['name'])}: postings ranked by evidence, "
    "and application documents that only use facts from your own resume."
)

_DEMO = os.getenv("JOBHUNTER_DEMO") == "1"


@st.cache_data(ttl=30, show_spinner=False)
def _setup_checks() -> list[tuple[str, str, str, str]]:
    return [(c.name, c.status, c.detail, c.fix) for c in run_checks()]


# Sidebar
with st.sidebar:
    st.header("🎯 Profile Summary")
    st.write(f"**Name:** {USER_PROFILE['name']}")
    st.write(f"**Degree:** {USER_PROFILE['degree']}")
    st.write(f"**Location:** {USER_PROFILE['location']}")
    st.write(f"**Target Roles:** {len(USER_PROFILE['target_roles'])} defined")

    st.divider()
    if st.button("🔄 Collect jobs now", type="primary", width="stretch"):
        with st.spinner("Collecting from your sources, then scoring and filtering..."):
            collected = run_daily_collection()
            st.success(f"Collected and scored {len(collected)} matching opportunities!")
            st.rerun()

    st.divider()
    st.subheader("Target Roles")
    for role in USER_PROFILE["target_roles"][:8]:
        st.caption(f"• {role}")
    if len(USER_PROFILE["target_roles"]) > 8:
        st.caption(f"... and {len(USER_PROFILE['target_roles']) - 8} more")

    if not _DEMO:
        st.divider()
        checks = _setup_checks()
        to_review = [c for c in checks if c[1] != OK]
        has_failure = any(c[1] == FAIL for c in checks)
        label = "✅ Setup looks good" if not to_review else f"⚙️ Setup: {len(to_review)} to review"
        with st.expander(label, expanded=has_failure):
            icons = {"ok": "✅", "warn": "⚠️", "fail": "❌"}
            for name, status, detail, fix in checks:
                st.markdown(
                    f"{icons.get(status, '•')} **{_escape_markdown(name)}**: {_escape_markdown(detail)}"
                )
                if fix and status != OK:
                    st.caption(f"→ {fix}")
            st.caption("Same checks as `python -m jobhunter doctor`.")

    st.divider()
    st.caption(
        f"JobHunter v{__version__} · local-first: your resume and tracker data stay on this machine."
    )

# Top Metrics
stats = get_job_stats()
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Jobs", stats.get("total_jobs", 0) or 0)
col2.metric("Average Fit Score", f"{round(stats.get('avg_fit_score') or 0, 1)}%")
col3.metric("Top Fit Score", f"{round(stats.get('max_fit_score') or 0, 1)}%")
col4.metric("High Fit Opportunities (≥80)", stats.get("high_fit_jobs", 0) or 0)

st.divider()

tab_jobs, tab_tracker, tab_profile = st.tabs(
    ["🚀 Top Opportunities", "📋 Application Tracker", "👤 Profile & Keywords"]
)

with tab_jobs:
    stored_jobs = [as_job_dict(row) for row in get_top_jobs(200)]
    top_jobs = stored_jobs
    if stored_jobs:
        f_search, f_fit, f_source, f_show = st.columns([2.2, 1.4, 1.8, 0.9])
        query = f_search.text_input(
            "Search", placeholder="Filter by title or company", label_visibility="collapsed"
        )
        min_fit = f_fit.slider("Minimum fit", 0, 100, 0, help="Hide postings scoring below this.")
        known_sources = sorted({str(j.get("source") or "unknown") for j in stored_jobs})
        chosen_sources = f_source.multiselect(
            "Sources",
            known_sources,
            default=known_sources,
            label_visibility="collapsed",
            placeholder="Sources",
        )
        limit = f_show.selectbox("Show", [10, 30, 60, 100], index=1, label_visibility="collapsed")
        needle = query.strip().lower()
        filtered = [
            j
            for j in stored_jobs
            if float(j.get("fit_score") or 0) >= min_fit
            and str(j.get("source") or "unknown") in chosen_sources
            and (not needle or needle in f"{j.get('title', '')} {j.get('company', '')}".lower())
        ]
        top_jobs = filtered[:limit]
        st.caption(
            f"Showing {len(top_jobs)} of {len(filtered)} matching postings ({len(stored_jobs)} stored)."
        )
    if not stored_jobs:
        st.markdown("### 👋 Welcome to JobHunter")
        st.markdown(
            "No postings yet. To get started:\n\n"
            "1. Check the **Setup** panel in the sidebar and fix anything marked ❌.\n"
            "2. Click **Collect jobs now** (the first run can take a few minutes).\n"
            "3. Come back here: postings appear ranked, with a *Why this score* explanation.\n\n"
            "Want to look around first? Run `python -m jobhunter demo` for a fully fictional workspace."
        )
    elif not top_jobs:
        st.info("No postings match these filters. Lower the minimum fit or clear the search.")
    else:
        for idx, job in enumerate(top_jobs):
            job = as_job_dict(job)
            fit = float(job["fit_score"] or 0)
            interview_chance = float(job["interview_chance"] or 0)
            color_badge = "🟢" if fit >= 80 else "🟡" if fit >= 65 else "⚪"
            job_title = job["title"]
            company_name = job["company"]
            salary_market = salary_comparison(job["salary"], job_title)

            # Inspect if application pack already exists (does NOT generate)
            # Generate only the language(s) the posting calls for (French posting -> French docs).
            languages = suggest_languages(dict(job))
            pack = get_application_pack_files(dict(job), languages=languages)
            docs_ready = bool(pack.get("exists"))
            hook_key = f"hook_{job['id']}_{idx}"

            # Header row with title & action button
            header_col1, header_col2 = st.columns([3.5, 1.5])
            with header_col1:
                st.markdown(
                    f"### {color_badge} **{_escape_markdown(job_title)}** @ "
                    f"**{_escape_markdown(company_name)}**"
                )
                st.caption(f"Fit: **{fit}%**")
                meta = [
                    f"💰 {job['salary']}",
                    f"📍 {job['location']}",
                    f"🏠 {job['remote_status']}",
                ]
                if job.get("posting_date") and job["posting_date"] != "Unknown":
                    meta.append(f"🗓 {job['posting_date']}")
                if job.get("source"):
                    meta.append(f"🔎 {job['source']}")
                st.caption(_escape_markdown("  ·  ".join(meta)))
                st.caption(
                    f"Typical entry-level CAD: **${salary_market['minimum']:,}-${salary_market['maximum']:,}** "
                    f"({salary_market['family']}) | **{salary_market['comparison']}**"
                )
            with header_col2:
                if not docs_ready:
                    if st.button(
                        "⚡ Generate CV & Resume",
                        key=f"quick_gen_{job['id']}_{idx}",
                        type="primary",
                        width="stretch",
                    ):
                        with st.spinner("Tailoring documents..."):
                            generate_application_pack(
                                dict(job),
                                languages=languages,
                                company_hook=st.session_state.get(hook_key, ""),
                            )
                            st.success("Generated documents!")
                            st.rerun()
                else:
                    en_pdf_path = Path(str(pack.get("en_resume_pdf", "")))
                    if en_pdf_path.exists():
                        st.download_button(
                            label="📥 Download Resume PDF",
                            data=en_pdf_path.read_bytes(),
                            file_name=en_pdf_path.name,
                            mime="application/pdf",
                            key=f"quick_dl_{job['id']}_{idx}",
                            width="stretch",
                        )

            with st.expander(
                "📄 View Application Pack, ATS Analysis & Job Details", expanded=False
            ):
                m_col1, m_col2, m_col3, m_col4 = st.columns(4)
                m_col1.metric("Fit Score", f"{fit}%")
                m_col2.metric(
                    "Match strength",
                    f"{interview_chance}%",
                    help="Heuristic blend of fit and skill coverage - NOT a callback probability. "
                    "See the Funnel in the tracker tab for your real response rates.",
                )
                m_col3.metric("Work Model", job["remote_status"] or "Hybrid/On-site")
                m_col4.metric("Source", job["source"] or "Direct")

                st.caption(
                    f"Salary benchmark: CAD ${salary_market['minimum']:,}-${salary_market['maximum']:,} "
                    f"for entry-level {salary_market['family'].lower()} roles."
                )

                st.markdown("**Job Description:**")
                st.text(
                    job["description"][:1200] + ("..." if len(job["description"]) > 1200 else "")
                )

                details = parse_match_details(job.get("match_details"))
                if details:
                    st.markdown("#### 🎯 Why this score")
                    skills = details.get("skills", {})
                    adjustments = details.get("adjustments", {})
                    if skills.get("matched"):
                        st.write("**Skills you match:** " + ", ".join(skills["matched"]))
                    if skills.get("missing_required"):
                        st.write(
                            "**Asked for, not on your record:** "
                            + ", ".join(skills["missing_required"])
                        )
                    if skills.get("core_gaps"):
                        st.warning("Hard-stack gap: " + ", ".join(skills["core_gaps"]))
                    if details.get("years_required") is not None:
                        st.caption(f"Years of experience asked: {details['years_required']}")
                    notable = {k: v for k, v in adjustments.items() if v}
                    if notable:
                        st.caption(
                            "Adjustments: "
                            + ", ".join(f"{k.replace('_', ' ')} {v:+}" for k, v in notable.items())
                        )

                # Application Pack Section
                st.markdown("#### 📂 Application Documents")
                st.text_input(
                    "Company-specific line for the cover letter (optional - you write it; nothing is invented)",
                    key=hook_key,
                    placeholder="e.g. Why this company/team interests you, in one sentence",
                )
                if not (st.session_state.get(hook_key) or "").strip():
                    st.caption(
                        "No company-specific line yet: the letter will be accurate but generic."
                    )
                st.caption(
                    "Documents for: "
                    + ", ".join(languages)
                    + " (chosen from the posting's language)."
                )
                if not docs_ready:
                    st.info("Documents haven't been generated yet for this posting.")
                    if st.button(
                        "⚡ Generate Resume & Cover Letter Pack",
                        key=f"exp_gen_{job['id']}_{idx}",
                        type="primary",
                    ):
                        with st.spinner(
                            "Generating tailored English & French application packets..."
                        ):
                            generate_application_pack(
                                dict(job),
                                languages=languages,
                                company_hook=st.session_state.get(hook_key, ""),
                            )
                            st.success("Generated!")
                            st.rerun()
                else:
                    if not pack.get("complete"):
                        st.warning(
                            "This application pack is incomplete. Available files remain downloadable below."
                        )
                        if st.button(
                            "Regenerate incomplete pack",
                            key=f"complete_pack_{job['id']}_{idx}",
                        ):
                            with st.spinner("Completing application documents..."):
                                generate_application_pack(
                                    dict(job),
                                    languages=languages,
                                    company_hook=st.session_state.get(hook_key, ""),
                                )
                                st.success("Application pack regenerated.")
                                st.rerun()
                    doc_tab_en, doc_tab_fr = st.tabs(
                        ["🇺🇸 English Documents", "🇫🇷 Documents en Français"]
                    )

                    with doc_tab_en:
                        d_col1, d_col2, d_col3 = st.columns(3)
                        en_pdf = Path(str(pack.get("en_resume_pdf", "")))
                        en_docx = Path(str(pack.get("en_resume_docx", "")))
                        en_cov = Path(str(pack.get("en_cover_letter_docx", "")))

                        with d_col1:
                            if en_pdf.exists():
                                st.download_button(
                                    "📥 Resume (PDF)",
                                    en_pdf.read_bytes(),
                                    file_name=en_pdf.name,
                                    mime="application/pdf",
                                    key=f"en_pdf_{job['id']}_{idx}",
                                    width="stretch",
                                )
                        with d_col2:
                            if en_docx.exists():
                                st.download_button(
                                    "📄 Resume (DOCX)",
                                    en_docx.read_bytes(),
                                    file_name=en_docx.name,
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    key=f"en_docx_{job['id']}_{idx}",
                                    width="stretch",
                                )
                        with d_col3:
                            if en_cov.exists():
                                st.download_button(
                                    "✉️ Cover Letter (DOCX)",
                                    en_cov.read_bytes(),
                                    file_name=en_cov.name,
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    key=f"en_cov_{job['id']}_{idx}",
                                    width="stretch",
                                )

                    with doc_tab_fr:
                        f_col1, f_col2, f_col3 = st.columns(3)
                        fr_pdf = Path(str(pack.get("fr_resume_pdf", "")))
                        fr_docx = Path(str(pack.get("fr_resume_docx", "")))
                        fr_cov = Path(str(pack.get("fr_cover_letter_docx", "")))

                        with f_col1:
                            if fr_pdf.exists():
                                st.download_button(
                                    "📥 CV Français (PDF)",
                                    fr_pdf.read_bytes(),
                                    file_name=fr_pdf.name,
                                    mime="application/pdf",
                                    key=f"fr_pdf_{job['id']}_{idx}",
                                    width="stretch",
                                )
                        with f_col2:
                            if fr_docx.exists():
                                st.download_button(
                                    "📄 CV Français (DOCX)",
                                    fr_docx.read_bytes(),
                                    file_name=fr_docx.name,
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    key=f"fr_docx_{job['id']}_{idx}",
                                    width="stretch",
                                )
                        with f_col3:
                            if fr_cov.exists():
                                st.download_button(
                                    "✉️ Lettre de motivation (DOCX)",
                                    fr_cov.read_bytes(),
                                    file_name=fr_cov.name,
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    key=f"fr_cov_{job['id']}_{idx}",
                                    width="stretch",
                                )

                    warnings_list = read_verification_warnings(pack.get("verification_report"))
                    if warnings_list:
                        st.warning(
                            "Review before sending - generated text that is not directly from your "
                            "master resume or the posting:\n\n"
                            + "\n".join(f"- {w}" for w in warnings_list)
                        )
                    else:
                        st.caption(
                            "✅ Verified: resume lines come from your master resume; letter claims match your resume."
                        )

                    # Regenerate Option
                    if st.button("🔄 Regenerate Application Pack", key=f"regen_{job['id']}_{idx}"):
                        with st.spinner("Re-generating fresh documents..."):
                            generate_application_pack(
                                dict(job),
                                languages=languages,
                                company_hook=st.session_state.get(hook_key, ""),
                            )
                            st.success("Re-generated fresh resume and cover letter documents!")
                            st.rerun()

                st.divider()

                # ATS Analysis
                st.markdown("#### 🔍 ATS & Match Analysis")
                resume_text = build_master_resume("en")
                analysis = ats_analysis(resume_text, job["description"])
                st.write(f"**Keyword coverage estimate:** {analysis['ats_score']}%")
                st.caption(
                    "Heuristic word overlap only; this is not a prediction of any employer's ATS result."
                )
                if analysis["missing_keywords"]:
                    st.text(f"Keywords to highlight: {', '.join(analysis['missing_keywords'][:6])}")
                if analysis["missing_skills"]:
                    st.text(
                        f"Skills you have that this resume doesn't show: {', '.join(analysis['missing_skills'][:5])}"
                    )
                if analysis.get("skill_gaps"):
                    st.text(
                        f"Named in the posting, not on your record (don't claim): {', '.join(analysis['skill_gaps'][:5])}"
                    )

                st.divider()
                act_col1, act_col2, act_col3 = st.columns([3, 1, 1])
                with act_col1:
                    if job["url"]:
                        st.link_button("🌐 Apply on Company Site", job["url"], width="stretch")
                with act_col2:
                    if st.button("📌 Log as Applied", key=f"apply_{job['id']}_{idx}"):
                        save_application(
                            {
                                "company": job["company"],
                                "role": job["title"],
                                "salary": job["salary"],
                                "fit_score": job["fit_score"],
                                "application_date": datetime.now().strftime("%Y-%m-%d"),
                                "status": "applied",
                                "notes": f"Applied via JobHunterAI. Direct link: {job['url']}",
                                "url": job.get("url") or job["url"],
                                "source": job.get("source") or "",
                                "language": languages[0] if len(languages) == 1 else "",
                            }
                        )
                        st.success("Logged application!")
                        st.rerun()
                with act_col3:
                    if st.button("Dismiss", key=f"dismiss_{job['id']}_{idx}"):
                        dismiss_job(dict(job))
                        st.rerun()
            st.divider()

with tab_tracker:
    st.subheader("📋 Tracked Applications")
    st.caption(
        "Record what happens after you apply (screening, interview, rejected, ghosted). "
        "That is the only way to learn which kinds of postings actually lead to interviews."
    )
    try:
        conn = get_connection()
        apps = conn.execute(
            "SELECT * FROM applications ORDER BY application_date DESC, id DESC"
        ).fetchall()
        conn.close()
        if not apps:
            st.info(
                "No applications logged yet. Click 'Log as Applied' on any job to track your progress."
            )
        else:
            for app in apps:
                with st.container():
                    st.text(
                        f"{app['role']} @ {app['company']} | Applied: {app['application_date']}"
                    )
                    status_col, date_col, save_col = st.columns([2, 2, 1])
                    current = (app["status"] or "applied").lower()
                    options = list(ALL_STATUSES)
                    new_status = status_col.selectbox(
                        "Status",
                        options,
                        index=options.index(current) if current in options else 0,
                        key=f"status_{app['id']}",
                    )
                    interview_on = date_col.text_input(
                        "Interview date (YYYY-MM-DD)",
                        value=app["interview_date"] or "",
                        key=f"interview_{app['id']}",
                    )
                    if save_col.button("Save", key=f"save_status_{app['id']}"):
                        update_application_status(
                            app["id"], new_status, interview_date=interview_on.strip() or None
                        )
                        st.rerun()
                    if app["notes"]:
                        st.caption(f"Notes: {app['notes']}")
                    st.divider()

            st.subheader("📈 Funnel: what actually works")
            stats = funnel_stats()
            overall = stats["overall"]
            if overall["applied"]:
                f1, f2, f3, f4 = st.columns(4)
                f1.metric("Applied", overall["applied"])
                f2.metric("Heard back", overall["responded"])
                f3.metric("Interviews", overall["interviews"])
                f4.metric("Ghosted", overall["ghosted"])
                for label, key in (
                    ("By match-score band", "by_band"),
                    ("By source", "by_source"),
                    ("By document language", "by_language"),
                ):
                    rows = [
                        {
                            "group": group,
                            **values,
                            "interview rate": f"{round(100 * values['interviews'] / values['applied'])}%"
                            if values["applied"]
                            else "-",
                        }
                        for group, values in sorted(stats[key].items())
                    ]
                    st.markdown(f"**{label}**")
                    st.dataframe(rows, width="stretch", hide_index=True)
                if overall["responded"] + overall["ghosted"] < 10:
                    st.caption(
                        "Too few recorded outcomes to draw conclusions yet - keep updating statuses."
                    )
    except Exception as err:
        st.warning(f"Could not load applications: {err}")

with tab_profile:
    st.subheader("⚙️ Active search criteria")
    left, right = st.columns(2)
    with left:
        st.markdown("**Target roles**")
        st.write(", ".join(USER_PROFILE["target_roles"]) or "—")
        st.markdown("**Priority roles** (score highest)")
        st.write(", ".join(USER_PROFILE.get("priority_target_roles", [])) or "—")
        st.markdown("**Languages**")
        st.write(", ".join(str(lang).upper() for lang in USER_PROFILE.get("languages", [])) or "—")
    with right:
        st.markdown("**Skills you claim** (your keywords)")
        st.write(", ".join(USER_PROFILE.get("keywords", [])) or "—")
        detected = [label_for(skill) for skill in USER_PROFILE.get("resume_skills", [])]
        st.markdown("**Skills detected in your master resume**")
        st.write(", ".join(detected) or "None found. Add your master resume (see the Setup panel).")
    st.caption(
        "Edit these in `.env` (see docs/CONFIGURATION.md). A skill that is on neither list is never "
        "claimed in generated documents."
    )
    with st.expander("Raw configuration"):
        st.json(USER_PROFILE)
