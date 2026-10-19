# Brand memory and HITL verification — 2026-10-19

Implementation is ready for review on `codex/brand-memory-hitl`. Huawei authentication is verified using the existing Hermes deployment key. Production rollout remains gated.

| Requirement | Implementation and evidence |
| --- | --- |
| Concise identity core | Canonical passport renders three named Markdown exports; oversized input is rejected, never silently truncated. Identity, aliases, palette and tenant boundaries have deterministic coverage. |
| Searchable factual memory | Supabase current revisions, BM25L with Unicode normalization and 30-day recency half-life, eight-result default and context budgets. Current catalog prices override historical text. Large catalogs are bounded and selected by relevance. |
| Durable extraction | Committed-write triggers, revision-deduplicated jobs, leased claims, fencing, retry/dead-letter and manual retry. Exact quote validation rejects invented spans and empty Atoms. Source timestamps remain authoritative. |
| Resolved objections | Requires buyer-linked Sleyz draft, confirmed publisher receipt and explicit human resolution. Tests reject approval-only and nonbuyer content. Browser QA indexed the exact objection and final delivered answer after resolution. |
| Transactional lifecycle | Revision CAS, idempotency fingerprints, legal-transition matrix, terminal rejection, generation retry, delivery reservation and receipt validation. Real PostgreSQL tests cover concurrent decisions and rollback. |
| Durable SSE | Organization lock serializes commit cursors and atomic snapshots. Replay, deduplication, stale revisions, token refresh, tenant changes and disconnects are covered. Two browser tabs reflected decisions without refresh. |
| Existing UI integration | Brand save/export, product update, FAQ creation/search/forget, approval/edit, delivery failure/retry, reload hydration and resolution exercised through the local browser harness. |
| Shared inference | Active core, manager, Milo and Sleyz text paths use the Huawei AsyncOpenAI boundary. The TypeScript qualifier uses a service-authenticated backend extraction endpoint. Temperatures and 429/503-only retry behavior have mocked tests. |

## Executed checks

- Core: **133 tests passed, no skips**, including real PostgreSQL memory and workflow tests against disposable local databases. The latest run used ports 15440 and 15439 because Windows denied binding the original test ports after WSL startup.
- Workflow deterministic eval: **39/39**; memory deterministic eval: **5/5**.
- Web: **14 tests**, TypeScript check and Next.js production build passed.
- TypeScript qualifier: **2 gateway tests**, TypeScript check and build passed; npm audit reported zero vulnerabilities after dependency updates.
- Local QA backfill: inspected five canonical rows, changed zero already-current sources, exit 0. Before/after snapshots, progress log and CSV were generated outside the repository. This proves idempotency on the fixture, not production data.
- Browser QA used actual routes and PostgreSQL migrations with fixture authentication, extraction and delivery. These fixtures do not prove live provider or channel connectivity.
- Huawei live checks: smoke passed, exact-output extraction **5/5**, actual indexer Atom extraction **1/1**, and customer-intent classification **8/8**. Earlier attempts included a Unicode exact-match miss and a provider permission response; these were not silently retried by the client. The latest complete extraction run passed every case. Source-span validation still rejects altered quotations rather than persisting them.
- The former Huawei 401 was caused by an extra trailing character in Converza's local key copy. The exact existing Hermes key fixed it; no replacement or credential rotation was needed for MaaS. The working model is `deepseek-v4.1-flash`. A live run also exposed a missing model-facing JSON contract in the shared client; this is fixed and covered by a red/green regression test. Strict local schema and source-span validation remain enforced.

## Outstanding gates

- Docker Desktop daemon is unavailable locally; images have not been built or started. A local startup attempt on 2026-10-19 failed while binding its `dockerInference` Unix socket (address already in use / invalid filename). The engine stopped before readiness. The task-started Desktop processes were closed; no factory reset, socket deletion or Docker configuration change was attempted.
- Production migrations, backfill and restarts have not been run. Follow [the rollout procedure](brand-memory-rollout.md) after explicit approval.
- Historical hardcoded credentials in the existing Sleyz Kubernetes manifest were replaced with Secret references. Rotate those previously exposed credentials before deployment; removing source values does not revoke them.
- The workspace contained substantial preexisting consolidation changes. Unrelated root deletions and archived support/media applications are excluded from this feature commit. Supporting consolidated core and active agent files are included because the new runtime imports them.
