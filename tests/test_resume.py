import tempfile
from pathlib import Path

import pytest

from jobhunter.resume import tailor
from jobhunter.resume.tailor import (
    ats_analysis,
    export_cover_letter,
    export_resume_docx,
    export_resume_files,
    export_resume_pdf,
    generate_application_pack,
    generate_cover_letter,
    generate_cover_letter_french,
    get_application_pack_files,
    tailor_resume_for_job,
)

# Fully synthetic master-resume fixtures -- no contributor's real name, employer,
# school, or contact info. The real master_resume(.txt|_fr.txt) files are
# gitignored (private, per-contributor) and must never be required by or leaked
# into committed tests, so every test in this module is forced to read this
# synthetic content instead via the autouse fixture below, regardless of
# whether a real master resume happens to exist on the machine running them.
SYNTHETIC_SUMMARY_EN = (
    "Bilingual Software Engineering graduate from Lakeside University with "
    "hands-on experience spanning IT support, cloud infrastructure, full-stack "
    "and mobile development, automation, and machine learning. Resolved "
    "technical incidents and improved support processes in corporate IT roles, "
    "built and tested cloud infrastructure using Google Cloud Platform, "
    "Terraform, and Pub/Sub as part of an industry capstone project, and wrote "
    "automation scripts and REST APIs in Python. Also contributed to full-stack "
    "web applications, a React Native mobile app, and trained machine learning "
    "models with PyTorch and scikit-learn. Collaborates effectively in Agile "
    "teams and brings strong written and verbal communication in both French "
    "and English."
)
SYNTHETIC_SUMMARY_FR = (
    "Diplômé bilingue en génie logiciel de l'Université Lakeside avec une "
    "expérience pratique touchant le soutien informatique, l'infrastructure "
    "infonuagique, le développement Web et mobile, l'automatisation et "
    "l'apprentissage automatique. A résolu des incidents techniques et "
    "amélioré les processus de soutien dans des rôles de TI en entreprise, mis "
    "en place et testé une infrastructure infonuagique avec Google Cloud "
    "Platform, Terraform et Pub/Sub dans le cadre d'un projet capstone en "
    "partenariat avec une entreprise, et écrit des scripts d'automatisation et "
    "des API REST en Python. Collabore efficacement en équipe Agile et possède "
    "d'excellentes compétences de communication écrite et orale en français et "
    "en anglais."
)
SYNTHETIC_RESUME_EN = f"""Alex Example
123 Example Street
Montreal, H0H 0H0
(514) 555-0100
alex.example@gmail.com
https://github.com/alex-example
https://www.linkedin.com/in/alex-example/

PROFESSIONAL SUMMARY
{SYNTHETIC_SUMMARY_EN}

EXPERIENCE

Example Logistics Inc, Montreal — End User Support Analyst
April 2024 - Current
- Resolved technical incidents and conducted root-cause analysis for corporate operations across Quebec
- Collaborated with cross-functional teams across Canada to improve support processes and documentation

Example Tech Corp, Montreal — IT Help Desk Analyst
January 2024 - April 2024
- Resolved hardware, software, and network issues to reduce downtime and support stable operations
- Gathered requirements and translated operational challenges into technical support solutions

EDUCATION

Lakeside University, Montreal — Bachelor of Science in Software Engineering
September 2022 - June 2026

Lakeside College, Montreal — DEC (Diploma of College Studies) in Computer Science and Mathematics
August 2020 - April 2022

PROJECTS

Colorectal Cancer Detection Using Deep Learning
- Built a ResNet18 image-classification pipeline with PyTorch and torchvision for three colorectal histology tissue classes
- Implemented a data preprocessing and augmentation pipeline, validating results with cross-validation and confusion matrix analysis
- Applied scikit-learn and Google Colab with GPU acceleration

JobHunter — Job Search and Application Platform
- Built a Python platform that collects job postings from multiple sources, scores and filters opportunities, and tracks applications in SQLite
- Developed a Streamlit dashboard and English/French application-document generation, with an in-process daily collection schedule while the app is running
- Added automated tests for scraping, scoring, tracking, and document generation

Machine Learning Coursework (472-A2) — Classification and Clustering
- Implemented K-Means, decision-tree, MLP, and CNN experiments on Iris and Fashion-MNIST datasets
- Generated training curves, confusion matrices, and per-class precision, recall, and F1 evaluation outputs

SvelteShipSolutions — Team Full-Stack Web Application
- Contributed to a team-developed shipping and logistics application with package tracking and automated rate quoting
- Modeled relational data and integrated third-party REST APIs (Google Places API) using Prisma ORM and SQL
- Collaborated in an Agile team using iterative development and Git version control

Campus Guide Mobile App — Team Project
- Contributed to a React Native and Expo mobile navigation app, including campus maps, indoor and outdoor directions, and schedule-aware routing
- Implemented GPS tracking and a real-time user location indicator on the map

TECHNICAL SKILLS

Programming & Machine Learning
- Python, SQL, PyTorch, scikit-learn, pandas, NumPy, automation scripting, REST APIs, JavaScript, Java, Node.js, Express.js

Tools & Practices
- Git, GitHub, Docker, CI/CD, pytest, VS Code, Google Colab, Prisma ORM, Agile / Scrum, Google Cloud Platform (GCP), Terraform, Pub/Sub

Support & Collaboration
- Requirements Gathering, Root Cause Analysis, Stakeholder Communication, Incident Management, Technical Documentation

LANGUAGES
French - Fluent
English - Fluent
"""
SYNTHETIC_RESUME_FR = f"""Alex Example
123 Rue Exemple
Montréal, H0H 0H0
(514) 555-0100
alex.example@gmail.com
https://github.com/alex-example

PROFIL PROFESSIONNEL
{SYNTHETIC_SUMMARY_FR}

EXPÉRIENCE

Entreprise Exemple A, Montréal - Analyste soutien informatique
Avril 2024 - Aujourd'hui
- Résout des incidents techniques et effectue des analyses de causes racines pour les opérations corporatives au Québec
- Collabore avec des équipes interfonctionnelles à travers le Canada pour améliorer les processus de support et la documentation

Entreprise Exemple B, Montréal - Analyste soutien informatique
Janvier 2024 - Avril 2024
- Résolu des problèmes matériels, logiciels et réseau afin de réduire les temps d'arrêt
- Recueilli les besoins des utilisateurs et transformé les défis opérationnels en solutions techniques

FORMATION

Université Lakeside, Montréal - Baccalauréat en sciences, génie logiciel
Septembre 2022 - Juin 2026

Collège Lakeside, Montréal - DEC en informatique et mathématiques
Août 2020 - Avril 2022

PROJETS

JobHunter — Plateforme de recherche d'emploi et de candidature
- Développé une plateforme Python qui collecte des offres de plusieurs sources, évalue et filtre les postes, et suit les candidatures dans SQLite
- Créé un tableau de bord Streamlit et la génération de CV et lettres de présentation en français et en anglais
- Ajouté des tests automatisés pour la collecte, l'évaluation, le suivi et la génération de documents

Application mobile Campus Guide — Projet d'équipe
- Contribué à une application React Native et Expo de navigation, avec cartes des campus, itinéraires intérieurs et extérieurs et trajets selon l'horaire
- Implémenté le suivi GPS et un indicateur de position en temps réel sur la carte

SvelteShipSolutions — Application Web full-stack en équipe
- Contribué à une application de logistique développée en équipe, avec suivi de colis et calcul automatisé de devis
- Modélisé des données relationnelles et intégré des API REST tierces avec Prisma ORM et SQL

Détection du cancer colorectal par apprentissage profond
- Développé un pipeline de classification d'images avec ResNet18, PyTorch et torchvision pour trois types de tissus histologiques colorectaux
- Utilisé scikit-learn et Google Colab avec accélération GPU

COMPÉTENCES TECHNIQUES

Programmation et apprentissage automatique
- Python, SQL, PyTorch, scikit-learn, pandas, NumPy, scripts d'automatisation, API REST, JavaScript, Java, Node.js, Express.js

Outils et pratiques
- Git, GitHub, Docker, CI/CD, pytest, VS Code, Google Colab, Prisma ORM, Agile / Scrum, Google Cloud Platform (GCP), Terraform, Pub/Sub

Soutien et collaboration
- Collecte des exigences, analyse des causes racines, communication avec les parties prenantes, gestion des incidents, documentation technique

LANGUES
Français - Courant
Anglais - Courant
"""


