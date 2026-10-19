import unittest
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from lib.repository import InMemoryRepository
from services.milo.routes import create_milo_router
from services.milo.store import MiloStore
from test_milo_pipeline import fixture, artifact


class MiloRouteTests(unittest.TestCase):
    def setUp(self):
        self.repo = InMemoryRepository()
        context = fixture()
        self.repo.seed_brand_passport('a', {**context['passport'],'revision':3,'proof_points':context['proof_points']})
        self.repo.memory_sources = context['sources']
        self.repo.brand_products = context['products']
        async def auth(): return SimpleNamespace(user_id='owner')
        def owner(user,org):
            if org != 'a': raise HTTPException(403,'Wrong organization')
        app=FastAPI(); app.include_router(create_milo_router(lambda:self.repo,auth,owner))
        self.client=TestClient(app)

    def test_owner_scoping_and_manual_idempotency(self):
        self.assertEqual(self.client.get('/api/milo/b/campaigns').status_code,403)
        headers={'Idempotency-Key':'one'}
        first=self.client.post('/api/milo/a/campaigns',json={'prompt':'Draft'},headers=headers)
        second=self.client.post('/api/milo/a/campaigns',json={'prompt':'Draft'},headers=headers)
        self.assertEqual(first.status_code,202,first.text)
        self.assertEqual(first.json()['id'],second.json()['id'])
        self.assertEqual(self.client.post('/api/milo/a/campaigns',json={'prompt':'Changed'},headers=headers).status_code,409)

    def test_brand_confirmation_verifies_exact_current_source_and_owner_stamp(self):
        body={'campaign_language':'ru','personas':[],'proof_points':[{'id':'one','source_id':'fact','revision':2,'quote':'The shell uses reinforced stitching.'}],
              'banned_terms':[],'competitor_names':[]}
        result=self.client.put('/api/milo/a/brand',json=body)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['proof_points'][0]['confirmed_by'],'owner')
        body['proof_points'][0]['quote']='Fabricated durability proof'
        self.assertEqual(self.client.put('/api/milo/a/brand',json=body).status_code,422)

    def test_source_list_excludes_unresolved_customer_claims_and_deleted_rows(self):
        self.repo.memory_sources += [{'id':'objection','org_id':'a','revision':1,'kind':'objection','content':'Fake proof'},
            {'id':'foreign','org_id':'b','revision':1,'kind':'manual','content':'secret'}]
        value=self.client.get('/api/milo/a/proof-sources').json()
        self.assertEqual([s['id'] for s in value['sources']],['fact'])

    def test_invalid_settings_timezone_and_schema_fail(self):
        self.assertEqual(self.client.put('/api/milo/a/settings',json={'timezone':'Invented/Zone'}).status_code,422)
        self.assertEqual(self.client.post('/api/milo/a/campaigns',json={'prompt':'x','language':'xx'},headers={'Idempotency-Key':'x'}).status_code,422)

    def ready(self):
        async def prepare():
            store=MiloStore(self.repo)
            context=fixture()
            objection={**context['objections'][0],'created_at':datetime.now(timezone.utc).isoformat()}
            store.state['objections']['buyer']=objection
            row=await store.enqueue('a','manual',key='test-ready')
            job=(await store.claim('generate'))[0]
            return await store.complete_generation(job,artifact(),{'passed':True,'semantic_checked':True,'checked_brand_revision':3,'violations':[]})
        return asyncio.run(prepare())

    def test_edit_requires_new_approval_and_approval_replays_exactly_one_build(self):
        row=self.ready(); id=row['id']
        with patch('services.milo.routes.review_compliance',AsyncMock(return_value={'passed':True,'semantic_checked':True,'checked_brand_revision':3,'violations':[]})) as review:
            scene=artifact()['video_script']; scene[0]['on_screen_text']='Stitching details'
            edited=self.client.post(f'/api/milo/a/campaigns/{id}/script/edit',json={'expected_revision':row['revision'],'video_script':scene},headers={'Idempotency-Key':'edit'})
            self.assertEqual(edited.status_code,200,edited.text)
            self.assertEqual(edited.json()['script_status'],'pending')
            self.assertFalse([j for j in asyncio.run(MiloStore(self.repo).jobs('a')) if j['kind']=='build'])
            body={'expected_revision':edited.json()['revision']}
            first=self.client.post(f'/api/milo/a/campaigns/{id}/script/approve',json=body,headers={'Idempotency-Key':'approve'})
            second=self.client.post(f'/api/milo/a/campaigns/{id}/script/approve',json=body,headers={'Idempotency-Key':'approve'})
            self.assertEqual(first.status_code,200,first.text)
            self.assertEqual(first.json(),second.json())
            self.assertEqual(review.await_count,2) # edit and first approval, not replay
        jobs=asyncio.run(MiloStore(self.repo).jobs('a'))
        builds=[j for j in jobs if j['kind']=='build']
        self.assertEqual(len(builds),1)
        self.assertEqual(builds[0]['payload']['video_script'],scene)

    def test_stale_source_blocks_approval_before_paid_semantic_review(self):
        row=self.ready(); self.repo.memory_sources[0]['revision']=999
        with patch('services.milo.routes.review_compliance',AsyncMock()) as review:
            response=self.client.post(f"/api/milo/a/campaigns/{row['id']}/script/approve",json={'expected_revision':row['revision']},headers={'Idempotency-Key':'a'})
            self.assertEqual(response.status_code,409)
            review.assert_not_awaited()

    def test_forgotten_source_cannot_be_reconfirmed(self):
        self.repo.memory_sources[0]['forgotten_at']='now'
        response=self.client.put('/api/milo/a/brand',json={'proof_points':[{'id':'p','source_id':'fact','revision':2,'quote':'The shell uses reinforced stitching.'}]})
        self.assertEqual(response.status_code,422)

    def test_committed_reconciliation_replays_when_provider_is_later_unavailable(self):
        row=self.ready()
        async def uncertain():
            store=MiloStore(self.repo)
            await store.decide_script('a',row['id'],'approve',row['revision'],'approve')
            job=(await store.claim('build'))[0]
            await store.update_build(job,{'submission_state':'submission_started'})
            await store.fail(job,'Lost response')
            return job
        job=asyncio.run(uncertain())
        url=f"/api/milo/a/jobs/{job['id']}/reconcile"
        with patch('services.milo.video.validate_provider_receipt',AsyncMock(side_effect=[{},RuntimeError('offline')])) as validate:
            first=self.client.post(url,json={'task_id':'original-task'},headers={'Idempotency-Key':'receipt'})
            second=self.client.post(url,json={'task_id':'original-task'},headers={'Idempotency-Key':'receipt'})
            self.assertEqual(first.status_code,202,first.text)
            self.assertEqual(second.status_code,202,second.text)
            self.assertEqual(first.json(),second.json())
            self.assertEqual(validate.await_count,1)
