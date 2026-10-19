# Milo rollout

Production is unchanged. This delivery prepares source and local verification;
production migration and restarts require separate authorization under
`core/AGENTS.md`.

1. Review the additive008 migration after001–007. It adds Milo Passport fields,
   tenant-scoped campaigns/settings/demand telemetry/jobs/decision receipts,
   service-only RPCs and the Sleyz-inbox capture trigger. It idempotently queues
   historical genuine inbox records, excluding simulations and refresh copies.
2. Before applying it to an existing deployment, snapshot affected Passport,
   inbox and job rows following the repository's backfill protocol. Inspect
   counts and queued extraction volume. Run the real SQL gate against a
   disposable database first. No production backfill ran during this task.
3. Configure the existing Supabase/shared LLM values server-side. New text
   inference still goes through `services.llm`; no model or provider fallback
   is introduced. Set `PEXELS_API_KEY` server-side for Vea stock footage and
   `MPT_API_KEY` to the same private worker credential in core and renderer.
   The dedicated `Dockerfile.milo` runs the API in approved-scenes-only mode,
   acquires its Unicode font during image build and disables provider text
   generation and automatic publishing. Edge TTS needs network connectivity.
   Set `MONEYPRINTERTURBO_PUBLIC_BASE_URL` to the browser-reachable renderer
   output-file origin in production; the Compose default is loopback8080 for
   local use. Expose only preview files publicly. Renderer control APIs require
   the private worker credential and belong on the internal network.
   The worker uses the internal renderer service name. Do not commit local
   `config.toml`, `.env`, fonts, videos, logs or provider task storage.
4. Restart API, Sleyz ingress/worker, Milo worker, Web, and Vea provider from the
   same source revision after the migration is approved and applied. The
   provider must advertise approved-scene and job-binding capabilities; older
   providers are rejected before a paid render is submitted.
5. Confirm a real current proof point in Brand Passport, inspect buyer evidence,
   generate a campaign, edit the script, explicitly approve it and inspect the
   resulting Vea review draft. Verify no second build appears after replaying
   approval. Keep rendered output in review until separately approved for use.

Core integrated restart (from repository root, after deployment approval):

```powershell
docker compose -f core/compose.memory.yml up -d --build api indexer sleyz-ingress sleyz-worker milo-worker vea-renderer
```

Web deployment uses the existing frontend host's build/restart procedure. For
local development, run `npm run dev --prefix web`; a production Next deployment
uses `npm run build --prefix web` and its existing process supervisor.

Monitor evidence-blocked/compliance-blocked campaigns, job failures, queued
submission receipts and `approval_to_build_seconds`. A failed provider task with
an existing task ID is polled rather than resubmitted. An ambiguous submission
requires its original matching receipt through the owner recovery control.