@pytest.fixture(autouse=True)
def synthetic_master_resume(monkeypatch):
    """Force every test in this module to read the synthetic resume fixtures
    above instead of a real master_resume(.txt|_fr.txt), whether or not one
    exists locally, so these committed tests never depend on (or risk
    leaking) a contributor's real personal/employment data."""

    def _fake_build_master_resume(language: str = "en") -> str:
        if language not in {"en", "fr"}:
            raise ValueError("language must be 'en' or 'fr'")
        return SYNTHETIC_RESUME_FR if language == "fr" else SYNTHETIC_RESUME_EN

    def _fake_verified_resume_summary(language: str) -> str:
        return SYNTHETIC_SUMMARY_FR if language == "fr" else SYNTHETIC_SUMMARY_EN

    monkeypatch.setattr(tailor, "build_master_resume", _fake_build_master_resume)
    monkeypatch.setattr(tailor, "_verified_resume_summary", _fake_verified_resume_summary)


def test_build_master_resume():
    resume = tailor.build_master_resume()
    assert "Alex Example" in resume
    assert "Montreal" in resume
    assert "Bachelor of Science in Software Engineering" in resume
    assert "IT Help Desk" in resume
    assert "Example Logistics Inc" in resume or "Example Tech Corp" in resume
    assert "@gmail.com" in resume or "github" in resume.lower()


