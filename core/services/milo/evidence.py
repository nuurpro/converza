"""Tenant-scoped evidence selection; buyer concerns never become product facts."""
from copy import deepcopy
from datetime import datetime, timezone

from starlette.concurrency import run_in_threadpool
from services.memory import is_complete_claim_quote

from .contracts import BrandConfig, Persona


def get_top_buyer_objections(rows, *, org_id, since=None):
    groups = {}
    for row in rows:
        if row.get('org_id') != org_id or row.get('simulated') or row.get('deleted_at'):
            continue
        if since and datetime.fromisoformat(row['created_at'].replace('Z', '+00:00')) < since:
            continue
        topic = row.get('topic') or row.get('objection_type')
        key = (row.get('product_id'), topic)
        group = groups.setdefault(key, dict(product_id=key[0], topic=topic, count=0, examples=[], source_ids=[], latest_at=''))
        if row['id'] in group['source_ids']:
            continue
        group['source_ids'].append(row['id'])
        group['examples'].append(deepcopy(row))
        group['latest_at'] = max(group['latest_at'], row.get('created_at', ''))
    for group in groups.values():
        group['count'] = len({r['prospect_id'] for r in group['examples']})
        group['source_ids'].sort()
    return sorted(groups.values(), key=lambda g: (-g['count'], g['topic'], g['product_id'] or ''))


def personas(context):
    supplied = context['passport'].get('personas') or []
    if supplied:
        return [Persona.model_validate(item).model_dump() for item in supplied]
    audience = str(context['passport'].get('target_audience') or '').strip()
    return [dict(id='default', name=audience[:200], description=audience[:2000])] if audience else []


def valid_proof_points(context):
    sources = {row['id']: row for row in context['sources'] if row.get('org_id') == context['org_id'] and not row.get('deleted_at') and not row.get('forgotten_at') and row.get('kind') in ('product', 'faq', 'manual')}
    valid = []
    for point in context.get('proof_points', context['passport'].get('proof_points') or []):
        source = sources.get(point.get('source_id'))
        if (source and point.get('confirmed_by') and point.get('confirmed_at')
                and point.get('revision') == source.get('revision') and point.get('quote')
                and is_complete_claim_quote(source['content'], point['quote'])):
            if source['kind'] == 'product' and point.get('product_id') not in (None, source.get('external_id')):
                continue
            point=deepcopy(point)
            if source['kind']=='product': point['product_id']=source['external_id']
            valid.append(point)
    return valid


def prepare_evidence(context, *, topic=None, product_id=None):
    ranked = get_top_buyer_objections(context['objections'], org_id=context['org_id'])
    if topic:
        ranked = [g for g in ranked if g['topic'] == topic and g['product_id'] == product_id]
    elif product_id is not None:
        ranked = [g for g in ranked if g['product_id'] == product_id]
    selected = ranked[0] if ranked else None
    proofs = valid_proof_points(context)
    if selected:
        proofs = [p for p in proofs if (not p.get('product_id') or p['product_id'] == selected['product_id'])
                  and (not p.get('objection_topics') or selected['topic'] in p['objection_topics'])]
    targets = personas(context)
    missing = []
    if not selected:
        missing.append('Collect a real buyer objection through Sleyz before generating a campaign.')
    if not targets:
        missing.append('Add a target audience or persona to Brand Passport.')
    if not proofs:
        missing.append('Confirm a current product spec or brand fact that addresses the selected objection in Brand Passport.')
    return dict(selected=selected, proof_points=proofs, personas=targets, missing_evidence=missing)


async def load_context(repo, org_id, store, *, since):
    if hasattr(repo, 'client'):
        from services.memory import MemoryStore
        memory = MemoryStore(repo.client)
        identity = await run_in_threadpool(memory.identity, org_id)
        sources = await run_in_threadpool(memory._rows, 'memory_sources', org_id)
        products = await run_in_threadpool(memory.products, org_id)
        passport = identity['passport']
        revision = identity['revision']
    else:
        passport = await repo.get_brand_passport(org_id)
        revision = passport.get('revision', 1)
        sources = getattr(repo, 'memory_sources', [])
        products = getattr(repo, 'brand_products', [])
    return dict(org_id=org_id, passport=passport, brand_revision=revision, sources=sources, products=products,
                proof_points=passport.get('proof_points') or [], objections=await store.objections(org_id, since.isoformat()))


async def save_brand(repo, org_id, config, user_id):
    values = BrandConfig.model_validate(config).model_dump(mode='json')
    from datetime import timedelta
    from .store import MiloStore
    context = await load_context(repo, org_id, MiloStore(repo), since=datetime.now(timezone.utc)-timedelta(days=7))
    sources = {row['id']: row for row in context['sources'] if row.get('org_id') == org_id and not row.get('deleted_at') and not row.get('forgotten_at')}
    for point in values['proof_points']:
        source = sources.get(point['source_id'])
        if not source or source['kind'] not in ('product', 'faq', 'manual') or source['revision'] != point['revision'] or not is_complete_claim_quote(source['content'], point['quote']):
            raise ValueError('Proof must quote a current product, FAQ, or manual source exactly; refresh source revisions.')
        if source['kind'] == 'product':
            if point['product_id'] and point['product_id'] != source['external_id']:
                raise ValueError('Proof product does not match its source')
            point['product_id'] = source['external_id']
        point.update(confirmed_by=user_id, confirmed_at=datetime.now(timezone.utc).isoformat())
    if hasattr(repo, 'client'):
        from services.memory import MemoryStore
        await run_in_threadpool(MemoryStore(repo.client).save_identity, org_id, values)
    else:
        repo.seed_brand_passport(org_id, {**context['passport'], **values, 'revision': context['brand_revision'] + 1})
    return values
