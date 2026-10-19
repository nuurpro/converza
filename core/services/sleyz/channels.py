"""Authenticated server-configured channel ingress; acknowledge only durable writes."""
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

logger = logging.getLogger('converza.sleyz.channels')


def instagram_connections():
    """Credentials are read only on the server and never returned by status APIs."""
    try:
        values = json.loads(os.getenv('INSTAGRAM_CONNECTIONS', '{}'))
        if not isinstance(values, dict):
            raise ValueError()
        for account, value in values.items():
            if not isinstance(value, dict) or not value.get('org_id') or not value.get('access_token') or not str(account).isdigit():
                raise ValueError()
        return values
    except (TypeError, ValueError):
        raise ValueError('Instagram connections are invalid') from None


def valid_instagram_signature(raw, signature, secret):
    if not secret or not isinstance(signature, str) or not signature.startswith('sha256='):
        return False
    expected = 'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def normalize_instagram(payload, connections):
    rows = []
    if not isinstance(payload, dict) or payload.get('object') != 'instagram':
        return rows
    for entry in payload.get('entry') or []:
        if not isinstance(entry, dict):
            continue
        account = str(entry.get('id', ''))
        connection = connections.get(account)
        if not connection:
            continue
        for event in entry.get('messaging') or []:
            if not isinstance(event, dict):
                continue
            message = event.get('message') or {}
            sender = str((event.get('sender') or {}).get('id') or '')
            recipient = str((event.get('recipient') or {}).get('id') or '')
            if not isinstance(message, dict) or message.get('is_echo') or sender == account or not sender or recipient != account:
                continue
            text, mid = message.get('text'), message.get('mid')
            if not isinstance(text, str) or not text.strip() or not mid:
                continue
            try:
                timestamp = float(event['timestamp']) / 1000
                received_at = datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
            except (KeyError, TypeError, ValueError, OverflowError, OSError):
                continue
            rows.append({'org_id':str(connection['org_id']), 'platform':'instagram','connection_id':account,
                         'external_message_id':str(mid),'customer_id':sender,'customer_handle':sender,
                         'text':text,'received_at':received_at,'simulated':False})
    return rows


def create_instagram_router(get_repo, *, accept=None):
    router = APIRouter(tags=['sleyz-channels'])

    @router.get('/webhooks/instagram')
    async def verify(request: Request):
        expected = os.getenv('INSTAGRAM_VERIFY_TOKEN')
        received = request.query_params.get('hub.verify_token')
        if request.query_params.get('hub.mode') != 'subscribe' or not expected or not received or not hmac.compare_digest(expected, received):
            raise HTTPException(403, 'Instagram webhook verification failed')
        challenge = request.query_params.get('hub.challenge')
        if not challenge:
            raise HTTPException(400, 'Instagram verification challenge required')
        return PlainTextResponse(challenge)

    @router.post('/webhooks/instagram')
    async def inbound(request: Request):
        started = time.monotonic()
        raw = await request.body()
        if not valid_instagram_signature(raw, request.headers.get('x-hub-signature-256'), os.getenv('INSTAGRAM_APP_SECRET')):
            raise HTTPException(403, 'Instagram webhook credentials required')
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, 'Invalid webhook payload') from None
        try:
            envelopes = normalize_instagram(payload, instagram_connections())
            if accept is None:
                from .store import SleyzStore
                persist = SleyzStore(get_repo()).accept
            else:
                persist = accept
            for envelope in envelopes:
                await persist(envelope)
        except Exception as exc:
            logger.warning('instagram_accept_failed error_type=%s', type(exc).__name__)
            raise HTTPException(503, 'Inbound storage temporarily unavailable') from None
        logger.info('sleyz_inbound_ack platform=instagram messages=%d ack_ms=%d',len(envelopes),int((time.monotonic()-started)*1000))
        return {'ok':True}

    return router
