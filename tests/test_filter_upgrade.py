"""Location/region handling and whole-word filters."""

from jobhunter.filter import (
    LocationAndRemotePredicate,
    RoleBlacklistPredicate,
    filter_jobs,
    remote_region_restricted,
)


def _job(**kw):
    base = {"title": "Business Analyst", "company": "Acme", "fit_score": 80, "location": "Montreal, QC", "description": "Analysis"}
    base.update(kw)
    return base


def test_missing_location_is_not_treated_as_remote():
    predicate = LocationAndRemotePredicate()
    assert not predicate.evaluate(_job(location="Unknown", description="Great analyst role."))
    assert not predicate.evaluate(_job(location="", description="Fully remote!"))


def test_missing_location_is_kept_when_the_posting_places_it_in_montreal():
    predicate = LocationAndRemotePredicate()
    assert predicate.evaluate(_job(location="Unknown", description="Our Montréal office is hiring."))


def test_us_only_remote_roles_are_rejected_but_canada_friendly_ones_kept():
    us_only = _job(location="Remote", description="You must be authorized to work in the United States.")
    us_region = _job(location="Remote - US", description="Great role")
    canada = _job(location="Remote, Canada", description="Open to candidates across Canada")
    generic = _job(location="Remote", description="Remote role")
    mixed = _job(location="Remote", description="US or Canada residents welcome; authorized to work in the US or Canada")
    assert remote_region_restricted(us_only) and remote_region_restricted(us_region)
    assert not remote_region_restricted(canada) and not remote_region_restricted(generic)
    assert not remote_region_restricted(mixed)
    assert [j["location"] for j in filter_jobs([us_only, us_region, canada, generic])] == ["Remote, Canada", "Remote"]


def test_suburbs_of_greater_montreal_count_as_local():
    assert LocationAndRemotePredicate().evaluate(_job(location="Saint-Laurent, QC"))
    assert LocationAndRemotePredicate().evaluate(_job(location="Dorval, Quebec"))
    assert not LocationAndRemotePredicate().evaluate(_job(location="Quebec City, QC"))


def test_blacklist_matches_whole_words_only():
    predicate = RoleBlacklistPredicate()
    assert not predicate.evaluate(_job(title="Senior Analyst"))
    assert not predicate.evaluate(_job(title="Sr. Developer"))
    # "lead" must not fire inside other words, and "staff" not inside "Staffing"
    assert predicate.evaluate(_job(title="Misleading Metrics Analyst"))
    assert predicate.evaluate(_job(title="Staffing Systems Analyst"))


def test_associate_product_manager_survives_the_manager_blacklist():
    assert RoleBlacklistPredicate().evaluate(_job(title="Associate Product Manager"))
    assert not RoleBlacklistPredicate().evaluate(_job(title="Product Manager"))
