"""Explicit paid candidate collection. Run only after development validation."""
import asyncio
import hashlib
import json
from pathlib import Path

from app.config import Settings
from app.providers import ApifyProvider
from app.schemas import now
from evaluation.sample import SEARCHES, sample_records


async def main():
    folder = Path("evaluation/results")
    folder.mkdir(exist_ok=True)
    raw_file, manifest_file = folder / "pool.json", folder / "sample.json"
    if raw_file.exists() or manifest_file.exists():
        raise SystemExit("Collection already exists; preserve it rather than overwriting.")
    provider = ApifyProvider(Settings())
    raw = {"collected_at": now(), "batches": [], "provider_usage": []}
    try:
        # Resolve actor's published input schema to avoid silently ignoring a recency filter.
        actor = "piotrv1001/linkedin-jobs-search-scraper"
        info = await provider.request("GET", f"acts/{actor.replace('/', '~')}")
        build_id = info["data"].get("taggedBuilds", {}).get("latest", {}).get("buildId")
        if not build_id:
            raise SystemExit("Actor build ID unavailable; inspect schema before collecting.")
        document = await provider.request("GET", f"actors/{info['data']['id']}/builds/{build_id}/openapi.json")
        schema = document["components"]["schemas"]["inputSchema"]
        values = schema.get("properties", {}).get("postedWithin", {}).get("enum", [])
        if "r2592000" not in values:
            raise SystemExit("Could not validate postedWithin month enum. Inspect actor schema before running collection.")
        raw["actor_build_id"] = build_id
        for title, location in SEARCHES:
            payload = {"keywords": [title], "locations": [location], "maxItems": 20,
                       "enrichment": "listing", "postedWithin": "r2592000", "autoFanOut": False}
            records = await provider.actor(actor, payload, limit=20)
            raw["batches"].append({"input": payload, "records": records})
            raw["provider_usage"] = provider.usage
            raw_file.write_text(json.dumps(raw, indent=2))
        manifest = sample_records([r for batch in raw["batches"] for r in batch["records"]])
        manifest["created_at"] = now()
        manifest["protocol_sha256"] = hashlib.sha256(Path("evaluation/PROTOCOL.md").read_bytes()).hexdigest()
        manifest_file.write_text(json.dumps(manifest, indent=2))
        print(f"Saved {len(manifest['pool'])} unique candidates and a fixed 20-URL sample.")
    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
