# Random 20-URL evaluation protocol — version 2

Written before candidate collection and before any evaluation run. Finish live
development validation before freezing the sample/build. Local evaluation is
authorized; deployment is a separate later step.

## Population and selection

Source: `piotrv1001/linkedin-jobs-search-scraper` on Apify. Retrieve up to 20 jobs for each
of the following five fixed searches, in this order:

1. Software Engineer — United States
2. Product Manager — United Kingdom
3. Data Analyst — Germany
4. Sales Manager — Canada
5. Operations Manager — India

Use `postedWithin: "r2592000"`, `enrichment: "listing"`, `autoFanOut: false` and
`maxItems: 20`. The actor uses date sorting internally; its schema exposes no sort
parameter. The recency enum was confirmed in published OpenAPI build
`N5XNPfkzwYA2b4dMs`. Before collection, validate the current build's enum and record
the exact input/build.
No company, ATS, workplace, salary, or easy-apply filters.

Target: 100 records before deduplication. Retain raw provider responses, run IDs,
exact inputs, and retrieval timestamps. Canonicalize job URLs and deduplicate by
job ID. Exclude development job IDs `4427787182`, `4454956346`, `4461550377`, and
`4460752941` (Harvey, Anthropic, Stripe, Netflix). Do not discard unavailable jobs
based on later extraction results. Report invalid-source-record counts.

Sort eligible canonical URLs lexicographically. Draw 20 without replacement with
Python `random.Random(20260916).sample(pool, 20)`. Record Python version and SHA-256
of the pool and protocol. If fewer than 20 remain, stop; revise the protocol with
an explanation before collecting more, without inspecting agent outcomes.

This is a random sample of this defined search pool, not a random sample of all
LinkedIn. It has role, country, recency, language, and source-ranking bias. Repeated
companies are allowed; report the unique-company count after extraction.

### Pre-collection revision record

Version 1 proposed `harvestapi/linkedin-job-search`. A development selection attempt
returned HTTP 403 requiring additional full-account actor permission. No sample
was collected and no evaluation outcomes existed. Version 2 switches to the
FalconScrape actor above while retaining the five searches, pool target, month
window, seed, deduplication and denominator rules. The three additional development
IDs were selected before their agent outcomes using the company-jobs actor; their
selection is recorded in `evaluation/development.json`.

## Execution

Freeze source/config fingerprints, dependency lock, browser/CLI versions, sample,
and protocol before running. Use one normal bounded agent run per input, serially,
without result caching. Record the environment as local or deployed explicitly.
Run all 20 even when an individual input fails. Account-level auth failure is a
preflight blocker, not a reason to spend on 20 known-broken runs.

Save per-input JSON before advancing. A resumed runner must not overwrite existing
results. Preserve interrupted attempts and identify any operational reruns. Do not
edit implementation during the frozen run or replace failures with new URLs.

## Scoring and manual review

Primary: manually verified jobs-collection successes / **20** × 100.

For every claimed success, inspect company identity, the observed navigation path,
collection content and sampled role link. Record reviewer, timestamp, accepted
true/false, and notes in `review.json`. Until all 20 are adjudicated, label the
report preliminary and do not call model success labels a verified success rate.

Retain `no_openings`, expired jobs, provider failures, blocked navigation, timeouts,
and incorrect destinations as non-successes in the primary denominator. Report
agent status separately from reviewer decisions, with timing and failure categories.

If changed code is evaluated on the same sample, preserve the original output and
label the new run post-fix/non-held-out. No cherry-picking successful reruns.
