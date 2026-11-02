import unittest
from unittest.mock import AsyncMock,patch
import test_milo_worker as base
from test_milo_pipeline import artifact
from services.milo.worker import MiloWorker
from services.milo.director.documents import DirectorDocuments


class DirectorGenerationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=base.WorkerTests.asyncSetUp

    async def test_automatic_product_selection_keeps_authoritative_sku_constraints(self):
        self.context['products'][0]['sku']='selected-sku'
        campaign=await self.store.enqueue('a','manual',key='auto-product')
        self.assertIsNone(campaign.get('product_id'))
        generated={'artifact':artifact(),'compliance':{'passed':True,'violations':[]},'missing_evidence':[],
            'selected_scope':{'product_id':'p','topic':'durability'}}
        directions=AsyncMock(return_value={'directions':[{'prompt':'Show stitching','subject_action':'Hold bag',
            'camera_movement':'Static','lighting_style':'Daylight','target_duration_sec':12.0}]})
        with patch.dict('os.environ',{'MILO_DIRECTOR_ENABLED':'1'}),patch('services.milo.worker.generate_campaign',AsyncMock(return_value=generated)):
            worker=MiloWorker(self.repo,model=directions,context_loader=AsyncMock(return_value=self.context))
            await worker.run_once('generate')
        document=await DirectorDocuments(self.repo).document('a',campaign['id'])
        current=await self.store.get_campaign('a',campaign['id'])
        self.assertEqual(current['status'],'awaiting_review')
        self.assertEqual(document['storyboard']['scenes'][0]['asset_constraints']['required_sku_tags'],['selected-sku'])
        self.assertFalse(document['storyboard']['narration_approved'])
        self.assertFalse([j for j in await self.store.jobs('a') if j['kind']=='build'])
