"""VEA variant gate: independent renders retain Milo's transactional queue."""
import asyncio
import hashlib
import json
import unittest
from unittest.mock import AsyncMock, patch

from lib.repository import InMemoryRepository
from services.milo.store import MiloStore
from services.workflow.state import WorkflowConflict


class VeaStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.repo = InMemoryRepository()
        self.repo.seed_brand_passport('org', {'revision': 1, 'hex_colors': ['#112233']})
        self.milo = MiloStore(self.repo)
        c = await self.milo.enqueue('org', 'manual', key='manual')
        j = (await self.milo.claim('generate'))[0]
        a = {'brand_revision': 1, 'proof_references': [], 'video_script': [
            {'spoken_narration': 'Exact approved words', 'visual_broll_cues': 'Product', 'on_screen_text': 'Look'}]}
        c = await self.milo.complete_generation(j, a, {'passed': True, 'semantic_checked': True, 'checked_brand_revision': 1})
        self.c = await self.milo.decide_script('org', c['id'], 'approve', c['revision'], 'approve')

    async def test_default_is_attached_once_and_job_preserves_script(self):
        from services.vea.store import prepare_build, VeaStore
        job = (await self.milo.claim('build'))[0]
        first = await prepare_build(job, self.milo)
        second = await prepare_build(first, self.milo)
        rows = await VeaStore(self.repo).list_variants('org')
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['is_default'])
        self.assertEqual(first, second)
        self.assertEqual(first['payload']['vea_config']['variant_revision'], 1)
        self.assertEqual(first['payload']['video_script'], job['payload']['video_script'])
        self.assertEqual(rows[0]['approved_script_revision'], self.c['revision'] - 1)

    async def test_manual_is_atomic_idempotent_and_cannot_use_pending_or_foreign_campaign(self):
        from services.vea.store import VeaStore
        store = VeaStore(self.repo)
        rows = await asyncio.gather(*(store.create_variant('org', self.c['id'], self.c['revision'],
            'editorial_showcase', 'manual-variant') for _ in range(5)))
        self.assertEqual(len({r['id'] for r in rows}), 1)
        self.assertFalse(rows[0]['is_default'])
        self.assertEqual(len(await self.milo.jobs('org')), 3)
        with self.assertRaises(WorkflowConflict):
            await store.create_variant('org', self.c['id'], self.c['revision'], 'high_velocity_d2c', 'manual-variant')
        with self.assertRaises(WorkflowConflict):
            await store.create_variant('other', self.c['id'], self.c['revision'], 'editorial_showcase', 'other')
        with self.assertRaises(WorkflowConflict):
            await store.create_variant('org', self.c['id'], self.c['revision']-1, 'editorial_showcase', 'stale')

    async def test_stale_evidence_prevents_new_render_and_legacy_submission_is_not_upgraded(self):
        from services.vea.store import prepare_build, VeaStore
        self.repo.brand_passports['org']['revision'] = 2
        with self.assertRaises(WorkflowConflict):
            await VeaStore(self.repo).create_variant('org', self.c['id'], self.c['revision'], 'editorial_showcase', 'manual')
        job = (await self.milo.claim('build'))[0]
        job['payload']['submission_state'] = 'ambiguous'
        self.assertEqual(await prepare_build(job, self.milo), job)

    def result(self, row):
        from services.milo.video import build_binding
        binding=build_binding(self.milo.state['jobs'][row['job_id']])
        preset={'id':row['preset_id'],'version':1}
        preset_sha=hashlib.sha256(json.dumps(preset,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        manifest={'segments':[{'segment_id':'scene-0-cut-0','asset_id':'a','start_ms':0,'end_ms':3000,'scene_index':0}],
                  'preset':preset,'preset_sha256':preset_sha,'duration_ms':3000,
                  'org_id':'org','script_sha256':binding['script_sha256'],'vea_config_sha256':binding['vea_config_sha256'],'private':'path'}
        sha=hashlib.sha256(json.dumps(manifest,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        return dict(schema_version=1,id=row['id'],variant_revision=row['revision'],video_url='https://media.test/video.mp4',
            thumbnail_url='https://media.test/thumbnail.jpg',duration_sec=3.0,preset_used=row['preset_id'],preset_version=1,
            preset_sha256=preset_sha,source_milo_script_id=self.c['id'],approved_script_revision=self.c['revision']-1,
            composition_sha256=sha,render_telemetry={},composition_manifest=manifest)

    async def test_completion_is_typed_and_nondefault_does_not_replace_campaign_result(self):
        from services.vea.store import prepare_build, VeaStore
        store = VeaStore(self.repo)
        row = await store.create_variant('org', self.c['id'], self.c['revision'], 'editorial_showcase', 'manual')
        jobs = await self.milo.claim('build', limit=10)
        job = await prepare_build(next(j for j in jobs if j['id']==row['job_id']), self.milo)
        await self.milo.complete_build(job, self.result(row))
        row = await store.get_variant('org', row['id'])
        self.assertEqual(row['status'], 'completed')
        draft = await self.repo.get_draft(row['draft_id'])
        self.assertEqual(draft['vea_artifact']['id'], row['id'])
        self.assertEqual(draft['status'], 'AWAITING_HITL')
        self.assertIsNone((await self.milo.get_campaign('org', self.c['id']))['result'])
        self.assertNotIn('private', str(row['segments']))
        self.assertIsNone(await store.get_variant('other', row['id']))

    async def completed_default(self):
        from services.vea.store import prepare_build, VeaStore
        job = await prepare_build((await self.milo.claim('build'))[0], self.milo)
        row = (await VeaStore(self.repo).list_variants('org'))[0]
        await self.milo.complete_build(job, self.result(row))
        return await VeaStore(self.repo).get_variant('org', row['id'])

    async def test_swap_preserves_manifest_and_rejects_stale_approval(self):
        from services.vea.store import VeaStore, validate_review
        row = await self.completed_default()
        old_draft = await self.repo.get_draft(row['draft_id'])
        with patch('services.vea.store.fetch_renderer', AsyncMock(return_value={'assets':[{'id':'replacement','kind':'video','duration_sec':3,'tags':{'en':['Product']}}]})):
            new = await VeaStore(self.repo).swap('org', row['id'], 1, 'scene-0-cut-0', 'replacement', 'swap')
            replay = await VeaStore(self.repo).swap('org', row['id'], 1, 'scene-0-cut-0', 'replacement', 'swap')
        self.assertEqual(new, replay)
        self.assertEqual(new['revision'], 2)
        self.assertIsNone(new['artifact'])
        jobs = await self.milo.jobs('org')
        payload = next(j['payload'] for j in jobs if j['id']==new['job_id'])
        self.assertEqual(payload['vea_config']['reuse_manifest']['private'], 'path')
        self.assertEqual(payload['vea_config']['clip_overrides'], [{'segment_id':'scene-0-cut-0','asset_id':'replacement'}])
        with self.assertRaises(WorkflowConflict):
            await validate_review(self.repo, old_draft)

    async def test_retry_refuses_ambiguous_submission(self):
        from services.vea.store import VeaStore, prepare_build
        job = await prepare_build((await self.milo.claim('build'))[0], self.milo)
        await self.milo.update_build(job, {'submission_state':'submitting'})
        await self.milo.fail(job, 'timeout')
        row = (await VeaStore(self.repo).list_variants('org'))[0]
        with self.assertRaises(WorkflowConflict):
            await VeaStore(self.repo).retry('org', row['id'], row['revision'], 'retry')

    async def test_completion_rejects_artifact_for_another_variant(self):
        from services.vea.store import VeaStore, prepare_build
        job = await prepare_build((await self.milo.claim('build'))[0], self.milo)
        row = (await VeaStore(self.repo).list_variants('org'))[0]
        result = self.result(row); result['id'] = 'wrong'
        with self.assertRaises(WorkflowConflict):
            await self.milo.complete_build(job, result)
        self.assertEqual(self.repo.drafts, [])

    async def test_composition_hash_and_manifest_tenant_are_verified(self):
        from services.vea.store import VeaStore, prepare_build
        job = await prepare_build((await self.milo.claim('build'))[0], self.milo)
        row = (await VeaStore(self.repo).list_variants('org'))[0]
        result=self.result(row)
        result['composition_manifest']['org_id']='other'
        with self.assertRaises(WorkflowConflict):
            await self.milo.complete_build(job,result)

    async def test_swap_invalidates_an_already_approved_export(self):
        from services.vea.store import VeaStore
        row=await self.completed_default()
        draft=await self.repo.get_draft(row['draft_id'])
        await self.repo.transition_draft('org',draft['id'],'approve',draft['revision'],'approved-export')
        with patch('services.vea.store.fetch_renderer',AsyncMock(return_value={'assets':[{'id':'replacement','kind':'video','duration_sec':3,'tags':{'en':['Product']}}]})):
            await VeaStore(self.repo).swap('org',row['id'],1,'scene-0-cut-0','replacement','swap')
        draft=await self.repo.get_draft(draft['id'])
        self.assertEqual(draft['status'],'REJECTED')
        self.assertIsNone(draft['final_content'])

    async def test_invalid_brand_palette_uses_neutral_caption_configuration(self):
        from services.vea.store import prepare_build
        self.repo.brand_passports['org']['hex_colors']=['invalid',123,'#aBc123']
        job=await prepare_build((await self.milo.claim('build'))[0],self.milo)
        self.assertEqual(job['payload']['vea_config']['brand_snapshot']['hex_colors'],['#aBc123'])

    async def test_music_rights_are_revalidated_before_approval(self):
        from services.vea.store import VeaStore,prepare_build,validate_review
        job=await prepare_build((await self.milo.claim('build'))[0],self.milo)
        row=(await VeaStore(self.repo).list_variants('org'))[0]
        result=self.result(row)
        result['composition_manifest']['music']={'asset_id':'music','asset_sha256':'c'*64}
        result['composition_sha256']=hashlib.sha256(json.dumps(result['composition_manifest'],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        await self.milo.complete_build(job,result)
        row=await VeaStore(self.repo).get_variant('org',row['id'])
        draft=await self.repo.get_draft(row['draft_id'])
        with patch('services.vea.store.fetch_renderer',AsyncMock(return_value={'assets':[{'id':'a'}]})):
            with self.assertRaises(WorkflowConflict):await validate_review(self.repo,draft)

    async def test_pinned_recipe_cannot_silently_change(self):
        from services.vea.store import VeaStore,prepare_build
        job=await prepare_build((await self.milo.claim('build'))[0],self.milo)
        job=await self.milo.update_build(job,{'vea_config':{**job['payload']['vea_config'],'preset_version':1,'preset_sha256':'c'*64}})
        row=(await VeaStore(self.repo).list_variants('org'))[0]
        with self.assertRaises(WorkflowConflict):await self.milo.complete_build(job,self.result(row))

    async def test_swap_rejects_audio_and_clips_shorter_than_timeline_segment(self):
        from services.vea.store import VeaStore
        row=await self.completed_default()
        for asset in [{'id':'replacement','kind':'music','duration_sec':10},
                      {'id':'replacement','kind':'video','duration_sec':1}]:
            with patch('services.vea.store.fetch_renderer',AsyncMock(return_value={'assets':[asset]})):
                with self.assertRaises(WorkflowConflict):
                    await VeaStore(self.repo).swap('org',row['id'],1,'scene-0-cut-0','replacement','invalid-swap')

    async def test_completion_rejects_inconsistent_embedded_recipe_or_duration(self):
        from services.vea.store import VeaStore,prepare_build,validate_artifact
        job=await prepare_build((await self.milo.claim('build'))[0],self.milo)
        row=(await VeaStore(self.repo).list_variants('org'))[0]
        for key,value in [('preset',{'id':'editorial_showcase','version':1}),('preset_sha256','b'*64),('duration_ms',4000)]:
            result=self.result(row)
            result['composition_manifest'][key]=value
            result['composition_sha256']=hashlib.sha256(json.dumps(result['composition_manifest'],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
            with self.subTest(key=key),self.assertRaises(WorkflowConflict):
                validate_artifact(job,result)
