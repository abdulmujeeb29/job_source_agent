"""Publish a like-for-like listing comparison plus the new upstream diagnostic."""
import hashlib
import json
from pathlib import Path

folders = [Path("evaluation/results"), Path("evaluation/postfix-v2"), Path("evaluation/newest-v3")]
for folder, manifest in [
    (folders[0], Path("evaluation/baseline-artifacts.sha256.json")),
    (folders[1], Path("evaluation/postfix-v2-source.artifacts.sha256.json")),
]:
    for name, digest in json.loads(manifest.read_text()).items():
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest:
            raise SystemExit(f"Earlier evaluation artifact changed: {folder / name}")

samples = [json.loads((folder / "sample.json").read_text())["urls"] for folder in folders]
if not (samples[0] == samples[1] == samples[2]) or len(samples[0]) != 20:
    raise SystemExit("All evaluations must use the identical 20 inputs.")

totals, current_resolved = [], 0
for folder in folders:
    reviews = json.loads((folder / "review.json").read_text())
    count = 0
    for index in range(1, 21):
        run = json.loads((folder / f"run-{index:02}.json").read_text())
        review = reviews[str(index)]
        if not run.get("finished_at") or not isinstance(review.get("accepted"), bool):
            raise SystemExit("All executions and reviews must be complete.")
        listing = run["status"] == "succeeded" and review.get("listing_verified", review["accepted"])
        count += int(listing)
        if folder == folders[2]:
            current_resolved += int(listing and review["accepted"] and run.get("ats_resolution", {}).get("status") != "unverified")
    totals.append(count)

text = f"""# All three completed evaluations

Same 20 inputs, one full run per input in each batch. The later batches are not
held out because these inputs and failures were already known during development.

| Build | Correct company jobs-list pages | Rate |
|---|---:|---:|
| Original baseline | {totals[0]}/20 | {totals[0]/20:.0%} |
| v0.2 post-fix | {totals[1]}/20 | {totals[1]/20:.0%} |
| v0.3 newest build | {totals[2]}/20 | {totals[2]/20:.0%} |

For v0.3, **{current_resolved}/20 ({current_resolved/20:.0%})** also completed without an
unverified upstream/ATS flag. The remaining **{totals[2]-current_resolved}** verified company
collections were returned with such a flag. That stricter diagnostic was fixed
before this run and was not measured in the earlier reports. It must not be
compared directly with their broader listing success rates.

An unresolved ATS flag does not itself mean the returned company jobs page is
incorrect. For example, www/non-www handling and a platform pointing back to a
corporate collection can produce unnecessary or ambiguous handoffs. Those are
recorded as unresolved under the conservative protocol, not silently overridden.

Previous evaluation artifact hashes: unchanged. Review was performed by the
OpenCode assistant using browser evidence/screenshots and targeted live checks;
it is not an independent human audit. No application source code changed during
the newest batch. All failures and first attempts are retained.
"""
(folders[2] / "COMPARISON.md").write_text(text)
print(text)
