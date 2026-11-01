# Pending Approval Feed

Outcome: one oldest-first, tenant-scoped approval queue contains workflow drafts
and Milo scripts without merging their decision state machines.

## Contract

`GET /api/feed/pending?org_id=<org>&limit=50&cursor=<opaque>` requires the existing
authenticated user dependency and organization ownership check. Limit is 1-100.
Responses are `Cache-Control: no-store`:

```json
{
  "items": [{
    "id": "workflow:<draft-id>", "kind": "workflow", "source_id": "<draft-id>",
    "revision": 3, "created_at": "2026-01-01T00:00:00+00:00",
    "restrictions": {"can_approve": true, "can_edit": true, "can_reject": true, "reasons": []},
    "payload": {"draft": {"id": "<draft-id>"}}
  }],
  "next_cursor": null,
  "snapshot_at": "2026-01-01T00:00:01+00:00"
}
```

Milo items use `id=milo:<campaign-id>`, `kind=milo`, and
`payload={campaign: <existing campaign row>, review_href: <existing reviewer>}`.
The payloads retain the full existing review data, not just snippets. Restrictions
are snapshot hints, never permission grants; existing mutation endpoints still
recheck current ownership, revision, evidence and idempotency. Blocked and
needs-evidence items remain visible, with explicit reasons and disabled approval.

Each page uses **one SQL statement snapshot**, joining no independently queried
lists. Ordering is `(created_at, namespaced id COLLATE "C")`. Cursors bind the
organization, timestamp boundary and last key. A later page sees current statuses
but excludes rows created after the first page's timestamp: it is not a retained
MVCC transaction spanning HTTP requests. Backdated inserts can appear only on a
full refresh. The dashboard refreshes the whole loaded prefix on SSE snapshots,
state changes, reconnect, visibility/online recovery and five-second polling.
It cancels/ignores responses from unmounted organization scopes and preserves the
last good page during failures. Every valid snapshot is published even if another
SSE invalidation arrived during the read; one coalesced follow-up rechecks it.
This prevents continuous agent activity from starving the feed. Unrelated ledger
steps/messages do not invalidate the approval projection. Mutation endpoints
always recheck the current revision, not the snapshot's advisory restrictions.
New revisions remount draft review controls so
an old text edit cannot silently acquire a newer expected revision.

## Integration (Parent-Owned Glue)

In `core/main.py`, alongside the other router factories:

```python
from services.feed.routes import create_feed_router
app.include_router(create_feed_router(
    get_switchboard_repo, require_authenticated_user, _assert_user_owns_org,
))
```

Allow only `GET /api/feed/pending` through the existing authenticated frontend
backend proxy; retain its origin, fixed upstream and redirect protections.
Apply `core/migrations/012_pending_feed.sql` after the existing 001-011 schema.
The SQL RPC is executable by `service_role` only. It adds indexes and a read-only
function; it changes no approval lifecycle or production data.

No production migration, provider call, customer send or deployment is part of
this service's local verification. Frontend and core must be released together
after the additive migration is explicitly authorized/applied.

## Verification

From `E:/Coding/Converza/core`:

```powershell
python -m unittest discover -s tests -p 'test_pending_feed.py'
python -m services.feed.evals
# Explicit disposable DB only; tests reject any other database prefix.
$env:CONVERZA_FEED_TEST_DSN='host=127.0.0.1 port=55441 user=postgres password=converza-test-only dbname=test_converza_feed'
python -m unittest discover -s tests -p 'test_pending_feed*.py'
```

The SQL suite creates only projection fixture tables within its isolated
`test_converza_feed*` database and applies 012 there. Existing full lifecycle
tests remain the integration authority for stale revisions and duplicate
decisions. The parent rollout should apply 012 to its full-schema QA database
and inspect desktop/mobile before deploying. Frontend regressions live in
`Web/lib/data/pendingFeed.test.mjs`; the existing video card fixture was updated
to the polymorphic payload shape.
