import httpx
import pytest

from app.providers import ApifyProvider, description_websites, is_usable_company_site, looks_unavailable
from app.schemas import DiscoveryError


async def test_transient_get_retried_but_actor_post_not_repeated(settings, monkeypatch):
    calls = []
    async def request(req):
        calls.append(req.method)
        return httpx.Response(503, json={"error": "temporary"}, headers={"Retry-After": "0"})
    provider = ApifyProvider(settings)
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(base_url="https://api.apify.com/v2/", transport=httpx.MockTransport(request))
    try:
        with pytest.raises(DiscoveryError):
            await provider.request("GET", "users/me")
        assert calls == ["GET"] * 3
        calls.clear()
        with pytest.raises(DiscoveryError):
            await provider.request("POST", "acts/test/runs", json={})
        assert calls == ["POST"]
    finally:
        await provider.close()


async def test_permanent_auth_failure_not_retried(settings):
    calls = []
    async def request(req):
        calls.append(req)
        return httpx.Response(401, json={"error": "bad auth"})
    provider = ApifyProvider(settings)
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(base_url="https://api.apify.com/v2/", transport=httpx.MockTransport(request))
    try:
        with pytest.raises(DiscoveryError, match="HTTP 401"):
            await provider.request("GET", "users/me")
        assert len(calls) == 1
    finally:
        await provider.close()


def test_social_profiles_are_not_usable_company_sites():
    assert not is_usable_company_site("https://instagram.com/greenfeast_jaipur?igshid=x")
    assert not is_usable_company_site("http://www.facebook.com/acme")
    assert not is_usable_company_site("https://x.com/acme")
    assert not is_usable_company_site("linktr.ee/acme")
    assert not is_usable_company_site("")
    assert not is_usable_company_site(None)
    # Real corporate sites, including a company whose name contains a social word.
    assert is_usable_company_site("https://www.stripe.com")
    assert is_usable_company_site("acme.io")
    assert is_usable_company_site("https://careers.facebookmarketing-agency.com")


def test_description_websites_drops_social_links():
    desc = "Apply at https://acme.io/careers or follow https://instagram.com/acme and https://linkedin.com/company/acme"
    assert description_websites(desc) == ["https://acme.io/careers"]


def test_looks_unavailable_classifier():
    assert looks_unavailable("No job details extracted from 1 URL(s). The posting may have been removed")
    assert looks_unavailable("LinkedIn served an auth-wall page rather than the posting")
    assert looks_unavailable("Apify actor ended with FAILED. LinkedIn returned a 404")
    assert not looks_unavailable("Apify actor ended with FAILED.")
    assert not looks_unavailable("Apify connection failed; actor start was not retried")


async def test_removed_posting_classified_as_job_unavailable(settings):
    """A hard actor FAILED whose status message means the job is gone becomes
    job_unavailable, not provider_error."""
    def request(req):
        if req.method == "POST":
            return httpx.Response(201, json={"data": {"id": "R1", "status": "RUNNING"}})
        return httpx.Response(200, json={"data": {
            "id": "R1", "status": "FAILED", "usageTotalUsd": 0.01,
            "statusMessage": "No job details extracted from 1 URL(s). The job posting may have "
                             "been removed, or LinkedIn served an auth-wall."}})
    provider = ApifyProvider(settings)
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(base_url="https://api.apify.com/v2/",
                                        transport=httpx.MockTransport(request))
    try:
        with pytest.raises(DiscoveryError) as info:
            await provider.extract("https://www.linkedin.com/jobs/view/4383274196/")
        assert info.value.code == "job_unavailable"
    finally:
        await provider.close()


async def test_generic_actor_failure_stays_provider_error(settings):
    """An actor failure with no removed/gated signal remains a provider_error."""
    def request(req):
        if req.method == "POST":
            return httpx.Response(201, json={"data": {"id": "R1", "status": "RUNNING"}})
        return httpx.Response(200, json={"data": {
            "id": "R1", "status": "FAILED", "statusMessage": "Actor exceeded memory limit."}})
    provider = ApifyProvider(settings)
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(base_url="https://api.apify.com/v2/",
                                        transport=httpx.MockTransport(request))
    try:
        with pytest.raises(DiscoveryError) as info:
            await provider.extract("https://www.linkedin.com/jobs/view/4383274196/")
        assert info.value.code == "provider_error"
    finally:
        await provider.close()
