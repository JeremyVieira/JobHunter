"""Offline tests for ATS adapters, board APIs, detection, de-duplication and enrichment.

Payloads mirror each vendor's documented public response shape; no network is used.
"""

import json

import pytest

from jobhunter.scraper import ats, boards, collector, discover, enrich
from jobhunter.scraper.dedupe import dedupe_jobs

JSONLD_PAGE = """<html><head><script type="application/ld+json">
{"@type":"JobPosting","title":"%s","datePosted":"2026-10-28","url":"%s",
 "jobLocation":{"address":{"addressLocality":"Montreal","addressRegion":"QC"}},
 "description":"<p>%s</p>"}
</script></head></html>"""


class FakeResponse:
    def __init__(self, payload=None, text=""):
        self._payload = payload
        self.text = text or (json.dumps(payload) if payload is not None else "")

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def router(routes):
    """Return a fake request function that serves ``routes`` by URL substring."""
    calls = []

    def fake(url, **kwargs):
        calls.append((url, kwargs))
        for needle, payload in routes.items():
            if needle in url:
                return FakeResponse(payload() if callable(payload) else payload)
        raise AssertionError(f"unexpected request: {url}")

    fake.calls = calls
    return fake


# ---- Ashby -----------------------------------------------------------------
def test_ashby_scraper_maps_posting_api(monkeypatch):
    payload = {"jobs": [
        {"id": "1", "title": "Software Developer", "location": "Toronto", "isRemote": False,
         "secondaryLocations": [{"location": "Montréal, QC"}],
         "descriptionPlain": "Build services with Python and SQL.", "publishedAt": "2026-10-27T10:00:00Z",
         "jobUrl": "https://jobs.ashbyhq.com/acme/1",
         "compensation": {"compensationTierSummary": "$90K – $110K"}},
        {"id": "2", "title": "Hidden", "isListed": False, "jobUrl": "https://jobs.ashbyhq.com/acme/2"},
    ]}
    monkeypatch.setattr(ats, "_request_get", router({"api.ashbyhq.com/posting-api/job-board/acme": payload}))
    jobs = ats.AshbyScraper(companies=[("Acme", "acme")]).scrape()
    assert len(jobs) == 1
    job = jobs[0]
    assert job["location"] == "Montréal, QC"  # the Montreal office wins over the primary location
    assert job["salary"] == "$90K – $110K" and job["posting_date"] == "2026-10-27"
    assert job["source"] == "ashby" and job["company"] == "Acme"


# ---- Workable --------------------------------------------------------------
def test_workable_scraper_maps_widget_api(monkeypatch):
    payload = {"name": "Acme Inc", "jobs": [
        {"title": "Data Analyst", "city": "Montreal", "state": "Quebec", "country": "Canada",
         "telecommuting": False, "description": "<p>SQL and Excel</p>", "published_on": "2026-10-20",
         "url": "https://apply.workable.com/acme/j/ABC/"},
        {"title": "Support Agent", "telecommuting": True, "description": "x", "created_at": "2026-10-01",
         "shortlink": "https://apply.workable.com/j/DEF"},
    ]}
    monkeypatch.setattr(ats, "_request_get", router({"widget/accounts/acme": payload}))
    jobs = ats.WorkableScraper(companies=[("Acme", "acme")]).scrape()
    assert jobs[0]["location"] == "Montreal, Quebec, Canada" and jobs[0]["description"] == "SQL and Excel"
    assert jobs[0]["company"] == "Acme Inc"
    assert jobs[1]["location"] == "Remote" and jobs[1]["remote_status"] == "Remote"


# ---- SmartRecruiters -------------------------------------------------------
def test_smartrecruiters_fetches_detail_only_for_plausible_local_titles(monkeypatch):
    listing = {"totalFound": 3, "content": [
        {"id": "p1", "name": "Software Developer", "releasedDate": "2026-10-25T00:00:00Z",
         "location": {"city": "Montreal", "region": "QC", "country": "ca", "remote": False},
         "company": {"name": "Acme"}},
        {"id": "p2", "name": "Warehouse Associate", "location": {"city": "Montreal", "country": "ca"}},
        {"id": "p3", "name": "Software Developer", "location": {"city": "Calgary", "region": "AB", "country": "ca"}},
    ]}
    detail = {"postingUrl": "https://jobs.smartrecruiters.com/Acme/p1",
              "jobAd": {"sections": {"jobDescription": {"text": "<p>Python APIs</p>"},
                                      "qualifications": {"text": "<p>SQL</p>"}}}}
    fake = router({"/postings/p1": detail, "/postings": listing})
    monkeypatch.setattr(ats, "_request_get", fake)
    jobs = ats.SmartRecruitersScraper(companies=[("Acme", "Acme")]).scrape()
    assert [j["title"] for j in jobs] == ["Software Developer"]
    assert "Python APIs" in jobs[0]["description"] and "SQL" in jobs[0]["description"]
    fetched = [url for url, _ in fake.calls]
    assert not any("/p2" in u or "/p3" in u for u in fetched)  # filtered out before the detail call


