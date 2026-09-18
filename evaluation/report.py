"""Render all sampled outcomes; manual adjudication is required for verified rate."""
import argparse
import json
import statistics
from collections import Counter
from pathlib import Path


def build_report(sample, runs, reviews, kind="baseline"):
    if len(sample["urls"]) != 20:
        raise ValueError("Report denominator must be exactly 20.")
    accepted = 0
    complete = True
    rows = []
    for index, url in enumerate(sample["urls"], 1):
        run = runs.get(index, {})
        review = reviews.get(str(index), {})
        reviewed = isinstance(review.get("accepted"), bool) and bool(review.get("reviewer")) and bool(review.get("at"))
        complete = complete and reviewed and bool(run)
        success = reviewed and review["accepted"] and run.get("status") == "succeeded"
        accepted += int(success)
        seconds = round(run["duration_ms"] / 1000, 1) if run.get("duration_ms") is not None else "—"
        values = [index, url, run.get("company_name") or "—", run.get("status", "not_run"),
                  run.get("jobs_url") or "—", seconds, "yes" if success else ("no" if reviewed else "pending"),
                  review.get("notes") or run.get("failure_reason") or "—"]
        rows.append("| " + " | ".join(str(v).replace("|", "\\|").replace("\n", " ") for v in values) + " |")
    summary = (f"Verified success rate: **{accepted}/20 ({accepted / 20:.0%})**." if complete else
               f"**Preliminary — manual review or runs incomplete.** Currently {accepted}/20 adjudicated successes; no final rate claimed.")
    durations = [r["duration_ms"] / 1000 for r in runs.values() if r.get("duration_ms") is not None]
    statuses = dict(Counter(r.get("status", "unknown") for r in runs.values()))
    companies = {r.get("company_linkedin_url") for r in runs.values() if r.get("company_linkedin_url")}
    requests = sum(r.get("model_usage", {}).get("requests", 0) for r in runs.values())
    tokens = sum(sum(r.get("model_usage", {}).get(k, 0) for k in ("input_tokens", "output_tokens")) for r in runs.values())
    metrics = f"\n\n- Agent outcomes: `{statuses}`\n- Distinct extracted companies: {len(companies)}\n- Model requests: {requests}; input + output tokens: {tokens:,}."
    if durations:
        metrics += f"\n- Median run time: {statistics.median(durations):.1f}s; maximum: {max(durations):.1f}s."
    heading = "# Post-fix evaluation — same 20 inputs, not held out\n\n" if kind == "post-fix" else "# Evaluation results\n\n"
    return heading + summary + metrics + "\n\n| # | Input | Company | Agent status | Jobs URL | Seconds | Reviewed success | Notes |\n|---|---|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=Path("evaluation/results"))
    args = parser.parse_args()
    folder = args.directory
    sample = json.loads((folder / "sample.json").read_text())
    runs = {i: json.loads(path.read_text()) for i in range(1, 21)
            if (path := folder / f"run-{i:02}.json").exists()}
    review_file = folder / "review.json"
    if not review_file.exists():
        review_file.write_text(json.dumps({str(i): {"accepted": None, "reviewer": "", "at": "", "notes": ""}
                                          for i in range(1, 21)}, indent=2))
    reviews = json.loads(review_file.read_text())
    kind = json.loads((folder / "freeze.json").read_text())["configuration"].get("evaluation_kind", "baseline")
    (folder / "REPORT.md").write_text(build_report(sample, runs, reviews, kind=kind))
    print(f"Report written to {folder}/REPORT.md")


if __name__ == "__main__":
    main()
