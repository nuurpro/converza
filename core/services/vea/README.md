# VEA variants

The v1.3.9 upgrade and preservation gates are documented in
`Vea/services/MoneyPrinterTurbo/UPGRADE.v1.3.9.md`. The operator clip catalog now
includes all eligible same-tenant footage, even other initiatives or off-tag clips.
Only explicit persisted swaps bypass relevance; automatic selected-initiative
footage must match an explicit product assignment. Safe center cropping is allowed,
stretching is not. A swap still invalidates approval and needs fresh review.

VEA preserves approved Milo narration and renders deterministic vertical recipes.
Its measurable outcome is a reviewable preview for each approved source, with
no duplicate provider submission and traceable source/configuration hashes.

Apply `core/migrations/009_vea_variants.sql` after migration 008 before deploying
the new core API. The service-role-only `vea_store` RPC shares Milo's leased
`milo_jobs` queue and organization transaction lock. It creates separate variant
rows, keeps revision snapshots on clip swaps, and emits typed video drafts in the
existing workflow event stream. No browser receives source paths or private
composition manifests. Only the default variant updates Milo compatibility fields.

Set `VEA_PRESETS_ENABLED=true` only after provisioning and smoke-testing the
renderer. Existing preset jobs can finish or retry after the flag is disabled.
Legacy provider tasks with a submitted or uncertain receipt retain their original
binding; enabling presets never converts an already submitted legacy render.

Configure `MONEYPRINTERTURBO_BASE_URL`, `MONEYPRINTERTURBO_PUBLIC_BASE_URL`, and
`MPT_API_KEY` using the existing renderer integration. Restart core API, Milo
worker and the renderer after configuration or dependency changes. Narration
model, voice, asset catalog and FFmpeg setup are documented in the renderer.
Model weights and generated media belong on provisioned volumes, outside Git.
The optional `core/compose.vea.yml` overlay mounts the provisioned catalog and
models read-only. From `core/`, after creating the host asset/model directories:

```powershell
docker compose -f compose.memory.yml -f compose.vea.yml up -d --build api milo-worker vea-renderer
```

Owner-scoped API prefix: `/api/vea/{org_id}`. Read `presets`, `assets` (optional
`product_id`, `language`), and `variants`; inspect `variants/{id}`. Create variants
with `campaign_id`, current approved campaign `expected_revision`, and `preset_id`.
Swap `variants/{id}/swap` with the current variant `expected_revision`, `segment_id`
and eligible `asset_id`; retry `variants/{id}/retry` with its expected revision.
Every mutation requires `Idempotency-Key`. Creation and swaps are gated by the
capability flag. Returned variants include safe `segments`, `product_id` and
`language` for the clip picker. Automatic variants are attached lazily when their
approved Milo build is first claimed.

Presets: `high_velocity_d2c` (automatic default) and `editorial_showcase` (manual).
A clip swap keeps the narration/alignment manifest and queues a new revision;
it invalidates even an already-approved old export. Fresh media requires fresh
approval. Approval validates current brand/proof sources and eligible clip
checksums. Structured video drafts cannot be text-edited or sent through the
text publisher. Approve & Export records approval and permits MP4 download.

Unknown paid submissions still require Milo receipt reconciliation. Never clear
an ambiguous submission just to allow retry. Definitively failed provider tasks
receive a new attempt on explicit retry. Renderer failures retain actionable
codes/messages; telemetry includes per-stage durations, asset provenance,
alignment coverage/interpolation, fallback use and media properties.

Verification from `core/`:

```powershell
python -m unittest discover -s tests -p 'test_vea*.py' -v
python -m services.vea.evals.run
$env:CONVERZA_WORKFLOW_TEST_DSN='host=127.0.0.1 port=55441 user=postgres dbname=test_converza_vea'
python -m unittest discover -s tests -p test_vea_postgres.py -v
```

The PostgreSQL lane requires an isolated `test_converza*` database. The local
evaluation requires 100% source-safety and determinism success across English,
Russian and Uzbek. Renderer alignment/media evaluations are separate. Monitor
render success, approval-to-preview latency, alignment rejection/interpolation,
fallback frequency and missing-assets failures before wider rollout.
