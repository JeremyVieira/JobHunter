"""Whole-word matching, skill extraction, requirement analysis and seniority detection."""

from datetime import date

import pytest

from jobhunter.matching.levels import is_entry_level
from jobhunter.matching.requirements import (
    analyze_posting,
    candidate_inventory,
    closest_related,
    compare_requirements,
    extract_required_years,
    skill_score_from_match,
)
from jobhunter.matching.skills import get_matcher, skill_text
from jobhunter.textutils import (
    contains_term,
    detect_language,
    html_to_text,
    mentions_bilingual,
    normalize_salary,
    normalize_text,
    parse_posting_date,
)


# ---- textutils -------------------------------------------------------------
def test_contains_term_is_whole_word_and_punctuation_tolerant():
    text = normalize_text("Excellent communication, CI/CD pipelines and scikit-learn.")
    assert not contains_term(text, "excel")  # "Excellent" must not match
    assert contains_term(text, "ci/cd")  # normalized both sides
    assert contains_term(text, "scikit-learn")
    assert not contains_term(normalize_text("digital transformation"), "git")


def test_detect_language_and_bilingual_mentions():
    assert (
        detect_language(
            "Nous recherchons un développeur avec de l'expérience pour notre équipe et vous allez travailler avec nous."
        )
        == "fr"
    )
    assert (
        detect_language(
            "We are looking for a developer with strong experience to join our team and work with you."
        )
        == "en"
    )
    assert detect_language("ok") == "unknown"
    assert mentions_bilingual("Bilingual (English and French) required")
    assert mentions_bilingual("Poste bilingue")
    assert not mentions_bilingual("Fluent English only")


def test_parse_posting_date_handles_iso_and_relative_phrases():
    today = date(2026, 10, 30)
    assert parse_posting_date("2026-10-20T08:00:00Z", today) == date(2026, 10, 20)
    assert parse_posting_date("Posted 3 Days Ago", today) == date(2026, 10, 27)
    assert parse_posting_date("Posted Yesterday", today) == date(2026, 10, 29)
    assert parse_posting_date("Posted Today", today) == today
    assert parse_posting_date("Unknown", today) is None


def test_normalize_salary_canonicalizes_ranges_and_units():
    assert normalize_salary("$70,000 - $85,000") == "$70,000 - $85,000 CAD/yr"
    assert normalize_salary("$70,000 - $85,000 CAD/yr") == "$70,000 - $85,000 CAD/yr"
    assert normalize_salary("95K") == "$95,000 CAD/yr"
    assert normalize_salary("$80K - $100K") == "$80,000 - $100,000 CAD/yr"
    assert normalize_salary("85k-95k") == "$85,000 - $95,000 CAD/yr"
    assert normalize_salary("$30/hr") == "$30 CAD/hr"
    assert normalize_salary("25 - 35 $ per hour") == "$25 - $35 CAD/hr"
    assert normalize_salary("USD 100,000") == "$100,000 USD/yr"
    assert normalize_salary("Not disclosed") == "Not disclosed"
    assert normalize_salary("") == "Not disclosed"
    assert normalize_salary("Competitive") == "Not disclosed"


def test_html_to_text_collapses_markup_and_whitespace():
    raw = "<p>Hello <b>world</b></p>\n\n**bold**  `code`\n\n   lots   of   space"
    assert html_to_text(raw) == "Hello world bold code lots of space"


# ---- skills ----------------------------------------------------------------
def test_skill_extraction_keeps_symbols_and_avoids_substring_hits():
    found = get_matcher().extract(
        "C++/C# and .NET with Node.js, CI/CD, scikit-learn and PyTorch. "
        "Excellent skills in digital transformation. Java or JavaScript."
    )
    assert {
        "c++",
        "c#",
        ".net",
        "node.js",
        "ci/cd",
        "scikit-learn",
        "pytorch",
        "java",
        "javascript",
    } <= set(found)
    assert "excel" not in found and "git" not in found


def test_common_english_words_are_not_skills():
    found = get_matcher().extract(
        "We express interest this spring with a swift response; spark joy."
    )
    assert found == {}


def test_french_elisions_and_tableau_de_bord_are_not_skills():
    found = get_matcher().extract("J'ai conçu un tableau de bord. Je n'ai pas utilisé Tableau.")
    assert "artificial intelligence" not in found
    assert "tableau" in found  # the software, mentioned once explicitly
    assert found["tableau"] == 1
    assert "data visualization" in found  # the French "tableau de bord" is a dashboard


def test_skill_text_preserves_special_tokens():
    assert skill_text("Python. node.js, .NET, ci/cd") == "python node.js .net ci/cd"


def test_custom_profile_terms_are_matchable():
    matcher = get_matcher(("customer empathy",))
    assert "customer empathy" in matcher.extract("We value customer empathy daily.")


# ---- requirements ----------------------------------------------------------
@pytest.mark.parametrize(
    "text, expected",
    [
        ("Requires 2 years experience", 2),
        ("3-5 years of experience in Java", 3),
        ("Minimum 4 ans d'expérience", 4),
        ("No experience required", 0),
        ("With over 20 years we serve clients", None),
        ("1-2 years experience; 5+ years leadership experience", 5),
        ("Great team", None),
    ],
)
def test_extract_required_years(text, expected):
    assert extract_required_years(text) == expected


def test_analyze_posting_separates_required_from_preferred():
    posting = """About us
We build things.

Requirements:
- 3+ years Java and Spring Boot
- SQL and Docker
Nice to have:
- Kubernetes, Python"""
    requirements = analyze_posting("Java Developer", posting)
    assert requirements.skills["java"].level == "required" and requirements.skills["java"].in_title
    assert requirements.skills["sql"].level == "required"
    assert requirements.skills["kubernetes"].level == "preferred"
    assert requirements.skills["python"].level == "preferred"
    assert requirements.years_required == 3


def test_compare_requirements_flags_core_gaps_and_scores_coverage():
    requirements = analyze_posting("Java Developer", "Requirements: Java, SQL and Docker.")
    inventory = candidate_inventory(["python", "sql", "docker"])
    match = compare_requirements(requirements, inventory)
    assert match.core_gaps == ["java"]  # hard-stack skill named in the title and missing
    assert "sql" in match.matched and "docker" in match.matched
    assert 0 < skill_score_from_match(match) < 100


def test_skill_score_is_neutral_low_without_evidence_and_shrinks_on_thin_evidence():
    empty = compare_requirements(analyze_posting("Associate", "A fine place to work."), set())
    assert skill_score_from_match(empty) == 35.0
    thin = compare_requirements(analyze_posting("Dev", "Requirements: SQL."), {"sql"})
    assert skill_score_from_match(thin) < 100  # one skill is not proof of a perfect match


def test_inventory_implies_cloud_and_sql_from_specific_tools():
    inventory = candidate_inventory(["gcp", "sqlite"])
    assert {"cloud", "sql"} <= inventory


def test_closest_related_only_returns_skills_the_candidate_has():
    assert closest_related("aws", {"gcp"}) == "gcp"
    assert closest_related("aws", {"python"}) is None


# ---- levels ----------------------------------------------------------------
def test_entry_level_detection():
    assert is_entry_level({"title": "Junior Developer", "description": ""})
    assert is_entry_level({"title": "Developer", "description": "Recent graduates welcome"})
    assert is_entry_level({"title": "Developer", "description": "1 year of experience"})
    # an incidental "1 year" must not count
    assert not is_entry_level(
        {
            "title": "Developer",
            "description": "Pays a bonus after 1 year at the company; 4 years experience required.",
        }
    )
