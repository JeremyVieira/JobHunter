from jobhunter.filter import filter_jobs


def test_filter_jobs_rejects_staffing_agency_by_name():
    jobs = [
        {
            "title": "Junior Software Engineer",
            "company": "Hunter Bond",
            "fit_score": 90,
            "location": "Montreal, QC",
            "description": "Great opportunity.",
        },
        {
            "title": "Junior Software Engineer",
            "company": "mthree",
            "fit_score": 90,
            "location": "Montreal, QC",
            "description": "Great opportunity.",
        },
        {
            "title": "Junior Software Engineer",
            "company": "Shopify",
            "fit_score": 90,
            "location": "Montreal, QC",
            "description": "Great opportunity.",
        },
    ]
    filtered = filter_jobs(jobs)
    assert len(filtered) == 1
    assert filtered[0]["company"] == "Shopify"


def test_filter_jobs_rejects_confidential_client_postings():
    jobs = [
        {
            "title": "Junior Software Engineer",
            "company": "Acme Recruiting",
            "fit_score": 90,
            "location": "Montreal, QC",
            "description": "On behalf of our client, we are hiring a junior engineer.",
        },
    ]
    filtered = filter_jobs(jobs)
    assert len(filtered) == 0


def test_filter_jobs_rejects_tiny_or_stealth_companies():
    jobs = [
        {
            "title": "Junior Software Engineer",
            "company": "StealthCo",
            "fit_score": 90,
            "location": "Montreal, QC",
            "description": "We are a stealth startup, 1-10 employees, pre-seed funding.",
        },
    ]
    filtered = filter_jobs(jobs)
    assert len(filtered) == 0


def test_filter_jobs_keeps_target_roles_and_high_fit_scores():
    jobs = [
        {
            "title": "Business Systems Analyst",
            "company": "Bank of Montreal",
            "fit_score": 92,
            "location": "Montreal, QC",
        },
        {
            "title": "Senior Software Engineer",
            "company": "StartupX",
            "fit_score": 30,
            "location": "Montreal, QC",
        },
        {"title": "Project Manager", "company": "ACME", "fit_score": 70, "location": "Toronto, ON"},
        {
            "title": "Business Analyst",
            "company": "Bell",
            "fit_score": 88,
            "location": "Montreal, QC",
        },
    ]

    filtered = filter_jobs(jobs)

    assert [job["title"] for job in filtered] == ["Business Systems Analyst", "Business Analyst"]


def test_filter_jobs_removes_low_fit_scores():
    """Test that jobs with fit score < 60 are removed."""
    jobs = [
        {
            "title": "Business Analyst",
            "company": "Company A",
            "fit_score": 50,
            "location": "Montreal, QC",
            "description": "Remote role",
        },
        {
            "title": "Business Analyst",
            "company": "Company B",
            "fit_score": 75,
            "location": "Montreal, QC",
            "description": "Hybrid role",
        },
    ]
    filtered = filter_jobs(jobs)
    assert len(filtered) == 1
    assert filtered[0]["company"] == "Company B"


def test_filter_jobs_accepts_entry_level_role_at_entry_threshold():
    jobs = [
        {
            "title": "Junior Business Analyst",
            "company": "Company A",
            "fit_score": 56,
            "location": "Montreal, QC",
            "description": "Entry level hybrid role",
        },
        {
            "title": "Business Analyst",
            "company": "Company B",
            "fit_score": 56,
            "location": "Montreal, QC",
            "description": "Hybrid role",
        },
    ]

    filtered = filter_jobs(jobs)

    assert [job["company"] for job in filtered] == ["Company A"]


def test_filter_jobs_removes_wrong_location():
    """Test that non-Montreal jobs are filtered out."""
    jobs = [
        {
            "title": "Business Analyst",
            "company": "Company A",
            "fit_score": 85,
            "location": "Toronto, ON",
            "description": "On-site",
        },
        {
            "title": "Business Analyst",
            "company": "Company B",
            "fit_score": 85,
            "location": "Montreal, QC",
            "description": "Hybrid",
        },
    ]
    filtered = filter_jobs(jobs)
    assert len(filtered) == 1
    assert filtered[0]["company"] == "Company B"


def test_filter_jobs_accepts_remote_roles():
    """Test that remote roles are accepted."""
    jobs = [
        {
            "title": "Business Analyst",
            "company": "Company A",
            "fit_score": 75,
            "location": "Remote",
            "description": "Remote role",
        },
    ]
    filtered = filter_jobs(jobs)
    assert len(filtered) == 1


