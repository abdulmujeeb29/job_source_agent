# Baseline evaluation interpretation

- **Environment:** local macOS, Chrome 153, agent-browser 0.33.2, Playwright via CDP,
  Azure deployment `gpt-6-astra`. Exact source/configuration hashes are in `freeze.json`.
- **Sample:** 20 distinct job URLs selected from 100 unique candidates with seed
  `20260916`, under the predeclared version-2 protocol. No development job IDs were
  eligible. No failed input was replaced.
- **Outcome:** 11 successes, 9 failures; all 20 remain in the denominator.
- **Review:** OpenCode assistant inspected stored evidence and screenshots, with
  additional live browser checks for Affirm, Cint, and Flix. Review identity,
  timestamps, decisions and notes are in `review.json`. This is not an independent
  human evaluation; the submitter should review the report before presenting it.
- **Worldpay:** accepted the shared Global Payments jobs board because the observed
  Careers link on Worldpay's official site led directly to it. The board displayed
  actual listings. This association decision is explicitly noted in its review.
- **Overlays:** a consent/region modal appearing in a screenshot did not make the
  destination a failure when rendered listings and detail evidence were present.
  Affirm was reopened and the region modal dismissed to independently inspect the
  listings. No applications or interviews were initiated.

## Failure categories

| Category | Count | Inputs |
|---|---:|---|
| No official company website from enrichment | 2 | 10, 20 |
| Initial website navigation/network failure | 2 | 9, 11 |
| Evidence grounding failure | 2 | 2, 3 |
| Repeated action / no-progress cycle | 3 | 5, 7, 13 |

Some failures are implementation limitations rather than an absence of listings.
For example, Plaid's generic "See role" labels did not contain the adjacent role
title, so the strict verifier rejected an otherwise discovered collection. This
should motivate a general bounded-card-context improvement, not a Plaid mapping.
Company identity should also consider observed branding/title evidence carefully,
without accepting unrelated companies or generic ATS pages.

## Reproducibility and future iterations

`pool.json` retains exact search inputs, raw returned records and provider run IDs.
`sample.json` retains the unique pool, selected URLs and protocol/pool checksums.
Each `run-NN.json` retains its full trace, evidence, timings and token usage.
`screenshots/` contains representative original success screenshots; the full
per-step artifacts remain under local `data/artifacts/`.

The original baseline is final. If code is improved using these failures, any
rerun on these same URLs is a **post-fix, non-held-out evaluation** and must be
stored/reported separately. Do not combine successful reruns with this baseline
or describe the combined result as the original random evaluation.
