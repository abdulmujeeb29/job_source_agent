"""Record an explicit review decision after inspecting the run and its evidence."""
import argparse
import json
import shutil
from pathlib import Path

from app.schemas import now

parser = argparse.ArgumentParser()
parser.add_argument("index", type=int)
parser.add_argument("--decision", choices=["accept", "reject"], required=True)
parser.add_argument("--note", required=True)
parser.add_argument("--reviewer", default="OpenCode assistant — evidence review")
parser.add_argument("--directory", type=Path, default=Path("evaluation/results"))
parser.add_argument("--listing-verified", action="store_true",
                    help="For a rejected final destination, separately confirm a valid company-listing fallback.")
args = parser.parse_args()
folder = args.directory
run = json.loads((folder / f"run-{args.index:02}.json").read_text())
if not run.get("finished_at"):
    raise SystemExit("Run is not complete.")
accepted = args.decision == "accept"
if accepted and run["status"] != "succeeded":
    raise SystemExit("Cannot accept a failed agent result as a success.")
path = folder / "review.json"
reviews = json.loads(path.read_text()) if path.exists() else {}
entry = {"accepted": accepted, "reviewer": args.reviewer, "at": now(), "notes": args.note}
entry["listing_verified"] = accepted or args.listing_verified
entry["ats_resolution_status"] = run.get("ats_resolution", {}).get("status", "not_discovered")
if entry["listing_verified"] and run["status"] != "succeeded":
    raise SystemExit("A failed run cannot be recorded as a verified listing result.")
if entry["listing_verified"] and (screenshot := run.get("verification", {}).get("screenshot")):
    source = Path("data/artifacts") / run["run_id"] / Path(screenshot).name
    destination = folder / "screenshots" / f"{args.index:02}.png"
    destination.parent.mkdir(exist_ok=True)
    shutil.copyfile(source, destination)
    entry["screenshot"] = str(destination.relative_to(folder))
reviews[str(args.index)] = entry
path.write_text(json.dumps(reviews, indent=2, ensure_ascii=False))
print(f"Recorded {args.decision} for input {args.index}.")