# ---- Recruitee -------------------------------------------------------------
def test_recruitee_scraper_combines_description_and_requirements(monkeypatch):
    payload = {"offers": [{"title": "QA Analyst", "careers_url": "https://acme.recruitee.com/o/qa", "location": "Montréal",
                           "remote": False, "description": "<p>Test things</p>", "requirements": "<p>Selenium</p>",
                           "created_at": "2026-10-22 10:00:00 UTC"}]}
    monkeypatch.setattr(ats, "_request_get", router({"acme.recruitee.com/api/offers": payload}))
    job = ats.RecruiteeScraper(companies=[("Acme", "acme")]).scrape()[0]
    assert "Test things" in job["description"] and "Selenium" in job["description"]
    assert job["url"] == "https://acme.recruitee.com/o/qa"


# ---- Workday ---------------------------------------------------------------
def test_workday_searches_then_fetches_detail_for_local_matching_titles(monkeypatch):
    search = {"jobPostings": [
        {"title": "Software Developer", "externalPath": "/job/Montreal/Software-Developer_R1", "locationsText": "Montreal, Quebec", "postedOn": "Posted 3 Days Ago"},
        {"title": "Software Developer", "externalPath": "/job/Austin/Software-Developer_R2", "locationsText": "Austin, Texas"},
        {"title": "Branch Manager", "externalPath": "/job/Montreal/Manager_R3", "locationsText": "Montreal, Quebec"},
    ]}
    detail = {"jobPostingInfo": {"title": "Software Developer", "location": "Montreal, Quebec",
                                 "jobDescription": "<p>Python and CI/CD</p>", "startDate": "2026-10-27",
                                 "externalUrl": "https://acme.wd3.myworkdayjobs.com/en-US/Careers/job/Montreal/Software-Developer_R1"}}
    posts = router({"/wday/cxs/acme/Careers/jobs": search})
    gets = router({"/wday/cxs/acme/Careers/job/Montreal/Software-Developer_R1": detail})
    monkeypatch.setattr(ats, "_request_post", posts)
    monkeypatch.setattr(ats, "_request_get", gets)
    scraper = ats.WorkdayScraper(companies=[("Acme", "acme", "wd3", "Careers")], search_terms=["software"])
    jobs = scraper.scrape()
    assert len(jobs) == 1
    assert jobs[0]["posting_date"] == "2026-10-27" and "CI/CD" in jobs[0]["description"]
    assert jobs[0]["url"].endswith("Software-Developer_R1")
    assert posts.calls[0][1]["json"]["searchText"] == "software"
    assert len(gets.calls) == 1  # Austin and Manager never cost a detail request


def test_workday_relative_posted_date_is_parsed_when_detail_is_missing(monkeypatch):
    search = {"jobPostings": [{"title": "Data Analyst", "externalPath": "/job/x_R9", "locationsText": "2 Locations", "postedOn": "Posted Yesterday"}]}
    monkeypatch.setattr(ats, "_request_post", router({"/jobs": search}))

    def failing_get(url, **kwargs):
        raise RuntimeError("detail unavailable")

    monkeypatch.setattr(ats, "_request_get", failing_get)
    job = ats.WorkdayScraper(companies=[("Acme", "acme", "wd3", "Careers")], search_terms=["data"]).scrape()[0]
    assert job["posting_date"] != "Unknown" and job["url"].endswith("/Careers/job/x_R9")


