# Brand Memory, Indexing, and HITL Implementation Plan

## Summary

Implement the three tasks in the consolidated Converza backend and existing Next.js UI, using Supabase for durable storage and Huawei MaaS DeepSeek for inference.

Deliver in dependency order: shared LLM client → memory and indexing → draft lifecycle and SSE → editing screens and integration checks.

## 1. Shared Huawei LLM Client

- Create a service under `core/services/llm/` using `AsyncOpenAI`, with:
  - `HUAWEI_MAAS_BASE_URL`, defaulting to `https://api.modelarts-maas.ap-southeast-1.myhuaweicloud.com/v1`.
  - Required `HUAWEI_MAAS_API_KEY` and `HUAWEI_MAAS_MODEL`.
- Use temperature **0.1** for indexing, Atom extraction, tool extraction, and Sleyz reasoning; **0.7** for Milo creative copy.
- Route active generation and orchestration paths through this service, replacing their direct provider calls. Preserve existing streaming and tool-result interfaces through adapters.
- Retry HTTP **429/503** up to three times after the initial request, with exponential backoff, jitter, and bounded `Retry-After` support. Disable overlapping SDK retries.
- Validate structured outputs before use. Unsupported model capabilities produce explicit errors; they never trigger another provider.
- Log operation, model, latency, retry count, and usage without credentials or buyer-message contents.

## 2. Two-Tier Brand Memory

Implement an organization-scoped memory service under `core/services/memory/`.

**Tier 1: identity core**

- Persist versioned identity content in Supabase and expose exports named `brand_passport.md`, `voice_rules.md`, and `negative_constraints.md`.
- Keep identity concise and always include it in generation context. Keep catalog details, pricing, FAQs, and historical objections in Tier 2.
- Render the documents deterministically from canonical passport fields and explicit voice/negative rules. Existing onboarding and Telegram passport edits update the same canonical data.
- Treat identity rules as instructions and retrieved knowledge as supporting evidence.

**Tier 2: searchable knowledge**

- Persist versioned plain-text sources for products, prices, FAQs, human knowledge edits, and explicitly resolved buyer conversations.
- Store source identity, organization, revision, timestamps, summary, and extracted Atoms. Superseded or deleted revisions cannot appear in current retrieval.
- Use the existing Python [rank-bm25 library](https://github.com/dorianbrown/rank_bm25), selecting BM25L with shared Unicode normalization for documents and queries.
- Rank matching documents using:

  `score = BM25L × (0.25 + 0.75 × 2^(-age_days / 30))`

- Default to eight results with a bounded context budget. Use source-update timestamps, never indexing timestamps, for recency.
- Keep search indexes rebuildable from Supabase, with revision-based cache invalidation across backend processes.
- Read current price and currency directly from authoritative catalog records. Old summaries cannot override current prices, including during indexing delays.
- Feed this context into Milo, Sleyz, and Vea while retaining recent, agent-scoped conversation history.

## 3. Background Summary and Atom Indexer

Implement a separately runnable worker under `core/services/indexer/`.

- Capture committed product, price, passport, knowledge, and resolution changes through database-backed jobs. Cover existing web and Telegram writers.
- Deduplicate jobs by source revision. Claim work transactionally with leases so restarts and concurrent workers cannot lose updates.
- Generate a short searchable summary and structured Atoms through the Huawei client.
- An objection Atom contains the **exact objection**, **exact final answer**, source references, and a server-assigned UTC resolution timestamp. Verify quoted spans against the recorded source.
- Product and FAQ updates produce factual Atoms without invented objection fields. Human identity edits never become synthetic buyer conversations.
- Only index buyer objections after confirmed delivery **and an explicit human “resolved” action**. Approval alone does not qualify.
- Discard obsolete extraction results if the source changes during processing. Retry failed jobs with backoff, then retain an inspectable failure with manual retry.
- Keep current raw facts searchable while extraction is pending. Deleting or forgetting knowledge immediately excludes it from retrieval.
- Backfill existing passports and factual knowledge idempotently. Historical approvals remain unclassified until explicitly resolved.

## 4. HITL State Machine, APIs, and UI

Use one transactional draft lifecycle:

`PENDING_DRAFT → AWAITING_HITL → APPROVED | EDITED | REJECTED`

`APPROVED | EDITED → PUBLISHED`

- Create draft records before customer-facing generation; move completed assets to `AWAITING_HITL`. Record generation failures separately and allow retry.
- Require HITL for Milo customer-facing copy, Sleyz buyer replies, and Vea videos. Internal analysis and recommendations remain outside this lifecycle.
- Make `REJECTED` terminal. Editing records the final approved content. `PUBLISHED` requires a successful publisher receipt.
- Preserve approved/edited state after delivery failure and expose the failure for retry. Record ambiguous delivery outcomes for reconciliation instead of blindly resending.
- Integrate the existing Telegram delivery path with the shared lifecycle, validating both HTTP success and Telegram’s response. Additional channel connectors are outside this delivery.
- Enforce transitions with database transactions, expected draft revisions, and idempotency keys. Conflicting decisions return HTTP 409.

**Public contracts**

- Retain existing approve/edit/reject routes, adding revision-aware requests and authoritative draft responses.
- Add authenticated identity read/update/export, product/pricing CRUD, knowledge CRUD/search, draft hydration, and explicit resolution endpoints.
- Add a service-authenticated publication-receipt interface; browser clients cannot declare successful delivery.
- Define matching Python and TypeScript contracts for draft states, knowledge records, Atoms, and versioned events.
- Extend the Next.js backend proxy to support the required update/delete methods.

**Durable SSE**

- Append draft transitions, squad messages, and run-step events in their originating database transactions.
- Use organization-scoped event sequences serialized through commit, preventing concurrent transactions from creating replay gaps.
- Extend the existing squad stream with snapshot hydration, transition events, SSE IDs, cursor replay, heartbeats, and disconnect cleanup.
- Recover expired cursors through a fresh snapshot. Deduplicate events and ignore stale draft revisions in the UI.
- Replace message-text status inference with authoritative draft state across dashboard and squad cards.
- Wire the existing brand, products, and memory screens to real persistence, including FAQ editing, indexing status, retry, and forgetting knowledge. Show approval, delivery, and resolution as separate actions.

## Validation and Rollout

- Fix the existing identity-path regression and oldest-first conversation-history query before integrating memory.
- Add deterministic tests for tenant isolation, retrieval ranking, small corpora, stale pricing, revision invalidation, exact Atom extraction, worker restart/retry, and deletion.
- Test every allowed and forbidden state transition, concurrent decisions, duplicate receipts, delivery failures, and resolution eligibility.
- Test SSE reconnects, snapshot/replay consistency, concurrent commits, multiple tabs, token refresh, and proxy disconnect propagation.
- Mock Huawei to verify configuration, temperatures, structured outputs, and 429/503 backoff. Add a separate live smoke check against the configured deployment.
- Add extraction/retrieval eval fixtures requiring exact quote fidelity, no stale-price answers, and no unresolved conversations promoted into objection memory.
- Run backend tests, frontend type/build checks, and gstack browser checks for editing, approval, reconnect, and resolution flows.
- Apply additive migrations and idempotent backfills first, then coordinate deployment of updated writers, backend, worker, and frontend. Monitor indexing lag, failed jobs, invalid transitions, and SSE replay failures.

**Defaults:** Supabase is authoritative; markdown files are exports; recency half-life is 30 days; retrieval returns up to eight results; no embeddings, Redis, external price synchronization, or new publishing channels are required.
