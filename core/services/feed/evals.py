"""Free fixture matrix: each lifecycle/status and page size must preserve truth."""
import asyncio
from datetime import datetime, timedelta, timezone
import json

from lib.repository import InMemoryRepository
from services.milo.store import MiloStore
from . import PendingFeedStore


async def run():
    repo = InMemoryRepository()
    milo = MiloStore(repo)
    expected = []
    origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for n in range(24):
        created = (origin + timedelta(seconds=n // 2)).isoformat()
        org = 'a' if n % 3 else 'other'
        status = ('AWAITING_HITL', 'REJECTED', 'APPROVED', 'PUBLISHED')[n % 4]
        draft = dict(id=f'd-{n:02}', org_id=org, revision=n+1, agent_slug='sleyz',
                     created_at=created, status=status, draft_content='Only verified content')
        repo.drafts.append(draft)
        if org == 'a' and status == 'AWAITING_HITL':
            expected.append((created, 'workflow:' + draft['id']))
        reviewable = ('awaiting_review','blocked','needs_evidence','queued')[n % 4]
        campaign = dict(id=f'c-{n:02}', org_id=org, revision=n+1, created_at=created, status=reviewable,
                        script_status='pending', artifact={'trigger_reason':'Fixture buyer evidence'},
                        compliance={'passed':reviewable=='awaiting_review'}, missing_evidence=[], build_status=None)
        milo.state['campaigns'][campaign['id']] = campaign
        if org == 'a' and reviewable != 'queued':
            expected.append((created, 'milo:' + campaign['id']))
    results = []
    for size in (1, 2, 3, 7, 50, 100):
        cursor = None
        items = []
        while True:
            page = await PendingFeedStore(repo).pending('a', limit=size, cursor=cursor)
            items.extend(page['items'])
            cursor = page['next_cursor']
            if not cursor:
                break
        ordered = [id for _,id in sorted(expected)]
        passed = [item['id'] for item in items] == ordered
        passed &= all(not item['restrictions']['can_approve'] for item in items
                      if item['kind'] == 'milo' and item['payload']['campaign']['status'] != 'awaiting_review')
        result = dict(fixture=f'mixed_tenants_page_size_{size}', passed=passed, item_count=len(items))
        results.append(result)
        print(json.dumps(result), flush=True)
    if not all(value['passed'] for value in results):
        raise SystemExit(1)
    return results


if __name__ == '__main__':
    asyncio.run(run())
