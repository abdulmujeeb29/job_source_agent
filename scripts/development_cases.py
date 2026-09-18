"""Select and run a small, explicit development set, separate from held-out sampling."""
import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.controller import Controller
from app.providers import ApifyProvider
from app.schemas import Run, now
from app.storage import Store
from app.urls import normalize_job_url


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--select", action="store_true")
    parser.add_argument("--case", type=int)
    args = parser.parse_args()
    settings = Settings()
    manifest = Path("evaluation/development.json")
    if args.select:
        if manifest.exists():
            raise SystemExit("Development selection already exists.")
        provider = ApifyProvider(settings)
        cases = []
        try:
            for company in ["Anthropic", "Stripe", "Netflix"]:
                payload = {"keywords": "Software Engineer", "companies": [company],
                           "maxItems": 1, "scrapeJobDetails": False, "autoFanOut": False}
                records = await provider.actor("piotrv1001/linkedin-company-jobs-scraper", payload, limit=1)
                cases.append({"requested_company": company, "input": payload, "records": records})
            manifest.write_text(json.dumps({"selected_at": now(), "cases": cases,
                                            "provider_usage": provider.usage}, indent=2))
        finally:
            await provider.close()
        print("Development selection saved; no agent outcomes have been used to select cases.")
        return
    store = Store(settings.data_dir / "runs.sqlite3")
    folder = settings.data_dir / "development"
    folder.mkdir(exist_ok=True)
    try:
        for index, case in enumerate(json.loads(manifest.read_text())["cases"], 1):
            if args.case and index != args.case:
                continue
            for row in case["records"]:
                url = normalize_job_url(row["jobUrl"])
                run = Run(run_id=uuid4().hex, input_url=url, normalized_input_url=url)
                await Controller(settings, store).execute(run)
                (folder / f"{index}-{run.run_id}.json").write_text(run.model_dump_json(indent=2))
                print(json.dumps({"company": run.company_name, "status": run.status, "jobs_url": run.jobs_url,
                                  "reason": run.failure_reason, "run_id": run.run_id, "seconds": run.duration_ms / 1000}), flush=True)
    finally:
        store.close()


if __name__ == "__main__":
    asyncio.run(main())
