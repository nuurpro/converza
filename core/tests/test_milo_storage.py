import asyncio
import time
import unittest
from datetime import datetime, timezone

from lib.repository import InMemoryRepository
from services.sleyz.store import SleyzStore
from services.milo.store import MiloStore
from services.workflow.state import WorkflowConflict


class MiloStorageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = InMemoryRepository()
        self.store = MiloStore(self.repo)
        self.repo.seed_brand_passport('org', {'revision': 1})

    async def inbound(self, **changes):
        return await SleyzStore(self.repo).accept({**dict(org_id='org', platform='telegram', connection_id='biz',
            external_message_id='1', customer_id='42', text='Will it last?',
            received_at=datetime.now(timezone.utc).isoformat()), **changes})

    async def ready(self):
        c = await self.store.enqueue('org', 'manual', key='manual')
        j = (await self.store.claim('generate'))[0]
        a = {'brand_revision': 1, 'proof_references': [], 'video_script': [{'spoken_narration': 'Exact voice', 'visual_broll_cues': 'Close up', 'on_screen_text': 'Look'}]}
        c = await self.store.complete_generation(j, a, {'passed': True, 'semantic_checked': True, 'checked_brand_revision': 1})
        return c

    async def test_inbox_transaction_enqueues_before_sales_processing_and_excludes_simulation(self):
        accepted = await self.inbound()
        await self.inbound()
        await self.inbound(simulated=True, external_message_id='simulation')
        jobs = await self.store.claim('extract', limit=10)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['payload']['inbound_id'], accepted['inbound_id'])
        self.assertEqual(jobs[0]['payload']['text'], 'Will it last?')
        self.assertEqual(self.repo.drafts[0]['status'], 'PENDING_DRAFT')

    async def test_exact_spans_are_atomic_deduplicated_and_tenant_scoped(self):
        await self.inbound()
        j = (await self.store.claim('extract'))[0]
        item = dict(objection_type='durability', topic='durability', product_id=None, buyer_text='last', span_start=8, span_end=12)
        with self.assertRaises(WorkflowConflict):
            await self.store.finish_extraction(j, [item, {**item, 'buyer_text': 'fake'}])
        self.assertEqual(await self.store.objections('org', '2000-01-01T00:00:00+00:00'), [])
        await self.store.finish_extraction(j, [item, item])
        self.assertEqual(len(await self.store.objections('org', '2000-01-01T00:00:00+00:00')), 1)
        self.assertEqual(await self.store.objections('other', '2000-01-01T00:00:00+00:00'), [])

    async def test_approval_is_revision_checked_idempotent_and_enqueues_one_exact_script(self):
        c = await self.ready()
        approved = await self.store.decide_script('org', c['id'], 'approve', c['revision'], 'approve')
        again = await self.store.decide_script('org', c['id'], 'approve', c['revision'], 'approve')
        self.assertEqual(approved, again)
        with self.assertRaises(WorkflowConflict):
            await self.store.decide_script('org', c['id'], 'approve', c['revision'], 'different')
        jobs = await self.store.claim('build', limit=10)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['payload']['video_script'], c['artifact']['video_script'])
        result = await self.store.complete_build(jobs[0], {'video_url': 'https://video.example/result.mp4'})
        self.assertEqual(result['build_status'], 'completed')
        d = await self.repo.get_draft(result['result']['draft_id'])
        self.assertEqual(d['agent_slug'], 'vea')
        self.assertEqual(d['status'], 'AWAITING_HITL')

    async def test_edit_requires_separate_approval_and_rejection_never_builds(self):
        c = await self.ready()
        c = await self.store.decide_script('org', c['id'], 'edit', c['revision'], 'edit', script=[{'spoken_narration': 'Edited'}], compliance={'passed': True})
        self.assertEqual(c['script_status'], 'pending')
        self.assertEqual(await self.store.claim('build'), [])
        await self.store.decide_script('org', c['id'], 'reject', c['revision'], 'reject')
        self.assertEqual(await self.store.claim('build'), [])

    async def test_approval_rejects_stale_brand_or_unvalidated_copy(self):
        c = await self.ready()
        self.repo.brand_passports['org']['revision'] = 2
        with self.assertRaises(WorkflowConflict):
            await self.store.decide_script('org', c['id'], 'approve', c['revision'], 'approve')
        self.repo.brand_passports['org']['revision'] = 1
        c = await self.store.decide_script('org', c['id'], 'edit', c['revision'], 'edit', script=[{'spoken_narration': 'Edited'}])
        with self.assertRaises(WorkflowConflict):
            await self.store.decide_script('org', c['id'], 'approve', c['revision'], 'approve2')

    async def test_lease_recovery_is_fenced_and_submitted_build_not_resubmitted(self):
        c = await self.ready()
        await self.store.decide_script('org', c['id'], 'approve', c['revision'], 'approve')
        old = (await self.store.claim('build'))[0]
        await self.store.update_build(old, {'submission_state': 'submitting'})
        self.repo._milo_state['jobs'][old['id']]['lease_until'] = 0
        new = (await self.store.claim('build'))[0]
        self.assertEqual(new['payload']['submission_state'], 'submitting')
        with self.assertRaises(WorkflowConflict):
            await self.store.complete_build(old, {})
        await self.store.fail(new, 'private token')
        self.assertNotIn('private', str(await self.store.jobs('org')))

    async def test_auto_dedup_and_cooldown_transaction(self):
        rows = await asyncio.gather(*(self.store.enqueue('org', 'spike', key='evidence', topic='durability') for _ in range(8)))
        self.assertEqual(len({c['id'] for c in rows}), 1)
        self.assertIsNone(await self.store.enqueue('org', 'spike', key='new-evidence', topic='durability'))
        self.assertEqual((await self.store.enqueue('org', 'daily', key='evidence', topic='durability'))['id'], rows[0]['id'])
        self.assertEqual(len(await self.store.list_campaigns('org')), 1)

    async def test_retry_exhaustion_and_settings_validation(self):
        await self.store.enqueue('org', 'manual')
        for _ in range(3):
            j = (await self.store.claim('generate'))[0]
            await self.store.fail(j, 'private')
            self.repo._milo_state['jobs'][j['id']]['available_at'] = 0
        self.assertEqual(await self.store.claim('generate'), [])
        self.assertEqual((await self.store.jobs('org'))[0]['status'], 'failed')
        await self.store.retry('org', j['id'])
        self.assertEqual((await self.store.claim('generate'))[0]['attempts'], 1)
        with self.assertRaises(ValueError):
            await self.store.save_settings('org', {'timezone': 'Missing/Zone'})
        self.assertEqual((await self.store.settings('org'))['daily_hour'], 9)

    async def test_daily_is_once_per_timezone_day_and_manual_keys_bind_request(self):
        first = await self.store.enqueue('org', 'daily', key='evidence-one')
        self.assertIsNone(await self.store.enqueue('org', 'daily', key='evidence-two'))
        self.assertEqual((await self.store.enqueue('org', 'spike', key='evidence-one'))['id'], first['id'])
        await self.store.enqueue('org', 'manual', prompt='One', key='manual')
        with self.assertRaises(WorkflowConflict):
            await self.store.enqueue('org', 'manual', prompt='Two', key='manual')

    async def test_ambiguous_build_requires_receipt_and_preserves_script(self):
        c = await self.ready()
        await self.store.decide_script('org', c['id'], 'approve', c['revision'], 'approve')
        j = (await self.store.claim('build'))[0]
        await self.store.update_build(j, {'submission_state': 'submitting'})
        await self.store.fail(j, 'No receipt')
        self.assertEqual(await self.store.claim('build'), [])
        with self.assertRaises(WorkflowConflict):
            await self.store.reconcile_build('other', j['id'], 'task')
        reconciled = await self.store.reconcile_build('org', j['id'], 'task')
        claimed = (await self.store.claim('build'))[0]
        self.assertEqual(claimed['payload']['provider_task_id'], 'task')
        self.assertEqual(claimed['payload']['video_script'], c['artifact']['video_script'])
        self.assertEqual(reconciled['status'], 'pending')

    async def test_product_identity_and_forgotten_proof_are_checked_at_storage_boundary(self):
        await self.inbound()
        j = (await self.store.claim('extract'))[0]
        item = dict(objection_type='durability', topic='durability', product_id='foreign', buyer_text='last', span_start=8, span_end=12)
        self.repo.brand_products = [{'id': 'foreign', 'org_id': 'other'}]
        with self.assertRaises(WorkflowConflict):
            await self.store.finish_extraction(j, [item])
        item['product_id'] = None
        await self.store.finish_extraction(j, [item])
        c = await self.ready()
        c['artifact']['proof_references'] = [{'source_id': 'proof', 'revision': 1, 'quote': 'fact'}]
        self.store.state['campaigns'][c['id']]['artifact'] = c['artifact']
        self.repo.memory_sources = [{'id': 'proof', 'org_id': 'org', 'revision': 1, 'content': 'fact', 'forgotten_at': '2026-10-19T00:00:00Z'}]
        with self.assertRaises(WorkflowConflict):
            await self.store.decide_script('org', c['id'], 'approve', c['revision'], 'approve')

    async def test_refresh_is_excluded_and_lease_renewal_requires_current_token(self):
        await self.inbound(external_message_id='1:refresh:one')
        self.assertEqual(await self.store.claim('extract'), [])
        await self.store.enqueue('org', 'manual')
        old = (await self.store.claim('generate'))[0]
        renewed = await self.store.renew(old)
        self.assertGreaterEqual(renewed['lease_until'], old['lease_until'])
        self.store.state['jobs'][old['id']]['lease_until'] = 0
        new = (await self.store.claim('generate'))[0]
        with self.assertRaises(WorkflowConflict):
            await self.store.renew(old)
        self.assertNotEqual(new['lease_token'], old['lease_token'])

    async def test_expiring_evidence_cannot_trigger_another_auto_campaign(self):
        c = await self.store.enqueue('org', 'spike', key='all-evidence', topic='durability', evidence_ids=['one', 'two'])
        self.store.state['campaigns'][c['id']]['created_at'] = '2020-01-01T00:00:00+00:00'
        self.assertIsNone(await self.store.enqueue('org', 'spike', key='expiry-changed-hash', topic='durability', evidence_ids=['two']))
        self.assertIsNone(await self.store.enqueue('org', 'daily', key='proof-changed-hash', topic='durability', evidence_ids=['two']))
        next_campaign = await self.store.enqueue('org', 'spike', key='new-id', topic='durability', evidence_ids=['two', 'three'])
        self.assertEqual(next_campaign['evidence_ids'], ['two', 'three'])

    async def test_paid_submission_rechecks_approved_evidence_but_polling_does_not(self):
        c = await self.ready()
        self.repo.memory_sources = [{'id': 'proof', 'org_id': 'org', 'revision': 1, 'content': 'fact'}]
        self.store.state['campaigns'][c['id']]['artifact']['proof_references'] = [{'source_id': 'proof', 'revision': 1, 'quote': 'fact'}]
        await self.store.decide_script('org', c['id'], 'approve', c['revision'], 'approve')
        j = (await self.store.claim('build'))[0]
        self.repo.memory_sources[0]['revision'] = 2
        with self.assertRaises(WorkflowConflict):
            await self.store.update_build(j, {'submission_state': 'submission_started'})
        self.repo.memory_sources[0]['revision'] = 1
        self.repo.brand_passports['org']['revision'] = 2
        with self.assertRaises(WorkflowConflict):
            await self.store.update_build(j, {'submission_state': 'submission_started'})
        self.repo.brand_passports['org']['revision'] = 1
        self.repo.memory_sources[0]['deleted_at'] = '2026-10-19T00:00:00Z'
        with self.assertRaises(WorkflowConflict):
            await self.store.update_build(j, {'submission_state': 'submission_started'})
        self.repo.memory_sources[0]['deleted_at'] = None
        await self.store.update_build(j, {'submission_state': 'submission_started'})
        await self.store.update_build(j, {'submission_state': 'submitted', 'provider_task_id': 'task'})
        self.repo.brand_passports['org']['revision'] = 2
        await self.store.complete_build(j, {'video_url': 'https://example.test/existing.mp4'})

    async def test_ambiguous_build_cannot_use_generic_retry(self):
        c = await self.ready()
        await self.store.decide_script('org', c['id'], 'approve', c['revision'], 'approve')
        j = (await self.store.claim('build'))[0]
        await self.store.update_build(j, {'submission_state': 'submission_started'})
        await self.store.fail(j, 'Lost provider receipt')
        with self.assertRaises(WorkflowConflict):
            await self.store.retry('org', j['id'])

    async def test_cooldown_is_shared_across_daily_and_spike(self):
        await self.store.enqueue('org', 'spike', key='first', topic='durability', evidence_ids=['one'])
        self.assertIsNone(await self.store.enqueue('org', 'daily', key='next', topic='durability', evidence_ids=['one', 'two']))
        await self.store.enqueue('org', 'daily', key='daily-other-topic', topic='price', evidence_ids=['three'])
        self.assertIsNone(await self.store.enqueue('org', 'spike', key='after-daily', topic='price', evidence_ids=['three', 'four']))

    async def test_explicit_provider_failure_retry_creates_new_attempt_once(self):
        c = await self.ready()
        await self.store.decide_script('org', c['id'], 'approve', c['revision'], 'approve')
        j = (await self.store.claim('build'))[0]
        await self.store.update_build(j, {'provider_task_id': 'task-one', 'submission_state': 'provider_failed'})
        await self.store.fail(j, 'ProviderRenderFailed')
        self.assertEqual((await self.store.jobs('org'))[-1]['status'], 'failed')
        retried = await self.store.retry('org', j['id'], key='retry-one')
        self.assertEqual(retried['payload']['provider_attempt'], 2)
        self.assertFalse(retried['payload'].get('provider_task_id'))
        self.assertEqual(retried['payload']['submission_state'], 'not_submitted')
        self.assertEqual(retried['payload']['provider_attempts'][0]['provider_task_id'], 'task-one')
        self.assertEqual(await self.store.retry('org', j['id'], key='retry-one'), retried)
        new = (await self.store.claim('build'))[0]
        self.assertEqual(new['id'], j['id'])
        self.assertEqual(new['payload']['video_script'], c['artifact']['video_script'])
        self.assertEqual(await self.store.retry('org', j['id'], key='retry-one'), retried)
        with self.assertRaises(WorkflowConflict):
            await self.store.reconcile_build('org', j['id'], 'other-task', key='retry-one')

    async def test_timeout_retry_polls_same_task_and_reconcile_replay_is_idempotent(self):
        c = await self.ready()
        await self.store.decide_script('org', c['id'], 'approve', c['revision'], 'approve')
        j = (await self.store.claim('build'))[0]
        await self.store.update_build(j, {'provider_task_id': 'live-task', 'submission_state': 'submitted'})
        self.store.state['jobs'][j['id']]['attempts'] = 3
        await self.store.fail(j, 'TimeoutError')
        retried = await self.store.retry('org', j['id'], key='poll-again')
        self.assertEqual(retried['payload']['provider_task_id'], 'live-task')
        self.assertEqual(retried['payload'].get('provider_attempt', 1), 1)
        self.assertEqual(retried['payload'].get('provider_attempts', []), [])
        new = (await self.store.claim('build'))[0]
        await self.store.update_build(new, {'provider_task_id': None, 'submission_state': 'ambiguous'})
        await self.store.fail(new, 'SubmissionUncertain')
        receipt = await self.store.reconcile_build('org', j['id'], 'receipt-task', key='receipt')
        self.assertEqual(await self.store.reconcile_build('org', j['id'], 'receipt-task', key='receipt'), receipt)
        live = (await self.store.claim('build'))[0]
        self.assertEqual(await self.store.replay_reconcile('org', j['id'], 'receipt-task', 'receipt'), receipt)
        self.assertEqual(self.store.state['jobs'][j['id']]['lease_token'], live['lease_token'])
        self.assertIsNone(await self.store.replay_reconcile('org', j['id'], 'receipt-task', 'not-yet-used'))
        self.assertIsNone(await self.store.replay_reconcile('other', j['id'], 'receipt-task', 'receipt'))
        with self.assertRaises(WorkflowConflict):
            await self.store.reconcile_build('org', j['id'], 'changed-task', key='receipt')
        with self.assertRaises(WorkflowConflict):
            await self.store.replay_reconcile('org', j['id'], 'changed-task', 'receipt')
