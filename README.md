# Converza

Supported application root: `E:\Coding\Converza`.

Converza's current product is the Supabase-backed Milo, Sleyz, and Vea workforce.
Customer delivery and video export require human review. No social publishing
or real billing integration is implemented.

## Supported Services

| Service | Source | Loopback Port |
| --- | --- | --- |
| Core API, memory, approvals, SSE | `core/main.py`, `core/services/` | 8000 |
| Sleyz Telegram/Instagram ingress | `Sleyz/sales_main.py` | 8001 |
| Telegram review adapter | `core/manager/` | 8002 |
| Approved-script renderer | `Vea/services/MoneyPrinterTurbo/` | 8080 |
| Next.js frontend | `web/` | 3000 |
| Indexer, Sleyz worker, Milo/Vea build worker | `core/services/` | None |

Agent identities live only in `Milo/identity.md`, `Sleyz/identity.md`, and
`Vea/identity.md`. Application inference uses the shared Huawei service.

## Start

1. Install Docker Desktop with Linux containers.
2. Configure private `core/.env` from `core/.env.example` and `web/.env.local`
   from `web/.env.example`. Use the same `BACKEND_API_KEY` in both. Only the
   Supabase URL and anon key are public; service-role/model/channel keys stay
   server-side. Native Python services load `core/.env`, regardless of cwd;
   existing process variables take precedence.
3. Review and apply migrations `001` through `014` in order in the target
   Supabase project. This repository never applies production migrations at startup.
   Pre-workflow legacy databases require the backed-up compatibility procedure
   in `core/compatibility/README.md` first; do not cast legacy tenant keys blindly.
4. Provision local service credentials and persistent storage:

```powershell
python scripts/check_upgrade_schema.py --require-ready
python scripts/provision_local.py
docker volume create converza-vea-storage
docker compose --env-file web/.env.local up -d --build
```

Open <http://127.0.0.1:3000>. Core health: <http://127.0.0.1:8000/health>.
The authenticated renderer capability endpoint is `/api/v1/capabilities`.
Set `WEB_PUBLIC_ORIGIN` to the exact browser origin, including its port. The
default is `http://127.0.0.1:3000`; using `localhost` instead requires changing
that setting. Docker's internal host is not a trusted public origin.

For the workspace/feed/renderer upgrade, follow
[the migration and rollout gates](docs/WORKSPACE_RENDERER_UPGRADE.md) before
replacing an existing stack. Source verification is not a production migration.

Background workers are deliberately opt-in. They can invoke paid inference and
deliver already-approved real messages. Start them only after reviewing the
configured organization, channel destinations, and provider:

```powershell
docker compose --env-file web/.env.local --profile workers up -d --build
```

Register the two Telegram webhook URLs separately with their corresponding
`SALES_WEBHOOK_SECRET` and `MANAGER_WEBHOOK_SECRET`. Health alone does not prove
channel credentials, SQL migrations, models, or assets are ready.

### Deterministic Video Production

Preset Vea production additionally needs a rights-cleared organization/product
asset catalog, narration voices, and a local Whisper model. Do not enable it to
hide missing resources. Mount these read-only using a deployment override (see
`core/compose.vea.yml`) and configure `VEA_ASSET_ROOT`, `VEA_PIPER_VOICES`, and
`VEA_WHISPER_MODEL`, then set both `VEA_ENABLED=1` and `VEA_PRESETS_ENABLED=1`.
The default stack exposes the approved-only renderer but does not provision
models, download stock clips, or publish anything.

## Verify

```powershell
python -m pip install -r core/requirements.test.txt
Set-Location core
python -m unittest discover -s tests -q
python -m services.workflow.evals.run
python evals/memory/run.py
python evals/memory_sleyz_safety.py
python -m services.sleyz.evals.run
python -m services.milo.evals.run
python -m services.vea.evals.run
Set-Location ../web
npm ci
npm test
npm run typecheck
npm run build
```

SQL tests require explicitly named disposable PostgreSQL databases via
`CONVERZA_WORKFLOW_TEST_DSN`, `MEMORY_TEST_DSN`, and `CONVERZA_FEED_TEST_DSN`
(its own `test_converza_feed` database). `scripts/verify.ps1 -Journey`
also enables the real-media journey with its separate
`CONVERZA_JOURNEY_TEST_DSN` (`test_converza_journey`) and an isolated renderer
test container. Paid `--live` evaluation lanes are separate,
not part of automated local verification. Real-media renderer tests use
synthetic provider inputs but execute actual FFmpeg composition.

## Recovery And Consolidation

Private verified snapshots and Git bundles are outside the product at
`E:\Coding\_Converza_recovery\20261027-122215`. They contain credentials and
must never be committed or uploaded. See [consolidation report](docs/CONSOLIDATION.md)
for evidence, retirement gates, rollback, and remaining acceptance blockers.
