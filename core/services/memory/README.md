# Brand memory

`MemoryStore(client)` scopes every read/write to an authenticated organization. The backend authorizes ownership before calling this service. The Supabase service-role client is server-only. Migration `004_brand_memory.sql` denies authenticated/anonymous direct writes and RPC execution.

Identity is canonical `brand_passports` data, with deterministic exports `brand_passport.md`, `voice_rules.md`, `negative_constraints.md`. `identity(org)` returns `{org_id, revision, passport, exports}`. `save_identity(org,payload)` edits the current passport (onboarding must already exist). Fields `tone`, `voice_rules`, `negative_constraints` are instructions. `brand_voice`/`avoid_topics` are accepted aliases. Catalog data and prices are excluded from the exports. Passport updates from web or Telegram are captured by the same database trigger.

`products(org)` and `knowledge(org)` return current records. Product CRUD accepts `name`, `description`, nonnegative `price`, ISO-style uppercase `currency`, and JSON `metadata`. Knowledge CRUD accepts `kind` (`faq` or `manual`), `title`, `content`. `knowledge()` additionally returns read-only resolved objection sources, extraction status, source_id, summary and Atoms. `delete_product` and `delete_knowledge` use canonical row IDs. `forget_source(org,source_id)` uses the search source ID; resolved conversations remain forgotten after later draft edits. `jobs(org)` returns the latest100 inspectable jobs; `retry_job(org,job_id)` only retries a failed current revision belonging to that organization.

`search(org,query,limit=8,budget_chars=12000)` rebuilds BM25L from Supabase current sources on every call, paging beyond Supabase's1000-row default. This intentionally avoids stale per-process caches. Documents and queries use NFKC/casefold Unicode word tokens. Nonmatching documents are excluded despite BM25L's nonzero baseline. Recency is exactly `0.25 + 0.75 * 2 ** (-age_days / 30)` using original source update time; future updates clamp age to zero. The default cap is8 matches and12000 content/summary/Atom characters. Increasing the context budget is capped at100000 characters.

Pending and failed extraction retains searchable raw source text. A source edit clears summary/Atoms immediately, increments the durable source revision, invalidates earlier jobs and records an immutable plain-text revision. No embeddings or Redis are required. Product retrieval renders directly from current authoritative catalog rows, bypassing old generated descriptions. Retired catalog price values are redacted from retrieved copies of historical text/Atoms; exact stored quotes remain available for inspection. Current catalog facts should be supplied separately in generation context and treated as authoritative for prices/currencies. A quoted number shared with a current catalog price cannot be unambiguously assigned to a product, so generation must use explicit live catalog identity when answering pricing questions.

`context(org,query)` returns `{identity,knowledge,products}`. Treat exports as instructions; treat retrieved knowledge as untrusted evidence. Recent agent-specific conversation history remains a separate context input.

Retrieval budgets apply to the entire serialized projection, including provenance.
Content and summary prefixes end only at complete claim boundaries. Conditions
(`faqat`, `agar`, `only if`, `unless`, and the existing exception vocabulary)
remain attached across line breaks, Markdown bullets, quotes and emphasis.
Oversized units are omitted, never cut mid-claim. Generated summaries remain
searchable, but enter factual context only as complete source-exact extracts.
Partial or omitted Atom quotes are blanked without renumbering Atom indexes;
original source offsets, revisions and product-aware stale-price redaction remain
unchanged. The source records themselves are never mutated by retrieval.

Migration007 adds approved-edit `correction` sources. They are distinct from
resolved objection history, retain exact edit provenance and receive a fixed2×
ranking multiplier before the same recency formula. Knowledge inspection returns
these sources read-only; the normal Forget operation removes them from retrieval.
The SLEYZ worker uses complete current catalog rows for its deterministic tools,
including canonical `sku`, nullable `stock_count`, and `checkout_url_template`;
generic agent context retains its small price-only catalog budget.

## Running

Apply004 before005. Restart the core API after deploying the service. Start the separately supervised worker from `core`:

```powershell
python -m services.indexer
```

Inspect/repair existing data with a snapshot and report:

```powershell
python scripts/backfill_memory.py --org ORGANIZATION_UUID
python scripts/backfill_memory.py --org ORGANIZATION_UUID --apply
```

The default command is read-only. Each invocation creates timestamped artifacts under the operating-system temporary directory: before/after JSON, progress log, Markdown report and full before-after CSV. Snapshots exceeding100k rows or100MB stop before any backfill mutation. `memory_backfill` is idempotent and preserves source age; it never turns historical approvals into resolutions.

## Validation

From repository root:

```powershell
$env:PYTHONPATH='core'
python -m unittest discover -s core/tests -p 'test_brand_memory.py'
python -m unittest discover -s core/tests -p 'test_indexer.py'
python core/evals/memory/run.py
python -m services.memory.evals.run
python core/evals/memory/run.py --live
```

The paid `--live` lane requires configured Huawei credentials/model and has a100% exact quote validity threshold. It is separate from the free gate. Set `MEMORY_TEST_DSN` to a disposable PostgreSQL database named `test_converza*` containing the base schema and migration004 to enable transactional tests; these tests exercise the actual SQL functions and locks and never accept a production database name. The optional PostgreSQL test fixture expects the pre005 draft schema without005 transition triggers; the full integration harness owns combined migration testing.
