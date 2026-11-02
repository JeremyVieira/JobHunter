from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is in sys.path for direct Streamlit execution
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

try:
    from jobhunter.app import run_daily_collection
    from jobhunter.config.settings import USER_PROFILE
    from jobhunter.resume.tailor import (
        ats_analysis,
        build_master_resume,
        generate_application_pack,
        get_application_pack_files,
        read_verification_warnings,
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
except ModuleNotFoundError:  # pragma: no cover
    from app import run_daily_collection
    from config.settings import USER_PROFILE
    from resume.tailor import (
        ats_analysis,
        build_master_resume,
        generate_application_pack,
        get_application_pack_files,
        read_verification_warnings,
    )
    from scoring.engine import salary_comparison
    from tracker.db import (
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

st.set_page_config(page_title="JobHunterAI Dashboard", page_icon="💼", layout="wide")

ensure_database()


def as_job_dict(job):
    """Normalize SQLite row objects and dict-like records to a plain dict."""
    if job is None:
        return {}
    if hasattr(job, "keys"):
        return dict(job)
    return dict(job)


def _read_download_file(value):
    """Read a generated document only when its path points to a regular file."""
    if not value:
        return None
    path = Path(str(value))
    try:
        if not path.is_file():
            return None
        return path, path.read_bytes()
    except OSError:
        return None


_MARKDOWN_SPECIAL_CHARS = re.compile(r"([\\`*_{}\[\]()#+.!|>~-])")


def _escape_markdown(value: str) -> str:
    plain_text = " ".join((value or "").splitlines())
    return _MARKDOWN_SPECIAL_CHARS.sub(lambda match: "\\" + match.group(1), plain_text)


st.title("💼 JobHunterAI Dashboard")
st.caption(f"Intelligent Career & Job Opportunity Hub for {_escape_markdown(USER_PROFILE['name'])}")

# Sidebar
with st.sidebar:
    st.header("🎯 Profile Summary")
    st.write(f"**Name:** {USER_PROFILE['name']}")
    st.write(f"**Degree:** {USER_PROFILE['degree']}")
    st.write(f"**Location:** {USER_PROFILE['location']}")
    st.write(f"**Target Roles:** {len(USER_PROFILE['target_roles'])} defined")

    st.divider()
    if st.button("🔄 Collect & Score Jobs Now", type="primary", use_container_width=True):
        with st.spinner(
            "Scraping boards, scoring, filtering & generating top application packs..."
        ):
            collected = run_daily_collection()
            st.success(f"Collected and scored {len(collected)} matching opportunities!")
            st.rerun()

    st.divider()
    st.subheader("Target Roles")
    for role in USER_PROFILE["target_roles"][:8]:
        st.caption(f"• {role}")
    if len(USER_PROFILE["target_roles"]) > 8:
        st.caption(f"... and {len(USER_PROFILE['target_roles']) - 8} more")

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
    top_jobs = get_top_jobs(30)
    if not top_jobs:
        st.info(
            "No jobs stored yet. Click 'Collect & Score Jobs Now' in the sidebar to start scraping."
        )
    else:
        for idx, job in enumerate(top_jobs):
            job = as_job_dict(job)
            fit = float(job["fit_score"] or 0)
            interview_chance = float(job["interview_chance"] or 0)
            color_badge = "🟢" if fit >= 80 else "🟡" if fit >= 65 else "⚪"
            job_title = job["title"]
            company_name = job["company"]
            salary_market = salary_comparison(job["salary"], job_title)

            # Inspect if application pack already exists (does NOT generate).
            # Generate both English and French documents by default.
            languages = ("en", "fr")
            pack = get_application_pack_files(dict(job), languages=languages)
            docs_ready = bool(pack.get("complete"))
            hook_key = f"hook_{job['id']}_{idx}"

            # Header row with title & action button
            header_col1, header_col2 = st.columns([3.5, 1.5])
            with header_col1:
                st.markdown(
                    f"### {color_badge} **{_escape_markdown(job_title)}** @ "
                    f"**{_escape_markdown(company_name)}**"
                )
                st.caption(f"Fit: **{fit}%**")
                st.text(
                    f"Salary: {job['salary']} | Location: {job['location']} | "
                    f"Work Model: {job['remote_status']}"
                )
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
                        use_container_width=True,
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
                    download = _read_download_file(pack.get("en_resume_pdf"))
                    if download:
                        en_pdf_path, en_pdf_data = download
                        st.download_button(
                            label="📥 Download Resume PDF",
                            data=en_pdf_data,
                            file_name=en_pdf_path.name,
                            mime="application/pdf",
                            key=f"quick_dl_{job['id']}_{idx}",
                            use_container_width=True,
                        )

            with st.expander("📄 View Application Pack, ATS Analysis & Job Details", expanded=False):
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
                        st.write("**Asked for, not on your record:** " + ", ".join(skills["missing_required"]))
                    if skills.get("core_gaps"):
                        st.warning("Hard-stack gap: " + ", ".join(skills["core_gaps"]))
                    if details.get("years_required") is not None:
                        st.caption(f"Years of experience asked: {details['years_required']}")
                    notable = {k: v for k, v in adjustments.items() if v}
                    if notable:
                        st.caption("Adjustments: " + ", ".join(f"{k.replace('_', ' ')} {v:+}" for k, v in notable.items()))

                # Application Pack Section
                st.markdown("#### 📂 Application Documents")
                st.text_input(
                    "Company-specific line for the cover letter (optional - you write it; nothing is invented)",
                    key=hook_key,
                    placeholder="e.g. Why this company/team interests you, in one sentence",
                )
                if not (st.session_state.get(hook_key) or "").strip():
                    st.caption("No company-specific line yet: the letter will be accurate but generic.")
                st.caption("Documents for: " + ", ".join(languages) + " (chosen from the posting's language).")
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
                        st.warning("This application pack is incomplete. Available files remain downloadable below.")
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
                        en_pdf_download = _read_download_file(pack.get("en_resume_pdf"))
                        en_docx_download = _read_download_file(pack.get("en_resume_docx"))
                        en_cov_download = _read_download_file(pack.get("en_cover_letter_docx"))

                        with d_col1:
                            if en_pdf_download:
                                en_pdf, en_pdf_data = en_pdf_download
                                st.download_button(
                                    "📥 Resume (PDF)",
                                    en_pdf_data,
                                    file_name=en_pdf.name,
                                    mime="application/pdf",
                                    key=f"en_pdf_{job['id']}_{idx}",
                                    use_container_width=True,
                                )
                        with d_col2:
                            if en_docx_download:
                                en_docx, en_docx_data = en_docx_download
                                st.download_button(
                                    "📄 Resume (DOCX)",
                                    en_docx_data,
                                    file_name=en_docx.name,
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    key=f"en_docx_{job['id']}_{idx}",
                                    use_container_width=True,
                                )
                        with d_col3:
                            if en_cov_download:
                                en_cov, en_cov_data = en_cov_download
                                st.download_button(
                                    "✉️ Cover Letter (DOCX)",
                                    en_cov_data,
                                    file_name=en_cov.name,
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    key=f"en_cov_{job['id']}_{idx}",
                                    use_container_width=True,
                                )

                    with doc_tab_fr:
                        f_col1, f_col2, f_col3 = st.columns(3)
                        fr_pdf_download = _read_download_file(pack.get("fr_resume_pdf"))
                        fr_docx_download = _read_download_file(pack.get("fr_resume_docx"))
                        fr_cov_download = _read_download_file(pack.get("fr_cover_letter_docx"))

                        with f_col1:
                            if fr_pdf_download:
                                fr_pdf, fr_pdf_data = fr_pdf_download
                                st.download_button(
                                    "📥 CV Français (PDF)",
                                    fr_pdf_data,
                                    file_name=fr_pdf.name,
                                    mime="application/pdf",
                                    key=f"fr_pdf_{job['id']}_{idx}",
                                    use_container_width=True,
                                )
                        with f_col2:
                            if fr_docx_download:
                                fr_docx, fr_docx_data = fr_docx_download
                                st.download_button(
                                    "📄 CV Français (DOCX)",
                                    fr_docx_data,
                                    file_name=fr_docx.name,
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    key=f"fr_docx_{job['id']}_{idx}",
                                    use_container_width=True,
                                )
                        with f_col3:
                            if fr_cov_download:
                                fr_cov, fr_cov_data = fr_cov_download
                                st.download_button(
                                    "✉️ Lettre de motivation (DOCX)",
                                    fr_cov_data,
                                    file_name=fr_cov.name,
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    key=f"fr_cov_{job['id']}_{idx}",
                                    use_container_width=True,
                                )

                    warnings_list = read_verification_warnings(pack.get("verification_report"))
                    if warnings_list:
                        st.warning(
                            "Review before sending - generated text that is not directly from your "
                            "master resume or the posting:\n\n" + "\n".join(f"- {w}" for w in warnings_list)
                        )
                    else:
                        st.caption("✅ Verified: resume lines come from your master resume; letter claims match your resume.")

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
                st.caption("Heuristic word overlap only; this is not a prediction of any employer's ATS result.")
                if analysis["missing_keywords"]:
                    st.text(
                        f"Keywords to highlight: {', '.join(analysis['missing_keywords'][:6])}"
                    )
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
                        st.link_button(
                            "🌐 Apply on Company Site", job["url"], use_container_width=True
                        )
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
                    st.dataframe(rows, use_container_width=True, hide_index=True)
                if overall["responded"] + overall["ghosted"] < 10:
                    st.caption("Too few recorded outcomes to draw conclusions yet - keep updating statuses.")
    except Exception as err:
        st.warning(f"Could not load applications: {err}")

with tab_profile:
    st.subheader("⚙️ Active Search Criteria & Config")
    st.json(USER_PROFILE)