# ---- failure isolation -----------------------------------------------------
def test_one_failing_company_does_not_stop_the_others(monkeypatch):
    def fake(url, **kwargs):
        if "bad" in url:
            raise RuntimeError("404")
        return FakeResponse({"jobs": [{"title": "Developer", "location": "Montreal", "jobUrl": "https://jobs.ashbyhq.com/good/1", "descriptionPlain": "x"}]})

    monkeypatch.setattr(ats, "_request_get", fake)
    jobs = ats.AshbyScraper(companies=[("Bad", "bad"), ("Good", "good")]).scrape()
    assert [j["company"] for j in jobs] == ["Good"]


# ---- detection -------------------------------------------------------------
def test_detect_ats_finds_boards_in_links_iframes_and_scripts():
    html = """
    <a href="https://boards.greenhouse.io/acme">Jobs</a>
    <script src="https://boards.greenhouse.io/embed/job_board/js?for=widgetco"></script>
    <iframe src="https://jobs.lever.co/leverco"></iframe>
    <a href="https://jobs.ashbyhq.com/ashbyco">x</a>
    <a href="https://apply.workable.com/workableco/">x</a>
    <a href="https://careers.smartrecruiters.com/SmartCo">x</a>
    <a href="https://recruiteeco.recruitee.com/">x</a>
    <a href="https://bigbank.wd3.myworkdayjobs.com/en-US/BankCareers">x</a>
    """
    found = {(d["ats"], d["key"]) for d in ats.detect_ats(html, "https://example.com/careers")}
    assert found == {
        ("greenhouse", "acme"), ("greenhouse", "widgetco"), ("lever", "leverco"), ("ashby", "ashbyco"),
        ("workable", "workableco"), ("smartrecruiters", "SmartCo"), ("recruitee", "recruiteeco"),
        ("workday", "bigbank|wd3|BankCareers"),
    }


def test_detect_ats_ignores_reserved_words_and_works_from_the_url_alone():
    assert ats.detect_ats('<a href="https://boards.greenhouse.io/embed/">x</a>') == []
    assert ats.detection_from_url("https://jobs.lever.co/acme.")[0]["key"] == "acme"


def test_scrapers_for_detections_builds_one_scraper_per_board():
    detections = ats.detect_ats("https://jobs.lever.co/a https://jobs.ashbyhq.com/b https://c.wd3.myworkdayjobs.com/Careers")
    kinds = {type(s).__name__ for s in ats.scrapers_for_detections("Co", detections)}
    assert kinds == {"LeverScraper", "AshbyScraper", "WorkdayScraper"}


def test_career_page_scraper_delegates_to_a_detected_ats(monkeypatch):
    page = '<html><a href="https://jobs.lever.co/acme">Open roles</a></html>'
    monkeypatch.setattr(collector, "_request_get", lambda url, **kw: FakeResponse(text=page))
    monkeypatch.setattr(
        collector.LeverScraper, "scrape",
        lambda self: [collector.normalize_job({"title": "Developer", "company": self.companies[0][0], "url": "https://jobs.lever.co/acme/1", "source": "lever"})],
    )
    scraper = collector.CompanyCareerPageScraper(pages=[("Acme", "https://acme.com/careers")])
    jobs = scraper.scrape()
    assert [j["source"] for j in jobs] == ["lever"]
    assert scraper.detected_boards == [("Acme", "lever", "acme")]


def test_career_page_scraper_follows_job_links_and_reads_their_jsonld(monkeypatch):
    listing = """<html>
      <a href="/careers/jobs/dev-1">Developer</a><a href="/careers/jobs/dev-2">Analyst</a>
      <a href="/about">About</a><a href="https://other.com/jobs/x">Elsewhere</a></html>"""
    pages = {
        "https://acme.com/careers": listing,
        "https://acme.com/careers/jobs/dev-1": JSONLD_PAGE % ("Developer", "https://acme.com/careers/jobs/dev-1", "Python"),
        "https://acme.com/careers/jobs/dev-2": JSONLD_PAGE % ("Analyst", "https://acme.com/careers/jobs/dev-2", "SQL"),
    }
    requested = []

    def fake_get(url, **kwargs):
        requested.append(url)
        return FakeResponse(text=pages[url])

    monkeypatch.setattr(collector, "_request_get", fake_get)
    jobs = collector.CompanyCareerPageScraper(pages=[("Acme", "https://acme.com/careers")], max_detail_pages=5).scrape()
    assert sorted(j["title"] for j in jobs) == ["Analyst", "Developer"]
    assert "https://acme.com/about" not in requested and "https://other.com/jobs/x" not in requested


