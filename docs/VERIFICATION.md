# Verification Report

Date: 2026-10-27. Overall consolidation status: **BLOCKED at physical retirement**.
The application repairs and local integrated verification pass. Eight obsolete
sibling roots remain because directory deletion is blocked and the desktop chat
still uses the old `Converza_ai` cwd. No claim of a one-source-tree finish is made.

## Results

| Gate | Result |
| --- | --- |
| Core, real SQL concurrency/migrations, memory SQL, real-media journey | 390 tests passed, 0 failures, 0 skips |
| Frontend | 72 tests, type checking, production build |
| Focused approved-only renderer suite | 61 tests passed, 0 skips |
| Workflow fixtures | 39/39 |
| Memory extraction fixtures | 5/5 |
| Retrieval/citation/pricing/learning safety matrix | 341/341 |
| Sleyz/Milo/Vea offline evaluations | All fixture safety/quality thresholds met |
| Renderer synthetic alignment/catalog evaluation | 4/4; not real speech-quality evidence |
| npm audit | 0 reported vulnerabilities after Next 15.5.28 and PostCSS override |
| Recovery | 10 verified source archives, 14 verified Git bundles, 17 restored sample files, SQLite integrity OK |
| Renderer state cutover | 110 storage files hash-verified; 14 final MP4 files preserved; 3 served previews hash-checked |
| Canonical Docker stack | Core 8000, ingress 8001, review adapter 8002, renderer 8080, web 3000 running |

The staged Git index was also restored into a clean directory without private
environment files or untracked application files: all 390 core tests (including
the SQL/real-media journey) and all 72 frontend tests plus type checking passed.
The production core image's Python 3.12 dependencies separately passed 389 tests;
its sole skip was the duplicate Docker-exec journey, already verified by the
host lane. This is not an unverified integration gate.

`reports/local/core-tests.json` and `core-tests.log` contain the latest core
results. The full journey writes its report, real H.264/AAC 1080x1920 MP4, and
thumbnail under the printed temporary `converza-journey/<run-id>` directory.
The final renderer has authenticated controls, durable receipts, automatic
publishing disabled, and preset production disabled pending real provisioning.
HTTP health does not imply Supabase migrations or live channels are ready.

## End-To-End Evidence

The integrated test uses signed inbound fixture traffic, production Sleyz
drafting/retrieval, a real SQL human-edit transition, one controlled outbound
delivery and durable receipt, approved-edit learning, correction reuse on the
next DM, Milo objection mining, human-approved scripts, actual FFmpeg
composition, receipt reconciliation, preview download, and final human video
approval. It verifies that unapproved execution and cross-tenant reads fail.

Models, owner authentication, and channel HTTP are controlled fixtures. Narration
uses synthetic tones with fixture timestamps and generated footage. Renderer
requests run through its real ASGI app via TestClient over a Docker exec bridge,
not through its listening socket. The listening canonical renderer is separately
checked for authentication, capabilities, and migrated-media downloads. These
tests do not establish live model quality, acoustic alignment quality, or
successful customer delivery.

## Browser Evidence

gstack browser inspected the actual Next.js app against loopback SQL fixtures:

- Desktop at 1440x1000 and mobile at 390x844; dashboard and Squad screenshots are
  retained privately under `.gstack/consolidation-*.png`.
- No horizontal overflow. Mobile Squad header and feed meet at y=80 rather than
  overlapping; composer remains visible at the bottom. Desktop header/feed meet
  at y=66. Original visual design is retained.
- A fresh browser restores organization identity without a local org cache.
  Switching from Nova Training to Festival Studio removes the first account's
  data even when stale cached org/brand values are planted. A cross-tenant
  product request returns 403. Reload preserves the correct organization;
  signout returns to the public route without the prior workspace.
- Initial SSE and reconnect with an invalid future cursor both return HTTP 200
  with `id:` and a fresh snapshot. Unit tests additionally cover cursor resume,
  token refresh, in-flight account changes, and delayed-response cancellation.
- Browser testing exposed and fixed concurrent session-restore cancellation;
  a dedicated regression now shares a single restore request.
