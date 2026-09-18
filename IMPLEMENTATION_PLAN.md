# Job Source Agent — implementation and validation plan

## 1. Goal and definition of done

Build an independently deployable application that accepts a LinkedIn job-posting
URL and discovers the hiring company's actual jobs-list page through browser
navigation starting at the company website.

A successful run must include:

- Extracted company identity and the source of its website URL.
- A traceable path from that website to its jobs list, including external ATS links.
- Observed listing evidence: job titles, job-detail links, and relevant page text.
- Verification that the destination belongs to the intended company and is a jobs
  collection, rather than a homepage, marketing page, or individual job description.
- A timestamped result with navigation evidence and a working destination URL at
  the time of verification.

A careers page containing actual listings can also be the final jobs page. A list
with one opening can qualify if the page is demonstrably the jobs collection. An
explicit empty board is reported separately as `no_openings`, not counted as a
verified-listings success in the primary evaluation. A site failure must not be
interpreted as an empty board.

Submission completion means a deployed reviewer interface, a documented random
20-input evaluation with every result retained, and a walkthrough recording.
There is no promised 100% success rate or exhaustive coverage of the public web.

## 2. Selected architecture

```text
Web interface
    |
FastAPI: validate input -> create run -> expose progress/results
    |
Run controller + SQLite run/event store
    |
LinkedIn provider (Apify)
    | job URL -> company identity -> company website
    |
Isolated Chromium session for this run
    |
    +-- Astra Responses API: propose structured actions from observations
    +-- agent-browser: primary navigation and accessibility snapshots
    +-- Playwright over CDP: targeted inspection and verification evidence
    |
Verifier -> success / no_openings / explicit failure
    |
Persist result, evidence, timings, usage -> close browser
```

### Responsibilities

- **Apify:** retrieve a single LinkedIn job and enrich its company profile when
  needed. Validate the actor's input/output schema before integration. Never
  substitute an unrelated search result for the submitted job.
- **Astra:** interpret observations, select navigation actions, and assess semantic
  evidence. Use the Azure OpenAI v1 Responses endpoint and deployment
  `gpt-6-astra`; validate actual API access and structured output support first.
- **agent-browser:** open discovered URLs, snapshot, click, scroll, inspect tabs,
  and capture screenshots. Refresh references after every page-changing action.
- **Playwright:** inspect rendered content, links and frames, wait for specific
  content, and gather independent browser evidence for candidate verification.
  Targeted recovery actions are allowed only through the controller.
- **Controller:** validate proposed actions, serialize browser operations, enforce
  budgets, track progress, choose recovery paths, persist state, and clean up.
- **Verifier:** combine explicit rules with semantic assessment. Model confidence
  alone, an ATS hostname, or a `/careers` path is never sufficient for success.

### Sharing a browser

Launch one Chromium process per active run with a local CDP connection. Attach
agent-browser and Playwright to that process. Assign explicit session/run IDs and
track the active page by target identity/URL; do not assume each client's default
tab is the same. Treat tab creation, redirects, frame changes, and tab closure as
state changes requiring fresh observations.

One controller owns each session. Never run competing browser actions in parallel.
After Playwright changes a page, invalidate agent-browser references and snapshot
again. Close attachments and terminate the owned browser process in `finally`,
including cancellation, timeout, and error paths.

**Feasibility gate:** demonstrate attach, navigate, inspect, new-tab coordination,
and teardown with the pinned versions before building the main agent. If shared
CDP has a concrete limitation, document it and revise the adapter design before
proceeding; do not build two independent navigation loops.

### Application shape

Start with a single FastAPI process, a bounded asynchronous run queue, SQLite
persistence, and an artifact directory. Default to one active browser run; raise
concurrency only after measuring memory and session isolation. Mark in-flight runs
as interrupted after a restart rather than silently leaving them running.

Use a small server-rendered HTML/JavaScript interface with progress polling or SSE.
If SSE is used, reconnect using persisted event IDs. Avoid a separate frontend
deployment or distributed queue until demonstrated load requires it.

## 3. Contracts and result schema

Define typed contracts before provider and browser integration:

- `LinkedInProvider.extract(job_url) -> CompanyIdentity`
- `BrowserSession.observe() -> Observation`
- `BrowserSession.act(action) -> ActionOutcome`
- `ListingInspector.inspect(page) -> ListingEvidence`
- `Verifier.verify(identity, trail, evidence) -> VerificationDecision`

