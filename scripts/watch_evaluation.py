"""Wait for a batch of evaluation artifacts; never rerun or alter attempts."""
import argparse
import json
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--until", type=int, default=20)
parser.add_argument("--timeout", type=int, default=600)
parser.add_argument("--directory", type=Path, default=Path("evaluation/results"))
parser.add_argument("--start", type=int, default=1)
args = parser.parse_args()
deadline = time.monotonic() + args.timeout
reported = set()
while time.monotonic() < deadline:
    for index in range(1, 21):
        file = args.directory / f"run-{index:02}.json"
        if not file.exists():
            continue
        try:
            run = json.loads(file.read_text())
        except ValueError:
            continue
        if not run.get("finished_at") or index in reported:
            continue
        reported.add(index)
        if index < args.start:
            continue
        print(json.dumps({"index": index, "company": run.get("company_name"), "status": run["status"],
                          "jobs_url": run.get("jobs_url"), "reason": run.get("failure_reason"),
                          "seconds": run.get("duration_ms", 0) / 1000,
                          "run_id": run["run_id"], "ats_resolution": run.get("ats_resolution", {}),
                          "verification": run.get("verification")}), flush=True)
    if len(reported) >= args.until:
        break
    time.sleep(5)
print(f"Completed artifacts observed: {len(reported)}/20")
