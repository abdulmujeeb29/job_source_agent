from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DiscoveryError(Exception):
    def __init__(self, code: str, reason: str):
        self.code, self.reason = code, reason
        super().__init__(reason)


class CompanyIdentity(BaseModel):
    name: str
    website: str
    linkedin_url: str
    sources: list[dict] = Field(default_factory=list)
    website_candidates: list[str] = Field(default_factory=list)


class Link(BaseModel):
    text: str
    url: str
    frame_url: str = ""
    provenance: str = "rendered_anchor"
    context: str = ""


class Observation(BaseModel):
    url: str
    title: str
    text: str
    snapshot: str
    links: list[Link]
    frames: list[str] = Field(default_factory=list)
    identity_text: str = ""
    visited_urls: list[str] = Field(default_factory=list)
    scroll_y: int = 0


class ListingSample(BaseModel):
    model_config = {"extra": "forbid"}
    title: str
    url: str


class Decision(BaseModel):
    model_config = {"extra": "forbid"}
    action: Literal["click", "open", "fill", "scroll", "back", "wait", "verify", "stop"]
    target: str
    value: str
    reason: str
    page_kind: Literal["other", "careers", "listings", "job_detail", "empty_board", "blocked"]
    company_matches: bool
    company_evidence: str
    collection_evidence: str
    listings: list[ListingSample]


TERMINAL = {"succeeded", "failed", "no_openings", "cancelled", "interrupted"}


class Run(BaseModel):
    run_id: str
    input_url: str
    normalized_input_url: str
    status: str = "queued"
    stage: str = "queued"
    company_name: str | None = None
    company_website: str | None = None
    company_linkedin_url: str | None = None
    identity_sources: list[dict] = Field(default_factory=list)
    careers_url: str | None = None
    company_listings_url: str | None = None
    jobs_url: str | None = None
    ats_resolution: dict = Field(default_factory=dict)
    verification: dict = Field(default_factory=dict)
    navigation_events: list[dict] = Field(default_factory=list)
    failure_code: str | None = None
    failure_reason: str | None = None
    created_at: str = Field(default_factory=now)
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    model_usage: dict = Field(default_factory=dict)
    provider_usage: list[dict] = Field(default_factory=list)
    attempt_counts: dict = Field(default_factory=dict)
    config_version: str = "0.3.0"
    build_revision: str = "local"

    def event(self, stage: str, message: str, **details) -> None:
        self.stage = stage
        self.navigation_events.append({
            "id": len(self.navigation_events) + 1, "at": now(),
            "stage": stage, "message": message, **details,
        })
