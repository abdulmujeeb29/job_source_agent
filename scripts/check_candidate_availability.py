"""Short bounded public-API checks of unresolved PDF inputs; no careers discovery."""
import argparse
import asyncio
import html
import json
import re
from collections import Counter
from pathlib import Path

import httpx

from app.schemas import now

FOLDER = Path("evaluation/gemini-candidates-20260917")


def clean(value):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--extracted", action="store_true", help="Check the four records already returned by Apify.")
    args = parser.parse_args()
    output = FOLDER / ("guest_checks_extracted.json" if args.extracted else "guest_checks.json")
    if output.exists():
        raise SystemExit("Checks already recorded; refusing to overwrite.")
    validation = json.loads((FOLDER / "validation.json").read_text())
    unresolved = [row for row in validation["rows"] if row["extractable"] == args.extracted]
    semaphore = asyncio.Semaphore(4)
    async with httpx.AsyncClient(timeout=10, follow_redirects=True, trust_env=False,
                                 headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"}) as client:
        async def check(row):
            result = {"id": row["id"], "index": row["index"], "checked_at": now(),
                      "endpoint": f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{row['id']}"}
            async with semaphore:
                try:
                    response = await client.get(result["endpoint"])
                    result["http_status"] = response.status_code
                    result["response_url"] = str(response.url)
                    title = re.search(r'<h[12][^>]*class=[\"\'][^\"\']*(?:top-card-layout__title|topcard__title)[^\"\']*[\"\'][^>]*>(.*?)</h[12]>', response.text, re.S)
                    company = re.search(r'<a[^>]*class=[\"\'][^\"\']*topcard__org-name-link[^\"\']*[\"\'][^>]*>(.*?)</a>', response.text, re.S)
                    if response.status_code == 200 and title and company:
                        result.update(status="public_job_content", title=clean(title[1]), company=clean(company[1]),
                                      closed_marker_observed="no longer accepting applications" in clean(response.text).lower())
                    elif response.status_code in {404, 410}:
                        result["status"] = "not_available_via_guest_endpoint"
                    elif response.status_code in {401, 403, 429, 999}:
                        result["status"] = "access_limited"
                    else:
                        result["status"] = "unconfirmed_response"
                except httpx.RequestError as exc:
                    result.update(status="request_failed", error_type=type(exc).__name__)
            return result
        results = await asyncio.gather(*(check(row) for row in unresolved))
    report = {"completed_at": now(), "concurrency": 4, "timeout_seconds": 10, "retries": 0,
              "note": "Guest endpoint availability is not proof that a posting never existed. Lack of a closed marker does not prove it is active.",
              "counts": dict(Counter(row["status"] for row in results)), "results": results}
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2, ensure_ascii=False))


asyncio.run(main())
