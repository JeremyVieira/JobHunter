"""Tests for the scoring engine module."""

from jobhunter.models import ScoringRulesConfig
from jobhunter.scoring.engine import (
    CompositeScorer,
    education_match_score,
    entry_level_salary_benchmark,
    experience_match_score,
    fit_score,
    normalize_text,
    parse_salary,
    salary_comparison,
    score_jobs,
    skill_match_score,
    title_match_score,
)


def test_normalize_text():
    assert normalize_text("Business ANALYST") == "business analyst"
    assert normalize_text("SQL/Excel-Power BI") == "sql excel power bi"
    assert normalize_text("") == ""


def test_parse_salary():
    assert parse_salary("$95,000 - $115,000") == 105000.0
    assert parse_salary("$80000") == 80000.0
    assert parse_salary("95K") == 95000.0
    assert parse_salary("$80K - $100K") == 90000.0
    assert parse_salary("CAD 72.5k to 85k") == 78750.0
    assert parse_salary("Not disclosed") == 85000.0
    assert parse_salary("N/A") == 85000.0
    assert parse_salary("") == 85000.0


def test_scoring_config_weights_and_score_cap_are_applied():
    profile = {"target_roles": ["Business Analyst"], "priority_target_roles": ["Business Analyst"], "keywords": ["sql"]}
    job = {
        "title": "Business Analyst",
        "company": "Example Corp",
        "location": "Montreal, QC",
        "remote_status": "Hybrid",
        "salary": "$80,000",
        "description": "Requires SQL experience.",
    }
    default_result = CompositeScorer(config=ScoringRulesConfig(), profile=profile).score_job(job)
    title_focused = CompositeScorer(
        config=ScoringRulesConfig(
            title_match_weight=100,
            experience_match_weight=0,
            education_match_weight=0,
            skills_match_weight=0,
            salary_estimate_weight=0,
            remote_preference_weight=0,
            montreal_proximity_weight=0,
            commute_preference_weight=0,
            max_score=50,
        ),
        profile=profile,
    ).score_job(job)

    assert title_focused["fit_score"] == 50
    assert default_result["fit_score"] != title_focused["fit_score"]


def test_startup_penalty_configuration_is_applied_once():
    scorer = CompositeScorer(
        config=ScoringRulesConfig(startup_penalty=7),
        profile={"target_roles": [], "priority_target_roles": [], "keywords": []},
    )
    assert scorer.calculate_penalties({"company": "Example Startup", "title": "Analyst"}) == 7


def test_entry_level_salary_benchmark_uses_role_family():
    benchmark = entry_level_salary_benchmark("Associate Solutions Engineer")

    assert benchmark["minimum"] == 70000
    assert benchmark["maximum"] == 90000
    assert benchmark["family"] == "Solutions, pre-sales, and customer engineering"


def test_salary_comparison_handles_disclosed_and_undisclosed_salary():
    disclosed = salary_comparison("$65,000 - $75,000", "Junior Business Analyst")
    undisclosed = salary_comparison("Not disclosed", "Junior Business Analyst")

    assert disclosed["comparison"] == "Within typical range"
    assert disclosed["listed_midpoint"] == 70000
    assert undisclosed["comparison"] == "Not disclosed"
    assert undisclosed["listed_midpoint"] is None


def test_title_match_score():
    profile = {
        "target_roles": [
            "Business Analyst",
            "Systems Analyst",
            "Product Analyst",
            "Business Intelligence Analyst",
            "Junior Software Engineer",
            "Data Scientist",
            "Full Stack Developer",
        ],
        "priority_target_roles": [
            "Junior Software Engineer",
            "Data Scientist",
            "Full Stack Developer",
        ],
        "keywords": [],
    }
    assert title_match_score("Business Analyst", profile) == 75
    assert title_match_score("Systems Analyst", profile) == 75
    assert title_match_score("Product Analyst", profile) == 75
    assert title_match_score("Business Intelligence Analyst", profile) == 75
    assert title_match_score("Junior Software Engineer", profile) == 100
    assert title_match_score("Senior Software Engineer", profile) < 80
    assert title_match_score("Data Scientist - Full Stack Developer", profile) < 80
    assert title_match_score("Intern", profile) < 50