def test_build_french_master_resume():
    resume = tailor.build_master_resume(language="fr")
    assert "Alex Example" in resume
    assert "PROFIL PROFESSIONNEL" in resume
    assert "Entreprise Exemple A" in resume
    assert "COMPÉTENCES TECHNIQUES" in resume
    assert "Université Lakeside" in resume
    assert "expérience pratique" in resume


def test_tailor_resume_for_job_business_analyst():
    resume = tailor_resume_for_job("Business Analyst", "Bell Canada")
    assert "Alex Example" in resume
    assert "Example Logistics Inc" in resume
    assert "Example Tech Corp" in resume


def test_tailor_resume_for_job_systems_analyst():
    resume = tailor_resume_for_job("Systems Analyst", "TD Bank")
    assert "PROFESSIONAL SUMMARY" in resume
    assert "EXPERIENCE" in resume
    assert "TECHNICAL SKILLS" in resume


def test_tailor_resume_for_job_data_analyst():
    resume = tailor_resume_for_job("Data Analyst", "RBC")
    assert "Alex Example" in resume
    assert "Lakeside University" in resume


def test_tailor_resume_for_job_product_analyst():
    resume = tailor_resume_for_job("Product Analyst", "CIBC")
    assert "Alex Example" in resume
    assert "SvelteShipSolutions" in resume


def test_tailor_resume_selects_projects_relevant_to_posting():
    resume = tailor_resume_for_job(
        "Machine Learning Engineer",
        "Example AI",
        job_description="Build computer vision models with PyTorch and evaluate classification performance.",
    )
    assert "ResNet18" in resume
    assert "Machine Learning Coursework" in resume
    assert "SvelteShipSolutions" not in resume


def test_tailor_resume_for_software_role_surfaces_jobhunter_project():
    resume = tailor_resume_for_job(
        "Python Developer",
        "Example Corp",
        job_description="Python automation, web scraping, SQLite, Streamlit dashboard, and automated tests.",
    )
    assert "JobHunter" in resume
    assert "Streamlit dashboard" in resume
    assert "ResNet18" in resume


