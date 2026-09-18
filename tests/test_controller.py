import asyncio

import pytest

from app.controller import Controller
from app.schemas import DiscoveryError, Run
from app.storage import Store
from tests.test_verification import evidence


class FakeProvider:
    usage = []
    closed = False

    def __init__(self, settings):
        pass

    async def extract(self, url):
        return evidence()[0]

    async def close(self):
        self.closed = True


class FakeModel:
    usage = {"requests": 1}

    def __init__(self, settings):
        pass

    async def decide(self, context):
        return evidence()[2]

    async def close(self):
        pass


class FakeBrowser:
    closed = False

    def __init__(self, *args):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def open(self, url):
        pass

    async def observe(self):
        return evidence()[1]

    async def screenshot(self, path, focus_text=""):
        pass

    async def check_detail(self, url, expected_title=""):
        return {"status": 200, "url": url, "text": "Software Engineer " * 30}


def new_run():
    return Run(run_id="a" * 32, input_url="https://www.linkedin.com/jobs/view/4427787182/",
               normalized_input_url="https://www.linkedin.com/jobs/view/4427787182/")


async def test_controller_success_persists_evidence(settings):
    store = Store(settings.data_dir / "runs.sqlite3")
    controller = Controller(settings, store, FakeProvider, FakeModel, FakeBrowser)
    run = new_run()
    await controller.execute(run)
    saved = store.get(run.run_id)
    assert saved.status == "succeeded"
    assert saved.verification["detail_check"]["title_confirmed"]
    assert saved.jobs_url == "https://jobs.example.com/"
    assert saved.duration_ms is not None
    store.close()


async def test_loop_stops_on_repeated_false_verification(settings):
    class WrongModel(FakeModel):
        async def decide(self, context):
            result = evidence()[2]
            result.listings[0].url = "https://invented.example"
            return result
    store = Store(settings.data_dir / "runs.sqlite3")
    run = new_run()
    await Controller(settings, store, FakeProvider, WrongModel, FakeBrowser).execute(run)
    assert run.status == "failed"
    assert run.failure_code == "navigation_exhausted"
    assert any(e["stage"] == "recovering" for e in run.navigation_events)
    assert run.attempt_counts["steps"] == 3
    store.close()


async def test_deadline_cleans_up_provider(settings):
    provider = FakeProvider(settings)
    async def slow(url):
        await asyncio.sleep(10)
    provider.extract = slow
    settings.run_timeout_seconds = 0
    store = Store(settings.data_dir / "runs.sqlite3")
    run = new_run()
    await Controller(settings, store, lambda _: provider, FakeModel, FakeBrowser).execute(run)
    assert run.failure_code == "deadline_exceeded"
    assert provider.closed
    store.close()


async def test_source_linked_website_requires_observed_brand_and_domain(settings):
    company, observation, decision = evidence()
    company.website = ""
    company.website_candidates = ["https://jobs.example.com/help"]
    decision.action = "stop"
    class IdentityModel(FakeModel):
        async def decide(self, context):
            assert context["stage"] == "identity_validation"
            return decision
    browser = FakeBrowser()
    store = Store(settings.data_dir / "runs.sqlite3")
    run = new_run()
    controller = Controller(settings, store)
    await controller.resolve_website(run, company, IdentityModel(settings), browser)
    assert company.website == observation.url
    assert company.sources[-1]["verified"] is True
    store.close()


async def test_source_linked_unrelated_site_is_rejected_even_if_brand_is_mentioned(settings):
    company, observation, decision = evidence()
    company.website = ""
    company.website_candidates = ["https://unrelated.test/blog"]
    observation.url = "https://unrelated.test/blog"
    decision.company_matches = True
    class IdentityModel(FakeModel):
        async def decide(self, context):
            return decision
    class UnrelatedBrowser(FakeBrowser):
        async def observe(self):
            return observation
    store = Store(settings.data_dir / "runs.sqlite3")
    try:
        with pytest.raises(DiscoveryError, match="could not be verified"):
            await Controller(settings, store).resolve_website(new_run(), company, IdentityModel(settings), UnrelatedBrowser())
    finally:
        store.close()


async def test_transient_observe_failure_recovers_and_succeeds(settings):
    class FlakyBrowser(FakeBrowser):
        attempts = 0
        async def observe(self):
            FlakyBrowser.attempts += 1
            if FlakyBrowser.attempts == 1:
                raise TimeoutError("momentary CDP hiccup")
            return evidence()[1]
    store = Store(settings.data_dir / "runs.sqlite3")
    run = new_run()
    await Controller(settings, store, FakeProvider, FakeModel, FlakyBrowser).execute(run)
    assert run.status == "succeeded"
    assert any(e["stage"] == "recovering" for e in run.navigation_events)
    store.close()


async def test_repeated_observe_failure_fails_as_navigation_blocked(settings):
    class BlindBrowser(FakeBrowser):
        async def observe(self):
            raise DiscoveryError("browser_action_failed", "Operation timed out.")
    store = Store(settings.data_dir / "runs.sqlite3")
    run = new_run()
    await Controller(settings, store, FakeProvider, FakeModel, BlindBrowser).execute(run)
    assert run.status == "failed"
    assert run.failure_code == "navigation_blocked"
    store.close()


async def test_initial_open_retries_on_transient_failure(settings):
    class FlakyOpenBrowser(FakeBrowser):
        opens = 0
        async def open(self, url):
            FlakyOpenBrowser.opens += 1
            if FlakyOpenBrowser.opens == 1:
                raise DiscoveryError("browser_action_failed", "Navigation exceeded its time limit.")
    store = Store(settings.data_dir / "runs.sqlite3")
    run = new_run()
    await Controller(settings, store, FakeProvider, FakeModel, FlakyOpenBrowser).execute(run)
    assert run.status == "succeeded"
    assert FlakyOpenBrowser.opens >= 2
    store.close()


async def test_initial_open_fails_after_persistent_failure(settings):
    class DeadOpenBrowser(FakeBrowser):
        async def open(self, url):
            raise DiscoveryError("browser_action_failed", "Navigation exceeded its time limit.")
    store = Store(settings.data_dir / "runs.sqlite3")
    run = new_run()
    await Controller(settings, store, FakeProvider, FakeModel, DeadOpenBrowser).execute(run)
    assert run.status == "failed"
    assert run.failure_code == "browser_action_failed"
    store.close()


def test_restart_interrupts_nonterminal_runs(settings):
    store = Store(settings.data_dir / "runs.sqlite3")
    run = new_run()
    store.save(run)
    store.interrupt_pending()
    assert store.get(run.run_id).status == "interrupted"
    store.close()
