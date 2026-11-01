# Workspace, Feed, And Renderer Upgrade

Source changes and isolated verification are implemented.
**Renderer rollout is complete; core/frontend rollout is gated on production SQL.**
The user approved the full 100.23 MB snapshot and local renderer cutover. The
canonical renderer on port 8080 now uses the verified v1.3.9 image. All 112 stored
files match the private snapshot after restart, and existing previews work.
The configured Supabase project's read-only schema metadata confirms 011-013
are missing. Core/frontend remain on their previous images to avoid a partial,
schema-incompatible deployment. SQL administration is not connected in this
session; the Supabase integration or a separately configured SQL connection is
needed to execute authorized migrations, otherwise use the SQL editor manually.
No production Supabase migration, paid inference or customer send was performed.

## Source Changes

| Area | Implementation |
| --- | --- |
| Origin protection | Explicit server-only `WEB_PUBLIC_ORIGIN`, fail-closed production configuration, no forwarded-host trust; existing authentication, path allowlist and redirect refusal remain |
| Sign-in | Awaits authenticated passport restoration before navigation; returning credentials are not subjected to sign-up-only password rules |
| Onboarding | Completed accounts redirect; incomplete accounts restore persisted answers; lookup failures have Retry controls; no browser/proxy UUID recovery |
| Creation | `workspace_save_passport` serializes per owner and creates org/passport atomically; preserves org/completion/payment fields and rejects known unresolved or ambiguous ownership |
| Approvals | One authenticated SQL statement snapshot combines workflow and Milo pending reviews; stable namespaced identities, revisions, oldest-first pagination and blocked-review restrictions |
| Dashboard | One feed controller refreshes on SSE, reconnect, visibility/online changes and polling; keeps existing mutation lifecycles and review components |
| Facts | Complete source claims only, including cross-line English/Uzbek qualifiers; exact citation offsets, product-aware stale-price suppression and atom indexes retained |
| Initiative | Existing `product_id` is validated transactionally and retained through generation, approval, retries and Vea variants; optional initiative picker uses the authenticated catalog |
| Automatic clips | Explicit initiative assignment plus semantic relevance required; unassigned footage cannot substitute |
| Operator clips | Persisted authenticated swaps may use any eligible same-tenant clip; safe center crop, no stretching; duration/rights/hash/path/dimensions checks remain; swaps require new approval |
| Renderer | Three-way import of official v1.3.9, exact commit `6992380c5e82f07f3e1fc46b90927b6f1c655407`; approved-only API, durable receipts, bindings and no publishing retained |

Legacy passports without an authoritative owner link are not claimed by name,
email guesses or cached tenant IDs. An ownership error needs an operator repair
using verified account records; refreshing must not manufacture a replacement.

## Additive Database Changes

Review/apply these manually to production after the existing 001-010 schema:

1. `core/migrations/011_workspace_restore.sql`: service-only transactional
   onboarding RPC. Existing `orgs` requires `id`, `name`, `created_at`; the
   existing Brand Passport and auth ownership columns remain authoritative.
2. `core/migrations/012_pending_feed.sql`: read-only service-only snapshot RPC
   and partial indexes. Does not merge approval mutation state machines.
3. `core/migrations/013_milo_scope.sql`: validates catalog selection under the
   campaign transaction, retains selected scope and idempotent request identity.

No redundant initiative column, membership table or destructive migration was
added. The local tests apply migrations only in disposable loopback databases.
Do not deploy the new dashboard against a core/schema missing migration 012.
Do not enable workers to discover missing migrations through live jobs.

## Verified Evidence

- Latest complete core run: **442 passed, zero failures/errors/skips**, with
  workflow, memory, pending-feed SQL and real-media journey enabled. Evidence:
  `reports/local/core-tests.json` and `core-tests.log`.
- Real journey report:
  `C:/Users/ACER/AppData/Local/Temp/converza-journey/1889ead3a3f0403898b36142945f163a/report.json`.
  It traversed signed fixture DM, Sleyz draft, human edit, controlled receipt,
  learned correction, Milo campaign/script approval, actual FFmpeg video,
  durable bound receipt, preview and final human approval.
- Latest frontend run: **93 passing tests**, passing TypeScript and a successful
  final-tree production build with the initiative picker and auth-form changes.
- Renderer candidate: **68 focused tests**, zero skips, including real media,
  off-tag/cross-initiative landscape crops, bindings, authentication and receipts.
  Details/provenance: `Vea/services/MoneyPrinterTurbo/UPGRADE.v1.3.9.md`.
- Actual Docker-origin smoke: configured public origin reaches authentication
  (401 without credentials); forged origin returns 403. New core image starts
  and serves health. No live-provider request is part of either smoke.
