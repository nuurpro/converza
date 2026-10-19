import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


def load_file(name, relative):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TelegramOwnershipTests(unittest.IsolatedAsyncioTestCase):
    def load_callback(self):
        db = ModuleType('db.client')
        self.sb = MagicMock()
        self.answer = AsyncMock()
        self.decide = AsyncMock()
        db.sb = self.sb
        db.get_org_by_group = lambda _: {'org_id':'owned','owner_tg_id':7}
        for name in ('get_org_by_owner','get_connection_by_org'):
            setattr(db,name,MagicMock())
        db.send_telegram = AsyncMock()
        db.answer_callback = self.answer
        manager = ModuleType('agents.manager')
        manager.MANAGER_BOT_TOKEN = 'test'
        agents = ModuleType('agents')
        agents.manager = manager
        adapter = ModuleType('workflow_adapter')
        adapter.decide_and_publish = self.decide
        with patch.dict(sys.modules, {'db.client':db,'agents':agents,'agents.manager':manager,'workflow_adapter':adapter}):
            return load_file('callback_under_test','manager/routers/webhook.py')

    async def test_another_group_member_cannot_decide_owner_draft(self):
        module = self.load_callback()
        await module._process_callback({'id':'cb','data':'approve:draft:2',
            'from':{'id':9},'message':{'chat':{'id':42}}})
        self.sb.table.assert_not_called()
        self.decide.assert_not_awaited()
        self.assertIn('owner',self.answer.call_args.args[2])

    async def test_owner_cannot_decide_draft_from_another_org(self):
        module = self.load_callback()
        query = self.sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value
        query.execute.return_value = SimpleNamespace(data=[])
        await module._process_callback({'id':'cb','data':'approve:draft:2',
            'from':{'id':7},'message':{'chat':{'id':42}}})
        self.decide.assert_not_awaited()
        self.assertIn('workspace',self.answer.call_args.args[2])


class ManagerPublicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_destination_is_loaded_from_scoped_prospect_and_configuration_failure_is_durable(self):
        from lib.repository import InMemoryRepository
        module = load_file('adapter_under_test','manager/workflow_adapter.py')
        repo = InMemoryRepository()
        draft = await repo.create_draft('a','sleyz','Buyer concern','',prospect_id='buyer')
        draft = await repo.transition_draft('a',draft['id'],'ready',1,'ready',edited_content='Answer')
        client = MagicMock()
        repo.client = client
        query = client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value
        query.execute.return_value = SimpleNamespace(data=[{'tg_chat_id':42}])
        client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(data=[])
        with patch.object(module,'SupabaseRepository',return_value=repo):
            result = await module.decide_and_publish(client=client,conn={'org_id':'a'},draft_id=draft['id'],
                action='approve',revision=draft['revision'],key='decision')
        self.assertEqual(result['status'],'APPROVED')
        self.assertEqual(result['delivery_status'],'failed')
        self.assertIn('token',result['delivery_error'])
