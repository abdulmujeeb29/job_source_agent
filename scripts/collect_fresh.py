"""Collect recent, untested-company inputs with bounded parallel API calls."""
import asyncio
import hashlib
import json
import random
import re
from pathlib import Path

from app.config import Settings
from app.providers import ApifyProvider
from app.schemas import DiscoveryError, now
from app.urls import company_profile, normalize_job_url
from evaluation.sample import DEVELOPMENT_IDS, SEARCHES

FOLDER = Path("evaluation/fresh-current")
SEED = 2026091701


def name_key(name):
    return "".join(w for w in re.findall(r"\w+", (name or "").casefold())
                   if w not in {"inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "gmbh"})


def exclusions():
    ids, profiles, names = set(DEVELOPMENT_IDS), set(), set()
    for path in Path("evaluation").rglob("run-*.json"):
        data = json.loads(path.read_text())
        if data.get("input_url"):
            ids.add(data["input_url"].rstrip("/").split("/")[-1])
        if data.get("company_linkedin_url"):
            profiles.add(data["company_linkedin_url"].rstrip("/"))
        if data.get("company_name"):
            names.add(name_key(data["company_name"]))
    dev = json.loads(Path("evaluation/development.json").read_text())
    for case in dev["cases"]:
        for row in case["records"]:
            names.add(name_key(row.get("companyName")))
            if row.get("companyUrl"):
                profiles.add(company_profile(row["companyUrl"]))
    pdf = Path("evaluation/gemini-candidates-20260917")
    for row in json.loads((pdf / "candidates.json").read_text())["rows"]:
        ids.add(row["id"])
        if not row["company_claim"].startswith("Unknown"):
            names.add(name_key(row["company_claim"]))
    for path in pdf.glob("guest_checks*.json"):
        for row in json.loads(path.read_text())["results"]:
            if row.get("company"):
                names.add(name_key(row["company"]))
    return ids, profiles, names


async def main():
    if (FOLDER / "sample.json").exists() or (FOLDER / "pool.json").exists():
        raise SystemExit("Collection exists; preserve it rather than overwriting.")
    ids, profiles, names = exclusions()
    provider = ApifyProvider(Settings())
    gate = asyncio.Semaphore(3)
    raw = {"started_at": now(), "source": "piotrv1001/linkedin-jobs-search-scraper", "batches": [],
           "excluded_ids": sorted(ids), "excluded_profiles": sorted(profiles), "excluded_names": sorted(names)}
    groups = {}
    try:
        async def collect(title, location, count):
            payload = {"keywords": [title], "locations": [location], "maxItems": count,
                       "enrichment": "listing", "postedWithin": "r604800", "autoFanOut": False}
            async with gate:
                try:
                    records = await provider.actor(raw["source"], payload, limit=count)
                    return {"input": payload, "records": records, "error": None}
                except DiscoveryError as exc:
                    return {"input": payload, "records": [], "error": exc.reason}
        for count in (20, 50):
            batches = await asyncio.gather(*(collect(title, location, count) for title, location in SEARCHES))
            raw["batches"].extend(batches)
            raw["provider_usage"] = provider.usage
            (FOLDER / "pool.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False))
            for batch in batches:
                for row in batch["records"]:
                    try:
                        url = normalize_job_url(row.get("jobUrl", ""))
                        profile = company_profile(row.get("companyUrl", ""))
                    except DiscoveryError:
                        continue
                    if (not row.get("companyName") or url.rstrip("/").split("/")[-1] in ids
                            or profile in profiles or name_key(row["companyName"]) in names):
                        continue
                    groups.setdefault(profile, {})[url] = row["companyName"]
            print(f"Collected {sum(len(b['records']) for b in raw['batches'])} records; {len(groups)} eligible untested companies.", flush=True)
            if len(groups) >= 20:
                break
        if len(groups) < 20:
            raise SystemExit("Insufficient eligible companies after the predeclared expansion.")
        rng = random.Random(SEED)
        selected = []
        for profile in rng.sample(sorted(groups), 20):
            url = rng.choice(sorted(groups[profile]))
            selected.append({"url": url, "company": groups[profile][url], "company_profile": profile})
        manifest = {"created_at": now(), "seed": SEED, "sampling_unit": "company_profile_then_job",
                    "eligible_company_count": len(groups), "eligible_pool": groups,
                    "urls": [row["url"] for row in selected], "selected": selected,
                    "protocol_sha256": hashlib.sha256((FOLDER / "PROTOCOL.md").read_bytes()).hexdigest()}
        (FOLDER / "sample.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        (FOLDER / "URLS.md").write_text("# Fresh sample — frozen before agent execution\n\n" +
                                       "\n".join(f"{i}. **{row['company']}** — {row['url']}" for i, row in enumerate(selected, 1)) + "\n")
        print("Frozen 20 URLs from 20 previously untested company profiles.", flush=True)
    finally:
        await provider.close()


asyncio.run(main())
