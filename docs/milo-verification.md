# Milo verification — 2026-10-20

Milo is implemented on `codex/milo-engine`, stacked on the existing Sleyz
inbound branch. The Russian live campaign gate remains open because the
configured Huawei deployment explicitly reports multilingual-service maintenance
(`ModelArts.81013`). Production has not been migrated or restarted.

| Requirement | Current implementation and evidence |
| --- | --- |
| Real buyer demand, independent of sales success | Migration 008 captures extraction jobs with inbound acceptance; exact Unicode spans, deduplication, simulation/refresh exclusion, product/tenant boundaries and sales-generation independence have deterministic and real PostgreSQL coverage. |
| Scoped recent aggregation | `MiloTools.get_top_buyer_objections(time_window)` groups by product/topic, counts distinct prospects, and returns original language, source IDs and timestamps; tests exclude old and foreign records. |
| Verified Brand Passport facts | Owner-scoped proof confirmation checks exact current product/FAQ/manual sources, revisions and source ownership; server stamps owner/time. Deleted, forgotten and changed evidence fails generation and approval. |
| Persona and language defaults | Canonical personas or target-audience fallback; English default with English/Russian/Uzbek overrides. Deterministic tests prove selected language is preserved; live English and Uzbek generation pass. Russian is blocked by the provider, not silently replaced. |
| Three direct-response frameworks and campaign contract | Versioned artifact requires ordered A/B/C hooks, scene narration/cues/text, all three channel captions, persona and provenance. Creative inference writes copy; code attaches exact buyer/proof references. |
| Compliance and bounded rewriting | Schema, exact quotes, complete numeric/URL tokens, current facts, persona and product/topic scope are checked in code. Model review sees only cited proof and its original source context. Tests prove at most two rewrites and rejection of malformed or unsupported content. |
| Durable daily/manual/spike triggers | Configurable daily 09:00 Asia/Tashkent, five conversations/seven days, shared 24-hour topic cooldown; leased jobs, backoff, daily reservation, unchanged-evidence suppression and reserved generation snapshots are tested. |
| Script-only human review | Editing creates a pending revision; only explicit approval can enqueue a build. API tests and real browser QA prove separate edit/approve actions, stale-revision rejection and repeat-approval idempotency. |
| One Vea build per approved revision | Real PostgreSQL concurrency tests submit eight approvals and observe one build. Each confirmed-failure retry increments a provider attempt on that same unique job; uncertain submissions cannot resubmit. |
| Exact approved render input | Adapter tests prove no narration-generation call, unchanged scene fields, ordered search cues and all three language voices. Actual MoviePy/FFmpeg composition preserves multiline English, Russian and Uzbek overlays. |
| Rendering recovery and isolation | Private worker API authentication, organization/job/script/attempt binding, durable provider receipts, fenced queue claims, restart recovery and receipt reconciliation are covered by adapter/provider/SQL tests. Completed videos return as Vea AWAITING_HITL drafts. |
| Operator visibility and compatibility | Existing legacy text drafts and owner analysis remain available. Campaign cards show source evidence, compliance/missing evidence and build/recovery states. Browser QA verified persistence, separate decisions, final review state and mobile layout. |
| Deployment and traces | Additive migration, dedicated workers/provider image source, private credential examples and restart procedure are included. Logs record IDs/counts/failures and approval-to-build seconds without buyer text or secrets. |

## Verification commands

Run from the repository root. The PostgreSQL DSN must point only to an explicitly
named disposable `test_converza*` database; tests never use production Supabase.

```powershell
$env:PYTHONPATH='core'
$env:CONVERZA_WORKFLOW_TEST_DSN='host=127.0.0.1 port=55441 user=postgres dbname=test_converza_milo'
python -m unittest discover -s core/tests -q
python -m services.milo.evals.run
python -m services.milo.evals.run --live
npm test --prefix web
npm run typecheck --prefix web
npm run build --prefix web
docker compose -f core/compose.memory.yml config --quiet
```

The final full core run passed 304 tests, with eight optional unrelated
integration tests skipped. This includes 82 Milo tests with the real PostgreSQL
lane enabled and no Milo skips. Frontend tests passed 33/33; type checking and
the production Next build passed. The source-only Python 3.11 renderer passed
19 scene/schema/orchestration tests, two runtime tests, three durable-state
tests and six authenticated API tests. Its real media composition test also
passed; the ordinary fixture run deliberately skips that opt-in media test.

The fixture eval passes all safety and quality cases. The latest complete live
run passed English and Uzbek campaign generation, both extraction cases and all
four adversarial claim checks. Russian returned the vendor maintenance error,
so the complete live gate correctly exited 1: 11/12 safety cases and 4/5 quality
cases passed. Provider/infrastructure failures remain failures in these totals.

## Browser and media evidence

The loopback QA harness used the actual API, PostgreSQL migration and frontend,
with synthetic model/render fixtures. It verified:

- Edited campaign revision 3 remained pending; explicit approval produced
  revision 4 and one queued build.
- Build completion preserved the edited scene fields and created Vea draft
  `f6df746f-0803-4908-80fa-fc1a2b324463` in `AWAITING_HITL`.
- Saved Brand Passport constraints and owner-confirmed proof survived reload.
- At 390×844, document width remained 390 with no horizontal overflow.

Local screenshots are retained in `.gstack/milo-campaign-mobile.png`,
`.gstack/milo-review-mobile.png`, and `.gstack/milo-brand-proof-desktop.png`.
They are deliberately excluded from source commits. Provider media tests use
synthetic local assets with real FFmpeg, without TTS, stock-search, publishing
or LLM calls. Source-only packaging was independently tested under Python 3.11.

## Open gates

- Russian live campaign generation must be rerun after Huawei restores the
  configured multilingual service. The code preserves failed jobs and provides
  an explicit operator retry without switching languages or providers.
- The Docker Compose configuration validates, but actual image build/startup
  is unverified because Docker Desktop's Linux daemon is unavailable. Clean
  source, pinned Python 3.11 runtime, API and native media tests provide separate
  evidence; they are not described as a Docker build.
  A local `docker desktop start` attempt failed during backend initialization:
  the `dockerInference` Unix socket could not bind. No Docker data was reset.
- Production migration, historical extraction and service restarts require the
  separately authorized rollout in `milo-rollout.md`.
