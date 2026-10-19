"""Pure time/evidence decisions; queue RPC owns concurrent reservations."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from zoneinfo import ZoneInfo

from .evidence import get_top_buyer_objections, load_context
from .store import MiloStore


def evidence_key(group,context):
    values={'buyer_ids':sorted(group['source_ids']),'topic':group['topic'],'product_id':group['product_id'],
            'brand_revision':context['brand_revision'],
            'proof_revisions':sorted((p['source_id'],p['revision']) for p in context['proof_points'])}
    return 'auto:'+hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()


async def schedule(repo, *, now=None):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None: raise ValueError('Scheduling requires a timezone-aware instant')
    store=MiloStore(repo); enqueued=[]
    for org in await store.organizations():
        settings=await store.settings(org)
        if not settings['daily_enabled'] and not settings['spike_enabled']: continue
        current=await load_context(repo,org,store,since=now-timedelta(days=settings['window_days']))
        groups=get_top_buyer_objections(current['objections'],org_id=org)
        previous={row['id'] for row in await store.list_campaigns(org)}
        local=now.astimezone(ZoneInfo(settings['timezone']))
        if not groups:
            if settings['daily_enabled'] and local.hour>=settings['daily_hour']:
                row=await store.enqueue(org,'daily',key='auto:missing-evidence:'+str(current['brand_revision']))
                if row and row['id'] not in previous: enqueued.append(row)
            continue
        candidates=[]
        if settings['daily_enabled'] and local.hour>=settings['daily_hour']:
            candidates.append(('daily',groups[0]))
        if settings['spike_enabled']:
            candidates += [('spike',g) for g in groups if g['count']>=settings['spike_threshold']]
        for trigger,group in candidates:
            row=await store.enqueue(org,trigger,key=evidence_key(group,current),topic=group['topic'],product_id=group['product_id'],evidence_ids=group['source_ids'])
            if row and row['id'] not in previous:
                previous.add(row['id']); enqueued.append(row)
    return enqueued
