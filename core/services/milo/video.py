"""Approved Milo scripts enter Vea without any narration-generation call.

The provider has no idempotency key API. Persisting an intent before POST and
refusing to repeat an uncertain POST makes that limitation explicit. An operator
must reconcile a missing task ID rather than creating a second paid render.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
import os
from typing import Any
from urllib.parse import urlsplit

import httpx

from lib.moneyprinter import _absolute_worker_url, _base_url

VOICES = {'en': 'en-US-AriaNeural', 'ru': 'ru-RU-SvetlanaNeural', 'uz': 'uz-UZ-MadinaNeural'}


def _public_video_url(value: str, base_url: str) -> str:
    public_base = os.getenv('MONEYPRINTERTURBO_PUBLIC_BASE_URL', '').strip().rstrip('/') or base_url
    if not value.startswith(('http://', 'https://')):
        return _absolute_worker_url(value, public_base)
    parsed, provider = urlsplit(value), urlsplit(base_url)
    if (parsed.scheme, parsed.netloc) != (provider.scheme, provider.netloc):
        return value
    relative = parsed.path
    if provider.path and relative.startswith(provider.path.rstrip('/') + '/'):
        relative = relative[len(provider.path.rstrip('/')):]
    if parsed.query:
        relative += '?' + parsed.query
    if parsed.fragment:
        relative += '#' + parsed.fragment
    return _absolute_worker_url(relative, public_base)


class SubmissionUncertain(RuntimeError):
    """Provider submission needs reconciliation before another POST is safe."""


class ProviderRenderFailed(RuntimeError):
    """The bound provider receipt definitively failed; explicit retry required."""


def _control_headers():
    key = os.getenv('MPT_API_KEY', '').strip()
    if not key:
        raise RuntimeError('MPT_API_KEY must be configured for renderer control requests')
    return {'Authorization': 'Bearer ' + key}


def build_binding(job: dict[str, Any]) -> dict[str, Any]:
    payload = job['payload']
    serialized = json.dumps({'video_script': payload['video_script'], 'language': payload.get('language', 'en')},
                            sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return {'job_id': job['id'], 'org_id': job['org_id'],
            'campaign_id': job.get('campaign_id') or payload['campaign_id'],
            'script_revision': payload.get('approved_revision', payload.get('script_revision')),
            'provider_attempt': payload.get('provider_attempt', 1),
            'script_sha256': hashlib.sha256(serialized.encode('utf-8')).hexdigest()}


def _verify_binding(task: dict[str, Any], job: dict[str, Any]) -> None:
    if task.get('milo_binding') != build_binding(job):
        raise RuntimeError('Vea task binding does not match this brand, build, and approved script; receipt rejected')


async def validate_provider_receipt(job: dict[str, Any], task_id: str, *,
                                  client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Read-only validation before an operator receipt is saved for resumption."""
    if client is None:
        async with httpx.AsyncClient(timeout=30.0) as own_client:
            return await validate_provider_receipt(job, task_id, client=own_client)
    response = await client.get(f'{_base_url()}/api/v1/tasks/{task_id}', headers=_control_headers())
    response.raise_for_status()
    try:
        task = response.json()['data']
        if not isinstance(task, dict):
            raise ValueError('invalid task')
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError('Vea returned malformed receipt binding') from exc
    _verify_binding(task, job)
    return task


def _provider_payload(job: dict[str, Any]) -> dict[str, Any]:
    payload = job['payload']
    language = payload.get('language', 'en')
    if language not in VOICES:
        raise ValueError('Approved script language must be en, ru, or uz')
    scenes = payload.get('video_script')
    if not isinstance(scenes, list) or not scenes:
        raise ValueError('Approved script requires ordered scenes')
    for scene in scenes:
        if not isinstance(scene, dict) or any(not isinstance(scene.get(key), str) for key in
                ('spoken_narration', 'visual_broll_cues', 'on_screen_text')):
            raise ValueError('Approved scenes require narration, b-roll cues, and on-screen text strings')
        if not scene['spoken_narration'].strip() or not scene['visual_broll_cues'].strip():
            raise ValueError('Approved narration and b-roll cues cannot be blank')
    return {
        'video_subject': 'Approved Milo campaign',
        'video_script': '\n\n'.join(scene['spoken_narration'] for scene in scenes),
        'approved_scenes': deepcopy(scenes),
        'milo_binding': build_binding(job),
        'video_terms': [scene['visual_broll_cues'] for scene in scenes],
        'match_materials_to_script': True,
        'video_source': 'pexels', 'video_aspect': '9:16',
        'video_concat_mode': 'sequential', 'video_clip_duration': 5,
        'video_count': 1, 'video_language': language,
        'voice_name': VOICES[language], 'voice_rate': 1.0, 'voice_volume': 1.0,
        'subtitle_enabled': True, 'bgm_type': '', 'bgm_volume': 0,
        'font_name': 'DejaVuSans.ttf', 'font_size': 54, 'n_threads': 2,
    }


