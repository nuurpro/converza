# Summary and Atom indexer

Run `python -m services.indexer` from `core`. Huawei environment variables and the shared `services.llm` client are required. Indexing uses temperature0.1. No provider fallback is permitted.

`IndexWorker(client, extractor=None, lease_seconds=600)` offers async `run_once(limit=1)` and `run()` for a separately supervised process. The optional extractor injection is for deterministic tests. Claiming uses a database transaction with `FOR UPDATE SKIP LOCKED`; expired leases can be reclaimed. Every claim receives a fresh random token. Completion/failure compares the token, lease expiry and current source revision under locks. An old worker cannot publish after a reclaim, update or deletion. Multiple workers use the same queue without process-local coordination.

Each source revision has at most one job. Five attempts are allowed. Failures use durable exponential backoff (10,20,40,80,160 seconds, bounded at3600); exhausted jobs remain inspectable, and backend manual retry resets attempts only for a current, nondeleted revision. A worker process crash is recovered after lease expiry. If the last attempt crashes, the next poll marks the job failed rather than leaving it stuck. Lease duration bounds how long a provider call may run before its result is discarded; tune it to exceed the configured provider timeout/retry envelope.

The database captures committed edits to canonical passports, catalog products/prices and FAQ/manual rows. Draft objection sources require `status=PUBLISHED`, a successful delivery receipt, `delivered_at` and explicit human `resolved_at`. Approval alone creates no objection source. Resolution time comes from the database lifecycle, never the model.

`validate_extraction` checks all structured output. Factual Atoms require an exact source `text` span and forbid objection fields. Objection Atoms require exact inbound and delivered-answer spans, record source ID/revision/offsets, and replace model timestamps with server resolution time. Human identity is deterministic and never sent for synthetic buyer extraction. Model failures log only exception type/source IDs, avoiding buyer text.

Current raw facts remain searchable while a job is queued, failed or processing. Source deletion or forgetting immediately removes it from retrieval, cancels its queued work and fences leased results. Superseded revisions remain audit records but cannot be retrieved as current context. Before deleting historical audit records for a retention policy, coordinate the policy separately; forgetting excludes context but deliberately retains inspection history.

Free deterministic eval: `python evals/memory/run.py`. Credentialed smoke/eval: `python evals/memory/run.py --live`. Poll queue states (`jobs` endpoint) and compare oldest current pending `created_at` to database time to monitor indexing lag. `last_error`, attempts and lease fields support failure triage without retaining provider request bodies.
