"""Pure reproducible sampling; no network or agent calls."""
import hashlib
import json
import platform
import random

from app.schemas import DiscoveryError
from app.urls import normalize_job_url

SEED = 20260916
DEVELOPMENT_IDS = {"4427787182", "4454956346", "4461550377", "4460752941"}
SEARCHES = [("Software Engineer", "United States"), ("Product Manager", "United Kingdom"),
            ("Data Analyst", "Germany"), ("Sales Manager", "Canada"), ("Operations Manager", "India")]


def sample_records(records: list[dict]) -> dict:
    pool, invalid = set(), 0
    for row in records:
        try:
            url = normalize_job_url(row.get("jobUrl", row.get("linkedinUrl", "")))
        except DiscoveryError:
            invalid += 1
            continue
        if url.rstrip("/").split("/")[-1] not in DEVELOPMENT_IDS:
            pool.add(url)
    ordered = sorted(pool)
    if len(ordered) < 20:
        raise ValueError("Fewer than 20 eligible unique URLs; revise protocol before further collection.")
    return {"seed": SEED, "python_version": platform.python_version(), "pool": ordered,
            "invalid_record_count": invalid, "pool_sha256": hashlib.sha256(json.dumps(ordered).encode()).hexdigest(),
            "urls": random.Random(SEED).sample(ordered, 20)}
