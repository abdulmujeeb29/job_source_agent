"""Prefer an observed upstream hiring board without constructing tenant URLs."""
import re
from urllib.parse import urlsplit

from app.schemas import Observation

# Provider formats only. Company/tenant names always come from observed URLs.
ATS_HOSTS = {
    "jobs.ashbyhq.com", "boards.greenhouse.io", "job-boards.greenhouse.io",
    "boards.eu.greenhouse.io", "job-boards.eu.greenhouse.io", "jobs.lever.co",
    "jobs.eu.lever.co", "careers.smartrecruiters.com", "jobs.smartrecruiters.com",
    "apply.workable.com",
}
ATS_SUFFIXES = {"myworkdayjobs.com", "jobs.personio.de", "jobs.personio.com",
                "keka.com", "breezy.hr", "applytojob.com", "recruitee.com", "teamtailor.com"}
BACK_TO_JOBS = re.compile(r"(?:back|all|view|see).{0,60}(?:jobs|positions|openings|roles)|job listings", re.I)
APPLY = re.compile(r"\bapply\b|\bapplication\b", re.I)


def is_ats_url(url: str) -> bool:
    p = urlsplit(url)
    host = p.hostname or ""
    return p.scheme in {"http", "https"} and (host in ATS_HOSTS or any(
        host.endswith("." + suffix) for suffix in ATS_SUFFIXES
    ))


def board_handoff(observation: Observation, detail: dict | None) -> dict | None:
    """Only return URLs explicitly observed on the collection or its checked role."""
    if is_ats_url(observation.url) or not detail:
        return None
    source_host = urlsplit(observation.url).hostname
    detail_url = detail["url"]
    detail_host = urlsplit(detail_url).hostname
    links = detail.get("links", [])
    if detail_host != source_host:
        # A sampled ATS role may expose the collection directly (e.g. Back to jobs).
        for link in links:
            url, text = link.get("url", ""), link.get("text", "")
            if url == observation.url and BACK_TO_JOBS.search(text):
                return {"source_url": detail_url, "url": url, "link_text": text,
                        "kind": "observed_ats_backlink_to_company_collection"}
            if (url != detail_url and BACK_TO_JOBS.search(text)
                    and urlsplit(url).scheme in {"http", "https"}
                    and (urlsplit(url).hostname == detail_host or is_ats_url(url))):
                return {"source_url": detail_url, "url": url, "link_text": text,
                        "kind": "observed_role_to_board_link"}
        if is_ats_url(detail_url):
            return {"source_url": observation.url, "url": detail_url,
                    "link_text": "Sampled role link", "kind": "observed_ats_role"}
    for link in links:
        url, text = link.get("url", ""), link.get("text", "")
        p = urlsplit(url)
        if (p.scheme in {"http", "https"} and p.hostname != detail_host
                and APPLY.search(text)
                and (is_ats_url(url) or re.search(r"job|career|position|opening|apply", p.path, re.I))):
            return {"source_url": detail_url, "url": url, "link_text": text,
                    "kind": "observed_external_apply_link"}
    for frame in detail.get("frames", []):
        if is_ats_url(frame):
            return {"source_url": detail_url, "url": frame, "link_text": "Embedded hiring page",
                    "kind": "observed_ats_frame"}
    for link in observation.links:
        if is_ats_url(link.url) and BACK_TO_JOBS.search(link.text):
            return {"source_url": observation.url, "url": link.url, "link_text": link.text,
                    "kind": "observed_collection_to_board_link"}
    return None
