"""Validate the transcribed candidate pool using job extraction only, without LLM/browser discovery."""
import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

from app.config import Settings
from app.providers import ApifyProvider
from app.schemas import DiscoveryError, now
from app.urls import normalize_job_url
from evaluation.sample import DEVELOPMENT_IDS

FOLDER = Path("evaluation/gemini-candidates-20260917")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--structure-only", action="store_true")
    args = parser.parse_args()
    output = FOLDER / "validation.json"
    if output.exists():
        raise SystemExit("Validation already recorded; preserve it rather than overwriting.")
    document = json.loads((FOLDER / "candidates.json").read_text())
    previous = set(DEVELOPMENT_IDS)
    previous.update(url.rstrip("/").split("/")[-1] for url in json.loads(
        Path("evaluation/results/sample.json").read_text())["urls"])
    rows, urls = [], []
    for index, claim in enumerate(document["rows"], 1):
        row = {"index": index, **claim}
        try:
            row["url"] = normalize_job_url(f"https://www.linkedin.com/jobs/view/{claim['id']}/")
            row["syntax_valid"] = True
            urls.append(row["url"])
        except DiscoveryError:
            row.update(url=None, syntax_valid=False)
        row["previously_tested_id"] = claim["id"] in previous
        rows.append(row)
    inputs = list(dict.fromkeys(urls))
    analysis = {"started_at": now(), "document_claimed_count": document["claimed_total"],
                "actual_rows": len(rows), "unique_valid_urls": len(inputs),
                "duplicate_rows": len(urls) - len(inputs),
                "overlap_with_previous_tests": sum(r["previously_tested_id"] for r in rows),
                "claimed_status_counts": dict(Counter(r["status_claim"] for r in rows)),
                "request": {"searchUrls": inputs}, "records": [], "provider_error": None}
    (FOLDER / "validation_request.json").write_text(json.dumps(analysis, indent=2))
    print(json.dumps({k: analysis[k] for k in ("actual_rows", "unique_valid_urls", "duplicate_rows", "overlap_with_previous_tests")}), flush=True)
    if args.structure_only:
        return
    provider = ApifyProvider(Settings())
    try:
        try:
            analysis["records"] = await provider.actor(provider.settings.apify_job_actor,
                                                        analysis["request"], limit=len(inputs) + 5)
        except DiscoveryError as exc:
            analysis["provider_error"] = {"code": exc.code, "reason": exc.reason}
            # A timed-out/failed actor can still have produced useful partial data.
            if provider.usage:
                try:
                    run = (await provider.request("GET", f"actor-runs/{provider.usage[-1]['run_id']}"))["data"]
                    dataset = run.get("defaultDatasetId")
                    if dataset:
                        analysis["records"] = await provider.request("GET", f"datasets/{dataset}/items",
                                                                     params={"limit": len(inputs) + 5})
                except DiscoveryError as retrieval_error:
                    analysis["partial_read_error"] = retrieval_error.reason
    finally:
        analysis["provider_usage"] = provider.usage
        await provider.close()
    for row in rows:
        matches = [record for record in analysis["records"] if str(record.get("jobId", "")) == row["id"]]
        usable = [record for record in matches if all(isinstance(record.get(key), str) and record[key].strip()
                                                      for key in ("jobTitle", "companyName", "companyUrl"))]
        record = usable[0] if usable else (matches[0] if matches else {})
        row.update(extractable=bool(usable), observed_company=record.get("companyName"),
                   observed_title=record.get("jobTitle"), observed_company_url=record.get("companyUrl"),
                   observed_location=record.get("jobLocation"), posted_time_ago=record.get("postedTimeAgo"),
                   open_closed_state="not_verified")
    analysis.update(finished_at=now(), rows=rows, extractable_count=sum(r["extractable"] for r in rows))
    output.write_text(json.dumps(analysis, indent=2, ensure_ascii=False))
    lines = ["# Gemini PDF candidate validation", "", f"Rows: **{len(rows)}**, not {document['claimed_total']}. "
             f"Distinct valid URLs: **{len(inputs)}**. Prior-ID overlap: **{analysis['overlap_with_previous_tests']}**.", "",
             f"Matching job records with company/title/profile: **{analysis['extractable_count']}/{len(rows)}**.", "",
             "This is extraction availability, not an agent success rate or proof that postings are active. "
             "Forum citations and the PDF's status claims were not independently verified.", ""]
    if analysis["provider_error"]:
        lines += [f"Provider error: {analysis['provider_error']['reason']}. Missing records may reflect an incomplete batch.", ""]
    lines += ["| # | URL | PDF company | Observed company | Observed title | Extractable | PDF status claim |",
              "|---|---|---|---|---|---|---|"]
    for row in rows:
        values = [row["index"], row["url"], row["company_claim"], row["observed_company"] or "—",
                  row["observed_title"] or "—", "yes" if row["extractable"] else "no record confirmed", row["status_claim"]]
        lines.append("| " + " | ".join(str(v).replace("|", "\\|").replace("\n", " ") for v in values) + " |")
    (FOLDER / "VALIDATION.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"extractable_count": analysis["extractable_count"], "provider_error": analysis["provider_error"],
                      "report": str(FOLDER / "VALIDATION.md")}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