Result fields:

| Field | Purpose |
|---|---|
| `run_id`, `input_url`, `normalized_input_url` | Stable run/input identity |
| `status`, `stage` | Queued/running/terminal outcome and progress |
| `company_name`, `company_linkedin_url`, `company_website` | Extracted identity |
| `identity_sources` | Provider record/source provenance |
| `careers_url`, `jobs_url` | Discovered destinations, nullable until observed |
| `verification` | Outcome, rationale, evidence references, listing samples |
| `navigation_events` | Ordered observations, selected actions and outcomes |
| `failure_code`, `failure_reason` | Stage-specific explanation with partial results |
| `started_at`, `finished_at`, `duration_ms` | Timing |
| `model_usage`, `provider_usage`, `attempt_counts` | Usage and retry accounting |
| `config_version`, `build_revision` | Reproducibility |

Each navigation event records the source URL, action, observed target, destination
URL, timestamp, short decision rationale, and optional screenshot reference. Store
concise decision summaries rather than model chain-of-thought. Keep credentials
and authorization headers out of logs, artifacts, and browser subprocesses.

Failure codes include invalid input, job unavailable, extraction/provider error,
company ambiguous, website missing, navigation blocked, navigation exhausted,
verification failed, deadline exceeded, model error, browser error, interrupted,
and cancelled. `no_openings` is its own terminal outcome.

## 4. Runtime loop: discover, verify, recover

```text
validate input and create run
extract company identity; enrich website if necessary
open company website
while run remains within budget:
    observe current page, tabs, and available actions
    if page is a potential jobs list:
        inspect rendered listing evidence with Playwright
        verify company association and collection semantics
        if verified: persist success and stop
        if confirmed empty board: persist no_openings and stop
    ask Astra for one structured action based on current observations
    validate action against current refs/discovered URLs and allowed operations
    execute action; record outcome; refresh page state
    if blocked or no progress: apply a bounded recovery strategy
persist explicit failure if no terminal result was reached
always release browser resources
```

Recovery order should match the observed failure: refresh stale references, wait
for expected content, handle a visible menu/banner, inspect a frame or new tab,
then backtrack to another observed candidate link. Record redirects and link
provenance. Do not invent company domains, guess ATS tenants, or use company maps.

Initial configurable limits, to be tuned using development runs:

- Overall run deadline: 5 minutes, including extraction and browser work.
- Browser actions: 20; model calls: 24 maximum including verification.
- Page navigation timeout: 25 seconds, limited by the remaining run deadline.
- Provider/model transient retries: up to 2 per request, with backoff and
  `Retry-After` handling, also bounded by remaining time and total call limits.
- Unchanged page/action state: at most 2 repeats before backtracking or failure.
- Cancel runs explicitly; propagate cancellation into subprocess/API waits.

Record normalized URL, page-content fingerprint, and attempted actions to detect
cycles. A URL alone is insufficient because SPA content can change without it.
Never retry permanent errors indefinitely or keep searching until a false positive
can be labeled successful.

## 5. Engineering loop: implement, test, diagnose, improve

For each milestone:

1. Select a specific behavior and its acceptance criterion.
2. Implement the smallest complete slice.
3. Run relevant deterministic tests and inspect resulting evidence.
4. Run a targeted live development check when browser/provider behavior matters.
5. Classify failures: extraction, navigation, observation, verification,
   infrastructure, or genuinely unavailable source.
6. Fix the root cause and add a meaningful regression fixture where appropriate.
7. Repeat the affected tests until the criterion passes or a concrete blocker is
   documented. Broaden testing only for changes with wider impact.
8. Advance to the next milestone; keep test results and known limitations current.

No autonomous infinite edit/test loop: external failures need explicit stopping
conditions, and repeated paid API calls need recorded budgets. The goal is passing
acceptance criteria and truthful outcomes, not forcing every website to succeed.

Development URLs and the final evaluation sample are separate. Improve freely on
the development set; freeze the implementation before the held-out evaluation.

## 6. Test strategy and scenario matrix

Use pytest for controller/provider/verifier contracts and local browser fixtures
for real Chromium integration. Stub provider/model responses for repeatable
failure-path tests. Use real Azure/Apify calls only in explicitly enabled live
checks. Browser fixtures prove mechanics, not real-world generality.

