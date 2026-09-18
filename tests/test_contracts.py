import pytest

from app.providers import ApifyProvider, description_websites
from app.schemas import DiscoveryError
from app.urls import normalize_job_url, web_url


@pytest.mark.parametrize("url", [
    "https://www.linkedin.com/jobs/view/4427787182/",
    "https://linkedin.com/jobs/view/4427787182?tracking=test",
    "https://uk.linkedin.com/jobs/view/engineer-at-example-4427787182/",
])
def test_normalize(url):
    assert normalize_job_url(url) == "https://www.linkedin.com/jobs/view/4427787182/"


@pytest.mark.parametrize("url", [
    "https://linkedin.com.evil.org/jobs/view/4427787182", "http://linkedin.com/jobs/view/4427787182",
    "https://www.linkedin.com/jobs/search/?currentJobId=4427787182", "https://linkedin.com/jobs/view/no-id",
    "https://user:password@linkedin.com/jobs/view/4427787182", "https://linkedin.com:123/jobs/view/4427787182",
    "file:///etc/passwd", "javascript:alert(1)", "https://linkedin.com/jobs/view/123",
])
def test_reject_input(url):
    with pytest.raises(DiscoveryError, match="LinkedIn"):
        normalize_job_url(url)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "https://x:secret@example.com", "http://example.com:123"])
def test_reject_unsafe_navigation(url):
    with pytest.raises(DiscoveryError):
        web_url(url)


async def test_extraction_binds_job_and_company(settings):
    provider = ApifyProvider(settings)
    calls = []

    async def actor(name, payload):
        calls.append(payload)
        return ([{"jobId": "4427787182", "companyName": "Example", "companyUrl": "https://uk.linkedin.com/company/example/"}]
                if "searchUrls" in payload else [{"linkedinUrl": "https://www.linkedin.com/company/example", "website": "example.com"}])

    provider.actor = actor
    try:
        company = await provider.extract("https://www.linkedin.com/jobs/view/4427787182/")
        assert company.website == "https://example.com"
        assert calls[1] == {"companies": ["https://www.linkedin.com/company/example"]}
    finally:
        await provider.close()


@pytest.mark.parametrize("records,code", [
    ([{"jobId": "9999999999", "companyName": "Wrong"}], "job_unavailable"),
    ([{"jobId": "4427787182", "companyName": "Example"}], "company_ambiguous"),
    ([], "job_unavailable"),
])
async def test_extraction_never_substitutes_another_job(settings, records, code):
    provider = ApifyProvider(settings)

    async def actor(*args):
        return records

    provider.actor = actor
    try:
        with pytest.raises(DiscoveryError) as exc:
            await provider.extract("https://www.linkedin.com/jobs/view/4427787182/")
        assert exc.value.code == code
    finally:
        await provider.close()


@pytest.mark.parametrize("fallback_profile,website,code", [
    ("example", "https://example.com", None),
    ("unrelated", "https://unrelated.com", "company_ambiguous"),
    ("example", None, "website_missing"),
])
async def test_missing_website_uses_matching_secondary_extractor(settings, fallback_profile, website, code):
    provider = ApifyProvider(settings)
    calls = []
    async def actor(name, payload, **kwargs):
        calls.append(name)
        if name == settings.apify_job_actor:
            return [{"jobId": "4427787182", "companyName": "Example", "companyUrl": "https://www.linkedin.com/company/example"}]
        if name == settings.apify_company_actor:
            return [{"linkedinUrl": "https://www.linkedin.com/company/example", "website": None}]
        return [{"companyUrl": f"https://www.linkedin.com/company/{fallback_profile}", "companyWebsite": website}]
    provider.actor = actor
    try:
        if code:
            with pytest.raises(DiscoveryError) as exc:
                await provider.extract("https://www.linkedin.com/jobs/view/4427787182/")
            assert exc.value.code == code
            assert provider.partial_identity.name == "Example"
        else:
            identity = await provider.extract("https://www.linkedin.com/jobs/view/4427787182/")
            assert identity.website == website
            assert identity.sources[-1]["actor"] == settings.apify_company_fallback_actor
        assert len(calls) == 3
    finally:
        await provider.close()


def test_description_candidates_are_observed_urls_not_guessed_domains():
    text = 'Accommodations: https://careers.example.com/help. Profile https://www.linkedin.com/company/example; invalid https://[bad'
    assert description_websites(text) == ["https://careers.example.com/help"]