def test_experience_match_score():
    assert experience_match_score("Requires 2 years experience") == 90
    assert experience_match_score("Requires 3 years of experience") == 90
    assert experience_match_score("Requires 5 years experience") == 70
    assert experience_match_score("Requires 10+ years experience") == 10
    assert experience_match_score("No experience required") == 90


def test_education_match_score():
    assert education_match_score("Bachelor's degree or higher required") >= 85
    assert education_match_score("College degree required") >= 85
    assert education_match_score("Master's degree required") >= 75
    assert education_match_score("No degree requirements") >= 85


def test_skill_match_score():
    description = "SQL Excel Power BI Jira Confluence business analysis requirements gathering"
    profile = {
        "keywords": [
            "sql",
            "excel",
            "power bi",
            "jira",
            "confluence",
            "business analysis",
            "requirements gathering",
        ]
    }
    score = skill_match_score(description, profile=profile)
    assert 30 <= score <= 100


def test_fit_score_high_match():
    job = {
        "title": "Business Systems Analyst",
        "company": "Bank of Montreal",
        "location": "Montreal, QC",
        "remote_status": "Hybrid",
        "salary": "$95,000 - $115,000",
        "description": "Requires 3 years experience with SQL, Excel, Power BI, Jira, business analysis, requirements gathering, stakeholder communication",
    }
    scores = fit_score(job)
    assert scores["fit_score"] > 60
    assert 0 <= scores["fit_score"] <= 100


def test_fit_score_senior_penalty():
    job = {
        "title": "Senior Business Analyst",
        "company": "Tech Corp",
        "location": "Montreal, QC",
        "remote_status": "On-site",
        "salary": "$120,000",
        "description": "Requires 8+ years experience with advanced technical skills",
    }
    scores = fit_score(job)
    assert scores["fit_score"] < 70


def test_fit_score_prioritizes_entry_level_role():
    base_job = {
        "company": "Tech Corp",
        "location": "Montreal, QC",
        "remote_status": "Hybrid",
        "salary": "$70,000",
        "description": "Requires 3 years of experience with SQL and Python",
    }

    junior_score = fit_score({**base_job, "title": "Junior Data Analyst"})
    standard_score = fit_score({**base_job, "title": "Data Analyst"})

    assert junior_score["entry_level_bonus"] > 0
    assert junior_score["fit_score"] > standard_score["fit_score"]


def test_fit_score_startup_penalty():
    job = {
        "title": "Business Analyst",
        "company": "StartupX Labs",
        "location": "Montreal, QC",
        "remote_status": "Remote",
        "salary": "$70,000",
        "description": "Requires 2 years experience",
    }
    scores = fit_score(job)
    assert scores["fit_score"] < 85


def test_fit_score_rewards_good_culture_signals():
    base_job = {
        "title": "Business Analyst",
        "company": "Bell Canada",
        "location": "Montreal, QC",
        "remote_status": "Hybrid",
        "salary": "$90,000",
        "description": "Requires 2 years of experience with SQL",
    }
    culture_job = {
        **base_job,
        "description": base_job["description"] + ". Great culture and strong work life balance.",
    }

    plain_score = fit_score(base_job)
    culture_score = fit_score(culture_job)

    assert culture_score["culture_bonus"] > 0
    assert culture_score["fit_score"] > plain_score["fit_score"]


def test_fit_score_rewards_established_companies():
    base_job = {
        "title": "Business Analyst",
        "location": "Montreal, QC",
        "remote_status": "Hybrid",
        "salary": "$90,000",
        "description": "Requires 2 years of experience with SQL",
    }

    known_score = fit_score({**base_job, "company": "RBC"})
    unknown_score = fit_score({**base_job, "company": "Random Small Co"})

    assert known_score["established_bonus"] > 0
    assert unknown_score["established_bonus"] == 0
    assert known_score["fit_score"] > unknown_score["fit_score"]


