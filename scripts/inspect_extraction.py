"""Inspect public extraction fields from existing actor runs without starting new actors."""
import argparse
import asyncio
import html
import json
import re
from pathlib import Path

from app.config import Settings
from app.providers import ApifyProvider


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("result")
    args = parser.parse_args()
    result = json.loads(Path(args.result).read_text())
    provider = ApifyProvider(Settings())
    try:
        for usage in result["provider_usage"]:
            run = (await provider.request("GET", f"actor-runs/{usage['run_id']}"))["data"]
            records = await provider.request("GET", f"datasets/{run['defaultDatasetId']}/items", params={"limit": 1})
            for record in records:
                descriptions = " ".join(str(record.get(key, "")) for key in (
                    "description", "companyDescription", "descriptionText", "descriptionHtml"))
                print(json.dumps({"actor": usage["actor"], "fields": list(record),
                                  "name": record.get("companyName", record.get("name")),
                                  "website": record.get("website", record.get("companyWebsite")),
                                  "description_urls": sorted(set(re.findall(r'https?://[^\s<>"\)]+', html.unescape(descriptions))))}, indent=2))
    finally:
        await provider.close()


asyncio.run(main())
