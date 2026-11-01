"""One snapshot of both approval lifecycles, never a second mutation bus."""
import base64
import binascii
from copy import deepcopy
from datetime import datetime, timezone
import json

from starlette.concurrency import run_in_threadpool
from .contracts import PendingPage


class InvalidFeedCursor(ValueError):
    """Client pagination state is malformed or belongs to another organization."""


def _time(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Feed timestamps must include a timezone')
    return parsed.astimezone(timezone.utc)


def _cursor(org, item, snapshot):
    value = dict(v=1, org=org, at=item['created_at'], id=item['id'], snapshot=snapshot)
    return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).decode().rstrip('=')


def _decode(cursor, org):
    if cursor is None:
        return None
    try:
        if not isinstance(cursor, str) or not 1 <= len(cursor) <= 2048:
            raise ValueError()
        value = json.loads(base64.b64decode(cursor + '=' * (-len(cursor) % 4), altchars=b'-_', validate=True))
        if (set(value) != {'v', 'org', 'at', 'id', 'snapshot'} or value['v'] != 1 or value['org'] != org
                or not isinstance(value['id'], str) or not value['id'].startswith(('workflow:', 'milo:'))):
            raise ValueError()
        if _time(value['at']) > _time(value['snapshot']):
            raise ValueError()
        return value
    except (ValueError, TypeError, AttributeError, binascii.Error, KeyError) as exc:
        raise InvalidFeedCursor('Invalid pending-feed cursor for this workspace') from exc


def _item(kind, row):
    if kind == 'workflow':
        restrictions = dict(can_approve=True, can_edit=not bool(row.get('vea_artifact')),
                            can_reject=True, reasons=[])
        payload = {'draft': row}
    else:
        ready = bool(row.get('artifact')) and row['status'] in ('awaiting_review', 'blocked') and not row.get('build_status')
        restrictions = dict(can_approve=ready and row['status'] == 'awaiting_review' and row.get('compliance', {}).get('passed') is True,
                            can_edit=ready, can_reject=ready,
                            reasons=[*row.get('compliance', {}).get('violations', []), *row.get('missing_evidence', [])])
        if not restrictions['can_approve'] and not restrictions['reasons']:
            restrictions['reasons'] = ['Campaign requires evidence or compliance review before approval']
        payload = {'campaign': row, 'review_href': '/agents/milo#campaign-' + row['id']}
    return dict(id=kind + ':' + row['id'], kind=kind, source_id=row['id'], revision=row['revision'],
                created_at=row['created_at'], restrictions=restrictions, payload=payload)


class PendingFeedStore:
    def __init__(self, repo):
        self.repo = repo

    async def pending(self, org, *, limit=50, cursor=None):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('Feed limit must be between 1 and 100')
        after = _decode(cursor, org)
        if hasattr(self.repo, 'client'):
            # UNION and page boundary execute in one PostgreSQL statement snapshot.
            params = dict(p_org_id=org, p_limit=limit,
                          p_after_created=after['at'] if after else None,
                          p_after_id=after['id'] if after else None,
                          p_snapshot=after['snapshot'] if after else None)
            result = (await run_in_threadpool(self.repo.client.rpc('pending_approval_feed', params).execute)).data
        else:
            # Both test-adapter mutation lifecycles use this same transaction lock.
            async with self.repo._lock:
                snapshot = after['snapshot'] if after else datetime.now(timezone.utc).isoformat()
                rows = [_item('workflow', row) for row in self.repo.drafts
                        if row['org_id'] == org and row['status'] == 'AWAITING_HITL' and not row.get('superseded_by')
                        and not (row.get('vea_artifact') or {}).get('superseded')]
                campaigns = getattr(self.repo, '_milo_state', {}).get('campaigns', {})
                rows += [_item('milo', row) for row in campaigns.values() if row['org_id'] == org
                         and row['script_status'] == 'pending' and row['status'] in ('awaiting_review', 'blocked', 'needs_evidence')]
                rows = [row for row in rows if _time(row['created_at']) <= _time(snapshot)
                        and (not after or (_time(row['created_at']), row['id']) > (_time(after['at']), after['id']))]
                rows.sort(key=lambda row: (_time(row['created_at']), row['id']))
                result = deepcopy(dict(items=rows[:limit], has_more=len(rows) > limit, snapshot_at=snapshot))
        items = result['items']
        page = dict(items=items, snapshot_at=result['snapshot_at'],
                    next_cursor=_cursor(org, items[-1], result['snapshot_at']) if items and result['has_more'] else None)
        return PendingPage.model_validate(page).model_dump()
