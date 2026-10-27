"""Isolated SQL/FFmpeg journey. Never import this module in the production app.

From core, set CONVERZA_JOURNEY_TEST_DSN to the loopback
test_converza_journey database, then CONVERZA_RUN_JOURNEY=1 and run:
python -m unittest discover -s tests -p test_consolidated_journey.py -v
The existing renderer candidate must mount the current renderer test directory.
All generated evidence is retained under the printed temporary run directory.
"""
import asyncio
import base64
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx


def validate_journey_dsn(dsn):
    from psycopg2.extensions import parse_dsn
    config = parse_dsn(dsn)
    loopback = ('127.0.0.1', 'localhost', '::1')
    if (config.get('host') not in loopback or config.get('hostaddr', config.get('host')) not in loopback
            or config.get('service') or config.get('dbname') != 'test_converza_journey'):
        raise ValueError('Journey requires an explicit loopback test_converza_journey database')


class RendererBridge(httpx.AsyncBaseTransport):
    """Forward requests to a real renderer TestClient over one Docker exec pipe."""
    def __init__(self, org, product, run_id, output):
        self.key = 'journey-' + run_id
        self.root = '/tmp/consolidated-journey-' + run_id
        self.log = (output / 'renderer.log').open('w', encoding='utf-8')
        self.lock = threading.Lock()
        self.process = subprocess.Popen(['docker', 'exec', '-i',
            os.getenv('CONVERZA_JOURNEY_RENDERER_CONTAINER', 'converza-renderer-candidate'),
            'python', '-u', '-m', 'test.services.consolidated_renderer'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, text=True,
            encoding='utf-8', bufsize=1)
        self.responses = queue.Queue()

        def read_responses():
            for line in self.process.stdout:
                self.responses.put(line)
            self.responses.put(None)

        self.reader = threading.Thread(target=read_responses, daemon=True)
        self.reader.start()
        self._write({'root': self.root, 'org_id': org, 'product_id': product, 'key': self.key})
        ready = self._read()
        if ready.get('ready') is not True or ready.get('root') != self.root:
            raise RuntimeError('Renderer fixture did not initialize its isolated root')

    def _write(self, message):
        self.process.stdin.write(json.dumps(message) + '\n')
        self.process.stdin.flush()

    def _read(self):
        try:
            line = self.responses.get(timeout=120)
        except queue.Empty:
            raise TimeoutError('Renderer bridge exceeded its 120-second response bound; inspect renderer.log') from None
        if not line:
            raise RuntimeError('Renderer bridge exited; inspect renderer.log')
        return json.loads(line)

    def command(self, message):
        with self.lock:
            self._write(message)
            return self._read()

    async def handle_async_request(self, request):
        if request.url.host != 'renderer.journey.invalid':
            raise AssertionError('Renderer transport refuses external hosts')
        result = await asyncio.to_thread(self.command, {'kind': 'http', 'method': request.method,
            'path': str(request.url), 'headers': dict(request.headers),
            'body': base64.b64encode(request.content).decode('ascii')})
        return httpx.Response(result['status'], headers=result['headers'],
            content=base64.b64decode(result['body']), request=request)

    async def aclose(self):
        # Several short-lived real clients share this one process.
        pass

    def close(self):
        if self.process.poll() is None:
            try:
                self._write({'kind': 'close'})
            except BrokenPipeError:
                pass
            self.process.stdin.close()
            self.process.wait(timeout=120)
        self.reader.join(timeout=5)
        self.process.stdout.close()
        self.log.close()


def bootstrap_journey(dsn):
    """Reuse the minimal SQL fixture schema without touching another test DSN."""
    validate_journey_dsn(dsn)
    import test_workflow_postgres as workflow
    from pg_supabase import PgSupabase
    with patch.object(workflow, 'DSN', dsn):
        workflow.PostgresWorkflowTests.setUpClass()
    client = PgSupabase(dsn)
    migrations = Path(__file__).resolve().parents[1] / 'migrations'
    with client.connect() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('sleyz_inbound')")
        if not cursor.fetchone()[0]:
            cursor.execute((migrations / '007_sleyz_inbound.sql').read_text(encoding='utf-8'))
        for name in ('008_milo_campaigns.sql', '009_vea_variants.sql', '010_consolidation.sql'):
            cursor.execute((migrations / name).read_text(encoding='utf-8'))
        cursor.execute('''ALTER TABLE brand_passports ADD COLUMN IF NOT EXISTS tone text,
            ADD COLUMN IF NOT EXISTS target_audience text, ADD COLUMN IF NOT EXISTS hex_colors text[]''')
        for table in ('sleyz_inbound', 'sleyz_learning_jobs', 'milo_jobs'):
            cursor.execute(f"SELECT count(*) FROM {table} WHERE status IN ('pending','leased')")
            if cursor.fetchone()[0]:
                raise RuntimeError('An unfinished previous journey exists; inspect its retained test records before rerunning')
    return client


def run_journey():
    import psycopg2
    from fastapi import FastAPI, Header, HTTPException
    from fastapi.testclient import TestClient
    from lib.repository import SupabaseRepository
    from lib.workflow_routes import create_workflow_router
    from services.memory import MemoryStore
    from services.milo.routes import create_milo_router
    from services.milo.pipeline import review_compliance
    from services.milo.video import build_binding
    from services.milo.store import MiloStore
    from services.milo.worker import MiloWorker
    from services.sleyz.channels import create_instagram_router
    from services.sleyz.store import SleyzStore
    from services.sleyz.worker import SleyzWorker
    from services.vea.store import VeaStore

    dsn = os.environ.get('CONVERZA_JOURNEY_TEST_DSN', '')
    validate_journey_dsn(dsn)
    run_id = uuid4().hex
    output = Path(tempfile.gettempdir()) / 'converza-journey' / run_id
    output.mkdir(parents=True)
    report = {'status': 'failed', 'run_id': run_id, 'output_dir': str(output), 'stages': [],
        'external_gaps': ['Fixture owner authentication, not Supabase sign-in.',
            'Controlled Instagram transport, not a live Meta account or network.',
            'Deterministic model fixtures, not live Huawei semantic quality.',
            'Synthetic tone speech, fixture acoustic timestamps and generated test-pattern footage.',
            'Renderer HTTP uses its production ASGI app through TestClient, not the candidate listening socket.']}

    def check(condition, message):
        if not condition:
            raise AssertionError(message)

    def stage(name):
        report['stages'].append(name)
        print('journey: ' + name, flush=True)

    def wait(value):
        return asyncio.run(value)

    with ExitStack() as stack:
        lock = psycopg2.connect(dsn)
        stack.callback(lock.close)
        lock.autocommit = True
        with lock.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(hashtext('consolidated-journey'))")
            check(cursor.fetchone()[0], 'Another journey is running against this database')
        try:
            client = bootstrap_journey(dsn)
            repo = SupabaseRepository(client)
            org, product = str(uuid4()), str(uuid4())
            report.update(org_id=org, product_id=product, database='test_converza_journey')
            client.table('orgs').insert({'id': org}).execute()
            client.table('brand_passports').insert({'org_id': org, 'brand_name': 'Journey Travel',
                'target_audience': 'Outdoor commuters', 'tone': 'Warm and direct',
                'hex_colors': ['#137A63'], 'voice_rules': [], 'negative_constraints': []}).execute()
            proof_text = 'The shell uses reinforced stitching.'
            client.table('brand_products').insert({'id': product, 'org_id': org, 'name': 'Travel bag',
                'sku': 'travel-bag', 'description': proof_text, 'price': 100, 'currency': 'USD', 'stock_count': 3}).execute()
            source = client.table('memory_sources').select('*').eq('org_id', org).eq('kind', 'product').execute().data[0]
            memory = MemoryStore(client)
            memory.save_identity(org, {'proof_points': [{'id': 'stitching', 'source_id': source['id'],
                'revision': source['revision'], 'quote': proof_text, 'product_id': product,
                'objection_topics': ['durability'], 'confirmed_by': 'journey-owner',
                'confirmed_at': datetime.now(timezone.utc).isoformat()}]})
            stage('isolated_sql_and_canonical_product')

            buyer_text = 'Will the Travel bag stitching last?'
            model_calls = []

            async def model(messages, **kwargs):
                properties = kwargs['schema'].get('properties', {})
                model_calls.append(sorted(properties))
                if 'intent_score' in properties:
                    return {'intent_score': .6, 'product_query': 'travel-bag', 'quantity': 1, 'language': 'en',
                            'objections': [{'type': 'trust', 'text': buyer_text}]}
                if 'citations' in properties:
                    return {'citations': [], 'acknowledgement': 'concern', 'next_step': 'needs',
                            'include_price': False, 'include_stock': False, 'include_description': True,
                            'apply_corrections': True}
                if 'rule_type' in properties:
                    return {'rule': 'Use short paragraphs.', 'rule_type': 'style', 'scope': 'general',
                            'supporting_spans': [{'text': '\n\n'}]}
                if 'objections' in properties:
                    return {'objections': [{'topic': 'durability', 'product_id': product, 'buyer_text': buyer_text}]}
                if 'hooks' in properties:
                    return {'target_persona': {'id': 'default', 'name': 'Outdoor commuters', 'description': 'Outdoor commuters'},
                        'hooks': [{'framework': f, 'text': text} for f, text in
                                  [('A', buyer_text), ('B', proof_text), ('C', 'Ask us about the Travel bag.')]],
                        'video_script': [
                            {'spoken_narration': proof_text, 'visual_broll_cues': 'bag stitching product', 'on_screen_text': 'Reinforced stitching'},
                            {'spoken_narration': 'Ask us about the Travel bag.', 'visual_broll_cues': 'Travel bag product', 'on_screen_text': 'Ask us for details'}],
                        'social_captions': {'instagram': 'Ask about the Travel bag.', 'telegram': proof_text, 'tiktok': buyer_text}}
                if 'passed' in properties:
                    return {'passed': True, 'violations': []}
                raise AssertionError('Unexpected model contract')

            async def authenticate(authorization: str | None = Header(None)):
                if authorization != 'Bearer journey-owner':
                    raise HTTPException(401, 'Fixture owner credentials required')
                return SimpleNamespace(user_id='journey-owner')

            def assert_owner(owner, requested_org):
                if owner != 'journey-owner' or requested_org != org:
                    raise HTTPException(403, 'Journey owner mismatch')

            async def fixture_review(artifact, context, **kwargs):
                return await review_compliance(artifact, context, model=model)

            stack.enter_context(patch.dict(os.environ, {'INSTAGRAM_APP_SECRET': 'journey-signing-key',
                'INSTAGRAM_CONNECTIONS': json.dumps({'123456': {'org_id': org, 'access_token': 'fixture-not-a-token'}}),
                'VEA_ENABLED': '1', 'VEA_PRESETS_ENABLED': '1', 'MONEYPRINTERTURBO_BASE_URL': 'http://renderer.journey.invalid',
                'MONEYPRINTERTURBO_PUBLIC_BASE_URL': 'http://renderer.journey.invalid'}))
            stack.enter_context(patch('services.milo.routes.review_compliance', fixture_review))
            stack.enter_context(patch('services.llm.complete_json', AsyncMock(side_effect=AssertionError('Paid model calls forbidden'))))
            app = FastAPI()
            app.include_router(create_instagram_router(lambda: repo))
            app.include_router(create_workflow_router(lambda: repo, authenticate, assert_owner))
            app.include_router(create_milo_router(lambda: repo, authenticate, assert_owner))
            api = stack.enter_context(TestClient(app))

            def owner_post(path, body, key, expected=200):
                response = api.post(path, json=body, headers={'Authorization': 'Bearer journey-owner', 'Idempotency-Key': key})
                check(response.status_code == expected, f'{path}: {response.status_code} {response.text}')
                return response.json()

            def inbound(mid):
                payload = {'object': 'instagram', 'entry': [{'id': '123456', 'messaging': [
                    {'sender': {'id': 'journey-buyer'}, 'recipient': {'id': '123456'},
                     'timestamp': int(datetime.now(timezone.utc).timestamp() * 1000),
                     'message': {'mid': mid, 'text': buyer_text}}]}]}
                raw = json.dumps(payload).encode()
                signature = 'sha256=' + hmac.new(b'journey-signing-key', raw, hashlib.sha256).hexdigest()
                response = api.post('/webhooks/instagram', content=raw, headers={'X-Hub-Signature-256': signature})
                check(response.status_code == 200, response.text)
                return client.table('sleyz_inbound').select('*').eq('org_id', org).eq('external_message_id', mid).execute().data[0]

            # Suppress only optional manager notifications; durable draft generation is real.
            import sys
            reporter = SimpleNamespace(report_hitl=AsyncMock())
            stack.enter_context(patch.dict(sys.modules, {'Sleyz.agents.reporter': reporter}))
            sales = SleyzWorker(repo, model=model)
            first = inbound('first-' + run_id)
            inbound('first-' + run_id)
            check(len(client.table('sleyz_inbound').select('*').eq('org_id', org).execute().data) == 1, 'Ingress replay duplicated the inbox')
            check(wait(sales.run_once()) == 1, 'Sleyz did not process the real inbox')
            draft = wait(repo.get_draft(first['draft_id']))
            check(draft['status'] == 'AWAITING_HITL' and draft['sleyz_artifact']['product_snapshot'][0]['id'] == product,
                  'A grounded Sleyz artifact must await human review')
            check(wait(MiloStore(repo).claim('build')) == [], 'Video queued without script approval')
            stage('signed_dm_to_actual_sleyz_draft')

            edited_copy = draft['draft_content'].replace('. ', '.\n\n')
            edited = owner_post('/api/hitl/' + draft['id'] + '/edit',
                {'expected_revision': draft['revision'], 'final_content': edited_copy}, 'sales-edit')
            check(edited['status'] == 'EDITED' and edited['final_content'] == edited_copy, 'Approved human edit was not stored')
            sends = []

            def delivery(request):
                check(request.url.host == 'graph.instagram.com', 'Unexpected external delivery host')
                body = json.loads(request.content)
                check(body['recipient']['id'] == 'journey-buyer' and body['message']['text'] == edited_copy,
                      'Delivery did not use the immutable buyer and approved copy')
                sends.append(body)
                return httpx.Response(200, json={'recipient_id': 'journey-buyer', 'message_id': 'controlled-' + run_id})

            original_client = httpx.AsyncClient
            with patch('services.sleyz.publication.httpx.AsyncClient',
                       side_effect=lambda **kwargs: original_client(transport=httpx.MockTransport(delivery))):
                delivered = owner_post('/api/drafts/' + draft['id'] + '/deliver', {'expected_revision': edited['revision']}, 'sales-send')
                replay = owner_post('/api/drafts/' + draft['id'] + '/deliver', {'expected_revision': edited['revision']}, 'sales-send')
            check(delivered['status'] == replay['status'] == 'PUBLISHED' and len(sends) == 1, 'Receipt/replay allowed a second delivery')
            check(delivered['delivery_receipt']['attempt_id'] == delivered['delivery_attempt_id'], 'Receipt attempt binding was lost')
            stage('human_edit_approval_and_controlled_receipt')

            check(wait(sales.run_once()) == 1, 'Correction learning did not run')
            correction = client.table('memory_sources').select('*').eq('org_id', org).eq('kind', 'correction').execute().data[0]
            check(correction['content'] == 'Use short paragraphs.' and correction['metadata']['draft_id'] == draft['id'], 'Correction provenance was lost')
            check(correction['metadata']['approved_revision'] == edited['revision'], 'Correction refers to the wrong human revision')
            published = wait(repo.get_draft(draft['id']))
            owner_post('/api/drafts/' + draft['id'] + '/resolve', {'expected_revision': published['revision']}, 'buyer-resolved')
            second = inbound('second-' + run_id)
            check(wait(sales.run_once()) == 1, 'Follow-up sales draft did not generate')
            followup = wait(repo.get_draft(second['draft_id']))
            refs = followup['sleyz_artifact']['cited_brand_passport_atoms']
            check(any(ref['source_id'] == correction['id'] for ref in refs) and '\n\n' in followup['draft_content'],
                  'The learned correction did not change the next actual Sleyz draft')
            owner_post('/api/hitl/' + followup['id'] + '/approve', {'expected_revision': followup['revision']}, 'followup-approve')
            stage('sql_correction_learning_reused_by_next_dm')

            milo = MiloStore(repo)
            worker = MiloWorker(repo, model=model)
            check(wait(worker.run_once('extract')) == 1 and wait(worker.run_once('extract')) == 1, 'Milo did not consume both logged inbox messages')
            objections = wait(milo.objections(org, '2000-01-01T00:00:00+00:00'))
            check(len(objections) == 2 and all(row['product_id'] == product and row['buyer_text'] == buyer_text for row in objections),
                  'Milo objections are not exact inbound product-scoped spans')
            campaign = owner_post('/api/milo/' + org + '/campaigns', {'prompt': 'Address the bag stitching concern', 'language': 'en'}, 'campaign', 202)
            check(wait(worker.run_once('generate')) == 1, 'Milo generation did not run')
            campaign = wait(milo.get_campaign(org, campaign['id']))
            check(campaign['status'] == 'awaiting_review' and campaign['product_id'] == product and campaign['topic'] == 'durability',
                  'Authoritative selected scope was lost')
            check(wait(milo.claim('build')) == [], 'Campaign rendered before human approval')
            approved = owner_post('/api/milo/' + org + '/campaigns/' + campaign['id'] + '/script/approve',
                {'expected_revision': campaign['revision']}, 'script-approve')
            stage('logged_objections_to_human_approved_milo_script')

            bridge = RendererBridge(org, product, run_id, output)
            stack.callback(bridge.close)
            report['renderer_root'] = bridge.root
            stack.enter_context(patch.dict(os.environ, {'MPT_API_KEY': bridge.key}))
            with patch('httpx.AsyncClient', side_effect=lambda **kwargs: original_client(transport=bridge, **kwargs)):
                # The production worker submits, pins recipes, polls and validates the receipt.
                check(wait(worker.run_once('build')) == 1, 'Build worker did not consume the approved job')
                variants = wait(VeaStore(repo).list_variants(org))
                check(len(variants) == 1 and variants[0]['status'] == 'completed',
                      'Real rendering did not complete: ' + json.dumps(variants))
                variant = variants[0]
                video_draft = wait(repo.get_draft(variant['draft_id']))
                check(video_draft['status'] == 'AWAITING_HITL' and video_draft['final_content'] is None, 'Video bypassed final human approval')
                jobs = wait(milo.jobs(org))
                build = next(j for j in jobs if j['id'] == variant['job_id'])
                task_id = build['payload']['provider_task_id']
                media = bridge.command({'kind': 'evidence', 'task_id': task_id})
                check(media['width'] == 1080 and media['height'] == 1920 and media['codec'] == 'h264' and 'aac' in media['audio_codecs'], 'FFmpeg output has the wrong streams')
                check(media['pixel_range'] > 20, 'Decoded video frame is blank')
                manifest = media['manifest']
                check(abs(media['duration_sec'] - manifest['duration_ms'] / 1000) <= 1 / 30 + .001, 'Media duration differs from the composition')
                check(media['receipt']['milo_binding'] == build_binding(build), 'Durable renderer receipt is not bound to the complete approved input')
                check([s['spoken_narration'] for s in manifest['scenes']] ==
                      [s['spoken_narration'] for s in campaign['artifact']['video_script']], 'Approved narration changed')
                check([word['word'] for word in manifest['words']] ==
                      [word for scene in campaign['artifact']['video_script'] for word in scene['spoken_narration'].split()],
                      'Aligned captions do not preserve the complete approved words')
                check(all(scene['on_screen_text'] in media['captions'] for scene in campaign['artifact']['video_script']),
                      'The actual ASS caption artifact lost an approved overlay')
                check(all(s['asset_id'] == 'journey-stitching' for s in manifest['segments']), 'Composition selected an unapproved asset')
                check(variant['artifact']['composition_sha256'] == hashlib.sha256(json.dumps(manifest, sort_keys=True,
                    ensure_ascii=False, separators=(',', ':')).encode()).hexdigest(), 'Composition hash differs from persisted artifact')
                stage('real_ffmpeg_composition_and_durable_bound_receipt')

                async def download():
                    async with original_client(transport=bridge) as transport:
                        for field, filename, digest in (('video_url', 'final-1.mp4', media['video_sha256']),
                                                        ('thumbnail_url', 'final-1.jpg', media['thumbnail_sha256'])):
                            response = await transport.get(variant['artifact'][field])
                            check(response.status_code == 200 and hashlib.sha256(response.content).hexdigest() == digest,
                                  'Artifact URL does not serve the actual FFmpeg output')
                            (output / filename).write_bytes(response.content)
                wait(download())
                # The real route calls catalog/source/revision validation before SQL approval.
                approval = owner_post('/api/hitl/' + video_draft['id'] + '/approve',
                    {'expected_revision': video_draft['revision']}, 'video-approve')
                same = owner_post('/api/hitl/' + video_draft['id'] + '/approve',
                    {'expected_revision': video_draft['revision']}, 'video-approve')
                check(approval == same and approval['status'] == 'APPROVED', 'Final human approval is not replay-safe')
                owner_post('/api/hitl/' + video_draft['id'] + '/approve',
                    {'expected_revision': video_draft['revision']}, 'stale-video-approve', 409)
            stage('real_preview_download_and_final_human_video_approval')
            report.update(status='passed', delivery={'send_count': len(sends), 'receipt': delivered['delivery_receipt']},
                correction={'id': correction['id'], 'reused': True, 'approved_revision': edited['revision']},
                campaign={'id': campaign['id'], 'product_id': campaign['product_id'], 'topic': campaign['topic'],
                          'approved_revision': approved['revision']},
                video={'draft_id': approval['id'], 'status': approval['status'], 'artifact': variant['artifact'], 'task_id': task_id},
                media={k: v for k, v in media.items() if k not in ('receipt', 'manifest', 'captions')},
                model_fixture_calls=len(model_calls), preview_file=str(output / 'final-1.mp4'),
                thumbnail_file=str(output / 'final-1.jpg'), renderer_container=os.getenv(
                    'CONVERZA_JOURNEY_RENDERER_CONTAINER', 'converza-renderer-candidate'))
            (output / 'composition.json').write_text(json.dumps(media['manifest'], indent=2), encoding='utf-8')
            (output / 'renderer-receipt.json').write_text(json.dumps(media['receipt'], indent=2), encoding='utf-8')
        except BaseException as exc:
            report['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
            raise
        finally:
            (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            print('journey report: ' + str(output / 'report.json'), flush=True)
    return report


class JourneySafetyTests(unittest.TestCase):
    def test_journey_requires_its_own_explicit_loopback_database(self):
        validate = globals().get('validate_journey_dsn')
        self.assertTrue(callable(validate), 'Implement the isolated journey DSN guard first')
        validate('host=127.0.0.1 port=55441 user=postgres dbname=test_converza_journey')
        for dsn in ('host=prod.example dbname=test_converza_journey',
                    'host=127.0.0.1 dbname=test_converza_cleanup',
                    'host=127.0.0.1 dbname=converza',
                    'dbname=test_converza_journey',
                    'host=localhost hostaddr=203.0.113.1 dbname=test_converza_journey'):
            with self.subTest(dsn=dsn), self.assertRaises(ValueError):
                validate(dsn)

    def test_renderer_bridge_is_a_real_transport_not_a_video_result_stub(self):
        bridge = globals().get('RendererBridge')
        self.assertTrue(callable(bridge), 'Implement the isolated renderer API transport')
        transport = object.__new__(bridge)
        with self.assertRaisesRegex(AssertionError, 'refuses external hosts'):
            asyncio.run(transport.handle_async_request(httpx.Request('GET', 'https://provider.example/video')))


@unittest.skipUnless(os.getenv('CONVERZA_RUN_JOURNEY') == '1', 'opt-in isolated SQL and real FFmpeg journey')
class ConsolidatedJourneyTests(unittest.TestCase):
    def test_inbound_to_final_human_video_approval(self):
        journey = globals().get('run_journey')
        self.assertTrue(callable(journey), 'Implement the complete SQL-backed journey')
        report = journey()
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['video']['status'], 'APPROVED')
        self.assertEqual(report['delivery']['send_count'], 1)
        self.assertTrue(report['correction']['reused'])
        self.assertEqual(report['media']['width'], 1080)
        self.assertEqual(report['media']['height'], 1920)


if __name__ == '__main__':
    unittest.main()