def test_tailor_resume_keeps_two_projects_when_only_one_matches():
    resume = tailor_resume_for_job(
        "Systems Analyst",
        "Example Corp",
        job_description="SQL, APIs, and system architecture.",
    )

    assert "JobHunter" in resume
    assert "Colorectal Cancer Detection Using Deep Learning" in resume


def test_professional_summary_stays_general_across_job_families():
    """The summary is a general overview of the candidate and must not be
    rewritten per posting -- only PROJECTS and skill ordering should adapt."""
    lines = tailor.build_master_resume().splitlines()
    summary_index = lines.index("PROFESSIONAL SUMMARY") + 1
    master_summary_line = lines[summary_index]

    ml_resume = tailor_resume_for_job(
        "Machine Learning Engineer",
        "Example AI",
        job_description="PyTorch, computer vision, deep learning.",
    )
    analyst_resume = tailor_resume_for_job(
        "Business Systems Analyst",
        "Example Corp",
        job_description="Requirements gathering and process improvement.",
    )
    developer_resume = tailor_resume_for_job(
        "Full-Stack Developer",
        "Example Corp",
        job_description="React Native mobile development.",
    )

    for resume in (ml_resume, analyst_resume, developer_resume):
        assert master_summary_line in resume


def test_tailor_resume_in_french_keeps_general_summary_and_adapts_projects():
    resume = tailor_resume_for_job(
        "Développeuse mobile",
        "Exemple",
        language="fr",
        job_description="React Native, Expo, campus navigation and mobile maps.",
    )
    # The summary is a general overview and must not be rewritten per posting --
    # only PROJECTS (and skill ordering) should adapt to the job.
    assert "Diplômé bilingue en génie logiciel de l'Université Lakeside" in resume
    assert "Campus Guide" in resume
    assert "JobHunter" in resume


def test_generate_cover_letter():
    letter = generate_cover_letter("Business Analyst", "Bell Canada")
    assert "Bell Canada" in letter
    assert "Business Analyst" in letter
    assert "Lakeside University" in letter
    assert "professional summary" in letter.lower()


def test_generate_cover_letter_with_job_description():
    letter = generate_cover_letter("Business Analyst", "TD Bank", "SQL and analytics")
    assert "TD Bank" in letter
    assert "sql" in letter.lower()


def test_cover_letter_sanitizes_scraped_markdown_and_html():
    description = "**Company Description** <p>Python, SQL, and <strong>automation</strong>.</p>"

    letter = generate_cover_letter("Business Systems Analyst", "American Iron & Metal", description)

    assert "Python, SQL, automation" in letter
    assert "**" not in letter
    assert "<p>" not in letter
    assert "Company Description" not in letter


def test_cover_letters_use_only_local_master_summary_for_candidate_claims(monkeypatch):
    from jobhunter.resume import tailor

    master_summaries = {
        "en": "Experienced hotel receptionist skilled in guest services and reservations.",
        "fr": "Réceptionniste d'hôtel expérimentée en accueil et gestion de réservations.",
    }
    monkeypatch.setattr(
        tailor,
        "_verified_resume_summary",
        lambda language: master_summaries[language],
    )
    monkeypatch.setitem(tailor.USER_PROFILE, "name", "Alex Example")
    monkeypatch.setitem(tailor.USER_PROFILE, "location", "Ottawa, ON")

    english = tailor.generate_cover_letter("Guest Services Agent", "Example Hotel")
    french = tailor.generate_cover_letter_french("Agente de réception", "Hôtel Exemple")

    assert master_summaries["en"] in english
    assert master_summaries["fr"] in french
    for letter in (english, french):
        assert "Example Logistics Inc" not in letter
        assert "Lakeside University" not in letter
        assert "Alex Example" in letter