# ---- boards ----------------------------------------------------------------
def test_the_muse_scraper_prefers_the_montreal_location(monkeypatch):
    payload = {"page_count": 1, "results": [{
        "name": "Junior Developer", "company": {"name": "MuseCo"}, "contents": "<p>Python</p>",
        "locations": [{"name": "New York, NY"}, {"name": "Montreal, Canada"}], "publication_date": "2026-10-26T00:00:00Z",
        "refs": {"landing_page": "https://www.themuse.com/jobs/museco/junior-developer"}}]}
    fake = router({"themuse.com/api/public/jobs": payload})
    monkeypatch.setattr(boards, "_request_get", fake)
    jobs = boards.TheMuseScraper().scrape()
    assert jobs[0]["location"] == "Montreal, Canada" and jobs[0]["source"] == "themuse"
    assert ("location", "Montreal, Canada") in fake.calls[0][1]["params"]
    assert boards.TheMuseScraper(enabled=False).scrape() == []


def test_keyed_aggregators_are_skipped_without_keys():
    assert boards.AdzunaScraper(app_id="", app_key="").scrape() == []
    assert boards.JoobleScraper(api_key="").scrape() == []


def test_adzuna_maps_results_and_salary(monkeypatch):
    payload = {"results": [{"title": "Developer", "company": {"display_name": "Acme"}, "location": {"display_name": "Montréal, Québec"},
                            "description": "Snippet about Python", "created": "2026-10-29T08:00:00Z",
                            "redirect_url": "https://www.adzuna.ca/land/ad/1", "salary_min": 70000, "salary_max": 90000}]}
    monkeypatch.setattr(boards, "_request_get", router({"api.adzuna.com": payload}))
    job = boards.AdzunaScraper(app_id="id", app_key="key", search_terms=["developer"]).scrape()[0]
    assert job["salary"] == "$70,000 - $90,000" and job["location"] == "Montréal, Québec"


def test_jooble_posts_keywords_and_maps_results(monkeypatch):
    payload = {"jobs": [{"title": "Analyst", "company": "Acme", "location": "Montreal", "snippet": "<b>SQL</b>", "link": "https://jooble.org/j/1", "updated": "2026-10-28T00:00:00"}]}
    fake = router({"jooble.org/api/KEY": payload})
    monkeypatch.setattr(boards, "_request_post", fake)
    job = boards.JoobleScraper(api_key="KEY", search_terms=["analyst"], location="Montreal, QC").scrape()[0]
    assert job["description"] == "SQL" and fake.calls[0][1]["json"]["keywords"] == "analyst"


def test_rss_feed_parsing_handles_rss_and_atom():
    rss = """<rss><channel><item><title>Dev</title><link>https://x/1</link><description>&lt;p&gt;Python&lt;/p&gt;</description>
             <pubDate>Mon, 26 Oct 2026 10:00:00 GMT</pubDate><location>Montreal</location></item></channel></rss>"""
    atom = """<feed><entry><title>Analyst</title><link href="https://x/2"/><summary>SQL</summary><updated>2026-10-27T00:00:00Z</updated></entry></feed>"""
    assert boards.RssFeedScraper.parse_feed(rss, "Feed")[0]["description"] == "Python"
    assert boards.RssFeedScraper.parse_feed(rss, "Feed")[0]["location"] == "Montreal"
    assert boards.RssFeedScraper.parse_feed(atom, "Feed")[0]["url"] == "https://x/2"


# ---- dedupe ----------------------------------------------------------------
def test_cross_board_duplicates_collapse_to_the_employers_own_copy():
    jobs = [
        {"title": "Software Developer", "company": "Acme Inc.", "location": "Montreal, QC", "source": "linkedin", "url": "https://linkedin.com/1", "description": "short"},
        {"title": "Software Developer", "company": "ACME", "location": "Montréal, Québec", "source": "greenhouse", "url": "https://boards.greenhouse.io/acme/1", "description": "Full description with a lot more detail"},
        {"title": "Software Developer", "company": "Acme", "location": "Toronto, ON", "source": "indeed", "url": "https://indeed.com/9", "description": "different city"},
    ]
    result = dedupe_jobs(jobs)
    assert len(result) == 2
    montreal = next(j for j in result if "Montr" in j["location"])
    assert montreal["source"] == "greenhouse"


