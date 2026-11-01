# Legacy Workspace Bridge

This optional bridge is for the inspected pre-workflow production schema, not
for a database already using migrations 004-013. It is not a new membership
system and does not claim ownerless passports.

## Evidence And Preconditions

- SQL inspection found five orphan passports: four non-UUID/unowned legacy
  tenants and one already UUID-scoped authenticated owner. Two additional
  child-only UUID keys already have canonical org rows and agent history.
- Preserve those two existing roots only after a private snapshot identity
  audit. No name/email matching, owner assignment, record deletion or automatic
  delivery is allowed. UUID spelling collisions and cross-tenant history fail.
- Read `legacy_workspace.sql` and run its PostgreSQL tests first. The complete
  migration chain is exercised against synthetic legacy records and existing
  agent tables/policies, not against production customer records.
- Independently inspect live constraints, policies, views, triggers and column
  types; the OpenAPI preflight cannot prove ownership or SQL body semantics.

## Maintenance Sequence

1. Build core/frontend before stopping anything. Preserve current container
   image IDs under rollback tags. Keep all worker profiles disabled.
2. Obtain explicit permission for the production bridge and prerequisite
   migrations, not merely permission for 011-013. Quiesce the local web, API,
   ingress and Telegram manager. Verify no other application writers are active.
3. Through privileged SQL, obtain exact counts for `orgs`, `brand_passports`,
   `prospects`, `messages`, `drafts`, and `tg_connections`. Save that JSON count
   object privately. Do not use a count derived from the same potentially
   RLS-filtered REST read as the independent check.
4. Run the bounded read-only snapshot:

   ```powershell
   python scripts/snapshot_workspace_database.py --writers-quiesced `
     --expected-counts <private-counts.json> --destination <new-private-directory>
   ```

   The script requires server-only credentials, an HTTPS fixed origin, two
   identical paginated reads and independently matching counts. It creates a
   private directory outside the repo and verifies the saved SHA-256. It stops
   above 100 MB/100,000 records; do not waive the size gate implicitly. Snapshot
   schema/constraints/policies and runtime configuration privately as well.
5. Audit existing roots against the backed-up `orgs` records. In the **same SQL
   transaction** as the bridge, supply a JSON array of their exact `id`, `name`,
   and `created_at` values with:

   ```sql
   SELECT set_config('converza.legacy_org_audit', '<private JSON array>', true);
   ```

   This is an admin-only migration parameter, not browser input. An absent,
   changed or fabricated root audit fails closed. Do not commit private values
   or put generated tenant IDs into the versioned SQL. The two roots remain
   unchanged and gain no new authenticated owner links.
6. Apply the bridge and migrations 001-013 as **one atomic maintenance
   migration**. Existing 001-003 tables/columns/policies are idempotent. Preserve
   this exact SQL bundle and its checksum privately. Do not deploy a partially
   applied chain. No memory backfill, workers or customer sends are part of DDL.
7. Reconcile all original IDs/content/owner links and table counts against the
   snapshot. Expected changes are canonical tenant references and draft status
   spelling (`pending` -> `AWAITING_HITL`, others uppercase); original delivery
   state must not be manufactured. Verify grants/RLS and service-only RPCs.
8. Run `python scripts/check_upgrade_schema.py --require-ready`. Deploy core
   and frontend together using the real public auth config. Verify health,
   legitimate/forged origins, authenticated restoration and pending feed.
   Restore only the intended ingress/manager services after schema acceptance.

## Recovery

Keep the private row snapshot, schema metadata, tenant map, exact applied bundle,
runtime configuration, old image tags and migration receipt. Never delete
renderer storage or restore a stale database snapshot over newly accepted work.
If a transaction fails, confirm rollback before resuming the old services. If
the database migration committed but deployment fails, keep workers disabled,
preserve current state, and use the retained image tags while investigating.
Database reversal requires a verified maintenance restore, not an unconditional
destructive script.

## Local Tests

Set `CONVERZA_LEGACY_TEST_DSN` to an **empty**, loopback `test_*` PostgreSQL
database. Tests use transactions and roll back all synthetic schema/data.

```powershell
python -m unittest discover -s core/tests -p test_legacy_workspace_upgrade.py -v
python -m unittest discover -s core/tests -p test_workspace_snapshot.py -v
python -m unittest discover -s core/tests -p test_upgrade_preflight.py -v
```

The snapshot is a verified quiescent maintenance copy of affected records, not
a substitute for PostgreSQL PITR or a backup of unrelated legacy billing data.
