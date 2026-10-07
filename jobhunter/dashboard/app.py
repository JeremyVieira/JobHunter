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
    )
    from jobhunter.scoring.engine import salary_comparison
    from jobhunter.tracker.db import (
        dismiss_job,
        ensure_database,
        get_connection,
        get_job_stats,
        get_top_jobs,
        save_application,
    )
except ModuleNotFoundError:  # pragma: no cover
    from app import run_daily_collection
    from config.settings import USER_PROFILE
    from resume.tailor import (
        ats_analysis,
        build_master_resume,
        generate_application_pack,
        get_application_pack_files,
    )
    from scoring.engine import salary_comparison
    from tracker.db import (
        dismiss_job,
        ensure_database,
        get_connection,
        get_job_stats,
        get_top_jobs,
        save_application,
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

            # Inspect if application pack already exists (does NOT generate)
            pack = get_application_pack_files(dict(job))
            docs_ready = bool(pack.get("exists"))

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
                            generate_application_pack(dict(job))
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
                            use_container_width=True,
                        )

            with st.expander("📄 View Application Pack, ATS Analysis & Job Details", expanded=False):
                m_col1, m_col2, m_col3, m_col4 = st.columns(4)
                m_col1.metric("Fit Score", f"{fit}%")
                m_col2.metric("Interview Chance", f"{interview_chance}%")
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

                # Application Pack Section
                st.markdown("#### 📂 Application Documents")
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
                            generate_application_pack(dict(job))
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
                                generate_application_pack(dict(job))
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
                                    use_container_width=True,
                                )
                        with d_col2:
                            if en_docx.exists():
                                st.download_button(
                                    "📄 Resume (DOCX)",
                                    en_docx.read_bytes(),
                                    file_name=en_docx.name,
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    key=f"en_docx_{job['id']}_{idx}",
                                    use_container_width=True,
                                )
                        with d_col3:
                            if en_cov.exists():
                                st.download_button(
                                    "✉️ Cover Letter (DOCX)",
                                    en_cov.read_bytes(),
                                    file_name=en_cov.name,
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    key=f"en_cov_{job['id']}_{idx}",
                                    use_container_width=True,
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
                                    use_container_width=True,
                                )
                        with f_col2:
                            if fr_docx.exists():
                                st.download_button(
                                    "📄 CV Français (DOCX)",
                                    fr_docx.read_bytes(),
                                    file_name=fr_docx.name,
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    key=f"fr_docx_{job['id']}_{idx}",
                                    use_container_width=True,
                                )
                        with f_col3:
                            if fr_cov.exists():
                                st.download_button(
                                    "✉️ Lettre de motivation (DOCX)",
                                    fr_cov.read_bytes(),
                                    file_name=fr_cov.name,
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    key=f"fr_cov_{job['id']}_{idx}",
                                    use_container_width=True,
                                )

                    # Regenerate Option
                    if st.button("🔄 Regenerate Application Pack", key=f"regen_{job['id']}_{idx}"):
                        with st.spinner("Re-generating fresh documents..."):
                            generate_application_pack(dict(job))
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
                        f"Core skills to include: {', '.join(analysis['missing_skills'][:5])}"
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
    try:
        from jobhunter.tracker.db import get_connection

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
                        f"{app['role']} @ {app['company']} | Status: {app['status']} | "
                        f"Applied: {app['application_date']}"
                    )
                    if app["notes"]:
                        st.text(f"Notes: {app['notes']}")
                    st.divider()
    except Exception as err:
        st.warning(f"Could not load applications: {err}")

with tab_profile:
    st.subheader("⚙️ Active Search Criteria & Config")
    st.json(USER_PROFILE)
