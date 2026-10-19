# Brand memory and HITL rollout

Production is unchanged. On 2026-10-19 the user requested keeping PR #4 as a draft. The current delivery ends at that draft PR; this procedure is for a separately authorized future deployment. `core/AGENTS.md` requires confirmation before production actions.

## Preflight

1. Rotate previously exposed Sleyz credentials. Supply runtime secrets outside Git.
2. Configure `core/.env`: existing Supabase service role and backend key, the supplied Huawei deployment URL, valid MaaS key/model, and distinct publisher and inference-service keys. Never expose service keys through `NEXT_PUBLIC_*` values.
3. From `core`, install requirements and run the paid gate with the deployment credentials:

```powershell
python -m pip install -r requirements.txt
python -m services.llm.smoke --live
python -m services.llm.evals --live
python evals/memory/run.py --live
python -m services.workflow.evals.run --live
```

All four commands must exit 0; live eval thresholds are 100%. The existing Hermes key now passes authentication after correcting a trailing character in Converza's local copy and matching the model name `deepseek-v4.1-flash`. Check inference-service endpoint access separately if running the optional TypeScript qualifier.

## Approved rollout sequence

1. Take a database backup and inventory active writers. Pause customer-facing generation and review actions during the coordinated migration/writer switch.
2. On an existing deployment, apply additive migrations `core/migrations/004_brand_memory.sql`, `005_hitl_events.sql`, then `006_telegram_destinations.sql` using the normal privileged migration mechanism. New databases need 001–003 first. Do not replay the base schema over an existing deployment.
3. From `core`, run `python scripts/backfill_memory.py --org ORGANIZATION_UUID` for a read-only preview. Inspect its timestamped temporary-directory snapshots and report. Run the same command with `--apply` only under the approved production change. Track its progress and inspect the before/after CSV. Historical approvals must remain unresolved.
4. Deploy the updated API, active manager/Sleyz writers, indexer and frontend together. Restore generation only after old direct writers are stopped. Populate each existing prospect's real Telegram destination through trusted ingestion; do not infer chat IDs from owner messages. Missing destinations fail visibly and preserve approval.

API and worker restart commands, from `core`, once Docker is available:

```powershell
docker compose -f compose.memory.yml up -d --build api indexer
```

The core API binds loopback port 8000; preserve the deployment's reverse proxy and streaming timeouts. The worker is independently supervised by Compose. The manager's existing Compose file also maps host port 8000; use its established separate host or change its host-port mapping before co-locating it with the API. Restart that writer from `core` after supplying its runtime `.env`:

```powershell
docker compose -f manager/docker-compose.yml up -d --build
```

Restart the active buyer webhook from the repository root:

```powershell
docker compose -f Sleyz/docker-compose.yml up -d --build
```

Rebuild and restart the frontend using its existing process supervisor after the build, from `Web`:

```powershell
npm ci
npm run build
```

For an existing foreground Node deployment, `npm start` starts the rebuilt frontend. Preserve the configured backend URL and authentication settings. The optional TypeScript qualifier needs its own `CONVERZA_LLM_URL` and matching `LLM_SERVICE_API_KEY`, then its existing Compose restart. It has no direct Huawei credentials.

## Verify after deployment

- Save identity, change a test product price, create a FAQ and verify raw search before extraction finishes.
- Watch current queue age, attempts, failed jobs and successful revision completion. Check that only current revisions are retrieved.
- Open two authorized tabs, approve/edit a test draft, reconnect one tab and confirm state matches. Exercise a conflict with an old revision; expect 409.
- Confirm actual Telegram delivery returns the expected destination/message ID, then mark a buyer conversation resolved. Inspect its exact Atom and UTC timestamp. Never use a synthetic receipt in production.
- Watch transition errors, ambiguous deliveries and SSE replay failures. Reconcile ambiguous sends with actual receipts; do not blindly retry them.

If rollout verification fails, pause generation and affected writers and retain the additive schema/audit records. Restore application code only after assessing whether its old direct-write behavior is compatible with the new transition triggers. Do not drop memory tables or bypass lifecycle enforcement as a rollback shortcut.
