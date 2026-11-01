# Converza approved renderer: v1.3.9

## Provenance

Official tag `v1.3.9`: `6992380c5e82f07f3e1fc46b90927b6f1c655407`.
Three-way base: `63113a34228ce569436e2cf0037d378c64b3a2ae`.
Import: 47 upstream files, two clean merges, three unchanged local overlays,
nine reviewed conflicts. The full previous tree, including untracked files, and
all merge inputs are preserved privately at
`E:/Coding/_Converza_recovery/renderer-upgrade-20261031-014806`.

Resolved conflicts: ASGI lifespan/preview protection; runtime config/read-only
fallback; approved schema fields; authenticated generation/video controllers;
disabled inference; approved task/receipt handling; approved overlay video;
and voice processing. Upstream media concurrency, runtime paths, subtitle/audio
handling and redacted diagnostics are retained. Converza's SQLite receipts,
bound jobs, deterministic presets and no-auto-publishing protections remain.

Only `Dockerfile.milo` is a supported build. It installs the hash-pinned Linux
Python 3.11 `requirements.milo.lock`, not upstream's optional-provider environment.
It does not install/start Streamlit, SDXL, the upstream CLI or a publishing service.
New diffusion/material providers are rejected by the approved HTTP API.
Pre-existing untracked upstream WebUI/docs/launchers are separate from the
approved source manifest and are neither deployed nor automatically staged.
Do not deploy this service with upstream `uv sync` or its WebUI Dockerfile.

`MPT_HOME=/MoneyPrinterTurbo` preserves existing storage, receipts and cache paths
despite upstream's installed-package runtime path changes. `config.toml` is not
overwritten; the checked-in template remains a read-only fallback. Keep the MIT
license and installed font license with the image. `UPSTREAM.json` records the pin.

## Selection Contract

Automatic B-roll must be rights-cleared, semantically matched and explicitly
assigned to selected `product_id`. Unassigned/other-initiative clips do not
substitute for missing initiative footage. Missing assets fail with instructions
to seed the vault. Tenant-owned music is not initiative/product B-roll.

The owner-authenticated core clip picker requests the renderer's `selection=manual`
catalog. Operator swaps may use off-tag or other-initiative footage, but still
require the same tenant, advertising rights, sufficient duration, valid dimensions,
verified hash and safe path. Geometry is center-cropped proportionally, never
stretched. Normalize non-square pixels/rotation before catalog ingestion.

Persisted `vea_variants.clip_overrides` are the manual authorization source.
They enter the immutable config hash and survive subsequent swaps/retries.
A flag in an old manifest cannot grant manual permission. Core validates the
rendered manual choices against the bound job before creating an approval draft.
Success supersedes old approval; invalid swaps do not mutate the variant, job,
receipt, draft or export. No additional variant-schema column is required.
Core migration 014 separately closes Supabase default workflow RPC grants.

## Verified Candidate

Final image: `converza-vea:v1.3.9-verified`, immutable ID
`sha256:27cdc38a708b9b4531abce688bb9dc66a961e19ebe495174eff327d684c14943`.
Container: `converza-vea-v139-verified`, loopback `127.0.0.1:8090`.
Storage: new `converza-vea-v139-verified-storage`, not the canonical volume.
Current test/scripts directories are mounted read-only for the journey bridge.
No production keys, vaults or models are mounted into candidate.

Reproduce the build from this directory:

```powershell
docker build -f Dockerfile.milo -t converza-vea:v1.3.9-verified .
```

Candidate has a local test-only bearer key, not the production key. For the
parent integration run:

```powershell
$env:CONVERZA_JOURNEY_RENDERER_CONTAINER='converza-vea-v139-verified'
```

The journey bridge creates a separate `/tmp/consolidated-journey-*` root with its
own SQLite database and assets; candidate ASGI/storage state is not changed.
Speech/timestamps are fixtures; FFmpeg, auth, contracts, receipts and media are
real. Do not send customer messages or invoke paid providers during verification.

Verified results:

- Core VEA focused suite: 43 passed before two further binding/retention tests;
  current storage/policy/route subset: 29 passed.
- PostgreSQL parity: 10 passed in separate `test_converza_renderer_upgrade`.
- Baked, hash-pinned image: 68 focused renderer tests passed, zero skips,
  networking disabled. Includes real FFmpeg/MoviePy, multilingual overlays,
  cross-initiative landscape manual crop, auth and durable receipt tests.
- Candidate capabilities confirm exact version/commit, approved-only jobs,
  durable state, manual overrides and strict automatic initiative scope.

Non-failing upstream warnings: MoviePy reader ResourceWarnings in local media
tests, Pydantic's enum-default serializer warning, and upstream's legacy
`app.api_key` startup warning. Converza bearer auth is separately enforced;
its 401/503 tests pass. These tests are not live-provider acceptance.
Real voice/ASR quality needs provisioned voices, models and annotated multilingual
speech recordings, none of which were supplied to this isolated candidate.

## Completed Canonical Cutover

The parent completed the separately authorized local renderer cutover after the
isolated tests. The live port-8080 service now uses the final image above, tagged
`converza/approved-renderer:1.3.9-converza`. All 112 stored file hashes and SQLite
integrity/digest match the private snapshot. Two old MP4s and one thumbnail serve
identical bytes; private task files remain blocked and controls require auth.
The legacy SQLite database had zero receipt rows; no historical receipt is
claimed or fabricated. The real-media journey separately verifies new receipts.

Private rollback snapshot: `E:/Coding/_Converza_recovery/renderer-cutover-20261101-121800`.
Old image tag: `converza/approved-renderer:rollback-pre-v139-20261101`.
Configuration/key identity was preserved. No volume was deleted. The renderer
cutover itself did not run production SQL. The separately authorized core/frontend
rollout has since applied the legacy bridge plus migrations 001-014 and deployed
both services. No paid call or customer send was part of verification. See
`docs/WORKSPACE_RENDERER_UPGRADE.md` at the repository root for evidence and rollback.

For a later upgrade, preserve the same gates:

1. Record the running canonical image ID and mounts/environment privately. Pause
   only its producers and finish active tasks or reconcile uncertain submissions.
   Retain all receipts, including failed/unknown attempts.
2. Quiesce the identified renderer before a final filesystem snapshot. Reuse the
   top-level `scripts/snapshot_renderer_volume.py` for named volumes. Never copy a live SQLite
   file without its WAL/consistent backup. Check SQLite integrity; copy/hash task
   previews, caches, models, catalog and configuration.
3. Keep an untouched private backup. Restore a separate copy into candidate
   storage and mount vault/models read-only. Preserve receipt IDs/runtime paths.
   Never attach canonical storage writable to two API processes.
4. Compare successful receipts/bindings and stored results; verify representative
   MP4/JPEG hashes and old preview URLs. Private scripts/audio/manifests must stay
   inaccessible. Run the real-FFmpeg approval journey on the candidate copy.
5. Only after approval, switch canonical renderer to the verified image with its
   persistent volume. Restart core/worker together; check auth, capabilities,
   reconciliation and old previews before resuming producers. Retain rollback
   image/container metadata and snapshots.
6. If readiness fails, restore the old image/config/state snapshot before
   resuming producers. Never delete volumes, receipts or media to retry.

Strict initiative scope may expose unassigned legacy catalogs: provision matching
footage before enabling workers. A synthetic journey does not authorize paid
providers, production migrations or customer delivery.
