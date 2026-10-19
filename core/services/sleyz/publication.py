"""Approved cross-platform sales delivery with one-time transport claims."""
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from starlette.concurrency import run_in_threadpool

from services.workflow import WorkflowConflict
from services.workflow.publication import deliver_telegram_draft
from services.workflow import publication as workflow_publication
from .channels import instagram_connections


def assert_instagram_window(received_at, *, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        value = datetime.fromisoformat(str(received_at).replace('Z', '+00:00'))
        if value.tzinfo is None or value > now or now - value >= timedelta(hours=24):
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError('Instagram messaging window expired or unknown; wait for a new buyer message') from None


async def load_inbound_row(repo, org_id, draft):
    """Bind destinations to the immutable accepted message behind this draft."""
    if hasattr(repo, '_sleyz_state'):
        rows = [row for row in repo._sleyz_state['inbox'].values()
                if row.get('org_id') == org_id and row.get('draft_id') == draft['id']
                and (not draft.get('inbound_id') or row['id'] == draft['inbound_id'])]
    else:
        query = repo.client.table('sleyz_inbound').select('*').eq('org_id', org_id).eq('draft_id', draft['id'])
        if draft.get('inbound_id'):
            query = query.eq('id', draft['inbound_id'])
        rows = (await run_in_threadpool(query.limit(1).execute)).data or []
    if not rows or rows[0].get('prospect_id') != draft.get('prospect_id'):
        raise ValueError('Draft has no authoritative inbound destination')
    row = rows[0]
    if row['envelope'].get('simulated') or row['envelope'].get('org_id') != org_id:
        raise ValueError('Draft has no live customer destination')
    return row


async def load_telegram_inbox_target(repo, org_id, draft):
    row = await load_inbound_row(repo, org_id, draft)
    envelope = row['envelope']
    chat_id = envelope.get('tg_chat_id')
    if envelope.get('platform') != 'telegram' or type(chat_id) is not int:
        raise ValueError('Draft has no authoritative Telegram destination')
    result = await run_in_threadpool(repo.client.table('tg_connections').select('bot_token,business_connection_id')
                                    .eq('org_id', org_id).limit(2).execute)
    if len(result.data or []) != 1 or not result.data[0].get('bot_token'):
        raise ValueError('Sales bot token is not uniquely configured for this organization')
    connection = result.data[0]
    business_id = envelope.get('business_connection_id')
    if business_id and (business_id != envelope.get('connection_id') or business_id != connection.get('business_connection_id')):
        raise ValueError('Original Telegram Business connection is no longer configured')
    return {'bot_token': connection['bot_token'], 'chat_id': chat_id, 'business_connection_id': business_id}


async def load_instagram_target(repo, org_id, draft):
    row = await load_inbound_row(repo, org_id, draft)
    envelope = row['envelope']
    if envelope.get('platform') != 'instagram':
        raise ValueError('Draft has no live Instagram destination')
    account = str(envelope.get('connection_id') or '')
    connection = instagram_connections().get(account)
    if not connection or str(connection['org_id']) != org_id or not envelope.get('customer_id'):
        raise ValueError('Instagram connection is not configured for this organization')
    # A later inbound from the same connected buyer refreshes the allowed window.
    if hasattr(repo, '_sleyz_state'):
        all_rows = repo._sleyz_state['inbox'].values()
        timestamps = [str((r.get('envelope') or r).get('received_at') or '') for r in all_rows if r.get('org_id') == org_id and (r.get('envelope') or r).get('connection_id') == account and (r.get('envelope') or r).get('customer_id') == envelope['customer_id'] and not (r.get('envelope') or r).get('simulated')]
    else:
        latest = await run_in_threadpool(repo.client.table('sleyz_inbound').select('received_at').eq('org_id',org_id).eq('platform','instagram').eq('connection_id',account).eq('prospect_id',draft['prospect_id']).order('received_at',desc=True).limit(1).execute)
        timestamps = [r['received_at'] for r in latest.data or []]
    assert_instagram_window(max(timestamps) if timestamps else envelope.get('received_at'))
    return {'account_id':account,'customer_id':str(envelope['customer_id']),'access_token':connection['access_token']}


async def deliver_sleyz_draft(*, repo, org_id, draft_id, expected_revision, idempotency_key):
    draft = await repo.get_draft(draft_id)
    if not draft or draft['org_id'] != org_id:
        raise KeyError(draft_id)
    if draft.get('simulated'):
        raise ValueError('Simulated drafts cannot send customer messages')
    if draft.get('superseded_by') or draft.get('superseded_by_draft_id'):
        raise ValueError('Superseded drafts require approval of their replacement')
    if draft['status'] == 'PUBLISHED':
        return draft
    if draft.get('delivery_status') in ('sending', 'ambiguous'):
        raise WorkflowConflict('Delivery requires reconciliation before retry')
    artifact = draft.get('sleyz_artifact')
    if artifact and (artifact.get('product_snapshot') or artifact.get('checkout_link')):
        from services.memory import MemoryStore
        from .tools import validate_commerce_snapshot
        products = getattr(repo, 'brand_products', None)
        if products is None:
            products = await run_in_threadpool(MemoryStore(repo.client).products, org_id) if hasattr(repo,'client') else []
        products = [p for p in products if str(p.get('org_id', org_id)) == org_id]
        try:
            validate_commerce_snapshot(artifact, products)
        except ValueError:
            return await repo.transition_draft(org_id,draft_id,'delivery_failed',expected_revision,
                idempotency_key + ':stale-commerce',error='Catalog changed. Regenerate a replacement draft and approve it before sending.')
    platform = draft.get('platform') or (artifact or {}).get('platform') or 'telegram'
    if platform == 'telegram':
        if not draft.get('inbound_id'):
            return await deliver_telegram_draft(repo=repo,org_id=org_id,draft_id=draft_id,expected_revision=expected_revision,idempotency_key=idempotency_key)
        try:
            target = await load_telegram_inbox_target(repo, org_id, draft)
        except ValueError as exc:
            return await repo.transition_draft(org_id,draft_id,'delivery_failed',expected_revision,
                idempotency_key + ':configuration-failure',error=str(exc))
        return await workflow_publication.publish_telegram(repo=repo,org_id=org_id,draft_id=draft_id,
            expected_revision=expected_revision,idempotency_key=idempotency_key,**target)
    if platform != 'instagram':
        raise ValueError('Unsupported delivery platform')
    try:
        target = await load_instagram_target(repo,org_id,draft)
    except ValueError as exc:
        return await repo.transition_draft(org_id,draft_id,'delivery_failed',expected_revision,
            idempotency_key + ':configuration-failure',error=str(exc))
    return await publish_instagram(repo=repo,org_id=org_id,draft_id=draft_id,expected_revision=expected_revision,idempotency_key=idempotency_key,**target)


async def publish_instagram(*, repo, org_id, draft_id, expected_revision, idempotency_key,
                            account_id, customer_id, access_token, client=None):
    draft = await repo.get_draft(draft_id)
    if not draft or draft['org_id'] != org_id:
        raise KeyError(draft_id)
    attempt_id = str(uuid.uuid5(uuid.NAMESPACE_URL,f'{org_id}:{draft_id}:{idempotency_key}'))
    sending = await repo.transition_draft(org_id,draft_id,'begin_delivery',expected_revision,idempotency_key+':begin',receipt={'attempt_id':attempt_id})
    current = await repo.get_draft(draft_id)
    if current['status'] == 'PUBLISHED':
        return current
    await workflow_publication.claim_delivery(repo=repo,org_id=org_id,draft_id=draft_id,attempt_id=attempt_id)
    transport = client or httpx.AsyncClient(timeout=15)
    try:
        version = os.getenv('INSTAGRAM_GRAPH_VERSION','v26.0')
        if not re.fullmatch(r'v\d+\.\d+',version) or not str(account_id).isdigit():
            raise InstagramRejected('Invalid Instagram transport configuration')
        response = await transport.post(f'https://graph.instagram.com/{version}/{account_id}/messages',
            headers={'Authorization':f'Bearer {access_token}'},
            json={'recipient':{'id':str(customer_id)},'message':{'text':draft.get('final_content') or draft['draft_content']}})
        response.raise_for_status()
        result = response.json()
        if result.get('error'):
            raise InstagramRejected('Instagram rejected publication')
        if not result.get('message_id') or str(result.get('recipient_id')) != str(customer_id):
            raise ValueError('Instagram success response lacks a matching receipt')
    except Exception as exc:
        definitive = isinstance(exc,InstagramRejected) or (isinstance(exc,httpx.HTTPStatusError) and exc.response.status_code < 500)
        return await workflow_publication.finish_delivery(repo=repo,org_id=org_id,draft_id=draft_id,attempt_id=attempt_id,
            action='delivery_failed' if definitive else 'delivery_ambiguous',idempotency_key=idempotency_key+':failure',error=type(exc).__name__)
    finally:
        if client is None:
            await transport.aclose()
    return await workflow_publication.finish_delivery(repo=repo,org_id=org_id,draft_id=draft_id,attempt_id=attempt_id,action='publish',idempotency_key=idempotency_key+':receipt',
        receipt={'channel':'instagram','message_id':result['message_id'],'recipient_id':str(customer_id),'attempt_id':attempt_id})


class InstagramRejected(ValueError):
    pass
