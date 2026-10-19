# Milo marketing and copy engine

Outcome: real buyer objections become grounded, inspectable campaign copy; only
an explicitly approved script revision creates a Vea build. Campaign approval
never publishes anything or spends ad budget.

## Evidence and model boundary

Migration008 captures extraction jobs in the same transaction as Sleyz inbox
acceptance, before any sales reply is generated. Duplicate channel deliveries,
simulations and replacement drafts cannot inflate demand. The migration also
queues historical genuine inbox messages once. Sales reply failure, delivery,
and human resolution have no bearing on emerging objection counts.

`milo_objections` is Milo's exact-span demand telemetry; Sleyz's existing
`objection_telemetry` and resolved-answer memory retain their own contracts.
Every extracted quote must match its original inbound span. Fixed objection
topics and catalog-backed product IDs keep grouping stable. Counts use distinct
prospects per product/topic, never repeated messages from the same buyer.

Brand Passport stores `campaign_language`, `personas`, `proof_points`,
`banned_terms`, and `competitor_names`. `target_audience` supplies a default
persona. Proof confirmation requires an authenticated owner, exact current
product/FAQ/manual source quote, source revision and server-stamped confirmer
and time. Buyer statements and resolved answers cannot be product proof.
Deleted, forgotten or changed sources invalidate their confirmed proof points.

The shared `services.llm` deployment selects exact buyer spans, writes creative
copy and reviews semantic claims. Server code attaches the exact buyer quotes,
source IDs and proof revisions; creative inference never generates provenance.
Code validates the versioned artifact, exact
quotes, current citations, persona, framework order, product/topic applicability,
banned terms, competitor mentions, numbers and URLs. Semantic review considers
only cited proof and its original source qualifications. It is model judgment,
not a deterministic guarantee. Generation makes one attempt and at most two
rewrites. Failure remains blocked and reviewable; missing evidence produces an
actionable request without any creative call.

## Campaign contract and approval

`contracts.MiloCampaignArtifact` is mirrored by `Web/lib/data/milo.ts`:

- `schema_version:1`, server-counted `trigger_reason`, target persona, language.
- Three ordered hooks: A pain question, B proof/mechanism, C low-friction CTA.
- Ordered video scenes containing narration, visual cues and on-screen text.
- Instagram, Telegram, TikTok captions; verbatim buyer references; current proof
  references and Brand Passport revision.

Campaign status is queued, generating, needs_evidence, blocked, awaiting_review
or failed. Script decisions have a separate pending/approved/rejected state.
Editing saves another reviewable revision and never enqueues Vea. Approval
revalidates current evidence and semantics, then one database transaction records
the decision and inserts a unique build for that script revision. Organization,
revision and idempotency fingerprints are checked in the same transaction.
Legacy text-only drafts remain readable and retryable. New Milo customer-copy
requests through the switchboard enqueue a campaign; free-text `@Vea` output
cannot start a campaign render. Owner-only analysis retains its existing path.

Vea receives approved narration unchanged, with ordered footage search cues,
scene overlay text and campaign language. The bundled provider supports these
fields and returns a binding containing organization, build, campaign, script
revision and a SHA256 of scenes/language. Both normal completion and reconciled
receipts must match this binding. Rendered videos create an AWAITING_HITL Vea
draft; provider automatic publishing is disabled for approved scenes.

## Scheduling and recovery

Defaults: daily09:00 Asia/Tashkent; spike five distinct conversations within
seven days;24-hour product/topic cooldown. Daily and spike generation are
enabled by default and configurable. Worker scheduling checks every30seconds,
catches up a due daily run after downtime, and reserves at most one daily run
per local calendar date. Both automatic trigger types share evidence dedup and
cooldown. Evidence expiry alone cannot trigger another campaign: new buyer
source IDs must exist. Automatic campaigns use the evidence snapshot reserved
at enqueue, so later arrivals cannot silently invalidate the deduplication basis.
Missing evidence creates one inspectable request until
the brand/evidence changes. Manual requests use explicit idempotency keys and
may deliberately generate a fresh campaign.

Jobs use600-second fenced leases, three attempts and durable backoff. Worker
processing is bounded at500seconds. An expired worker cannot complete another
worker's claim. Generation/extraction failures can retry independently of sales.
Before the first render submission the storage transaction rechecks brand/proof
freshness. The submission intent commits before HTTP POST and the provider task
ID immediately after it. Submitted jobs resume polling; uncertain submissions
without task IDs require the original provider receipt, never blind resubmission.
Confirmed provider failures stop immediately. An explicit operator retry preserves
the old receipt and increments the provider attempt on the same unique build job.
Timeouts retain the original task ID and resume polling. Retry/reconciliation
commands replay durable idempotency receipts even when the provider is offline.
An explicit provider language-maintenance response leaves a failed job with a
safe operator explanation. Manual retry remains available after provider recovery;
Milo never substitutes a different language or inference provider.

Logs contain IDs, counts, status, elapsed time, approval-to-build seconds and
sanitized error types. Buyer text and provider credentials are not logged.

## Owner APIs

All routes are under `/api/milo/{org_id}` and use existing backend/session and
organization ownership checks. The frontend forwards them through its server
proxy and polls active campaign/job state every five seconds.

- GET/POST `/campaigns`; POST accepts `{prompt,language?}` plus Idempotency-Key.
- GET `/campaigns/{id}`.
- POST `/campaigns/{id}/script/{edit|approve|reject}` accepts
  `{expected_revision,video_script?}` plus Idempotency-Key. Only edit accepts
  scenes. Compliance results always come from the server.
- GET/PUT `/settings`; GET/PUT `/brand`; GET `/proof-sources`.
- GET `/objections?time_window=7` (days) and `/jobs`; POST `/jobs/{id}/retry`
  requires Idempotency-Key.
- POST `/jobs/{id}/reconcile` accepts `{task_id}` from the original provider
  task and Idempotency-Key. The provider binding must match this build and
  provider attempt before polling resumes.

## Verify and deploy

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH='core'
python -m unittest discover -s core/tests -q
python -m services.milo.evals.run
python -m services.milo.evals.run --live
npm test --prefix web
npm run typecheck --prefix web
```

Real SQL gates require an explicitly selected disposable `test_converza*`
database through `CONVERZA_WORKFLOW_TEST_DSN`. Fixture evals make no network
calls. Live evals use synthetic customer text and the configured deployment;
they never send a buyer message or create a video. Safety must pass100%; campaign
availability/framework/language quality must reach90%. Failures count and are
reported with the failing case.

See `docs/milo-rollout.md` for migration, configuration, source packaging and
restart commands. Production migration and restarts require separate approval.
