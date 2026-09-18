"""Report listing correctness separately from completed upstream-board resolution."""
import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

from app.destinations import is_ats_url


def build_report(sample, runs, reviews, kind="post-fix"):
    if len(sample["urls"]) != 20 or len(set(sample["urls"])) != 20:
        raise ValueError("Exactly 20 distinct inputs required.")
    counts = Counter()
    rows = []
    complete = True
    for index, url in enumerate(sample["urls"], 1):
        run, review = runs.get(index, {}), reviews.get(str(index), {})
        reviewed = (isinstance(review.get("accepted"), bool)
                    and isinstance(review.get("listing_verified"), bool)
                    and bool(review.get("reviewer")) and bool(review.get("at")))
        complete = complete and reviewed and bool(run.get("finished_at"))
        status = run.get("ats_resolution", {}).get("status", "not_discovered")
        listing = reviewed and review["listing_verified"] and run.get("status") == "succeeded"
        resolved = listing and review["accepted"] and status != "unverified"
        counts["listing"] += int(listing)
        counts["resolved"] += int(resolved)
        if resolved:
            if is_ats_url(run.get("jobs_url") or ""):
                counts["ats_board"] += 1
            elif status == "company_hosted":
                counts["company_hosted"] += 1
            else:
                counts["other_collection"] += 1
        elif listing:
            counts["unverified_fallback"] += 1
        values = [index, url, run.get("company_name") or "—", run.get("status", "not_run"),
                  run.get("jobs_url") or "—", status,
                  "yes" if listing else ("no" if reviewed else "pending"),
                  "yes" if resolved else ("no" if reviewed else "pending"),
                  review.get("notes") or run.get("failure_reason") or "—"]
        rows.append("| " + " | ".join(str(v).replace("|", "\\|").replace("\n", " ") for v in values) + " |")
    heading = ("# Fresh-company evaluation — 20 previously untested company profiles\n\n" if kind == "fresh"
               else "# v0.3 full rerun — same 20 URLs, not held out\n\n")
    if complete:
        summary = (f"**Final destination resolved: {counts['resolved']}/20 ({counts['resolved']/20:.0%}).**\n\n"
                   f"Company-listing verified (broader criterion): **{counts['listing']}/20 ({counts['listing']/20:.0%})**.\n\n"
                   f"- Verified ATS-hosted final boards: {counts['ats_board']}\n"
                   f"- ATS-designated company-hosted collections: {counts['company_hosted']}\n"
                   f"- Other verified company collections: {counts['other_collection']}\n"
                   f"- Verified company-listing fallbacks with unverified ATS resolution: {counts['unverified_fallback']}\n")
        if kind == "fresh":
            summary = (f"**Verified company jobs collections (primary): {counts['listing']}/20 ({counts['listing']/20:.0%}).**\n\n"
                       f"Additional diagnostic — completed without an unresolved ATS flag: {counts['resolved']}/20 ({counts['resolved']/20:.0%}).\n\n"
                       f"Verified ATS-hosted boards: {counts['ats_board']}; valid company-listing fallbacks with an upstream warning: {counts['unverified_fallback']}.\n")
    else:
        summary = "**Preliminary: execution or evidence review is incomplete. No final success rate claimed.**\n"
    durations = [r["duration_ms"] / 1000 for r in runs.values() if r.get("duration_ms") is not None]
    requests = sum(r.get("model_usage", {}).get("requests", 0) for r in runs.values())
    tokens = sum(sum(r.get("model_usage", {}).get(k, 0) for k in ("input_tokens", "output_tokens")) for r in runs.values())
    metrics = f"\n- Model requests: {requests}; input + output tokens: {tokens:,}.\n"
    if durations:
        metrics += f"- Median recorded run duration: {statistics.median(durations):.1f}s; maximum: {max(durations):.1f}s.\n"
    sampling_note = ("This company-stratified recent-search sample was frozen before navigation and excludes previously tested company profiles/names. "
                     "Runs used three independent concurrent sessions; timing is not directly comparable to serial batches. See the accompanying PROTOCOL.md. "
                     if kind == "fresh" else "This previously used sample measures regression behavior, not unseen generalization. See `evaluation/NEWEST_PROTOCOL.md`. ")
    note = ("\nReview is by the OpenCode assistant using saved evidence/screenshots and targeted page inspection, "
            "not an independent human audit. " + sampling_note + "All 20 remain in each denominator.\n\n")
    table = "| # | Input | Company | Agent status | Final URL | ATS resolution | Listing verified | Final resolved | Review notes |\n|---|---|---|---|---|---|---|---|---|\n"
    return heading + summary + metrics + note + table + "\n".join(rows) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=Path("evaluation/newest-v3"))
    folder = parser.parse_args().directory
    sample = json.loads((folder / "sample.json").read_text())
    runs = {i: json.loads(p.read_text()) for i in range(1, 21)
            if (p := folder / f"run-{i:02}.json").exists()}
    review_file = folder / "review.json"
    if not review_file.exists():
        review_file.write_text(json.dumps({str(i): {"accepted": None, "listing_verified": None,
                                                   "reviewer": "", "at": "", "notes": ""}
                                          for i in range(1, 21)}, indent=2))
    kind = json.loads((folder / "freeze.json").read_text())["configuration"].get("evaluation_kind", "post-fix")
    report = build_report(sample, runs, json.loads(review_file.read_text()), kind=kind)
    (folder / "REPORT.md").write_text(report)
    print(f"Report written to {folder}/REPORT.md")


if __name__ == "__main__":
    main()
