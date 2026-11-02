"""Exercise actual owner routes and existing campaign sign-off boundary."""
import asyncio
import os
import unittest
from copy import deepcopy
from unittest.mock import AsyncMock,patch
import test_milo_routes as base
from test_milo_director_contracts import scene
from services.milo.director.documents import DirectorDocuments
from services.milo.director.runtime import handoff_build,worker
from services.milo.director.store import DirectorStore
from services.milo.store import MiloStore


class DirectorRouteTests(unittest.TestCase):
    setUp=base.MiloRouteTests.setUp
    ready=base.MiloRouteTests.ready

    def board(self,row):
        value=scene();approved=row['artifact']['video_script'][0]
        value['narration_chunk']=approved['spoken_narration'];value['overlay_text']['text']=approved['on_screen_text']
        value['asset_constraints']['required_sku_tags']=[]
        return {'revision':1,'narration_approved':False,'scenes':[value]}

    def test_original_signoff_starts_director_and_narration_edits_stop_it(self):
        row=self.ready();cid=row['id'];docs=DirectorDocuments(self.repo);board=self.board(row)
        asyncio.run(docs.command('a',cid,'initialize',board=board,campaign_revision=row['revision'],key='initial'))
        report={'passed':True,'semantic_checked':True,'checked_brand_revision':3,'violations':[]}
        with patch.dict(os.environ,{'MILO_DIRECTOR_ENABLED':'1'}),patch('services.milo.routes.review_compliance',AsyncMock(return_value=report)):
            result=self.client.post(f'/api/milo/a/campaigns/{cid}/script/approve',json={'expected_revision':row['revision']},headers={'Idempotency-Key':'original'})
            self.assertEqual(result.status_code,200,result.text)
            job=asyncio.run(MiloStore(self.repo).claim('build'))[0]
            asyncio.run(handoff_build(self.repo,job))
            view=self.client.get(f'/api/milo/a/campaigns/{cid}/director').json()
            self.assertEqual(view['run']['status'],'DIRECTING_SCENE')
            self.assertTrue(view['storyboard']['narration_approved'])
            changed=deepcopy(view['storyboard']['scenes']);changed[0]['narration_chunk']='Ask about reinforced stitching.'
            preview=asyncio.run(docs.preview('a',cid,1,dict(base_revision=1,scenes=changed,narration_changed=False,
                changed_scene_indices=[1],reusable_scene_indices=[],unresolved_instructions=[])))
            with patch('services.milo.director.routes.review_compliance',AsyncMock(return_value=report)):
                edited=self.client.post(f'/api/milo/a/campaigns/{cid}/director/edits',json={'expected_revision':1,'preview_id':preview['preview_id']},headers={'Idempotency-Key':'edit'})
                self.assertEqual(edited.status_code,200,edited.text)
            current=self.client.get(f'/api/milo/a/campaigns/{cid}/director').json()
            self.assertFalse(current['storyboard']['narration_approved'])
            self.assertEqual(current['run']['status'],'AWAITING_SCRIPT_APPROVAL')
            self.assertEqual(asyncio.run(DirectorStore(self.repo).claim()),[])

    def test_runtime_worker_factory_and_legacy_status(self):
        row=self.ready()
        self.assertEqual(self.client.get(f"/api/milo/a/campaigns/{row['id']}/director").json(),{'run':None,'storyboard':None})
        self.assertIsNotNone(worker(self.repo))
        self.assertEqual(self.client.get(f"/api/milo/b/campaigns/{row['id']}/director").status_code,403)

    def test_delayed_initial_build_cannot_approve_later_narration_revert(self):
        row=self.ready();cid=row['id'];docs=DirectorDocuments(self.repo);board=self.board(row)
        asyncio.run(docs.command('a',cid,'initialize',board=board,campaign_revision=row['revision'],key='initial'))
        store=MiloStore(self.repo)
        asyncio.run(store.decide_script('a',cid,'approve',row['revision'],'sign',compliance=row['compliance']))
        job=asyncio.run(store.claim('build'))[0]
        for revision,text in ((1,'New unsigned narration.'),(2,board['scenes'][0]['narration_chunk'])):
            changed=deepcopy(board['scenes']);changed[0]['narration_chunk']=text
            preview=asyncio.run(docs.preview('a',cid,revision,dict(base_revision=revision,scenes=changed,narration_changed=True,unresolved_instructions=[])))
            asyncio.run(docs.command('a',cid,'apply',expected_revision=revision,preview_id=preview['preview_id'],key=f'edit-{revision}'))
        asyncio.run(handoff_build(self.repo,job))
        current=asyncio.run(docs.document('a',cid))
        self.assertFalse(current['storyboard']['narration_approved'])
        self.assertEqual(asyncio.run(DirectorStore(self.repo).claim()),[])
