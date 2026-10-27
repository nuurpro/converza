import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

from lib.repository import InMemoryRepository
from services.milo.store import MiloStore
from services.milo.worker import MiloWorker
from services.milo.scheduler import schedule
from services.sleyz.store import SleyzStore
from test_milo_pipeline import artifact, fixture


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_generation_scope_survives_approval_and_vea_builds(self):
        from services.vea.store import VeaStore, prepare_build
        campaign = await self.store.enqueue('a', 'manual', key='manual-scope')
        model = AsyncMock(side_effect=[artifact(), {'passed': True, 'violations': []}])
        worker = MiloWorker(self.repo, model=model, context_loader=AsyncMock(return_value=self.context))
        await worker.run_once('generate')
        current = await self.store.get_campaign('a', campaign['id'])
        self.assertEqual((current['product_id'], current['topic']), ('p', 'durability'))
        replay = await self.store.enqueue('a', 'manual', key='manual-scope')
        self.assertEqual(replay, current)
        approved = await self.store.decide_script('a', current['id'], 'approve', current['revision'], 'approve-scope')
        job = await prepare_build((await self.store.claim('build'))[0], self.store)
        self.assertEqual(job['payload']['vea_config']['product_id'], 'p')
        self.assertEqual(job['payload']['video_script'], current['artifact']['video_script'])
        vea = VeaStore(self.repo)
        variants = await vea.list_variants('a')
        self.assertEqual(variants[0]['product_id'], 'p')
        alternate = await vea.create_variant('a', current['id'], approved['revision'], 'editorial_showcase', 'alternate')
        self.assertEqual(alternate['product_id'], 'p')
        self.assertEqual(vea.milo.state['jobs'][alternate['job_id']]['payload']['vea_config']['product_id'], 'p')

    async def asyncSetUp(self):
        self.repo=InMemoryRepository(); self.context=fixture(); self.store=MiloStore(self.repo)
        self.repo.seed_brand_passport('a',{**self.context['passport'],'revision':3,'proof_points':self.context['proof_points']})
        self.repo.memory_sources=self.context['sources']; self.repo.brand_products=self.context['products']

    async def test_sales_reply_failure_does_not_prevent_objection_extraction(self):
        sales=SleyzStore(self.repo)
        accepted=await sales.accept(dict(org_id='a',platform='telegram',connection_id='tg',external_message_id='1',customer_id='buyer',
            text='Will the stitching last?',received_at=datetime.now(timezone.utc).isoformat(),simulated=False))
        model=AsyncMock(return_value={'objections':[{'topic':'durability','product_id':'p','buyer_text':'Will the stitching last?'}]})
        worker=MiloWorker(self.repo,model=model)
        self.assertEqual(await worker.run_once('extract'),1)
        rows=await self.store.objections('a','2020-01-01T00:00:00+00:00')
        self.assertEqual(len(rows),1)
        self.assertEqual((await self.repo.get_draft(accepted['draft_id']))['status'],'PENDING_DRAFT')

    async def test_generation_worker_persists_full_campaign_without_video(self):
        campaign=await self.store.enqueue('a','manual',key='manual')
        model=AsyncMock(side_effect=[artifact(),{'passed':True,'violations':[]}])
        loader=AsyncMock(return_value=self.context)
        worker=MiloWorker(self.repo,model=model,context_loader=loader)
        await worker.run_once('generate')
        current=await self.store.get_campaign('a',campaign['id'])
        self.assertEqual(current['status'],'awaiting_review')
        self.assertEqual(current['script_status'],'pending')
        self.assertFalse([j for j in await self.store.jobs('a') if j['kind']=='build'])

    async def test_automatic_generation_uses_reserved_evidence_snapshot(self):
        campaign=await self.store.enqueue('a','daily',key='snapshot',topic='durability',product_id='p',evidence_ids=['buyer'])
        self.context['objections'].append({**self.context['objections'][0],'id':'arrived-after-enqueue','prospect_id':'two'})
        model=AsyncMock(side_effect=[artifact(),{'passed':True,'violations':[]}])
        worker=MiloWorker(self.repo,model=model,context_loader=AsyncMock(return_value=self.context))
        await worker.run_once('generate')
        row=await self.store.get_campaign('a',campaign['id'])
        self.assertEqual(row['artifact']['trigger_reason'],'Generated from 1 recent buyer conversation about durability')
        self.assertEqual([q['source_id'] for q in row['artifact']['buyer_quotes']],['buyer'])

    async def test_daily_spike_and_unchanged_evidence_suppression(self):
        now=datetime(2026,10,19,5,tzinfo=timezone.utc) #10am Tashkent
        for n in range(5):
            r={**self.context['objections'][0],'id':str(n),'prospect_id':str(n)}
            self.store.state['objections'][str(n)]=r
        self.assertEqual(len(await schedule(self.repo,now=now)),1)
        self.assertEqual(await schedule(self.repo,now=now),[])
        self.assertEqual(len(await self.store.list_campaigns('a')),1)

    async def test_objection_tool_enforces_time_window_and_organization(self):
        from services.milo.tools import MiloTools
        now=datetime(2026,10,20,tzinfo=timezone.utc)
        self.store.state['objections']['recent']={**self.context['objections'][0],'created_at':now.isoformat()}
        self.store.state['objections']['old']={**self.context['objections'][0],'id':'old','prospect_id':'old',
            'created_at':(now-timedelta(days=8)).isoformat()}
        self.store.state['objections']['foreign']={**self.context['objections'][0],'id':'foreign','org_id':'b','created_at':now.isoformat()}
        tools=MiloTools(self.repo,'a')
        result=await tools.get_top_buyer_objections(timedelta(days=7),now=now)
        self.assertEqual(result[0]['count'],1)
        self.assertEqual(result[0]['source_ids'],['buyer'])
        with self.assertRaises(ValueError): await tools.get_top_buyer_objections(timedelta(0),now=now)

    async def test_vendor_language_outage_remains_failed_and_manually_retryable(self):
        from services.milo.errors import LanguageServiceUnavailable
        campaign=await self.store.enqueue('a','manual',key='language-outage',language='ru')
        worker=MiloWorker(self.repo,model=AsyncMock(side_effect=LanguageServiceUnavailable('Provider unavailable')),
            context_loader=AsyncMock(return_value=self.context))
        await worker.run_once('generate')
        row=await self.store.get_campaign('a',campaign['id'])
        self.assertEqual(row['status'],'failed')
        self.assertEqual(row['language'],'ru')
        job=(await self.store.jobs('a'))[0]
        self.assertIn('language service is temporarily unavailable',job['last_error'])
        self.assertEqual(await worker.run_once('generate'),0)
        retried=await self.store.retry('a',job['id'])
        self.assertEqual(retried['status'],'pending')