| Area | Distinct scenarios | Expected assertion |
|---|---|---|
| Input | Numeric and slugged LinkedIn job URLs, query strings, supported regional hosts | Normalize without changing job identity |
| Invalid input | Wrong host/path, malformed ID, unsupported scheme | Reject before paid calls |
| Extraction | Website present; company profile enrichment required | Correct identity and source provenance |
| Missing source | Expired/deleted job, login wall, missing website, ambiguous company | Explicit failure; no guessed company/domain |
| Provider | Rate limit, timeout, transient 5xx, permanent 4xx, malformed output | Bounded appropriate retries and clear errors |
| Basic navigation | Header careers link, footer link, nested menu | Observed actions reach careers page |
| Dynamic navigation | SPA route, delayed content, menu requiring interaction | Fresh observations and correct waits |
| Overlays | Cookie banner, dismissible modal, covering element | Handle visible controls and continue |
| Destinations | Same tab, new tab, redirect chain, URL fragment | Correct active target and provenance |
| External ATS | Ashby, Greenhouse, Lever, Workday development examples | Follow observed company links; inspect actual content |
| Embedded/custom board | Same-origin iframe, cross-origin iframe, custom listings | Inspect accessible evidence; explain inaccessible cases |
| Listing load | Load-more, pagination, lazy content, search controls | Reach sufficient listing evidence without crawling every job |
| Language/layout | Non-English careers labels, icon menu, mobile layout | Reason from observations or fail explicitly |
| False positives | Culture page, blog mentioning jobs, talent community, individual role, generic ATS homepage | Reject as jobs collection |
| Company association | Wrong ATS tenant, recruiter/client ambiguity, unrelated job aggregator | Reject unsupported identity matches |
| Listing cardinality | Many roles, one-role collection, explicit zero openings | Success/success/no_openings respectively |
| Verification | Dead detail link, incomplete render, misleading heading | No success based solely on labels or URL |
| Agent behavior | Invalid tool arguments, invented URLs, stale refs, repeat clicks | Validate actions, refresh, detect cycles |
| Model | Timeout, rate limit, malformed structured output, refusal | Bounded recovery and typed failure |
| Shared browser | Attach both clients, tab switch, frame scope, page close | Consistent page identity; no competing operations |
| Lifecycle | Cancel, deadline, browser crash, process restart | Terminal state and browser cleanup |
| Public input | Private-network URL/redirect, page prompt injection, unsafe action | Enforce network/action boundaries |
| Session isolation | Two queued requests, separate cookies/tabs/artifacts | No cross-run state leakage |
| Web UI | Valid/invalid submit, progress reconnect, success, failure, cancellation | Accurate state and accessible result links |
| Persistence | Refresh result page, reconnect after completion, restart | Stored evidence/results remain readable |
| Deployment | Fresh image, browser dependencies, HTTPS, proxy timeouts, volume permissions | Remote end-to-end smoke test passes |

Include checks that untrusted page content cannot turn into shell commands,
credential access, application submission, or arbitrary backend requests. Limit
agent actions to navigation/inspection. Block private/local/metadata destinations
for browser and HTTP traffic at an appropriate network boundary; account for
redirects, subresources, DNS resolution, and externally attached CDP sessions.
Do not rely solely on model instructions or URL string checks.

### Live development set

Choose a small documented development set covering external ATS, custom/embedded
listings, and difficult navigation. Include at least one expected failure. Manually
review company association and listing evidence, rather than accepting the agent's
own success labels as ground truth. No development success-rate claim substitutes
for the required random 20-input evaluation.

## 7. Milestones and acceptance gates

### M0 — Configuration and hybrid-browser feasibility

- Validate local environment variable names without displaying secrets.
- Test one minimal Azure Responses request and structured action response.
- Select/validate Apify individual-job extraction and company enrichment actors.
- Pin compatible runtime/browser dependencies.
- Prove shared-CDP browser operations and cleanup on a local fixture.

**Exit:** working provider smoke checks and shared-browser integration check. Stop
and resolve missing permissions, schemas, or CDP limitations before expanding.

### M1 — Contracts, storage, and one complete flow

- Implement schemas, provider adapter, browser adapters, controller, and verifier.
- Persist run state and navigation events.
- Execute one real LinkedIn URL through to a verified jobs page.

**Exit:** inspectable end-to-end artifact produced without a hard-coded company
answer. The brief's Harvey example may be a development case, never a mapping.

### M2 — Generality and bounded recovery