- Retry identity tests cover lost response bodies after successful headers,
  not only connection failures before a response.

## Reproduce The Isolated Run

First use only; existing test containers can instead be started with `docker start`.
The candidate is deliberately separate from canonical renderer storage.

```powershell
docker run -d --name converza-cleanup-postgres -p 127.0.0.1:55441:5432 -e POSTGRES_PASSWORD=converza-test-only -e POSTGRES_DB=test_converza_cleanup postgres:16-alpine
docker exec converza-cleanup-postgres createdb -U postgres test_converza_memory
docker exec converza-cleanup-postgres createdb -U postgres test_converza_journey
docker build -f Vea/services/MoneyPrinterTurbo/Dockerfile.milo -t converza/approved-renderer:consolidation Vea/services/MoneyPrinterTurbo
docker run -d --name converza-renderer-candidate -e MPT_API_KEY=local-test-only -e VEA_ENABLED=1 --mount type=bind,source=E:/Coding/Converza/Vea/services/MoneyPrinterTurbo/test,target=/MoneyPrinterTurbo/test,readonly --mount type=bind,source=E:/Coding/Converza/Vea/services/MoneyPrinterTurbo/scripts,target=/MoneyPrinterTurbo/scripts,readonly converza/approved-renderer:consolidation
python -m pip install -r core/requirements.test.txt
$env:CONVERZA_WORKFLOW_TEST_DSN='host=127.0.0.1 port=55441 user=postgres password=converza-test-only dbname=test_converza_cleanup'
$env:MEMORY_TEST_DSN='host=127.0.0.1 port=55441 user=postgres password=converza-test-only dbname=test_converza_memory'
$env:CONVERZA_JOURNEY_TEST_DSN='host=127.0.0.1 port=55441 user=postgres password=converza-test-only dbname=test_converza_journey'
./scripts/verify.ps1 -Journey
```

The Python verifier requires loopback test databases, replaces usable
provider/channel credentials with test values, and blocks external sockets.
Core tests without explicit SQL/journey variables intentionally report skipped
gates rather than pretending those integrations ran.

Approved renderer tests (run in the candidate, never the canonical state volume):

```powershell
docker exec -e MPT_RUN_API_TESTS=1 -e MPT_RUN_MEDIA_TESTS=1 converza-renderer-candidate python -m unittest test.services.test_approved_scenes test.services.test_approved_scene_pipeline test.services.test_approved_scene_render test.services.test_milo_api test.services.test_milo_runtime test.services.test_milo_durable_state test.services.test_vea_contract test.services.test_vea_api test.services.test_vea_pipeline test.services.test_vea_evaluation -q
docker exec converza-renderer-candidate python scripts/eval_vea.py
```

## Remaining Gates

- Physical removal of the preserved standalone directories, unsupported
  renderer UI/launchers, old archives, and eight sibling roots. Four registered
  worktrees were retired through Git after verified preservation. No running
  Docker mount points at an old sibling/worktree.
- Re-home this desktop chat's cwd to the canonical primary checkout before
  retiring `Converza_ai`. Moving project membership alone did not change cwd;
  attaching the primary checkout was refused because it is not a managed worktree.
- Review/apply production migration `010_consolidation.sql` after `009` and
  verify the real Supabase base schema. No production SQL was run here.
- Configure and register channel webhook secrets, verify real Telegram/Meta
  destinations, and perform separately authorized channel acceptance. Existing
  channel tokens were adopted privately from the supported manager config;
  they were not used to send messages or verified against the providers.
- Provision rights-cleared product assets, local narration voices and Whisper
  weights before enabling preset production. Live Huawei/paid TTS quality and
  recorded en/ru/uz speech evaluations were deliberately not run.
- Vendor renderer tests emit Pydantic/FastAPI deprecation warnings and MoviePy
  resource warnings. No test failures resulted; migration off deprecated APIs
  remains a separate maintenance task.

Workers are not running by default. Enabling the workers profile can incur model
costs and send already-approved real replies; it is a separate operational step.
