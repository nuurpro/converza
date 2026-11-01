import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from lib.repository import InMemoryRepository
from services.milo.store import MiloStore


class VeaRouteTests(unittest.TestCase):
    def setUp(self):
        from services.vea.routes import create_vea_router
        self.repo=InMemoryRepository()
        self.repo.seed_brand_passport('a',{'revision':1})
        async def auth(): return SimpleNamespace(user_id='owner')
        def owner(user,org):
            if org!='a': raise HTTPException(403,'Wrong organization')
        app=FastAPI();app.include_router(create_vea_router(lambda:self.repo,auth,owner))
        self.client=TestClient(app)

    def test_disabled_capability_and_organization_scoping(self):
        with patch.dict('os.environ',{'VEA_PRESETS_ENABLED':'false'}):
            self.assertEqual(self.client.get('/api/vea/a/variants').status_code,200)
            self.assertEqual(self.client.post('/api/vea/a/variants',json={'campaign_id':'c','expected_revision':1},headers={'Idempotency-Key':'x'}).status_code,503)
        self.assertEqual(self.client.get('/api/vea/b/variants').status_code,403)

    def test_proxy_authenticates_and_omits_private_paths(self):
        with patch('services.vea.routes.fetch_renderer',AsyncMock(return_value={'assets':[{'id':'clip','path':'/private/file.mp4','tags':['close up'],'sha256':'a'*64}]})) as fetch:
            result=self.client.get('/api/vea/a/assets?language=ru&product_id=product')
        self.assertEqual(result.status_code,200,result.text)
        self.assertNotIn('path',result.json()['assets'][0])
        self.assertEqual(fetch.await_args.args,('assets',{'org_id':'a','selection':'manual','language':'ru'}))

    def test_approved_script_required_and_idempotency_header_required(self):
        with patch.dict('os.environ',{'VEA_PRESETS_ENABLED':'true'}):
            payload={'campaign_id':'missing','expected_revision':1,'preset_id':'editorial_showcase'}
            self.assertEqual(self.client.post('/api/vea/a/variants',json=payload).status_code,422)
            result=self.client.post('/api/vea/a/variants',json=payload,headers={'Idempotency-Key':'x'})
            self.assertEqual(result.status_code,409,result.text)
        self.assertEqual(self.client.get('/api/vea/a/variants/missing').status_code,404)

    def test_renderer_outage_is_actionable_and_no_internal_detail_leaks(self):
        with patch('services.vea.routes.fetch_renderer',AsyncMock(side_effect=RuntimeError('SECRET key missing'))):
            result=self.client.get('/api/vea/a/presets')
        self.assertEqual(result.status_code,503)
        self.assertNotIn('SECRET',result.text)
