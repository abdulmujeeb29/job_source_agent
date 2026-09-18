import pytest

from app.schemas import CompanyIdentity, Decision, DiscoveryError, Link, ListingSample, Observation
from app.verification import verify_detail, verify_evidence


def evidence():
    company = CompanyIdentity(name="Example Inc", website="https://example.com", linkedin_url="https://www.linkedin.com/company/example")
    observation = Observation(url="https://jobs.example.com/", title="Jobs", snapshot="", frames=[],
                              text="Example Inc. Open positions. Software Engineer. London.",
                              links=[Link(text="Software Engineer London", url="https://jobs.example.com/role/1")])
    decision = Decision(action="verify", target="", value="", reason="Collection with a role", page_kind="listings",
                        company_matches=True, company_evidence="Example Inc", collection_evidence="Open positions",
                        listings=[ListingSample(title="Software Engineer", url="https://jobs.example.com/role/1")])
    return company, observation, decision


def test_one_opening_collection_qualifies():
    assert verify_evidence(*evidence())["outcome"] == "verified"


def test_duplicate_apply_anchor_does_not_erase_title_evidence():
    company, observation, decision = evidence()
    observation.links.append(Link(text="Apply", url=decision.listings[0].url))
    assert verify_evidence(company, observation, decision)["outcome"] == "verified"


def test_generic_link_uses_its_own_card_context():
    company, observation, decision = evidence()
    observation.links[0].text = "See role"
    observation.links[0].context = "Software Engineer London See role"
    assert verify_evidence(company, observation, decision)["outcome"] == "verified"
    observation.links[0].context = "Data Analyst See role"
    with pytest.raises(DiscoveryError):
        verify_evidence(company, observation, decision)


def test_identity_can_use_observed_page_title():
    company, observation, decision = evidence()
    observation.text = "Open positions. Software Engineer. London."
    observation.identity_text = "Example Inc careers"
    decision.company_evidence = "Example Inc careers"
    result = verify_evidence(company, observation, decision)
    assert result["company_evidence_source"] == observation.url


def test_identity_fallback_requires_verified_linked_role():
    company, observation, decision = evidence()
    observation.text = "Open positions. Software Engineer. London."
    decision.company_evidence = ""
    detail = {"url": decision.listings[0].url, "status": 200,
              "text": "Software Engineer at Example Inc. " * 10}
    result = verify_evidence(company, observation, decision, detail=detail)
    assert result["company_evidence_kind"] == "verified_linked_role"
    detail["text"] = "Software Engineer at Unrelated Business. " * 10
    with pytest.raises(DiscoveryError):
        verify_evidence(company, observation, decision, detail=detail)
    detail.update(status=404, text="Software Engineer at Example Inc. " * 10)
    with pytest.raises(DiscoveryError):
        verify_evidence(company, observation, decision, detail=detail)


@pytest.mark.parametrize("change", ["marketing", "wrong_company", "invented_title", "invented_url", "invented_quote", "single_role", "no_roles"])
def test_reject_false_success(change):
    company, observation, decision = evidence()
    if change == "marketing":
        decision.page_kind = "careers"
    elif change == "wrong_company":
        decision.company_matches = False
    elif change == "invented_title":
        decision.listings[0].title = "CEO"
    elif change == "invented_url":
        decision.listings[0].url = "https://invented.example.com/"
    elif change == "invented_quote":
        decision.collection_evidence = "Join our amazing family"
    elif change == "single_role":
        decision.page_kind = "job_detail"
    else:
        decision.listings = []
    with pytest.raises(DiscoveryError):
        verify_evidence(company, observation, decision)


def test_empty_board_separate_from_success():
    company, observation, decision = evidence()
    observation.text = "Example Inc. No open positions at this time."
    decision.page_kind, decision.listings = "empty_board", []
    decision.collection_evidence = "No open positions at this time"
    assert verify_evidence(company, observation, decision)["outcome"] == "no_openings"


@pytest.mark.parametrize("detail", [
    {"status": 404, "text": "Software Engineer" * 30},
    {"status": 200, "text": "Something unrelated " * 30},
    {"status": 200, "text": "Software Engineer verify you are human " * 30},
])
def test_detail_page_must_confirm_the_role(detail):
    with pytest.raises(DiscoveryError):
        verify_detail({"title": "Software Engineer"}, detail)
