"""Regression tests for the matching upgrade: whole-word matching, gap penalties, feedback."""

from datetime import date, timedelta

from jobhunter.models import UserProfile
from jobhunter.scoring.engine import (
    CompositeScorer,
    score_jobs,
    skill_match_score,
    title_match_score,
)
from jobhunter.scoring.feedback import FeedbackModel

PROFILE = UserProfile(
    target_roles=["Software Developer", "Business Analyst"],
    priority_target_roles=["Software Developer"],
    keywords=["python", "sql", "docker", "git", "ci/cd", "scikit-learn", "excel"],
    experience_years=1,
    languages=["en", "fr"],
)


def _score(job, **overrides):
    base = {
        "title": "Software Developer",
        "company": "Example Co",
        "location": "Montreal, QC",
        "remote_status": "Hybrid",
        "salary": "Not disclosed",
        "description": "Python and SQL developer role.",
        "posting_date": "Unknown",
    }
    base.update(job)
    return CompositeScorer(profile=PROFILE).score_job({**base, **overrides})


def test_skill_keywords_with_punctuation_now_count():
    score = skill_match_score("Experience with CI/CD and scikit-learn.", PROFILE)
    nothing = skill_match_score("Experience with cooking and sewing.", PROFILE)
    assert score > nothing


def test_excellent_does_not_count_as_excel_and_digital_not_git():
    unrelated = skill_match_score("Excellent communication in digital marketing.", PROFILE)
    assert unrelated == 35  # no recognizable skills at all -> "no evidence"


def test_established_company_bonus_uses_whole_words():
    scorer = CompositeScorer(profile=PROFILE)
    assert scorer.calculate_established_bonus({"company": "Honeywell"}) == 0
    assert scorer.calculate_established_bonus({"company": "Disney"}) == 0
    assert scorer.calculate_established_bonus({"company": "EY"}) > 0
    assert scorer.calculate_established_bonus({"company": "Desjardins"}) > 0


def test_international_is_not_an_intern_and_bilingual_is_not_bi():
    profile = {
        "target_roles": ["Business Analyst"],
        "priority_target_roles": ["Business Analyst"],
        "keywords": [],
    }
    assert title_match_score("International Business Analyst", profile) == 100
    assert title_match_score("Bilingual Customer Service Representative", profile) == 0


def test_associate_product_manager_is_not_dropped_as_management():
    jobs = [{"title": "Associate Product Manager", "company": "Acme", "description": "Python SQL"}]
    assert len(score_jobs(jobs)) == 1
    assert score_jobs([{"title": "Product Manager", "company": "Acme", "description": "x"}]) == []


def test_core_stack_gap_costs_points_and_is_reported():
    covered = _score({"title": "Python Developer", "description": "Requirements: Python and SQL."})
    gap = _score(
        {"title": "Java Developer", "description": "Requirements: Java, Spring Boot and SQL."}
    )
    assert gap["fit_score"] < covered["fit_score"]
    assert "Java" in gap["match_details"]["skills"]["core_gaps"]
    assert gap["match_details"]["adjustments"]["core_skill_gaps"] > 0


def test_match_details_explain_the_score():
    result = _score(
        {
            "description": "Requirements: Python, SQL and Kubernetes. Nice to have: Docker. 2 years experience."
        }
    )
    details = result["match_details"]
    assert "Python" in details["skills"]["matched"]
    assert "Kubernetes" in details["skills"]["missing_required"]
    assert details["years_required"] == 2


def test_bilingual_posting_gets_bonus_only_for_bilingual_candidates():
    description = "Python developer. Bilingual English and French required."
    bilingual = _score({"description": description})
    english_only = CompositeScorer(
        profile=UserProfile(**{**PROFILE.to_dict(), "languages": ["en"]})
    ).score_job(
        {
            "title": "Software Developer",
            "company": "Example Co",
            "location": "Montreal, QC",
            "description": description,
        }
    )
    assert bilingual["match_details"]["adjustments"]["bilingual"] > 0
    assert english_only["match_details"]["adjustments"]["bilingual"] == 0


def test_french_posting_is_penalized_for_non_french_speakers():
    description = (
        "Nous recherchons un développeur avec de l'expérience pour notre équipe. "
        "Vous allez travailler avec nous sur des projets pour nos clients dans la région."
    )
    english_only = UserProfile(**{**PROFILE.to_dict(), "languages": ["en"]})
    result = CompositeScorer(profile=english_only).score_job(
        {
            "title": "Développeur",
            "company": "Acme",
            "location": "Montreal, QC",
            "description": description,
        }
    )
    assert result["match_details"]["adjustments"]["language_mismatch"] > 0


def test_freshness_bonus_and_stale_penalty():
    fresh = _score({"posting_date": (date.today() - timedelta(days=1)).isoformat()})
    stale = _score({"posting_date": (date.today() - timedelta(days=90)).isoformat()})
    unknown = _score({"posting_date": "Unknown"})
    assert fresh["match_details"]["adjustments"]["freshness"] > 0
    assert stale["match_details"]["adjustments"]["freshness"] < 0
    assert unknown["match_details"]["adjustments"]["freshness"] == 0


def test_scores_spread_good_and_poor_matches_apart():
    good = _score({"description": "Requirements: Python, SQL, Docker, Git. 1 year experience."})
    poor = _score(
        {
            "title": "Operations Analyst",
            "description": "Requirements: SAP, Salesforce, Oracle and 4 years experience.",
        }
    )
    assert good["fit_score"] - poor["fit_score"] >= 25


# ---- preference feedback ---------------------------------------------------
def _examples(titles, company="Co"):
    return [{"title": title, "company": company} for title in titles]


def test_feedback_model_is_inactive_without_enough_examples():
    model = FeedbackModel(_examples(["Python Developer"] * 3), _examples(["Sales Rep"] * 3))
    assert not model.active
    assert model.adjust({"title": "Sales Rep", "company": "Co"}) == 0.0


def test_feedback_model_pushes_dismissed_patterns_down_and_applied_up():
    liked = _examples(["Python Developer", "Software Developer", "Backend Developer"] * 8, "GoodCo")
    disliked = _examples(
        ["Sales Representative", "Account Executive", "Sales Manager"] * 8, "BadCo"
    )
    model = FeedbackModel(liked, disliked)
    assert model.active
    assert model.adjust({"title": "Sales Representative", "company": "BadCo"}) < -2
    assert model.adjust({"title": "Python Developer", "company": "GoodCo"}) > 2
    assert (
        abs(model.adjust({"title": "Python Developer", "company": "GoodCo"}))
        <= model.max_adjustment
    )
    assert model.adjust({"title": "Zebra Wrangler", "company": "Unseen"}) == 0.0


def test_scorer_applies_feedback_adjustment():
    model = FeedbackModel(
        _examples(["Python Developer"] * 20, "GoodCo"),
        _examples(["Software Developer"] * 20, "BadCo"),
    )
    job = {
        "title": "Software Developer",
        "company": "BadCo",
        "location": "Montreal, QC",
        "description": "Python SQL",
    }
    plain = CompositeScorer(profile=PROFILE).score_job(job)
    nudged = CompositeScorer(profile=PROFILE, feedback=model).score_job(job)
    assert nudged["fit_score"] < plain["fit_score"]
    assert nudged["match_details"]["adjustments"]["preference_feedback"] < 0
