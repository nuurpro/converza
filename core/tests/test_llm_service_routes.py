import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


class LLMServiceRoutesTests(unittest.TestCase):
    def test_trusted_service_extraction_uses_shared_client_and_server_controlled_temperature(self):
        from services.llm.routes import router
        app=FastAPI();app.include_router(router)
        with TestClient(app) as client, patch.dict(os.environ,{'LLM_SERVICE_API_KEY':'test-service-key'}), patch('services.llm.routes.complete_json',AsyncMock(return_value={'intent':'lead'})) as complete:
            payload={'messages':[{'role':'user','content':'Interested in training.'}],'output_schema':{'type':'object'},'max_tokens':1024}
            self.assertEqual(client.post('/api/internal/llm/extract',json=payload).status_code,403)
            result=client.post('/api/internal/llm/extract',json=payload,headers={'x-llm-service-key':'test-service-key'})
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.json(),{'intent':'lead'})
            self.assertEqual(complete.call_args.kwargs['operation'],'extraction')
            self.assertNotIn('temperature',complete.call_args.kwargs)
            bad=client.post('/api/internal/llm/extract',json={**payload,'temperature':1},headers={'x-llm-service-key':'test-service-key'})
            self.assertEqual(bad.status_code,422)