- Implement the runtime recovery loop, cycle detection, cancellation, and limits.
- Add targeted inspection for frames, new tabs, delayed listings, and custom boards.
- Implement relevant positive/negative regression scenarios from the matrix.

**Exit:** deterministic contract/browser suites pass; live development outcomes
have been manually reviewed; unresolved limitations are documented.

### M3 — Reviewer interface

- Build URL submission, progress timeline, final links, evidence, and failure views.
- Add a run details endpoint and result JSON export.
- Enforce queue/concurrency limits and sensible public request limits.

**Exit:** complete success and failure flows work from the browser, including page
refresh and queued requests. No provider credentials are shipped to the frontend.

### M4 — Deploy and smoke-test

- Prepare a reproducible Dockerfile containing the Python application,
  agent-browser, Chromium, and required Linux libraries. Use ThalesOps' Dockerfile
  build option, confirmed available by the user.
- Connect the Part 2 GitHub repository to a separate application in ThalesOps.
- Configure runtime secrets, persistence, application port and health checks through
  the platform. Use ThalesOps deployment, HTTPS and domain routing.
- Test a real run on the deployed environment and verify cleanup/resource use.

**Exit:** reviewer-accessible HTTPS URL with the same workflow tested locally.

### M5 — Freeze and evaluate 20 random inputs

- Document selection rules and collect a candidate pool before agent evaluation.
- Freeze code, configuration, model deployment, dependency versions, and sample.
- Execute all 20 inputs and manually adjudicate their evidence.
- Publish per-input results, primary success rate, failures, timing, and usage.

**Exit:** reproducible sample manifest and complete report, with no discarded
failures or substitutions.

### M6 — Submission and walkthrough

- Finish setup/architecture/deployment documentation and known limitations.
- Record an end-to-end run, evidence, architecture, and all 20 evaluation outcomes.
- Include repository and deployed app links in submission materials.

**Exit:** independent runnable repository, public demo, evaluation report, video.

## 8. Evaluation protocol

Write `evaluation/PROTOCOL.md` before running the evaluation. Specify the source,
search queries, locations, posting window, retrieval timestamp, pool target size,
deduplication, eligibility, random algorithm, and seed before inspecting agent
outcomes. A practical pool target is 100 unique job IDs from predeclared searches;
if unavailable, report the actual pool and any protocol revision before sampling.

Save the raw pool, canonicalized unique job URLs, sample-generation script, seed,
and checksums. Draw 20 URLs uniformly without replacement using a recorded Python
version/seed. Exclude development job IDs according to the predeclared rule, but
do not filter by known ATS, company popularity, or anticipated ease. Multiple jobs
from the same company may occur; report unique-company count and sample bias.

Run the frozen build in the deployed environment, without cross-run result caches,
using the normal per-run retry policy. Count the first complete agent run for each
sampled URL. Log runner failures/interruption and any reruns explicitly; retain
original outcomes. Expired jobs and provider failures stay in the denominator.

Manually review the observed destination, identity, navigation path, and actual
listings for every success claim. Report both agent status and reviewer adjudication.

Primary metric: `manually verified listing successes / 20 * 100`.

Report `no_openings` separately, plus failure categories and run durations. If code
changes after evaluation, preserve the original report; label any full rerun as
post-fix and no longer held-out. Never replace failed URLs to improve the score.

## 9. Deployment through ThalesOps

The user has selected **ThalesOps, the deployment platform**, not merely a domain
name. Its public site, https://www.thalesops.com/, describes GitHub-connected
deployments to the user's server, stack detection, push-to-deploy, health-gated
blue-green deployment, rollback, managed PostgreSQL, automatic HTTPS/domain routing,
and monitoring. Use that platform as the deployment workflow.

### Platform workflow

1. Prepare the independent Part 2 repository and a Dockerfile with browser runtime
   dependencies, plus a `.dockerignore` that excludes secrets and local artifacts.
2. When requested, publish the repository to GitHub and connect it in ThalesOps.
3. Select the user's connected server, create a separate Part 2 application, and
   choose the Dockerfile build method.
4. Configure Azure/Apify environment variables, startup command, app port, health
   endpoint, persistence, and browser resource settings as supported by ThalesOps.
5. Deploy through the platform; inspect build logs and runtime health.
6. Use the platform-provided app URL or configure the desired custom hostname in
   ThalesOps. Confirm the actual assigned URL rather than assuming one.
7. Run a deployed end-to-end smoke test, then optionally enable push-to-deploy.

