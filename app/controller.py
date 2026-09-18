import asyncio
import hashlib
import json
import os
import time
from collections import Counter
from urllib.parse import urlsplit

from app.browser import BrowserSession
from app.config import Settings
from app.destinations import board_handoff
from app.providers import ApifyProvider, Astra
from app.schemas import DiscoveryError, Run, now
from app.storage import Store
from app.verification import (
    contains_company,
    ground_listings,
    normalized,
    verify_detail,
    verify_evidence,
)


class Controller:
    def __init__(self, settings: Settings, store: Store, provider_factory=ApifyProvider,
                 model_factory=Astra, browser_factory=BrowserSession):
        self.settings, self.store = settings, store
        self.provider_factory, self.model_factory = provider_factory, model_factory
        self.browser_factory = browser_factory

    def event(self, run, stage, message, **details):
        run.event(stage, message, **details)
        self.store.save(run)

    async def execute(self, run: Run):
        started = time.monotonic()
        run.status, run.started_at = "running", now()
        run.build_revision = os.environ.get("BUILD_REVISION", "local")
        provider = model = None
        try:
            missing = self.settings.missing()
            if missing:
                raise DiscoveryError("configuration_error", "Missing configuration: " + ", ".join(missing))
            provider, model = self.provider_factory(self.settings), self.model_factory(self.settings)
            async with asyncio.timeout(self.settings.run_timeout_seconds):
                self.event(run, "extracting", "Retrieving the LinkedIn job and its company website.")
                company = await provider.extract(run.normalized_input_url)
                run.company_name, run.company_website = company.name, company.website
                run.company_linkedin_url, run.identity_sources = company.linkedin_url, company.sources
                run.provider_usage = provider.usage
                self.event(run, "opening", f"Opening the official website for {company.name}.", url=company.website)
                async with self.browser_factory(self.settings, run.run_id) as browser:
                    if not company.website:
                        await self.resolve_website(run, company, model, browser)
                    # The first page load of a heavy site can time out transiently,
                    # especially under concurrent runs. Retry before giving up, matching
                    # the recovery the navigation loop already provides.
                    open_error = None
                    for open_attempt in range(3):
                        try:
                            await browser.open(company.website)
                            open_error = None
                            break
                        except (DiscoveryError, TimeoutError) as exc:
                            open_error = exc
                            if open_attempt < 2:
                                await asyncio.sleep(2)
                    for attempt in getattr(browser, "navigation_attempts", []):
                        self.event(run, "opening", "Company website navigation attempt.", **attempt)
                    if open_error is not None:
                        raise open_error
                    await self.navigate(run, company, model, browser)
        except asyncio.CancelledError:
            run.status, run.failure_code = "cancelled", "cancelled"
            run.failure_reason = "Run cancelled; browser and provider cleanup requested."
        except TimeoutError:
            run.status, run.failure_code = "failed", "deadline_exceeded"
            run.failure_reason = "The overall run deadline was reached before listings could be verified."
        except DiscoveryError as exc:
            run.status, run.failure_code, run.failure_reason = "failed", exc.code, exc.reason
        except Exception as exc:
            # Never expose raw exceptions containing requests or credential-bearing config.
            run.status, run.failure_code = "failed", "internal_error"
            run.failure_reason = f"Unexpected {type(exc).__name__}; the run stopped and released its resources."
        finally:
            if provider:
                run.provider_usage = provider.usage
                partial = getattr(provider, "partial_identity", None)
                if partial and not run.company_name:
                    run.company_name = partial.name
                    run.company_website = partial.website or None
                    run.company_linkedin_url = partial.linkedin_url
                    run.identity_sources = partial.sources
                await provider.close()
            if model:
                run.model_usage = model.usage
                await model.close()
            run.finished_at, run.duration_ms = now(), round((time.monotonic() - started) * 1000)
            self.event(run, run.status, run.failure_reason or (
                "Jobs list verified with browser evidence." if run.status == "succeeded"
                else "The company board explicitly reports no open roles."
            ))

    async def resolve_website(self, run, company, model, browser):
        """Recover from missing profile fields using source-linked, independently verified URLs."""
        candidates = sorted(company.website_candidates, key=lambda url: not contains_company(
            (urlsplit(url).hostname or "").replace(".", " "), company.name))
        for candidate in candidates[:3]:
            self.event(run, "resolving_website", "Inspecting a website link present in the original job description.", url=candidate)
            try:
                await browser.open(candidate)
                observation = await browser.observe()
                decision = await model.decide({"stage": "identity_validation", "company": company.model_dump(),
                                               "observation": observation.model_dump()})
                corpus = normalized(observation.text + "\n" + observation.identity_text)
                quote = normalized(decision.company_evidence)
                host = (urlsplit(observation.url).hostname or "").replace(".", " ")
                backlink = any(link.url.rstrip("/") == company.linkedin_url.rstrip("/") for link in observation.links)
                if not (decision.company_matches and len(quote) >= 4 and quote in corpus
                        and contains_company(quote, company.name)
                        and (contains_company(host, company.name) or backlink)):
                    self.event(run, "resolving_website", "Candidate did not provide sufficient official company identity evidence.", url=candidate)
                    continue
                # Prefer an actually observed same-host home link; never construct one.
                roots = [link.url for link in observation.links
                         if urlsplit(link.url).hostname == urlsplit(observation.url).hostname
                         and urlsplit(link.url).path in {"", "/"}]
                company.website = roots[0] if roots else observation.url
                company.sources.append({"url": candidate, "field": "job_description_link",
                                        "verified": True, "identity_quote": decision.company_evidence,
                                        "verified_page": observation.url, "website": company.website})
                run.company_website, run.identity_sources = company.website, company.sources
                self.event(run, "resolving_website", "Verified company website from a source-linked page.", url=company.website)
                return
            except (DiscoveryError, TimeoutError) as exc:
                self.event(run, "resolving_website", str(exc)[:450], url=candidate)
        raise DiscoveryError("website_missing", "Company profile fields were missing and source-linked websites could not be verified.")

    async def navigate(self, run, company, model, browser):
        state = {"fallback": None, "attempted": set()}
        try:
            await self.navigate_pages(run, company, model, browser, state)
        except (DiscoveryError, TimeoutError) as exc:
            if not state["fallback"]:
                raise
            fallback = state["fallback"]
            reason = exc.reason if isinstance(exc, DiscoveryError) else "ATS navigation timed out."
            run.jobs_url, run.verification = fallback["url"], fallback["verification"]
            run.status = "succeeded"
            run.ats_resolution.update(status="unverified", reason=reason)
            self.event(run, "ats_fallback", "The company-hosted listings are verified; the upstream ATS board could not be verified.",
                       url=run.jobs_url, reason=reason)

    async def navigate_pages(self, run, company, model, browser, state):
        repeats = Counter()
        failures = []
        observe_failures = 0
        artifacts = self.settings.data_dir / "artifacts" / run.run_id
        artifacts.mkdir(parents=True, exist_ok=True)
        for step in range(1, self.settings.max_actions + 1):
            try:
                observation = await browser.observe()
            except (DiscoveryError, TimeoutError) as exc:
                # A transient read failure (slow page, momentary CDP hiccup) should be
                # retried within the action budget, not treated as a terminal error.
                observe_failures += 1
                reason = exc.reason if isinstance(exc, DiscoveryError) else "Reading the page timed out."
                failures.append(reason)
                self.event(run, "recovering", reason, step=step)
                if observe_failures >= 3:
                    raise DiscoveryError("navigation_blocked",
                                         "The page could not be read after repeated attempts: " + reason)
                await asyncio.sleep(1)
                continue
            observed_state = {"url": observation.url, "text": observation.text, "identity": observation.identity_text,
                              "links": [link.model_dump() for link in observation.links], "scroll_y": observation.scroll_y}
            fingerprint = hashlib.sha256(json.dumps(observed_state, sort_keys=True).encode()).hexdigest()
            self.event(run, "observing", "Reading the current page and available navigation.",
                       url=observation.url, title=observation.title, step=step)
            decision = await model.decide({
                "company": company.model_dump(), "observation": observation.model_dump(),
                "recent_events": run.navigation_events[-10:], "recent_failures": failures[-4:],
                "actions_remaining": self.settings.max_actions - step,
                "ats_resolution": run.ats_resolution,
            })
            run.model_usage = model.usage
            run.attempt_counts["steps"] = step
            signature = (fingerprint, decision.action, decision.target, decision.value,
                         tuple((item.url, item.title) for item in decision.listings))
            repeats[signature] += 1
            if repeats[signature] > 2:
                raise DiscoveryError("navigation_exhausted", "The agent repeated the same action without page progress.")
            if decision.page_kind in {"careers", "listings", "empty_board"} and not run.careers_url:
                run.careers_url = observation.url
            screenshot = None
            try:
                filename = f"step-{step:02}.png"
                await browser.screenshot(artifacts / filename)
                screenshot = f"/api/runs/{run.run_id}/artifacts/{filename}"
            except Exception:
                pass
            self.event(run, "deciding", decision.reason, url=observation.url,
                       action=decision.action, target=decision.target, page_kind=decision.page_kind,
                       value=decision.value, screenshot=screenshot, step=step)
            if decision.action == "stop":
                raise DiscoveryError("navigation_blocked" if decision.page_kind == "blocked" else "navigation_exhausted", decision.reason)
            try:
                if decision.action == "verify":
                    self.event(run, "verifying", "Checking company identity, collection evidence, and a sampled role.", url=observation.url)
                    samples = ground_listings(observation, decision)
                    detail = None
                    if samples:
                        detail = await browser.check_detail(samples[0]["url"], samples[0]["title"])
                        verify_detail(samples[0], detail)
                    evidence = verify_evidence(company, observation, decision, detail=detail)
                    if detail:
                        evidence["detail_check"] = {"url": detail["url"], "http_status": detail["status"],
                                                    "title_confirmed": True}
                        try:
                            await browser.screenshot(artifacts / filename, focus_text=samples[0]["title"])
                            screenshot = f"/api/runs/{run.run_id}/artifacts/{filename}"
                        except Exception:
                            pass
                    evidence.update(observed_at=now(), page_url=observation.url, screenshot=screenshot)
                    handoff = board_handoff(observation, detail)
                    if handoff and handoff["url"] == observation.url:
                        # Some ATS tenants intentionally use the corporate page as
                        # their official collection. Do not follow a self-loop.
                        run.ats_resolution = {"status": "company_hosted", **handoff,
                                              "jobs_url": observation.url}
                        handoff = None
                    if handoff and handoff["url"] not in state["attempted"]:
                        if state["fallback"] is None:
                            state["fallback"] = {"url": observation.url, "verification": evidence}
                            run.company_listings_url = observation.url
                        state["attempted"].add(handoff["url"])
                        run.ats_resolution = {"status": "following", **handoff}
                        self.event(run, "following_ats", "Following an observed hiring-platform link before choosing the final jobs board.",
                                   source_url=handoff["source_url"], url=handoff["url"],
                                   link_text=handoff["link_text"], evidence_kind=handoff["kind"],
                                   via_role_url=detail["url"])
                        await browser.open(handoff["url"])
                        continue
                    run.verification = evidence
                    run.jobs_url = observation.url
                    run.status = "succeeded" if evidence["outcome"] == "verified" else "no_openings"
                    if state["fallback"] and run.ats_resolution.get("status") != "company_hosted":
                        if observation.url == state["fallback"]["url"]:
                            run.ats_resolution.update(status="unverified", reason="Navigation returned to the original company-hosted collection.")
                        else:
                            run.ats_resolution.update(status="verified", jobs_url=observation.url)
                    return
                if decision.action == "fill" and normalized(decision.value) not in {
                    normalized(company.name), "jobs", "careers", "open roles"
                }:
                    raise DiscoveryError("invalid_action", "Search input must use the company name or a careers keyword.")
                await browser.act(decision, observation)
                self.event(run, "navigating", "Browser action completed; refreshing observations.",
                           source_url=observation.url, action=decision.action, target=decision.target)
            except (DiscoveryError, TimeoutError) as exc:
                reason = exc.reason if isinstance(exc, DiscoveryError) else "Browser operation timed out."
                failures.append(reason)
                self.event(run, "recovering", reason, url=observation.url)
        raise DiscoveryError("navigation_exhausted", "The action budget was exhausted without a verified jobs collection.")