def test_filter_jobs_accepts_remote_outside_region_but_rejects_hybrid_outside_region():
    jobs = [
        {
            "title": "Business Analyst",
            "company": "Remote Co",
            "fit_score": 75,
            "location": "Toronto, ON",
            "remote_status": "Remote",
            "description": "Fully remote role open across Canada.",
        },
        {
            "title": "Business Analyst",
            "company": "Hybrid Co",
            "fit_score": 75,
            "location": "Toronto, ON",
            "remote_status": "Hybrid",
            "description": "Hybrid, three days in the Toronto office.",
        },
    ]

    filtered = filter_jobs(jobs)

    assert [job["company"] for job in filtered] == ["Remote Co"]


def test_filter_jobs_accepts_accented_montreal_and_qc_abbreviation():
    jobs = [
        {
            "title": "Business Analyst",
            "company": "Company A",
            "fit_score": 75,
            "location": "Montréal, QC, CA",
            "description": "On-site",
        },
    ]

    filtered = filter_jobs(jobs)

    assert len(filtered) == 1
    assert filtered[0]["location"] == "Montréal, QC, CA"


def test_filter_jobs_removes_bad_role_titles():
    """Test that penalized role titles are filtered out."""
    jobs = [
        {
            "title": "Senior Software Engineer",
            "company": "Company A",
            "fit_score": 85,
            "location": "Montreal, QC",
            "description": "Senior dev role",
        },
        {
            "title": "Business Analyst",
            "company": "Company B",
            "fit_score": 85,
            "location": "Montreal, QC",
            "description": "BA role",
        },
        {
            "title": "Technical Project Coordinator",
            "company": "Company C",
            "fit_score": 85,
            "location": "Montreal, QC",
            "description": "Technical delivery role",
        },
        {
            "title": "Senior Business Analyst",
            "company": "Company D",
            "fit_score": 90,
            "location": "Montreal, QC",
            "description": "Senior analysis role",
        },
        {
            "title": "Sr Customer Success Engineer - Bilingual French",
            "company": "Company E",
            "fit_score": 90,
            "location": "Montreal, QC",
            "description": "Senior customer engineering role",
        },
        {
            "title": "Director of Data Analytics",
            "company": "Company F",
            "fit_score": 95,
            "location": "Montreal, QC",
            "description": "Data leadership role",
        },
    ]
    filtered = filter_jobs(jobs)
    assert len(filtered) == 1
    assert "Business Analyst" in filtered[0]["title"]


def test_filter_jobs_accepts_entry_level_software_engineering_roles():
    jobs = [
        {
            "title": "Junior Full Stack Developer",
            "company": "Company A",
            "fit_score": 70,
            "location": "Montreal, QC",
            "description": "Entry-level software development role",
        },
        {
            "title": "Senior Full Stack Developer",
            "company": "Company B",
            "fit_score": 85,
            "location": "Montreal, QC",
            "description": "Senior software development role",
        },
    ]

    filtered = filter_jobs(jobs)

    assert [job["title"] for job in filtered] == ["Junior Full Stack Developer"]


def test_filter_jobs_returns_sorted():
    """Test that filtered jobs are sorted by fit score descending."""
    jobs = [
        {
            "title": "Business Analyst",
            "company": "Company A",
            "fit_score": 70,
            "location": "Montreal, QC",
            "description": "Hybrid",
        },
        {
            "title": "Systems Analyst",
            "company": "Company B",
            "fit_score": 90,
            "location": "Montreal, QC",
            "description": "Remote",
        },
        {
            "title": "Product Analyst",
            "company": "Company C",
            "fit_score": 75,
            "location": "Montreal, QC",
            "description": "Hybrid",
        },
    ]
    filtered = filter_jobs(jobs)
    fit_scores = [job["fit_score"] for job in filtered]
    assert fit_scores == sorted(fit_scores, reverse=True)


def test_filter_jobs_accepts_target_roles():
    """Test that target roles are accepted."""
    target_roles = [
        "Business Analyst",
        "Systems Analyst",
        "Product Analyst",
        "Data Analyst",
        "Business Intelligence Analyst",
        "IT Business Analyst",
    ]

    for role in target_roles:
        jobs = [
            {
                "title": role,
                "company": "Company",
                "fit_score": 75,
                "location": "Montreal, QC",
                "description": "Hybrid",
            },
        ]
        filtered = filter_jobs(jobs)
        assert len(filtered) == 1, f"Role '{role}' should be accepted"