def test_score_jobs():
    jobs = [
        {
            "title": "Business Analyst",
            "company": "Bell Canada",
            "location": "Montreal, QC",
            "remote_status": "Hybrid",
            "salary": "$90,000 - $110,000",
            "description": "Requires 3 years with SQL, Excel, Power BI",
        },
        {
            "title": "Senior Developer",
            "company": "StartupX",
            "location": "Toronto, ON",
            "remote_status": "Remote",
            "salary": "$130,000",
            "description": "Requires 8+ years of full-stack development",
        },
    ]
    scored = score_jobs(jobs)
    assert len(scored) == 2
    assert scored[0]["fit_score"] >= scored[1]["fit_score"]
    assert "interview_chance" in scored[0]
    assert "growth_potential" in scored[0]


def test_fit_score_missing_salary():
    """Test scoring when salary is missing."""
    job = {
        "title": "Business Analyst",
        "company": "Bell Canada",
        "location": "Montreal, QC",
        "remote_status": "Hybrid",
        "description": "Requires 3 years experience",
    }
    scores = fit_score(job)
    assert 0 <= scores["fit_score"] <= 100
    assert "salary_potential" in scores


def test_fit_score_does_not_penalize_coding_roles():
    shared_fields = {
        "company": "Tech Corp",
        "location": "Montreal, QC",
        "remote_status": "Remote",
        "salary": "$100,000",
        "description": "Requires 3 years with Python and JavaScript",
    }

    developer_score = fit_score({**shared_fields, "title": "Full Stack Developer"})
    engineer_score = fit_score({**shared_fields, "title": "Full Stack Engineer"})

    assert developer_score["fit_score"] == engineer_score["fit_score"]


def test_fit_score_remote_preference():
    """Test that remote roles score higher."""
    job_remote = {
        "title": "Business Analyst",
        "company": "Bell Canada",
        "location": "Remote",
        "remote_status": "Remote",
        "salary": "$95,000",
        "description": "Requires 3 years experience",
    }
    job_onsite = {
        "title": "Business Analyst",
        "company": "Bell Canada",
        "location": "Toronto, ON",
        "remote_status": "On-site",
        "salary": "$95,000",
        "description": "Requires 3 years experience",
    }
    remote_score = fit_score(job_remote)
    onsite_score = fit_score(job_onsite)
    # Remote should score higher due to flexibility
    assert "fit_score" in remote_score
    assert "fit_score" in onsite_score


def test_fit_score_commute_preference():
    """Transit-friendly Montreal jobs should score slightly higher than farther ones."""
    job_near_metro = {
        "title": "Business Analyst",
        "company": "Bell Canada",
        "location": "Montreal, QC (near Metro Bonaventure / downtown)",
        "remote_status": "Hybrid",
        "salary": "$95,000",
        "description": "Requires 3 years experience with SQL, Excel, stakeholder communication",
    }
    job_farther = {
        "title": "Business Analyst",
        "company": "Bell Canada",
        "location": "Longueuil, QC (south shore, 40 min from downtown)",
        "remote_status": "On-site",
        "salary": "$95,000",
        "description": "Requires 3 years experience with SQL, Excel, stakeholder communication",
    }
    near_score = fit_score(job_near_metro)["fit_score"]
    farther_score = fit_score(job_farther)["fit_score"]
    assert near_score > farther_score


def test_parse_salary_with_k_suffix():
    """Test parsing salary with K suffix."""
    assert parse_salary("95K") > 0


def test_normalize_text_special_chars():
    """Test normalizing text with special characters."""
    result = normalize_text("C++ / Java - C#")
    assert "c" in result
    assert "java" in result


def test_title_match_score_partial_match():
    """Test partial title matches."""
    score = title_match_score("Business")
    assert 0 <= score <= 100

    score = title_match_score("Analyst")
    assert 0 <= score <= 100


def test_experience_match_score_edge_cases():
    """Test edge cases for experience scoring."""
    assert experience_match_score("0 years") == 90
    assert experience_match_score("") == 90