def test_dedupe_keeps_longest_description_from_the_losing_copy():
    jobs = [
        {"title": "Dev", "company": "Acme", "location": "Montreal", "source": "greenhouse", "url": "a", "description": "tiny"},
        {"title": "Dev", "company": "Acme", "location": "Montreal", "source": "linkedin", "url": "b", "description": "a much longer description from the aggregator"},
    ]
    merged = dedupe_jobs(jobs)[0]
    assert merged["source"] == "greenhouse" and merged["description"].startswith("a much longer")


def test_dedupe_never_merges_records_without_a_company():
    jobs = [{"title": "Dev", "company": "Unknown", "url": "a"}, {"title": "Dev", "company": "Unknown", "url": "b"}]
    assert len(dedupe_jobs(jobs)) == 2


# ---- enrichment ------------------------------------------------------------
def test_enrichment_replaces_short_descriptions_from_jobposting_jsonld():
    job = {"title": "Software Developer", "company": "Acme", "location": "Montreal, QC", "url": "https://acme.com/jobs/1", "description": "Short snippet."}
    page = JSONLD_PAGE % ("Software Developer", "https://acme.com/jobs/1", "Full text about Python, SQL and 2 years experience " * 5)
    count = enrich.enrich_descriptions([job], fetcher=lambda url, **kw: FakeResponse(text=page))
    assert count == 1 and "Python, SQL" in job["description"]


def test_enrichment_skips_blocked_hosts_long_descriptions_and_irrelevant_jobs():
    never = lambda url, **kw: (_ for _ in ()).throw(AssertionError("must not fetch"))  # noqa: E731
    jobs = [
        {"title": "Software Developer", "company": "A", "location": "Montreal", "url": "https://www.linkedin.com/jobs/view/1", "description": "short"},
        {"title": "Software Developer", "company": "B", "location": "Montreal", "url": "https://b.com/1", "description": "x" * 400},
        {"title": "Director of Engineering", "company": "C", "location": "Montreal", "url": "https://c.com/1", "description": "short"},
        {"title": "Software Developer", "company": "D", "location": "Seattle, WA", "url": "https://d.com/1", "description": "short"},
    ]
    assert enrich.enrich_descriptions(jobs, fetcher=never) == 0


def test_enrichment_respects_the_fetch_budget():
    page = JSONLD_PAGE % ("Software Developer", "https://acme.com/jobs/x", "Long text " * 60)
    jobs = [{"title": "Software Developer", "company": f"Co{i}", "location": "Montreal", "url": f"https://co{i}.com/1", "description": "short"} for i in range(5)]
    assert enrich.enrich_descriptions(jobs, max_fetches=2, fetcher=lambda url, **kw: FakeResponse(text=page)) == 2


# ---- discovery CLI ---------------------------------------------------------
def test_discover_prints_ready_to_paste_env_lines(monkeypatch, capsys):
    pages = {
        "https://acme.com/careers": '<a href="https://boards.greenhouse.io/acme">x</a>',
        "https://bank.com/careers": '<a href="https://bigbank.wd3.myworkdayjobs.com/en-US/BankCareers">x</a>',
        "https://plain.com/careers": "<html>nothing here</html>",
    }
    monkeypatch.setattr(discover, "_request_get", lambda url, **kw: FakeResponse(text=pages[url]))
    discover.main(["Acme|https://acme.com/careers", "Bank|https://bank.com/careers", "https://plain.com/careers"])
    out = capsys.readouterr().out
    assert "GREENHOUSE_COMPANIES=Acme|acme" in out
    assert "WORKDAY_COMPANIES=Bank|bigbank|wd3|BankCareers" in out
    assert "no ATS detected" in out


def test_factory_registers_the_new_sources():
    for name in ("ashby", "workable", "smartrecruiters", "recruitee", "workday", "themuse", "adzuna", "jooble", "rss"):
        assert isinstance(collector.ScraperFactory.create(name), collector.BaseScraper)


@pytest.mark.parametrize("env_value, expected", [("A|a,B|b", [("A", "a"), ("B", "b")]), ("broken,C|c", [("C", "c")]), ("", [])])
def test_board_env_lists_are_parsed_defensively(monkeypatch, env_value, expected):
    import importlib

    from jobhunter.config import settings

    monkeypatch.setenv("ASHBY_COMPANIES", env_value)
    reloaded = importlib.reload(settings)
    try:
        assert reloaded.ASHBY_BOARDS == expected
    finally:
        monkeypatch.delenv("ASHBY_COMPANIES")
        importlib.reload(settings)