def test_generate_french_cover_letter():
    letter = generate_cover_letter_french("Analyste d'affaires", "RBC", "SQL et analyse")
    assert "Madame, Monsieur" in letter
    assert "Analyste d'affaires" in letter
    assert "RBC" in letter
    assert "SQL" in letter
    assert "Université Lakeside" in letter
    assert "profil professionnel" in letter.lower()


def test_export_resume_docx():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = export_resume_docx("Business Analyst", "Bank of Montreal", output_dir=tmpdir)
        assert Path(path).exists()
        assert path.endswith(".docx")


def test_export_resume_pdf():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = export_resume_pdf("Business Analyst", "TD Bank", output_dir=tmpdir)
        assert Path(path).exists()
        assert path.endswith(".pdf")


def test_export_resume_files_txt_only():
    with tempfile.TemporaryDirectory() as tmpdir:
        files = export_resume_files(
            "Business Analyst", "Bank of Montreal", formats=["txt"], output_dir=tmpdir
        )
        assert "txt" in files
        assert Path(files["txt"]).exists()


def test_export_resume_files_docx_only():
    with tempfile.TemporaryDirectory() as tmpdir:
        files = export_resume_files("Business Analyst", "RBC", formats=["docx"], output_dir=tmpdir)
        assert "docx" in files
        assert Path(files["docx"]).exists()


def test_export_resume_files_pdf_only():
    with tempfile.TemporaryDirectory() as tmpdir:
        files = export_resume_files(
            "Business Analyst", "TD Bank", formats=["pdf"], output_dir=tmpdir
        )
        assert "pdf" in files
        assert Path(files["pdf"]).exists()


def test_export_cover_letter():
    path = export_cover_letter("Business Analyst", "RBC", "SQL and stakeholder communication")
    assert Path(path).exists()
    assert path.endswith(".docx")
    assert Path(path).stat().st_size > 0


def test_export_resume_files_all_formats():
    with tempfile.TemporaryDirectory() as tmpdir:
        files = export_resume_files(
            "Business Analyst",
            "Bank of Montreal",
            formats=["txt", "docx", "pdf"],
            output_dir=tmpdir,
        )
        assert "txt" in files
        assert "docx" in files
        assert "pdf" in files
        assert Path(files["txt"]).exists()
        assert Path(files["docx"]).exists()
        assert Path(files["pdf"]).exists()


def test_export_french_resume_and_cover_letter():
    with tempfile.TemporaryDirectory() as tmpdir:
        files = export_resume_files(
            "Analyste d'affaires", "RBC", formats=["docx", "pdf"], output_dir=tmpdir, language="fr"
        )
        letter_path = export_cover_letter("Analyste d'affaires", "RBC", language="fr")
        assert files["docx"].endswith("_fr.docx")
        assert files["pdf"].endswith("_fr.pdf")
        assert Path(files["docx"]).exists()
        assert Path(files["pdf"]).exists()
        assert letter_path.endswith("_fr.docx")
        assert Path(letter_path).exists()


def test_ats_analysis_perfect_match():
    resume = (
        "Python automation machine learning data pipelines pandas numpy scikit-learn "
        "pytorch pytest unit testing ci/cd docker rest api sql git "
        "scripting algorithms data structures cloud agile troubleshooting excel"
    )
    job_description = (
        "Python automation machine learning data pipelines pandas numpy scikit-learn "
        "pytorch pytest unit testing"
    )
    analysis = ats_analysis(resume, job_description)
    assert analysis["ats_score"] > 60
    assert "ats_score" in analysis
    assert "missing_keywords" in analysis


def test_ats_analysis_partial_match():
    resume = "Python SQL Excel business analysis"
    job_description = "Power BI Tableau Python SQL Excel requirements gathering business analysis"
    analysis = ats_analysis(resume, job_description)
    assert "ats_score" in analysis
    assert analysis["ats_score"] >= 0 and analysis["ats_score"] <= 100
    assert "missing_keywords" in analysis


def test_ats_analysis_no_match():
    resume = "COBOL Fortran Assembly"
    job_description = "Python SQL Excel Power BI business analysis requirements gathering"
    analysis = ats_analysis(resume, job_description)
    assert "ats_score" in analysis
    assert analysis["ats_score"] < 50