The user confirms ThalesOps supports both Nixpacks and Dockerfile builds. Select
Dockerfile for explicit, reproducible installation of browser binaries and Linux
dependencies. Install one compatible Chromium binary for both browser clients;
Playwright attaches over CDP rather than launching a second browser. Pin versions,
run the application as a non-root user, bind the HTTP server to `0.0.0.0` on the
configured app port, and keep CDP internal. Inject credentials at runtime, never
during image build.

The image packages the application but does not configure host resources or
persistence. Confirm Chromium launch permissions, persistent volumes, shared
memory, and long-running process behavior in ThalesOps settings. Smoke-test the
same image locally and after deployment before running the evaluation.

Application runtime requirements to configure through the platform:

- Linux container/VM with Chromium dependencies and sufficient shared memory.
- Start with roughly 2 vCPU/4 GB RAM and one active browser run as a sizing estimate;
  measure actual memory, CPU, and run latency before raising concurrency.
- ThalesOps-managed HTTPS/routing, suitable request limits, and SSE support if used.
- SQLite/artifact persistent volume and a documented artifact retention policy.
- Secrets injected at runtime; `.env`, keys, browser profiles, and private artifacts
  excluded from both Git and Docker build context.
- Internal-only CDP ports; browser egress isolation with public website access.
- Process supervision, health checks, startup interruption recovery, and cleanup.
- Asynchronous submission/progress so a long run does not depend on one HTTP request.

Short-lived function-only hosting is a poor default for this long-running browser
workflow. A static site can serve the frontend but still needs the browser backend.

Required deployment information: the relevant ThalesOps application/build settings,
selected connected server, and preferred Part 2 app name. Inspect only the platform
configuration needed for Part 2; do not call live Tavus services or initiate Part 1
interviews. Manual reverse-proxy/server deployment is not the planned workflow.

## 10. Proposed repository layout

```text
app/
  main.py                 # HTTP API and web interface
  config.py               # validated configuration
  schemas.py              # typed actions, observations, results
  controller.py           # runtime state machine and budgets
  storage.py              # run/event persistence
  providers/              # Azure model and LinkedIn extraction adapters
  browser/                # session owner, agent-browser and Playwright adapters
  verification/           # listing evidence and acceptance rules
  templates/              # reviewer interface
  static/
tests/
  unit/
  integration/
  fixtures/sites/
evaluation/
  PROTOCOL.md
  sample.py
  run.py
  report.py
scripts/                  # configuration/provider/browser smoke checks
Dockerfile
compose.yaml              # optional local deployment aid; ThalesOps is production workflow
.dockerignore
.env.example
pyproject.toml
README.md
IMPLEMENTATION_PLAN.md
```

Implementation update (2026-09-16): the local application, hybrid browser adapters,
verification/controller, UI, tests, Dockerfile and evaluation tooling now exist.
Apify extraction, local shared-browser tests, and Docker browser smoke checks pass.
The initial Azure 401 was resolved by removing a stale inherited key override;
local `.env` now has precedence. Development runs passed for Harvey, Anthropic,
Stripe, and Netflix (after a button-card fix). The frozen random evaluation is
complete: 11/20 successes (55%), with all failures retained and assistant evidence
review recorded. See README.md, TESTING.md and evaluation/results/REPORT.md. Public
deployment, independent human review, and walkthrough recording remain later tasks.

Post-fix update (2026-09-17): v0.2 general recovery/evidence improvements pass 76
tests. A full rerun of the same 20 inputs scored 16/20 (80%), with all original
successes retained and every failure reported. This is explicitly non-held-out;
the original 55% baseline and matching source archive remain preserved. See
evaluation/COMPARISON.md and evaluation/postfix-v2/REPORT.md.

v0.3 update (2026-09-17): prefer verified upstream hiring boards reached through
observed role/application/back-to-jobs links. The Harvey example now reaches
`https://jobs.ashbyhq.com/harvey` generically. 91 regression tests pass; the local
UI distinguishes careers and final jobs URLs. Existing 20-input reports remain
historical v0.1/v0.2 measurements, not new v0.3 evaluation claims.

Newest rerun update (2026-09-17): v0.3 has now completed all 20 inputs under a
separate frozen protocol. 17/20 returned verified company listings; 8/20 also
completed without an unresolved upstream flag. Nine verified listing fallbacks
and three failures are explicit in the report. These are different metrics, and
the sample is not held out. 94 tests pass; original reports remain unchanged.