async def render_approved_script(job: dict[str, Any], store: Any, *,
        client: httpx.AsyncClient | None = None, timeout_seconds: float = 180) -> dict[str, Any]:
    payload = _provider_payload(job)
    task_id = job['payload'].get('provider_task_id') or job.get('provider_task_id')
    submission_state = job['payload'].get('submission_state') or job.get('submission_state')
    if not task_id and submission_state in {'submission_started', 'ambiguous'}:
        raise SubmissionUncertain('Provider submission needs task-ID reconciliation; automatic resubmission blocked')
    if client is None:
        async with httpx.AsyncClient(timeout=30.0) as own_client:
            return await render_approved_script(job, store, client=own_client, timeout_seconds=timeout_seconds)

    base_url = _base_url()
    if not task_id:
        capabilities = await client.get(f'{base_url}/api/v1/capabilities', headers=_control_headers())
        if capabilities.status_code != 200:
            raise RuntimeError('Vea provider lacks approved scene support; deploy the bundled MoneyPrinterTurbo update')
        try:
            supported = capabilities.json()
            if (supported.get('approved_scenes_v1') is not True or supported.get('milo_job_binding_v1') is not True
                    or supported.get('durable_state_v1') is not True or supported.get('control_api_auth_v1') is not True
                    or supported.get('provider_attempt_binding_v1') is not True
                    or supported.get('automatic_publishing_disabled_for_approved_scenes') is not True):
                raise ValueError('missing capability')
        except (ValueError, AttributeError) as exc:
            raise RuntimeError('Vea provider lacks approved scene support; deploy the bundled MoneyPrinterTurbo update') from exc
        await store.update_build(job, {'submission_state': 'submission_started'})
        try:
            response = await client.post(f'{base_url}/api/v1/videos', json=payload, headers=_control_headers())
            response.raise_for_status()
            data = response.json()
            task_id = data['data']['task_id']
            if not isinstance(task_id, str) or not task_id.strip():
                raise ValueError('missing task_id')
        except httpx.HTTPStatusError as exc:
            # An explicit validation/queue rejection proves no job was accepted.
            if exc.response.status_code in {400, 401, 403, 404, 405, 422, 429}:
                await store.update_build(job, {'submission_state': 'rejected'})
                raise RuntimeError(f'Vea provider rejected the script ({exc.response.status_code})') from exc
            await store.update_build(job, {'submission_state': 'ambiguous'})
            raise SubmissionUncertain('Provider submission outcome unknown; reconcile before retrying') from exc
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            await store.update_build(job, {'submission_state': 'ambiguous'})
            raise SubmissionUncertain('Provider submission outcome unknown; reconcile before retrying') from exc
        await store.update_build(job, {'provider_task_id': task_id, 'submission_state': 'submitted'})

    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f'{base_url}/api/v1/tasks/{task_id}', headers=_control_headers())
        response.raise_for_status()
        try:
            task = response.json()['data']
            if not isinstance(task, dict):
                raise ValueError('invalid task')
        except (ValueError, KeyError, TypeError) as exc:
            raise RuntimeError('Vea returned malformed task status') from exc
        if task.get('state') == -1:
            _verify_binding(task, job)
            await store.update_build(job, {'submission_state': 'provider_failed'})
            raise ProviderRenderFailed('Vea provider render failed; explicit retry required')
        if task.get('state') == 1:
            _verify_binding(task, job)
            videos = task.get('videos')
            if not isinstance(videos, list) or not videos or not isinstance(videos[0], str) or not videos[0]:
                raise RuntimeError('Vea provider completed without a video')
            video_url = _public_video_url(videos[0], base_url)
            return {'task_id': task_id, 'video_url': video_url, 'output_path': video_url,
                'approved_script': deepcopy(job['payload']['video_script']),
                'approved_revision': job['payload'].get('approved_revision', job['payload'].get('script_revision')), 'raw': task}
        await asyncio.sleep(min(2, max(0, deadline - asyncio.get_running_loop().time())))
    raise TimeoutError(f'Vea render timed out; resume polling provider task {task_id}')
