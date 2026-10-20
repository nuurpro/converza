# VEA deterministic video production

VEA extends the existing approved-only MoneyPrinterTurbo renderer and Milo build
queue. Approved scripts automatically produce the high-velocity D2C preset when
the feature flags are enabled. Editorial variants and clip replacements are
requested in the VEA workspace. Video approval permits export; no social
publication is performed.

## Provision and enable

1. Apply migrations 001 through 009 in order. Migration 009 adds independent
   variants, revision history, transactional commands, and structured-video
   approval guards. Use the normal deployment migration process; this change
   does not apply production migrations automatically.
2. Provision a read-only asset directory containing `catalog.json` and the
   referenced rights-confirmed clips/music. Follow the catalog schema and hash
   instructions in `Vea/services/MoneyPrinterTurbo/README.vea.md`.
3. Provision the local faster-whisper model and any Piper ONNX voices outside
   Git. Map their host directory through `VEA_MODEL_HOST_PATH`. Configure
   `VEA_WHISPER_MODEL` to the mounted model directory. No model downloads occur
   in the render path. Unsupported or missing narration languages fail with an
   actionable error instead of changing language.
4. Configure `MPT_API_KEY`, ElevenLabs credentials and per-language voice IDs in
   the server-only environment. Configure Piper fallback only for installed,
   matching-language voices. Set the browser-accessible media origin in
   `MONEYPRINTERTURBO_PUBLIC_BASE_URL`.
5. After smoke tests, set `VEA_ENABLED=1` for the renderer and
   `VEA_PRESETS_ENABLED=1` for core. The example environment leaves both disabled.

Run from `core/` after provisioning the mount directories:

```powershell
docker compose -f compose.memory.yml -f compose.vea.yml config --quiet
docker compose -f compose.memory.yml -f compose.vea.yml up -d --build api milo-worker vea-renderer
```

Rebuild/restart the web application using its existing deployment process. For
a native web deployment, run `npm run build` and restart `npm run start` from
`web/`. Restart core API, Milo worker, and renderer after changing server
configuration or dependencies. Keep the renderer storage volume: it contains
durable task receipts and reusable narration/alignment caches.

The optional Compose override adds read-only asset/model mounts without changing
the existing flag-disabled stack. Host paths must already exist. No production
services were restarted as part of implementation.

## Behavior and recovery

Recipe version and SHA-256 are pinned before first submission. Receipts bind the
script, organization, brand snapshot, preset, variant revision, and provider
attempt. Composition manifests retain asset checksums, source intervals, music,
audio cache keys, and word-timing provenance. Private manifests and source paths
are excluded from browser responses.

Alignment uses normalized fuzzy tokens with a weighted-edit score of at least
90% and at least 90% acoustic anchors. At most two consecutive missed tokens and
10% overall may use linear neighbor interpolation. Approved wording remains the
caption source. Lower-confidence or invalid timing fails explicitly.

Clip replacement preserves narration and unaffected selections, invalidates the
previous review/export, and requires fresh approval. Final approval rechecks
current evidence and asset eligibility. Definitively failed renders have an
explicit retry; unknown submissions require receipt reconciliation through the
existing Milo job controls. Never clear an uncertain submission to force a retry.

Disable `VEA_PRESETS_ENABLED` to stop new manual variants and swaps. Existing
variant jobs retain their bindings and can finish or recover. Existing submitted
legacy jobs are never converted into preset jobs. Monitor render success,
approval-to-preview latency, missing-assets failures, narration fallback,
alignment rejection, and interpolated-token frequency before broader enablement.

## Verification

Core gate and evaluation commands, from `core/`:

```powershell
python -m unittest discover -s tests -q
python -m services.vea.evals.run
python -m services.milo.evals.run
python -m services.workflow.evals.run
```

Use `CONVERZA_WORKFLOW_TEST_DSN` only with an isolated `test_converza*` database
to run the PostgreSQL transaction lanes. The fixture suites never use production
Supabase. From `web/`, run `npm test`, `npm run typecheck`, and `npm run build`.
Renderer tests, media proof, and acoustic-corpus evaluation are documented in its
VEA README.

Real FFmpeg proof uses synthetic footage and audio to verify media composition,
captions, codecs, duration, and thumbnails. Synthetic timing fixtures do not
establish real ASR accuracy. The annotated recorded-speech corpus gate requires
provisioned speech fixtures and a local model; ElevenLabs/Piper voice quality
also requires the deployment's configured voices.

Docker Compose configuration was validated locally. Container build/startup
remains unverified because Docker Desktop's Linux daemon is unavailable. Native
renderer and actual FFmpeg checks provide separate validation, not a Docker
startup claim.
