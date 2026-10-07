"""Unit tests for newly implemented design patterns in JobHunterAI."""

import tempfile
from pathlib import Path

from jobhunter.app import (
    CollectionDependencies,
    FilteringStage,
    IPipelineStage,
    JobCollectionPipeline,
    PersistenceStage,
    ScoringStage,
)
from jobhunter.filter import (
    FilterChain,
    LocationAndRemotePredicate,
    MinFitScorePredicate,
    RoleBlacklistPredicate,
    TargetRolePredicate,
)
from jobhunter.models import JobListing, ScoringRulesConfig, UserProfile
from jobhunter.resume.tailor import (
    DocxResumeExporter,
    PdfResumeExporter,
    ResumeParser,
    TxtResumeExporter,
)
from jobhunter.scoring.engine import (
    CompositeScorer,
)
from jobhunter.scraper.collector import (
    ArbeitnowScraper,
    JobicyScraper,
    JobSpyScraper,
    RemotiveScraper,
    ScraperFactory,
)
from jobhunter.tracker.db import SQLiteApplicationRepository, SQLiteJobRepository


def test_repository_pattern_crud():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        job_repo = SQLiteJobRepository(db_path=db_path)
        app_repo = SQLiteApplicationRepository(db_path=db_path)

        job_repo.ensure_schema()
        app_repo.ensure_schema()

        # Save typed JobListing
        job = JobListing(
            title="Business Analyst",
            company="Test Corp",
            location="Montreal, QC",
            salary="$90,000",
            fit_score=88.5,
            url="https://example.com/jobs/1",
        )
        assert job_repo.save(job) == 1

        recent = job_repo.find_recent(limit=5)
        assert len(recent) == 1
        assert recent[0]["title"] == "Business Analyst"

        top = job_repo.find_top(limit=5)
        assert len(top) == 1
        assert top[0]["company"] == "Test Corp"

        stats = job_repo.get_stats()
        assert stats["total_jobs"] == 1
        assert stats["high_fit_jobs"] == 1


def test_scraper_factory_and_adapters():
    jobicy = ScraperFactory.create("jobicy")
    assert isinstance(jobicy, JobicyScraper)

    remotive = ScraperFactory.create("remotive")
    assert isinstance(remotive, RemotiveScraper)

    arbeitnow = ScraperFactory.create("arbeitnow")
    assert isinstance(arbeitnow, ArbeitnowScraper)

    jobspy = ScraperFactory.create("jobspy")
    assert isinstance(jobspy, JobSpyScraper)


def test_scoring_strategy_and_composite():
    profile = UserProfile(
        target_roles=["Business Analyst"],
        keywords=["sql", "excel", "jira"],
    )
    config = ScoringRulesConfig()
    scorer = CompositeScorer(config=config, profile=profile)

    job = {
        "title": "Business Analyst",
        "company": "Enterprise Inc",
        "location": "Montreal, QC",
        "remote_status": "Hybrid",
        "salary": "$90,000 - $110,000",
        "description": "Requires SQL, Excel, Jira and 2 years experience.",
    }

    scores = scorer.score_job(job)
    assert scores["fit_score"] >= 70
    assert scores["title_match"] == 100
    assert scores["experience_match"] == 90
    assert scores["skills_match"] >= 50


def test_filter_chain_of_responsibility():
    chain = FilterChain(
        [
            TargetRolePredicate(),
            LocationAndRemotePredicate(),
            MinFitScorePredicate(65.0),
            RoleBlacklistPredicate(),
        ]
    )

    jobs = [
        {"title": "Business Analyst", "location": "Montreal, QC", "fit_score": 85},
        {"title": "Senior Software Engineer", "location": "Montreal, QC", "fit_score": 90},
        {
            "title": "Business Analyst",
            "location": "Vancouver, BC",
            "fit_score": 85,
            "description": "On-site only",
        },
        {"title": "Business Analyst", "location": "Montreal, QC", "fit_score": 50},
    ]

    filtered = chain.apply(jobs)
    assert len(filtered) == 1
    assert filtered[0]["title"] == "Business Analyst"
    assert filtered[0]["location"] == "Montreal, QC"


def test_resume_parser_and_exporters():
    raw_resume = """ALEX EXAMPLE
Montreal, QC | alex@example.com | (514) 555-0100

PROFESSIONAL SUMMARY
Experienced analyst with strong SQL and business analysis skills.

EXPERIENCE
IT Help Desk Specialist - Example Corp
Montreal, QC - 2023 - Present
- Resolved complex incidents and optimized user workflows.
"""
    parsed = ResumeParser.parse(raw_resume)
    assert parsed.header_name == "ALEX EXAMPLE"
    assert parsed.contact_lines == ["Montreal, QC", "alex@example.com", "(514) 555-0100"]
    assert any(b.kind == "section" for b in parsed.blocks)
    assert any(b.kind == "bullet" for b in parsed.blocks)

    with tempfile.TemporaryDirectory() as tmpdir:
        txt_path = Path(tmpdir) / "resume.txt"
        docx_path = Path(tmpdir) / "resume.docx"
        pdf_path = Path(tmpdir) / "resume.pdf"

        assert TxtResumeExporter().export(parsed, txt_path) == str(txt_path)
        assert DocxResumeExporter().export(parsed, docx_path) == str(docx_path)
        assert PdfResumeExporter().export(parsed, pdf_path) == str(pdf_path)

        assert txt_path.exists()
        assert docx_path.exists()
        assert pdf_path.exists()


def test_job_collection_pipeline():
    class MockExtractionStage(IPipelineStage):
        def process(self, context):
            context["raw_jobs"] = [
                {
                    "title": "Business Analyst",
                    "company": "Bank of Montreal",
                    "location": "Montreal, QC",
                    "salary": "$95,000",
                    "description": "SQL Excel Jira",
                    "url": "https://example.com/job/test-pipeline",
                }
            ]
            return context

    with tempfile.TemporaryDirectory() as tmpdir:
        dependencies = CollectionDependencies(
            ensure_database=lambda: None,
            purge_placeholder_jobs=lambda: None,
            purge_red_flag_jobs=lambda: None,
            filter_applied_jobs=lambda jobs: list(jobs),
            save_jobs=lambda jobs: len(jobs),
            output_dir=Path(tmpdir),
        )
        pipeline = JobCollectionPipeline(
            stages=[
                MockExtractionStage(),
                ScoringStage(),
                FilteringStage(),
                PersistenceStage(limit=5),
            ],
            dependencies=dependencies,
        )
        results = pipeline.run()
        assert len(results) == 1
        assert results[0]["title"] == "Business Analyst"
        assert results[0]["fit_score"] >= 60
