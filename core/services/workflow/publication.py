"""Telegram publication only after review; uncertain sends require reconciliation."""
import uuid

import httpx
from starlette.concurrency import run_in_threadpool

from .state import WorkflowConflict


async def load_telegram_target(client, org_id, draft):
    """Load tenant-scoped delivery credentials and destination, never caller input."""
    if draft.get('org_id') != org_id or not draft.get('prospect_id'):
        raise ValueError('Draft has no buyer Telegram destination')
    result = await run_in_threadpool(client.table('prospects').select('*')
        .eq('id',draft['prospect_id']).eq('org_id',org_id).limit(1).execute)
    if not result.data or not result.data[0].get('tg_chat_id'):
        raise ValueError('Prospect has no configured Telegram destination')
    prospect = result.data[0]
    result = await run_in_threadpool(client.table('tg_connections').select('*')
        .eq('org_id',org_id).limit(1).execute)
    if not result.data or not result.data[0].get('bot_token'):
        raise ValueError('Sales bot token is not configured')
    connection = result.data[0]
    # Explicit null on a prospect is direct mode, even when its org also has
    # a Business connection. Older records with no mode field use the org mode.
    business_id = prospect['business_connection_id'] if 'business_connection_id' in prospect else connection.get('business_connection_id')
    return {'bot_token':connection['bot_token'],'chat_id':int(prospect['tg_chat_id']),
            'business_connection_id':business_id}


async def deliver_telegram_draft(*, repo, org_id, draft_id, expected_revision, idempotency_key):
    draft = await repo.get_draft(draft_id)
    if not draft or draft['org_id'] != org_id:
        raise KeyError(draft_id)
    try:
        target = await load_telegram_target(repo.client,org_id,draft)
    except ValueError as exc:
        return await repo.transition_draft(org_id,draft_id,'delivery_failed',expected_revision,
            idempotency_key + ':configuration-failure',error=str(exc))
    return await publish_telegram(repo=repo,org_id=org_id,draft_id=draft_id,
        expected_revision=expected_revision,idempotency_key=idempotency_key,**target)


async def publish_telegram(*, repo, org_id, draft_id, expected_revision,
                           idempotency_key, bot_token, chat_id, client=None, business_connection_id=None):
    draft = await repo.get_draft(draft_id)
    if not draft or draft['org_id'] != org_id:
        raise KeyError(draft_id)
    # Stable attempt IDs make request retries safe and bind receipts to a send.
    attempt_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f'{org_id}:{draft_id}:{idempotency_key}'))
    sending = await repo.transition_draft(org_id, draft_id, 'begin_delivery', expected_revision,
        idempotency_key + ':begin', receipt={'attempt_id':attempt_id})
    current = await repo.get_draft(draft_id)
    if current['status'] == 'PUBLISHED':
        return current
    # A repeated begin key must never resend an in-flight or ambiguous request.
    if current['revision'] != sending['revision'] or current['delivery_status'] != 'sending':
        raise WorkflowConflict('Delivery attempt requires reconciliation')
    # begin_delivery idempotency cannot distinguish first execution from a retry.
    # A second one-time CAS advances the attempt before transport. Only its winner sends.
    try:
        claimed = await repo.transition_draft(org_id, draft_id, 'claim_delivery', sending['revision'],
            str(uuid.uuid4()), receipt={'attempt_id':attempt_id})
    except WorkflowConflict:
        raise WorkflowConflict('Delivery already started; reconcile its receipt')
    transport = client or httpx.AsyncClient(timeout=15)
    try:
        payload = {'chat_id':int(chat_id), 'text':draft.get('final_content') or draft['draft_content']}
        if business_connection_id:
            payload['business_connection_id'] = business_connection_id
        response = await transport.post(f'https://api.telegram.org/bot{bot_token}/sendMessage',
            json=payload)
        response.raise_for_status()
        data = response.json()
        if data.get('ok') is not True:
            raise TelegramRejected(data.get('description', 'Telegram rejected publication'))
        result = data.get('result') or {}
        if not result.get('message_id') or (result.get('chat') or {}).get('id') != int(chat_id):
            raise ValueError('Telegram success response lacks a matching receipt')
    except Exception as exc:
        definitive = isinstance(exc, TelegramRejected) or (isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500)
        return await repo.transition_draft(org_id, draft_id,
            'delivery_failed' if definitive else 'delivery_ambiguous', claimed['revision'],
            idempotency_key + ':failure', error=type(exc).__name__)
    finally:
        if client is None:
            await transport.aclose()
    return await repo.transition_draft(org_id, draft_id, 'publish', claimed['revision'],
        idempotency_key + ':receipt', receipt={'channel':'telegram','message_id':result['message_id'],
            'chat_id':int(chat_id),'attempt_id':attempt_id})


class TelegramRejected(ValueError):
    pass