- gstack inspected the actual QA frontend against its full-schema disposable
  PostgreSQL harness. Completed-account sign-in and direct `/onboarding` access
  reached the persisted workspace. Cleared browser caches did not create a new
  tenant. Mixed Sleyz/Milo reviews appeared in one queue. Switching to Festival
  Studio cleared Nova approvals; a cross-tenant feed request returned 403.
- Desktop and 390x844 mobile screenshots are retained in
  `reports/local/upgrade-desktop.png`, `upgrade-mobile.png` and
  `upgrade-mobile-feed.png`. Mobile document width was 390, with no horizontal
  overflow. Existing visual design was preserved.

Models, auth, channel responses, narration and alignment in these tests are
controlled fixtures. FFmpeg, SQL transactions, application routes and receipt
handling are real. This is not live-provider, real speech-quality or customer
delivery acceptance.

## Reproduce The Final Gates

Use the existing disposable PostgreSQL container, or provision an isolated one.
Never point these variables at production. The feed suite requires its own
`test_converza_feed` database; the other test fixtures have different base schemas.

```powershell
$env:CONVERZA_WORKFLOW_TEST_DSN='host=127.0.0.1 port=55441 user=postgres password=converza-test-only dbname=test_converza_cleanup'
$env:MEMORY_TEST_DSN='host=127.0.0.1 port=55441 user=postgres password=converza-test-only dbname=test_converza_memory'
$env:CONVERZA_FEED_TEST_DSN='host=127.0.0.1 port=55441 user=postgres password=converza-test-only dbname=test_converza_feed'
$env:CONVERZA_JOURNEY_TEST_DSN='host=127.0.0.1 port=55441 user=postgres password=converza-test-only dbname=test_converza_journey'
$env:CONVERZA_JOURNEY_RENDERER_CONTAINER='converza-vea-v139-verified'
./scripts/verify.ps1 -Journey
```

Final candidate `converza-vea-v139-verified` listens only on 127.0.0.1:8090 and
uses its own volume, never canonical storage. The image is
`converza-vea:v1.3.9-verified`, immutable ID
`sha256:27cdc38a708b9b4531abce688bb9dc66a961e19ebe495174eff327d684c14943`.
It is also tagged `converza/approved-renderer:1.3.9-converza` for the canonical
compose service. Do not substitute a moving upstream image tag.

## Rollout And Rollback Gates

Completed renderer gates:

1. Confirmed no active tasks, then stopped only the identified renderer. Worker
   profiles remained disabled. No other application container was quiesced.
2. Used `scripts/snapshot_renderer_volume.py --confirm-backup` to copy complete
   named-volume storage and configuration privately. NTFS ACLs grant only the
   current owner and SYSTEM access. SQLite integrity and every checksum passed.
3. Restored a separate copy to `converza-vea-restored-v139` on loopback 8091.
   Its 112 file hashes matched. Authentication, exact version/commit, two old MP4
   URLs, one JPEG and denial of private task artifacts passed.
4. Preserved the old image as `converza/approved-renderer:rollback-pre-v139-20261101`.
   Replaced only the canonical renderer, reusing `converza-vea-storage`. Repeated
   all restore checks against port 8080 successfully. No volume was deleted.

The existing SQLite database contained **zero durable receipt rows**. Its digest
and integrity remain unchanged; no historical receipts were invented. Real
durable receipt creation/reconciliation is separately covered by the journey.

Remaining application gate: authorize/apply production migrations 011-013,
verify ownership links, then deploy core/frontend together. No production
backfill is implicit. Check readiness first:

```powershell
python scripts/check_upgrade_schema.py --require-ready
```

Never enable workers to discover missing schema or assets through real jobs.

Source rollback backup:
`E:/Coding/_Converza_recovery/renderer-upgrade-20261031-014806` contains the full
prior vendor tree, SHA-256 manifest and three-way merge inputs. It is private and
must not be committed. The consistent named-volume/configuration snapshot is at
`E:/Coding/_Converza_recovery/renderer-cutover-20261101-121800`.
It contains `files.json`, `report.json`, private original Docker inspection,
configuration, complete storage and `converza-vea-renderer-1.verification.json`.
The prior consolidation recovery remains untouched.

Rollback the image without deleting or overwriting state:

```powershell
docker compose --env-file web/.env.local -f compose.yml -f E:/Coding/_Converza_recovery/renderer-cutover-20261101-121800/rollback.compose.json up -d --no-deps --no-build vea-renderer
```

Before any later filesystem rollback, quiesce producers and preserve the then-current
state as another private snapshot so newer receipts/media cannot be discarded.

Once the migration/cutover gates are satisfied, the joint application command is:

```powershell
docker compose --env-file web/.env.local up -d --build api web
```

The worker profile can incur paid model/TTS work and send approved customer
messages. It must remain off during offline verification. Real rights-cleared
initiative footage, voices and Whisper weights remain deployment prerequisites.
