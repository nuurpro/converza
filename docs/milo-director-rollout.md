# Milo director rollout

Production has not been migrated, restarted, or enabled by this task. The feature
defaults off. Resolve the configured shared text-inference resource outage and
pass its live director eval before enabling production.

## Prepare

Apply the additive migrations after the existing 001–014 chain, in this order:
`018_milo_director.sql`, `019_milo_director_documents.sql`, and
`020_milo_director_approval.sql`. Numbers 015–017 were reserved by concurrent
work; this feature does not depend on those unrelated migrations.

First validate on an explicitly named disposable test database. Deployment SQL,
after separate production authorization and normal backup procedure:

```powershell
psql $env:DEPLOYMENT_DSN -v ON_ERROR_STOP=1 --single-transaction -f core/migrations/018_milo_director.sql
psql $env:DEPLOYMENT_DSN -v ON_ERROR_STOP=1 --single-transaction -f core/migrations/019_milo_director_documents.sql
psql $env:DEPLOYMENT_DSN -v ON_ERROR_STOP=1 --single-transaction -f core/migrations/020_milo_director_approval.sql
```

These migrations add director tables, service-only RPCs, narration binding and
final approval guards, visual Passport constraints, and a central-feed projection.
They do not run historical inference or modify existing text drafts.

Set the existing private `MPT_API_KEY` identically in core and renderer. Keep the
control API internal; public output exposes only final MP4/JPG previews. Retain
the browser-reachable `MONEYPRINTERTURBO_PUBLIC_BASE_URL` configuration.

Provision read-only tenant asset and model directories through
`VEA_ASSET_HOST_PATH` and `VEA_MODEL_HOST_PATH`. Compose mounts them as
`/MoneyPrinterTurbo/brand-assets` and `/MoneyPrinterTurbo/models`. The image
includes FFmpeg, FFprobe, DejaVu fonts and Tesseract English/Russian/Uzbek data.
Configure `VEA_WHISPER_MODEL` as an explicit locally provisioned directory and
calibrate that exact model/configuration before enabling it. No job downloads
models or substitutes a model/provider.

Provision language-matching local Piper voices in `VEA_PIPER_VOICES`, or place
exact approved recordings plus the documented catalog under the read-only model
mount and set `VEA_DIRECTOR_NARRATION_ROOT` to that directory. See the provider's
`README.director.md`. Existing remote-primary speech settings are not silently
used as a fallback for director jobs.

Keep `VEA_DIRECTOR_DB` and `VEA_DIRECTOR_ROOT` on the persistent renderer storage
volume. Preserve that volume across recreation; receipts and artifacts are
required for reconciliation and reuse.

## Enable and restart

After dependency, local calibration and live shared-model gates pass, set
`MILO_DIRECTOR_ENABLED=true`. Default assembly uses hard cuts and narration only.
`MILO_DIRECTOR_TRANSITION=crossfade` selects 150 ms transitions.
`MILO_DIRECTOR_BACKGROUND_ASSET_ID` optionally selects an owned, rights-cleared
catalog music asset; it must exist for the target tenant.

Following separately authorized deployment, restart from the same source revision:

```powershell
docker compose up -d --build api milo-worker vea-renderer web
```

API supplies director/approval routes, Milo's worker claims scene/master tasks,
Vea executes them, and Web shows progress and decisions. No other service restart
is required. New campaigns generated while enabled receive a storyboard before
sign-off. Existing campaigns without one retain the legacy path.

## Acceptance and recovery

Generate a campaign, inspect buyer/proof evidence, then approve its initial
script. Verify each scene moves through directing, automatic verification and
verified without a human scene prompt. After final inspection, verify exactly
one current master appears in Central Approval Feed with the recommendation.
It still requires human approval; it cannot publish automatically.

Apply a visual-only bulk edit and verify unaffected verified scenes are reusable.
Change narration and verify production stops for narration sign-off. The prior
master must immediately lose approval eligibility. Replaying decisions must not
produce additional paid tasks or master drafts.

Watch persisted scene/attempt events, `BLOCKED` alerts, provider receipt IDs,
inspection violations, and deferred-start/cache-context logs. Transient failures
back off; the recovery action expedites checks of the original receipt. It does
not reset exhausted attempts or authorize blind resubmission. Correct an
exhausted scene with a new storyboard revision. Never delete receipts to retry.

Disable `MILO_DIRECTOR_ENABLED` to stop directing new work. Preserve tables and
volumes. In-flight director runs remain durable and resume when the feature is
re-enabled; never reinterpret them as legacy whole-video renders.
