import re
from urllib.parse import urlsplit, urlunsplit

from app.schemas import DiscoveryError


def normalize_job_url(value: str) -> str:
    try:
        parts = urlsplit(value.strip())
        host = parts.hostname or ""
        valid_host = host in {"linkedin.com", "www.linkedin.com"} or bool(
            re.fullmatch(r"[a-z]{2}\.linkedin\.com", host)
        )
        match = re.fullmatch(r"/jobs/view/(?:[\w%-]+-)?(\d{6,20})/?", parts.path)
        if (parts.scheme != "https" or not valid_host or not match or
                parts.username or parts.password or parts.port not in (None, 443)):
            raise ValueError
        return f"https://www.linkedin.com/jobs/view/{match[1]}/"
    except ValueError:
        raise DiscoveryError("invalid_input", "Enter an HTTPS LinkedIn job URL containing /jobs/view/<job-id>.") from None


def web_url(value: str) -> str:
    try:
        p = urlsplit(value)
        if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password:
            raise ValueError
        if p.port not in (None, 80, 443):
            raise ValueError
        return urlunsplit(p)
    except ValueError:
        raise DiscoveryError("unsafe_url", "Only public HTTP(S) website URLs on standard ports are supported.") from None


def prefer_https(value: str) -> str:
    """Upgrade an external http:// URL to https:// for display and navigation.
    Loopback/localhost (test fixtures) and non-web schemes are left untouched.
    Never invents a hostname or path — only the scheme changes."""
    try:
        p = urlsplit(value)
    except ValueError:
        return value
    host = (p.hostname or "").lower()
    if (p.scheme == "http" and host and host != "localhost"
            and not host.startswith("127.") and not host.endswith(".local")):
        return urlunsplit(p._replace(scheme="https"))
    return value


def company_profile(value: str) -> str:
    p = urlsplit(value)
    if not (p.hostname == "linkedin.com" or (p.hostname or "").endswith(".linkedin.com")):
        raise DiscoveryError("company_ambiguous", "Provider did not return a LinkedIn company profile.")
    m = re.fullmatch(r"/company/([^/]+)/?", p.path)
    if not m:
        raise DiscoveryError("company_ambiguous", "Company profile is missing or ambiguous.")
    return f"https://www.linkedin.com/company/{m[1]}"
