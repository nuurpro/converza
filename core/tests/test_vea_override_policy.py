"""Core validates operator swaps before invalidating any prior export."""
from copy import deepcopy
import unittest
from unittest.mock import AsyncMock, patch

from services.vea.store import VeaStore, validate_review
from services.vea.store import prepare_build, validate_artifact
from services.workflow.state import WorkflowConflict
import test_vea_storage as fixtures


def eligible(**changes):
    item=dict(id='replacement',org_id='org',kind='video',duration_sec=4,
              width=1920,height=1080,sha256='b'*64,rights_confirmed=True,
              permitted_uses=['advertising'],product_ids=['other'],tags={})
    item.update(changes)
    return item


class ManualOverrideTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.VeaStorageTests.asyncSetUp
    completed_default=fixtures.VeaStorageTests.completed_default
    result=fixtures.VeaStorageTests.result

    async def test_off_tag_cross_initiative_manual_swap_invalidates_approval(self):
        row=await self.completed_default(); store=VeaStore(self.repo)
        draft=await self.repo.get_draft(row['draft_id'])
        await self.repo.transition_draft('org',draft['id'],'approve',draft['revision'],'approve-export')
        catalog=AsyncMock(return_value={'assets':[eligible()]})
        with patch('services.vea.store.fetch_renderer',catalog):
            new=await store.swap('org',row['id'],1,'scene-0-cut-0','replacement','swap')
        self.assertEqual(new['revision'],2)
        self.assertEqual(catalog.await_args.args[1]['selection'],'manual')
        self.assertEqual((await self.repo.get_draft(draft['id']))['status'],'REJECTED')
        cfg=self.milo.state['jobs'][new['job_id']]['payload']['vea_config']
        self.assertEqual(cfg['clip_overrides'],[dict(segment_id='scene-0-cut-0',asset_id='replacement')])

    async def test_unsafe_swaps_preserve_existing_export_and_receipts(self):
        row=await self.completed_default(); store=VeaStore(self.repo)
        before=deepcopy((store.state,self.milo.state,self.repo.drafts))
        changes=[dict(org_id='other'),dict(width=0),dict(height=True),dict(duration_sec=1),
                 dict(duration_sec=float('nan')),dict(rights_confirmed=False),
                 dict(permitted_uses=['internal']),dict(permitted_uses='not advertising'),
                 dict(permitted_uses=None),dict(permitted_uses={'advertising':False}),dict(sha256='invalid')]
        for change in changes:
            with self.subTest(change=change), patch('services.vea.store.fetch_renderer',AsyncMock(return_value={'assets':[eligible(**change)]})):
                with self.assertRaises(WorkflowConflict):
                    await store.swap('org',row['id'],1,'scene-0-cut-0','replacement','swap')
            self.assertEqual((store.state,self.milo.state,self.repo.drafts),before)

    async def test_prior_manual_override_survives_second_swap_and_fresh_review(self):
        row=await self.completed_default(); store=VeaStore(self.repo)
        raw=store.state['variants'][row['id']]
        raw['composition_manifest']['segments'].append(dict(segment_id='second',asset_id='a',start_ms=1500,end_ms=3000,scene_index=0))
        raw['composition_manifest']['segments'][0]['end_ms']=1500
        with patch('services.vea.store.fetch_renderer',AsyncMock(return_value={'assets':[eligible(),eligible(id='second-clip')]})):
            first=await store.swap('org',row['id'],1,'scene-0-cut-0','replacement','first')
            job=await prepare_build((await self.milo.claim('build'))[0],self.milo)
            result=self.result(first)
            result['composition_manifest']['segments'][0].update(asset_id='replacement',selection_mode='manual')
            import hashlib, json
            result['composition_sha256']=hashlib.sha256(json.dumps(result['composition_manifest'],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
            await self.milo.complete_build(job,result)
            current=store.state['variants'][row['id']]
            current['composition_manifest']['segments'].append(dict(segment_id='second',asset_id='a',start_ms=1500,end_ms=3000,scene_index=0))
            second=await store.swap('org',row['id'],2,'second','second-clip','second')
        cfg=self.milo.state['jobs'][second['job_id']]['payload']['vea_config']
        self.assertEqual({x['segment_id']:x['asset_id'] for x in cfg['clip_overrides']},
                         {'scene-0-cut-0':'replacement','second':'second-clip'})
        self.assertEqual(cfg['reuse_manifest']['segments'][0]['asset_id'],'replacement')

    async def test_renderer_cannot_assert_manual_authorization_not_in_bound_config(self):
        job=await prepare_build((await self.milo.claim('build'))[0],self.milo)
        row=(await VeaStore(self.repo).list_variants('org'))[0]
        result=self.result(row)
        result['composition_manifest']['segments'][0]['selection_mode']='manual'
        import hashlib, json
        result['composition_sha256']=hashlib.sha256(json.dumps(result['composition_manifest'],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        with self.assertRaises(WorkflowConflict): validate_artifact(job,result)
