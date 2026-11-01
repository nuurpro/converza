# Workspace, Feed, And Renderer Upgrade

Source changes and isolated verification are implemented.
**Renderer and joint core/frontend rollout are complete.**
The user approved the full 100.23 MB snapshot and local renderer cutover. The
canonical renderer on port 8080 now uses the verified v1.3.9 image. All 112 stored
files match the private snapshot after restart, and existing previews work.
SQL administration connected through the user-selected Primary connection.
Direct SQL inspection found missing prerequisite workflow/memory/Sleyz/Milo/Vea
tables/RPCs, not only 011-013. With explicit expanded authorization, the legacy
bridge and 001-013 were applied atomically as migration `20261101161357`.
Migration `20261101161726` then applied 014 to remove Supabase's direct browser
role grants from workflow functions before the application was restarted.
All five passports now reference valid orgs. Four remain ownerless, as explicitly
approved; their ownership was never guessed. The existing owned/completed
passport restores its saved answers and workspace through the deployed server.
`core/compatibility/legacy_workspace.sql` preserves exact legacy tenant joins in
a private mapping, creates missing org rows, keeps existing UUIDs and owner
links, and converts the five active tenant columns. It never guesses owners,
deletes records, schedules delivery or modifies the unused legacy billing tables.
The quiescent private snapshot verified all 104 original records against two
reads and independent SQL counts. Post-migration reconciliation found zero
unexpected field changes. The two existing child-only UUID roots were preserved
through a snapshot-bound audit; passport-bearing overlaps fail closed.
Core/frontend are running their verified images on 8000/3000. Ingress and
Telegram manager are restored on 8001/8002. Worker profiles remain disabled.
No paid inference, production backfill or customer send was performed.

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

## Database Rollout

The inspected live project is older than the tested 001-010 schema. Before
applying the following, take a verified private snapshot and run the optional
legacy bridge plus the prerequisite migration chain in a maintenance window.
Do not run the bridge against a database already using the workflow schema.

1. `core/migrations/011_workspace_restore.sql`: service-only transactional
   onboarding RPC. Existing `orgs` requires `id`, `name`, `created_at`; the
   existing Brand Passport and auth ownership columns remain authoritative.
2. `core/migrations/012_pending_feed.sql`: read-only service-only snapshot RPC
   and partial indexes. Does not merge approval mutation state machines.
3. `core/migrations/013_milo_scope.sql`: validates catalog selection under the
   campaign transaction, retains selected scope and idempotent request identity.
4. `core/migrations/014_workflow_rpc_privileges.sql`: closes direct Supabase
   default EXECUTE grants to browser roles. Actual post-migration SQL confirms
   zero anon/authenticated-executable agent/workflow functions.

No redundant initiative column, membership table or data-deleting migration was
added. Automated tests apply migrations only in disposable loopback databases;
the separately authorized production operations are recorded above.
Do not deploy the new dashboard against a core/schema missing migration 012.
Do not enable workers to discover missing migrations through live jobs.

The metadata preflight now verifies prerequisite RPCs, required tables/columns
and UUID tenant formats as well as the new upgrade RPCs. It is not a substitute
for SQL body/ownership checks. The bridge has eleven real-PostgreSQL regressions,
including the entire 001-014 chain, historical preservation and shared ingress;
snapshot safety has six regressions. Legacy Telegram-only NOT NULL fields are
relaxed so Instagram/shared ingress does not fail before drafting.
Maintenance and recovery steps are in `core/compatibility/README.md`.

Security advisors also flag four pre-existing public tables with RLS disabled:
`access_requests`, `org_subscriptions`, `org_subscription_payments`, and
`org_model_settings`. They are unused by this runtime and unchanged by the
bridge. This remains a separate security concern, not clean security acceptance.
Reference: https://supabase.com/docs/guides/database/database-linter?lint=0013_rls_disabled_in_public.
The legacy `deduct_credit`/`refund_credit` definer functions also remain callable
by browser roles. They are outside the current core/approved renderer and were
not enabled or changed by this rollout. These need a separate legacy billing
hardening decision; this report does not claim the entire Supabase project has
clean security advisories. New agent/workflow RPC browser access is verified zero.

## Verified Evidence

- Latest complete core run: **462 passed, zero failures/errors/skips**, with
  workflow, memory, pending-feed SQL and real-media journey enabled. Evidence:
  `reports/local/core-tests.json` and `core-tests.log`.
- Real journey report:
  `C:/Users/ACER/AppData/Local/Temp/converza-journey/3404113ff6a442d791376b3053fedce6/report.json`.
  It traversed signed fixture DM, Sleyz draft, human edit, controlled receipt,
  learned correction, Milo campaign/script approval, actual FFmpeg video,
  durable bound receipt, preview and final human approval.
- Latest frontend run: **93 passing tests**, passing TypeScript and a successful
  final-tree production build with the initiative picker and auth-form changes.
- Python 3.12 core-image lane before final audit guards: **453 passed**, zero failures/errors, with
  one skipped duplicate Docker-exec journey (454 discovered). The host lane ran that journey
  successfully, so no SQL/media gate is being replaced by this skip. Evidence:
  `reports/local/core-image/core-tests.json` and `core-tests.log`.
