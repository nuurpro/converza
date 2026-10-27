# Consolidation Evidence And Recovery

Branch: `codex/consolidate-current-product`. Canonical baseline commit: `09a3902`.

## Preservation

Private recovery: `E:\Coding\_Converza_recovery\20261027-122215`.
All ten source archives were checked against per-file SHA-256 manifests.
Fourteen repositories, including embedded repositories and registered
worktrees, have verified Git bundles, dirty patches, status, and worktree lists.
Seventeen representative files were restored and checked. Hermes's archived
SQLite database passes integrity checking, and the baseline commit was restored
from its bundle. Credentials remain in private snapshots, never in this report.

Preserved roots: canonical Converza plus Converza_ai, converza_bot, Converza_demo,
converza_intention, converza_manager, Converza_photo, Converza_sales,
Converza_hermes, and converza-comparison. The private `manifest.json` records
original paths and archive hashes. Dependency caches are excluded; source,
configuration, assets, nested worktree changes, and Git history are preserved.

## Implemented Repairs

- Session-authenticated frontend proxy with route allowlist, origin validation,
  fixed upstream origin, controlled headers, and no credential-bearing redirects.
- Server-restored workspace identity, owner-scoped onboarding caches, request
  cancellation, editor remounts, and SSE scope reset after account changes.
- Complete qualified retrieval claims, original-offset citation validation,
  bounded metadata, product-aware stale-price suppression, and accurate learning
  reporting. Omitted reply claims no longer retain citations.
- Authoritative Milo product/topic selection persists into both default and
  alternate approved video builds. Additive migration `010_consolidation.sql`
  requires deployment after `009`; older migration files remain unchanged.
- Clip replacements pass lexical relevance checks before superseding an export.
- Ambiguous mutation retries preserve operation keys. Vea jobs remain visible
  when unrelated catalogs fail. Dashboard links pending Milo reviews to their
  existing campaign approval controls.
- One identity per agent, explicit canonical environment loading, and root
  Compose/startup scripts. Telegram manager webhook now fails closed without
  its dedicated secret and validates it before reading updates.

## Retirement Manifest

Removed through scoped source edits: old `core/agents` DAG implementation,
unserved static chatbot pages, duplicate Milo content creator, test-only
`core/llm.py` alias, broken push launcher, duplicate identity files, unused
OpenClaw chat endpoint/permission widgets/DAG visualizer, disconnected frontend
demos and fabricated settings/metrics. Shared inference and workflow coverage
remain. `gsap` was removed with its lockfile entries.

Pending physical retirement gates:

- Recursive directory deletion was rejected by the execution environment. No
  standalone directory or sibling root was removed by that rejected command.
- This chat still has `Converza_ai` as its cwd. Project membership points to
  canonical Converza, but attaching the primary checkout was rejected because it
  is not a managed worktree. Do not delete that cwd until the desktop workspace
  is actually re-homed.
- Hermes was unregistered and retired with Git after its database/media and
  dirty source were verified in recovery. The three nested bot/legacy
  worktrees were also unregistered with Git. Branches and external bundles
  preserve their committed histories; archives and patches preserve dirty work.
- Standalone support-bot/qualifier/photo-bot directories, old archive copies,
  unsupported renderer UI/launchers, and eight sibling roots remain pending
  the physical-removal gate. They are not part of canonical Docker builds.

This is not yet the plan's one-source-tree completion state.

## Renderer Cutover

Built and tested the approved-only image on loopback 8081 before cutover.
Only `moneyprinterturbo-api` and `moneyprinterturbo-webui` were stopped.
The stock API reported zero in-flight tasks. A consistent final backup of their
bind mounts plus canonical renderer storage is in `renderer-final/` in recovery.
171 source/configuration files were verified; 110 merged storage files were
copied into the persistent named volume `converza-vea-storage` and hash-checked.
Supported queue/time/TLS settings were translated to `deployment/renderer.toml`.
Legacy provider tokens are not copied into that tracked configuration.

Canonical renderer now serves 8080, requires private control authentication,
persists receipts in SQLite, rejects unbound scripts, and never auto-publishes.
The obsolete stock API/UI containers and the temporary storage-transfer
container were removed after capability, storage, and media checks passed.
No volumes were deleted. Candidate test state remains isolated from canonical
renderer storage. Three preserved videos were served by the new API and checked
against their original hashes.

For rollback, first stop the canonical renderer:

```powershell
docker compose --env-file web/.env.local stop vea-renderer
```

Then restore configuration/storage into a separate private working directory
from `renderer-final/` and recreate the old containers using its saved
`docker-inspect.json` (original image, commands, environment, and mount targets).
Do not bind the immutable backup itself writable. A simple `docker start` is no
longer applicable to the removed containers. Keep the canonical storage volume
intact while rolling back.

## Restore Source

Use a new empty recovery checkout. Clone the corresponding verified bundle
listed in private `manifest.json`, then restore its source archive with a safe
tar extractor. Archives contain dirty/untracked files and configurations;
bundles contain committed histories. For canonical pre-task state use
`Converza.tar.gz` and `consolidated-start.patch`, not a reset of the current tree.
Never extract a snapshot over the supported working tree without reviewing it.

## Acceptance Status

Detailed verification results are recorded separately in `VERIFICATION.md`.
Production SQL migrations, live Huawei quality evaluations, real Telegram/Meta
delivery, local speech-model quality, and paid provider acceptance are not
authorized by this offline verification and are not claimed as passing.
