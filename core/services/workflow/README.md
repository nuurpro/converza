# Review, publication, and replay

Outcome: no customer asset can be approved twice, published without a publisher
receipt, or promoted into objection memory before a human marks its delivered
buyer conversation resolved.

`lib.repository` is the storage boundary. `InMemoryRepository` is the deterministic
test implementation; `SupabaseRepository` calls the service-only PostgreSQL RPCs
in migration `005_hitl_events.sql`. Apply migrations 001 through 005 in order.

Draft states are `PENDING_DRAFT -> AWAITING_HITL -> APPROVED | EDITED | REJECTED`.
Only `APPROVED` or `EDITED` can become `PUBLISHED`. Rejection is terminal.
Every change increments `revision`. `transition_draft(org_id, draft_id, action,
expected_revision, idempotency_key, edited_content=None, receipt=None, error=None)`
checks organization, revision, allowed transition, and the idempotency request
fingerprint in one transaction. A repeated key returns its original response;
reusing a key for different arguments is a conflict. API callers must supply
their last observed revision and a fresh key for a new operation.

Generation has a separate `generation_status` (`pending`, `running`, `failed`,
`completed`) and `generation_error`. A failed generation keeps `PENDING_DRAFT`.
`lib.switchboard.retry_generation` claims a retry before calling the provider;
concurrent retries cannot generate the same draft twice. Structured intent
classification excludes internal owner recommendations from the lifecycle.

`publish_telegram` first reserves and claims a unique delivery attempt. It checks
HTTP success, Telegram `ok`, message ID, and destination chat. A matching receipt
and expected revision are required to publish. Delivery failure preserves approval.
Timeouts, malformed success responses, and transport uncertainty become
`delivery_status=ambiguous`. A process crash after the transport claim leaves
`sending`; neither case can be resent blindly. Reconcile with the original
channel receipt through the service-authenticated receipt API, including the
stored `delivery_attempt_id`. A definitively failed send can be retried with a
new key. This deliberately favors avoiding duplicate customer messages over
automatic retry after uncertain outcomes.

Only published Sleyz drafts with an actual `prospect_id` can be resolved. The
server assigns `resolved_at`; migration 004 then captures the exact inbound
objection and final answer for indexing. Approval, delivery, and resolution are
separate operations.

`snapshot(org_id)` returns `{cursor, drafts, messages, steps}` under the same
organization lock used by every durable writer. `read_events(org_id, after,
limit=200)` returns ordered envelopes `{schema_version:1, id, org_id, type,
payload:{row}, created_at}`. Types are `draft_transition`, `squad_message`, and
`agent_run_step`. Organization cursor increments roll back with their mutations;
the organization lock is retained through commit, so replay cannot skip a later
commit behind an earlier sequence. No retention currently expires event cursors.
SSE transport owns disconnect cleanup, heartbeat, cursor validation, and snapshot
fallback; clients ignore duplicate event IDs and older draft revisions.

Gate: `python -m unittest discover -s tests -p 'test_workflow*.py'`.
The optional PostgreSQL suite requires `psycopg2-binary` and an explicit
`CONVERZA_WORKFLOW_TEST_DSN` pointing to an isolated `test_*` database; it bootstraps
minimal base tables plus migrations and checks real transactions and triggers.
It never uses the configured Supabase deployment.

Eval: `python -m services.workflow.evals.run`; add `--live` for paid Huawei intent
classification checks using the configured model. The live threshold is 100%:
customer requests must never be classified as internal recommendations.

Restart the core API and manager after applying migrations. The manager image
builds from `core/` so `lib` and all shared `services` are present:
`docker compose -f manager/docker-compose.yml up -d --build` (from `core/`).
