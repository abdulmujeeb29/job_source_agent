import pytest

from app.controller import Controller
from app.destinations import board_handoff, is_ats_url
from app.schemas import Link
from app.storage import Store
from tests.test_controller import FakeBrowser, FakeModel, FakeProvider, new_run
from tests.test_verification import evidence


@pytest.mark.parametrize("url", [
    "https://jobs.ashbyhq.com/example", "https://job-boards.greenhouse.io/example",
    "https://example.wd5.myworkdayjobs.com/en-US/jobs", "https://example.jobs.personio.de/",
])
def test_provider_formats_do_not_require_company_mapping(url):
    assert is_ats_url(url)


@pytest.mark.parametrize("url", [
    "https://jobs.ashbyhq.com.attacker.test/example", "https://www.ashbyhq.com/",
    "https://example.myworkdayjobs.com.attacker.test/", "javascript:alert(1)",
])
def test_non_provider_hosts_not_recognized(url):
    assert not is_ats_url(url)


def test_internal_role_exposes_exact_external_application_link():
    observation = evidence()[1]
    target = "https://jobs.ashbyhq.com/example/role-123?utm_source=observed"
    detail = {"url": "https://jobs.example.com/role/1", "links": [
        {"text": "Privacy Policy", "url": "https://www.ashbyhq.com/privacy"},
        {"text": "Apply Now", "url": target},
    ]}
    handoff = board_handoff(observation, detail)
    assert handoff["url"] == target
    assert handoff["source_url"] == detail["url"]


def test_external_role_back_link_is_used_without_constructing_root():
    observation = evidence()[1]
    board = "https://job-boards.greenhouse.io/example?gh_src=observed"
    detail = {"url": "https://job-boards.greenhouse.io/example/jobs/123", "links": [
        {"text": "Back to jobs", "url": board},
    ]}
    assert board_handoff(observation, detail)["url"] == board
    observation.url = board
    assert board_handoff(observation, detail) is None


def test_no_provider_url_is_invented_for_a_custom_board():
    assert board_handoff(evidence()[1], {"url": "https://jobs.example.com/role/1", "links": []}) is None


def test_ats_can_designate_the_company_page_as_its_official_collection():
    observation = evidence()[1]
    detail = {"url": "https://job-boards.greenhouse.io/example/jobs/123", "links": [
        {"text": "Back to jobs", "url": observation.url},
    ]}
    handoff = board_handoff(observation, detail)
    assert handoff["url"] == observation.url
    assert handoff["kind"] == "observed_ats_backlink_to_company_collection"


ATS_BOARD = "https://jobs.ashbyhq.com/example"
ATS_ROLE = ATS_BOARD + "/role-123"


class HandoffBrowser(FakeBrowser):
    current = "https://jobs.example.com/"

    async def open(self, url):
        if url.startswith(ATS_BOARD):
            self.current = url

    async def observe(self):
        observation = evidence()[1]
        observation.url = self.current
        if self.current == ATS_ROLE:
            observation.text = "Example Inc Software Engineer job description"
            observation.links = [Link(text="Back to Example's Job Listings", url=ATS_BOARD)]
        elif self.current == ATS_BOARD:
            observation.links = [Link(text="Software Engineer London", url=ATS_ROLE)]
        return observation

    async def act(self, decision, observation):
        assert decision.target in {link.url for link in observation.links}
        await self.open(decision.target)

    async def check_detail(self, url, expected_title=""):
        return {"url": url, "status": 200, "text": "Software Engineer at Example Inc. " * 10,
                "links": [{"text": "Apply Now", "url": ATS_ROLE}] if url != ATS_ROLE else []}


class HandoffModel(FakeModel):
    async def decide(self, context):
        decision = evidence()[2]
        url = context["observation"]["url"]
        if url == ATS_ROLE:
            decision.action, decision.target, decision.page_kind = "open", ATS_BOARD, "job_detail"
            decision.listings = []
        elif url == ATS_BOARD:
            decision.listings[0].url = ATS_ROLE
        return decision


async def test_controller_continues_to_underlying_board(settings):
    store = Store(settings.data_dir / "runs.sqlite3")
    run = new_run()
    try:
        await Controller(settings, store, FakeProvider, HandoffModel, HandoffBrowser).execute(run)
        assert run.status == "succeeded"
        assert run.jobs_url == ATS_BOARD
        assert run.company_listings_url == "https://jobs.example.com/"
        assert run.ats_resolution["status"] == "verified"
        assert run.verification["detail_check"]["url"] == ATS_ROLE
        event = next(e for e in run.navigation_events if e["stage"] == "following_ats")
        assert event["source_url"] == "https://jobs.example.com/role/1"
        assert event["url"] == ATS_ROLE
    finally:
        store.close()


async def test_unreachable_upstream_is_not_presented_as_verified_ats(settings):
    class StoppedModel(HandoffModel):
        async def decide(self, context):
            decision = await super().decide(context)
            if context["observation"]["url"] == ATS_ROLE:
                decision.action = "stop"
                decision.reason = "ATS blocked in this fixture."
            return decision
    store = Store(settings.data_dir / "runs.sqlite3")
    run = new_run()
    try:
        await Controller(settings, store, FakeProvider, StoppedModel, HandoffBrowser).execute(run)
        assert run.status == "succeeded"
        assert run.jobs_url == "https://jobs.example.com/"
        assert run.ats_resolution["status"] == "unverified"
        assert "blocked" in run.ats_resolution["reason"]
    finally:
        store.close()
