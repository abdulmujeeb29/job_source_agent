import re
import unicodedata

from app.schemas import CompanyIdentity, Decision, DiscoveryError, Observation


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def ground_listings(observation: Observation, decision: Decision) -> list[dict]:
    """Require each claimed title to be bound to its actual destination or single-job card."""
    text = normalized(observation.text)
    if len(normalized(decision.collection_evidence)) < 4 or normalized(decision.collection_evidence) not in text:
        raise DiscoveryError("verification_failed", "The collection excerpt was not found in rendered page text.")
    if decision.page_kind == "empty_board":
        if decision.listings:
            raise DiscoveryError("verification_failed", "Empty-board claim conflicts with supplied listings.")
        return []
    if decision.page_kind != "listings" or not decision.listings:
        raise DiscoveryError("verification_failed", "A jobs collection with observed job links is required.")
    links = {}
    for link in observation.links:
        # A second Apply anchor to the same URL must not overwrite a title anchor.
        links.setdefault(link.url, []).append(normalized(link.text + "\n" + link.context))
    grounded = []
    for listing in decision.listings[:5]:
        title = normalized(listing.title)
        if listing.url == observation.url:
            raise DiscoveryError("verification_failed", "The role URL is the current page. Return to the jobs collection before verifying.")
        if len(title) < 4 or listing.url not in links:
            raise DiscoveryError("verification_failed", "A claimed role is not linked from the observed jobs page.")
        if title not in text or not any(title in label for label in links[listing.url]):
            raise DiscoveryError("verification_failed", "A claimed job title is not grounded in the visible job link.")
        grounded.append(listing.model_dump())
    return grounded


def contains_company(text: str, name: str) -> bool:
    words = [w for w in re.findall(r"\w+", normalized(name))
             if w not in {"inc", "llc", "ltd", "limited", "corporation", "company", "the", "and"}]
    if not words:
        return False
    full = r"\b" + r"[\W_]*".join(map(re.escape, words)) + r"\b"
    if re.search(full, normalized(text)):
        return True
    # A distinctive brand can omit legal/industry suffixes, e.g. DISH vs DISH Digital Solutions.
    generic = {"group", "digital", "solutions", "financial", "bank", "staffing", "people", "services"}
    brands = [w for w in words if len(w) > 2 and w not in generic]
    return bool(brands) and bool(re.search(rf"\b{re.escape(brands[0])}\b", normalized(text)))


def verify_evidence(company: CompanyIdentity, observation: Observation, decision: Decision,
                    detail: dict | None = None) -> dict:
    """Identity must be grounded on the board or an independently checked linked role."""
    grounded = ground_listings(observation, decision)
    if not decision.company_matches:
        raise DiscoveryError("verification_failed", "The destination was not identified as belonging to the hiring company.")
    quote = decision.company_evidence
    corpus = normalized(observation.text + "\n" + observation.identity_text)
    identity_source = observation.url
    identity_kind = "board_text_or_accessible_metadata"
    if not (len(normalized(quote)) >= 4 and normalized(quote) in corpus and contains_company(quote, company.name)):
        if detail is None or not grounded:
            raise DiscoveryError("verification_failed", "Company identity was not grounded in board text or accessible metadata.")
        verify_detail(grounded[0], detail)
        detail_text = detail.get("text", "") + "\n" + detail.get("title", "")
        lines = [line.strip() for line in detail_text.splitlines() if contains_company(line, company.name)]
        if not lines:
            raise DiscoveryError("verification_failed", "Neither the board nor its verified role confirms the hiring company.")
        line = lines[0]
        quote = next(line[i:i + 1000] for i in range(0, len(line), 500)
                     if contains_company(line[i:i + 1000], company.name))
        identity_source, identity_kind = detail["url"], "verified_linked_role"
    return {"outcome": "verified" if grounded else "no_openings", "company_evidence": quote,
            "company_evidence_source": identity_source, "company_evidence_kind": identity_kind,
            "collection_evidence": decision.collection_evidence, "listings": grounded,
            "link_provenance": [link.model_dump() for link in observation.links
                                if link.url in {item["url"] for item in grounded}]}


def verify_detail(sample: dict, detail: dict):
    if not detail.get("status") or detail["status"] >= 400:
        raise DiscoveryError("verification_failed", "The sampled job-detail page did not load successfully.")
    text = normalized(detail.get("text", ""))
    if normalized(sample["title"]) not in text or len(text) < 100:
        raise DiscoveryError("verification_failed", "The sampled job-detail page did not confirm the role title and content.")
    if re.search(r"verify (?:that )?you are human|access denied|checking your browser", text):
        raise DiscoveryError("verification_failed", "The sampled job-detail page is blocked.")