- Final immutable renderer image: **68 supported-manifest tests**, zero skips, including real media,
  off-tag/cross-initiative landscape crops, bindings, authentication and receipts.
  Details/provenance: `Vea/services/MoneyPrinterTurbo/UPGRADE.v1.3.9.md`.
  Fresh network-disabled evidence: `reports/local/renderer-tests.json` and
  `renderer-tests.log`. The reusable runner mounts evaluation scripts as well
  as tests; an initial missing-script-mount harness failure is retained separately
  as `renderer-tests.missing-script-mount.*`, not disguised as a passing test.
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
- Deployed-stack smoke checks pass: health/page 200; legitimate public origin
  reaches authentication (401 without a session), forged origin 403, protected
  feed 401 and internal routes 403. The actual completed passport is restored by
  the deployed server without changing data or impersonating a user session.
  The live pending snapshot returns six existing reviews across seven orgs.
- Actual deployed sign-in screenshots are `reports/local/deployed-upgrade-desktop.png`
  and `deployed-upgrade-mobile.png`. The mobile document width equals its 390px
  viewport. No real credentials were entered in these browser checks; full
  authenticated/account-switch flows use the controlled QA accounts above.
- Current application images are core
  `sha256:2a54136c9c3c7003dd11d7899a0098e878aec38792a20ab053ffee69b0a4e46e`
  and frontend `sha256:c3c27357fb2889aa760f97c7e575b6cae0bb14de61c7e279b34ecba947a97300`.
  `reports/local/workspace-rollout.json` records all five running services,
  passing health/origin/auth checks and zero sampled runtime error entries.

## Requirement Evidence

| Requirement | Direct Evidence |
| --- | --- |
| Auth/workspace restoration and transactional creation | `test_workspace_postgres.py`, `test_workspace_restore.py`, frontend auth/origin/session regressions; controlled completed-account/direct-onboarding/cache/account-switch browser checks; actual deployed owned/completed passport restores its original answers/org |
| One chronological feed with independent approval mutations | `test_pending_feed.py`, `test_pending_feed_postgres.py`, frontend feed refresh/reconnect tests; production `pending_approval_feed` returns six preserved reviews; existing workflow/Milo mutation regressions cover CAS/idempotency |
| Whole qualified facts and exact citations | `test_memory_claim_units.py`, `test_memory_sleyz_safety.py`, 12 qualification fixtures and 341 safety evaluations; omitted clauses cannot retain authoritative quotes/citations |
| Transactional canonical product/initiative scope | `test_milo_consolidation_postgres.py`, `test_milo_scope_postgres.py`, `test_milo_scope_validation.py`, Vea selection tests and multilingual offline evaluations; missing assigned footage fails rather than using unrelated assets |
| Authenticated manual override parity and fresh review | `test_vea_override_policy.py`, `test_vea_postgres.py`, renderer override/media tests; real landscape center crop, preserved failed exports and successful approval invalidation |
| Exact renderer vendor upgrade and retained state | `UPSTREAM.json`, hash-pinned lock/Docker source, three-way upgrade report; immutable deployed image, 112 matching files, zero altered historical receipts, old preview byte hashes and private-path/auth checks |
| Integrated verification without live sends/provider spending | `reports/local/core-tests.json` (462/462), all fixture evaluations, frontend 93/93/typecheck/build, real-FFmpeg journey; fixture auth/models/channels/narration are explicitly separate from live acceptance |
| Actual rollout and recovery | Supabase migration receipts `20261101161357` and `20261101161726`; private 104-record reconciliation, ACL/migration/config/image backups; production schema readiness, zero browser-executable agent RPCs and `reports/local/workspace-rollout.json` health/origin/auth gates |

Unprovisioned real voices/ASR weights/rights-cleared tenant catalogs and real
provider/channel acceptance remain outside this fixture-based rollout. Four
ownerless legacy passports remain deliberately unclaimed, as authorized.

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
$env:CONVERZA_LEGACY_TEST_DSN='host=127.0.0.1 port=55441 user=postgres password=converza-test-only dbname=test_converza_legacy_upgrade'
./scripts/verify.ps1 -Journey -Renderer
```

This combined command was executed successfully against the final tree: core
462/462, all offline evaluations, frontend 93/93 plus typecheck/audit/build,
real-FFmpeg journey and supported renderer 68/68, with no skipped required gates.

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

Completed application gates: privately backed up the six affected tables and
runtime/schema configuration; applied the audited bridge plus 001-014;
reconciled all 104 original records; verified authoritative ownership and
service-only RPC grants; deployed core/frontend together; restored ingress and
Telegram manager without starting workers. Readiness now returns `ready: true`:

```powershell
python scripts/check_upgrade_schema.py --require-ready
```

Never enable workers to discover missing schema or assets through real jobs.

Application recovery is at
`E:/Coding/_Converza_recovery/workspace-rollout-20261101-primary`.
It includes private pre/post rows, verified counts, schema/configuration,
reconciliation, exact applied SQL and manifests. Old images are retained as
`converza-api:rollback-workspace-20261101` and
`converza-web:rollback-workspace-20261101`. Do not restore old rows over newly
accepted work or reverse tenant mappings without a verified maintenance plan.

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

For a later joint application rebuild, use:

```powershell
docker compose --env-file web/.env.local up -d --build api web
```

The worker profile can incur paid model/TTS work and send approved customer
messages. It must remain off during offline verification. Real rights-cleared
initiative footage, voices and Whisper weights remain deployment prerequisites.
