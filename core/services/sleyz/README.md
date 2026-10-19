# SLEYZ inbound sales

Outcome: accepted buyer messages survive API restarts, produce grounded reviewable
drafts, and require human approval before any customer delivery.

The active webhooks live in `Sleyz.sales_main`. Core hosts authenticated review,
simulation and recovery APIs. A separately supervised `python -m services.sleyz`
worker processes the durable inbox and approved-edit learning queue. No Redis or
new inference provider is required.

## Contracts and processing

`SleyzStore(repo)` owns transactional acceptance, deduplication, fenced claims,
artifact completion, retries, replacement drafts, telemetry and learning jobs.
`contracts.SleyzDraftArtifact` is mirrored by `Web/lib/data/sleyz.ts`.

Acceptance keys include organization, platform, connection and external message
ID. The inbox and initial draft commit before webhook acknowledgement. Three
attempts use durable exponential backoff; expired leases can be reclaimed and
old workers cannot complete their replacements. The worker bounds processing
to 500 seconds inside a 600-second lease. Failed drafts are retried through the
existing review API without allocating a second draft.

Inference classifies readiness and selects complete exact evidence quotes and
reply structure. Code computes quote offsets, validates source revisions,
composes current catalog price/stock, and expands configured checkout templates.
Scores below0.40 are COLD;0.40–0.74 WARM;0.75 or above HOT. The catalog tool uses
SKU/name identity matches; descriptor-only overlap cannot select a checkout.
Ambiguous or missing products produce a clarification. Unknown stock, missing
SKU/price/checkout configuration, or insufficient stock suppress the link and
produce an operator note. Product descriptions should be concise: replies above
120 words fail review generation rather than silently truncating verified facts.

Prices and checkout links come only from current catalog rows. Historical
scripts guide structure, while factual quotations preserve complete source
sentences and qualifications. Identity constraints can suppress disclosure of
price, stock or description. Checkout templates must use HTTPS, a fixed host,
and only `{sku}`/`{quantity}` substitutions; substituted SKUs are URL encoded.
Checkout remains a merchant redirect, without inventory reservation or payment
confirmation. Managed stock requires merchant updates.

## Approval, delivery and learning

The generated artifact and original copy remain separate from human final copy.
Delivery uses stored account/customer destinations and approved final text.
Catalog changes block delivery; Refresh creates a linked replacement requiring
new approval. Superseded and simulated drafts cannot send or become resolved
winning-response memory. Telegram destinations are bound to their original
inbox envelope; changing a prospect's later channel cannot reroute an old draft.

Instagram uses a conservative24-hour window from the latest real inbound by the
same buyer on the same account. Definite provider rejections can be retried;
uncertain transport results require reconciliation. A one-time send claim and
attempt-fenced completion prevent duplicate sends and tolerate unrelated
learning status revisions during transport. A provider receipt is required for
PUBLISHED; approval alone never proves delivery.

An edited approval atomically queues learning. The diff analyzer can choose a
reusable behavior rule from `learning.SAFE_RULES` (concise formatting, tone,
language, questions, signatures and objection acknowledgement), with exact
changed quote support. Arbitrary commercial rules and customer-specific
exceptions are excluded. This conservative vocabulary prevents synonyms such
as “complimentary freight” from becoming global business policy. Explicit
identity constraints and live catalog facts outrank learned rules. Relevant
correction sources receive the standard recency weighting multiplied by2.
Corrections are inspectable and forgettable in memory settings. Learning errors
are sanitized on the review card and retry independently of customer delivery.
No applicable rule gives `learning_status=skipped`.

## APIs

- `POST /api/simulate/inbound-dm`: owner session plus Idempotency-Key; body
  `{org_id,platform,customer_id,customer_handle?,text}`;202 returns inbound/draft
  IDs and duplicate status. Simulation is forced server-side and excluded from
  production learning and publication.
- `POST /api/drafts/{id}/refresh`: `{expected_revision}` and Idempotency-Key;
 202 returns replacement IDs. Old ambiguous/in-flight drafts cannot refresh.
- Existing `/retry-generation`, `/deliver`, HITL decisions and SSE carry the
  SLEYZ artifact alongside other draft fields.
- `POST /api/drafts/{id}/retry-learning`: retry a failed analysis.
- `GET /api/sleyz/connections?org_id=...`: safe configuration status, never tokens.

## Validation and operations

From the repository root:

```powershell
$env:PYTHONPATH='core'
python -m unittest discover -s core/tests -q
python -m services.sleyz.evals.run
python -m services.sleyz.evals.run --live
```

The free fixture lane tests rendering and contract safety; `--live` measures the
configured Huawei model, with at least90% intent/objection accuracy and100%
commercial safety required. Failures count against both metrics. Live evaluation
uses synthetic fixtures and never sends a customer message. PostgreSQL gates
require `CONVERZA_WORKFLOW_TEST_DSN` pointing at a disposable `test_converza*`
database. See the local QA harness for authenticated browser testing.

Worker logs record organization/draft IDs, intent, attempts, generation latency,
inbound-to-draft latency and sanitized failure types. Objections live in the
tenant-scoped telemetry table rather than application logs. Workflow events
retain approval/edited decisions; edit rate can be computed as edited decisions
divided by approved-or-edited decisions. Credentials and buyer text never belong
in operational logs.

Apply migrations001 through007 in order before deploying updated services.
After approval to change production, the integrated local Compose deployment is:

```powershell
docker compose -f core/compose.memory.yml up -d --build api indexer sleyz-ingress sleyz-worker
```

This uses the Sleyz image for the worker so manager notification modules are
included. Alternatively, an existing core deployment can run only the standalone
sales stack using `Sleyz/docker-compose.yml`; do not run both ingress stacks on
port8001. Restart the manager service too if it was running older publisher code,
and deploy/restart the Web frontend. Kubernetes includes a separate worker
Deployment using the same server-only runtime Secret. Apply only populated
secrets out of band, never the empty example template.
