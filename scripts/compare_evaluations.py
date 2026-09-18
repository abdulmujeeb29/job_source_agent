"""Compare reviewed full evaluations and verify the baseline has not been changed."""
import hashlib
import json
from pathlib import Path

baseline = Path("evaluation/results")
postfix = Path("evaluation/postfix-v2")
hashes = json.loads(Path("evaluation/baseline-artifacts.sha256.json").read_text())
changed = [name for name, digest in hashes.items()
           if hashlib.sha256((baseline / name).read_bytes()).hexdigest() != digest]
if changed:
    raise SystemExit("Baseline artifacts changed: " + ", ".join(changed))
reviews = [json.loads((folder / "review.json").read_text()) for folder in (baseline, postfix)]
counts = [0, 0]
recovered, regressed, rows = [], [], []
for index in range(1, 21):
    results = [json.loads((folder / f"run-{index:02}.json").read_text()) for folder in (baseline, postfix)]
    if results[0]["input_url"] != results[1]["input_url"]:
        raise SystemExit("Input mismatch between evaluations.")
    passed = []
    for position, run in enumerate(results):
        review = reviews[position].get(str(index), {})
        if not run.get("finished_at") or not isinstance(review.get("accepted"), bool):
            raise SystemExit("Both full runs and reviews must be complete before comparison.")
        accepted = run["status"] == "succeeded" and review["accepted"]
        counts[position] += int(accepted)
        passed.append(accepted)
    company = results[1].get("company_name") or results[0].get("company_name") or "Unknown"
    if passed == [False, True]:
        recovered.append(f"{index}: {company}")
    if passed == [True, False]:
        regressed.append(f"{index}: {company}")
    rows.append(f"| {index} | {company.replace('|', '/')} | {'success' if passed[0] else 'failure'} | {'success' if passed[1] else 'failure'} |")
text = f"""# Baseline versus post-fix evaluation

| Evaluation | Reviewed successes | Rate |
|---|---:|---:|
| Original frozen baseline | {counts[0]}/20 | {counts[0] / 20:.0%} |
| Post-fix full rerun, same inputs | {counts[1]}/20 | {counts[1] / 20:.0%} |

**The post-fix sample is not held out.** The failures informed development, and
all 20 inputs were rerun independently afterward. No earlier successes were carried
forward. Review was performed by the OpenCode assistant, not an independent human.

Original baseline artifact hashes: unchanged.

- Recovered: {', '.join(recovered) or 'none'}.
- Regressed: {', '.join(regressed) or 'none'}.

| # | Company | Baseline | Post-fix |
|---|---|---|---|
""" + "\n".join(rows) + "\n"
Path("evaluation/COMPARISON.md").write_text(text)
print(text)