def test_ats_analysis_ignores_common_words_and_reports_heuristic_type():
    resume = "Python SQL automation"
    description = "The role is Python and SQL automation with the team."

    analysis = ats_analysis(resume, description)

    assert analysis["ats_score"] == 100
    assert analysis["missing_keywords"] == []
    assert analysis["score_type"] == "keyword coverage estimate"


def test_generate_application_pack():
    job = {
        "title": "Technical Systems Analyst",
        "company": "National Bank",
        "description": "SQL, APIs, requirements gathering and system architecture.",
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        pack = generate_application_pack(job, output_dir=tmpdir)
        assert "en_resume_pdf" in pack
        assert "en_resume_docx" in pack
        assert "en_cover_letter_docx" in pack
        assert "fr_resume_pdf" in pack
        assert "fr_resume_docx" in pack
        assert "fr_cover_letter_docx" in pack
        assert Path(pack["en_resume_pdf"]).exists()
        assert Path(pack["en_resume_docx"]).exists()
        assert Path(pack["en_cover_letter_docx"]).exists()
        assert Path(pack["fr_resume_pdf"]).exists()
        assert Path(pack["fr_resume_docx"]).exists()
        assert Path(pack["fr_cover_letter_docx"]).exists()


def test_application_packs_for_same_company_and_different_roles_do_not_collide():
    first_job = {
        "title": "Business Analyst",
        "company": "Example Corp",
        "description": "SQL and requirements gathering.",
        "url": "https://jobs.example.com/business-analyst",
    }
    second_job = {
        "title": "Systems Analyst",
        "company": "Example Corp",
        "description": "APIs and process improvement.",
        "url": "https://jobs.example.com/systems-analyst",
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        first_pack = generate_application_pack(first_job, output_dir=tmpdir)
        second_pack = generate_application_pack(second_job, output_dir=tmpdir)

        assert Path(first_pack["en_resume_pdf"]).parent != Path(second_pack["en_resume_pdf"]).parent
        assert Path(first_pack["en_cover_letter_docx"]).exists()
        assert Path(second_pack["en_cover_letter_docx"]).exists()


def test_scraped_company_name_cannot_escape_resume_output_directory():
    job = {
        "title": "Operations Analyst",
        "company": "../../outside\\nested",
        "description": "Scheduling, reporting, and process coordination.",
        "url": "https://jobs.example.com/operations-analyst",
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        pack = generate_application_pack(job, output_dir=root)
        generated_paths = [Path(path).resolve() for path in pack.values()]

        assert generated_paths
        assert all(path.is_relative_to(root) for path in generated_paths)


def test_get_application_pack_files():
    job = {
        "title": "Solutions Engineer",
        "company": "CGI Inc",
        "description": "Enterprise cloud solutions and client demos.",
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        # Before generation, files do not exist
        info1 = get_application_pack_files(job, output_dir=tmpdir)
        assert info1["exists"] is False

        # Generate files on-demand
        generate_application_pack(job, output_dir=tmpdir)

        # After generation, files exist
        info2 = get_application_pack_files(job, output_dir=tmpdir)
        assert info2["exists"] is True
        assert info2["complete"] is True
        assert Path(str(info2["en_resume_pdf"])).exists()


def test_get_application_pack_files_reports_partial_pack():
    from jobhunter.resume.tailor import _application_pack_directory

    job = {
        "title": "Operations Analyst",
        "company": "Example Corp",
        "url": "https://jobs.example.com/operations-analyst",
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        pack_dir = _application_pack_directory(job, tmpdir)
        pack_dir.mkdir()
        partial_file = pack_dir / "resume_example_corp.pdf"
        partial_file.write_bytes(b"partial test file")

        info = get_application_pack_files(job, output_dir=tmpdir)

        assert info["exists"] is True
        assert info["complete"] is False
        assert info["en_resume_pdf"] == str(partial_file)
