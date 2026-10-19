"""Active Telegram sales service contracts, without network or real credentials."""
import asyncio
import importlib
import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from lib.repository import InMemoryRepository

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))


class SleyzImportTests(unittest.TestCase):
    def test_active_service_imports_from_repository_root_without_secrets(self):
        env = {**os.environ, "PYTHONPATH": ""}
        for key in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "HUAWEI_MAAS_API_KEY", "HUAWEI_MAAS_MODEL"):
            env.pop(key, None)
        script = "import Sleyz.sales_main; from Sleyz.agents import ingestor,searcher,reporter,closer; from Sleyz.db import client; print(Sleyz.sales_main.app.title)"
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Converza Sales Bot", result.stdout)


class SalesPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from Sleyz.routers import webhook
        self.webhook = webhook
        self.repo = InMemoryRepository()
        self.result = {"org_id": "org-a", "prospect_id": "buyer-1", "tg_chat_id": 42, "text": "Current price?", "biz_conn_id": "connection-1"}

    async def test_draft_exists_before_memory_or_generation_and_ready_after_success(self):
        async def context(*args, **kwargs):
            self.assertEqual(self.repo.drafts[0]["status"], "PENDING_DRAFT")
            self.assertEqual(args[:2], ("org-a", "Current price?"))
            self.assertEqual(kwargs["prospect_id"], "buyer-1")
            return {"identity": {}, "knowledge": [], "products": [], "history": []}
        async def generate(*args, **kwargs):
            self.assertEqual(self.repo.drafts[0]["generation_status"], "running")
            return "The current price is $29."
        with patch.object(self.webhook.db, "get_repository", return_value=self.repo), patch.object(self.webhook.searcher, "build_context", context), patch.object(self.webhook.closer, "generate", generate), patch.object(self.webhook.reporter, "report_hitl", AsyncMock()) as report:
            draft = await self.webhook._process(self.result)
        self.assertEqual(len(self.repo.drafts), 1)
        self.assertEqual(draft["status"], "AWAITING_HITL")
        self.assertEqual(draft["prospect_id"], "buyer-1")
        self.assertEqual(draft["draft_content"], "The current price is $29.")
        report.assert_awaited_once()

    async def test_generation_failure_keeps_retryable_draft_and_sanitized_error(self):
        with patch.object(self.webhook.db, "get_repository", return_value=self.repo), patch.object(self.webhook.searcher, "build_context", AsyncMock(return_value={})), patch.object(self.webhook.closer, "generate", AsyncMock(side_effect=RuntimeError("sensitive buyer text"))), patch.object(self.webhook.reporter, "report_hitl", AsyncMock()) as report:
            draft = await self.webhook._process(self.result)
        self.assertEqual(draft["status"], "PENDING_DRAFT")
        self.assertEqual(draft["generation_status"], "failed")
        self.assertEqual(draft["generation_error"], "RuntimeError")
        report.assert_not_awaited()

    async def test_notification_failure_does_not_erase_ready_generation(self):
        with patch.object(self.webhook.db, "get_repository", return_value=self.repo), patch.object(self.webhook.searcher, "build_context", AsyncMock(return_value={})), patch.object(self.webhook.closer, "generate", AsyncMock(return_value="answer")), patch.object(self.webhook.reporter, "report_hitl", AsyncMock(side_effect=RuntimeError("notification failed"))):
            draft = await self.webhook._process(self.result)
        self.assertEqual(draft["status"], "AWAITING_HITL")
        self.assertEqual(draft["generation_status"], "completed")


class SalesMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_searcher_uses_org_memory_and_recent_prospect_history(self):
        from Sleyz.agents import searcher
        context = {"identity": {"exports": {"brand_passport.md": "identity"}}, "knowledge": [{"content": "fact"}], "products": [{"price": 29}]}
        with patch.object(searcher.db, "get_client", return_value=object()), patch.object(searcher, "MemoryStore") as store, patch.object(searcher.db, "get_history", return_value=[{"role": "assistant", "content": "prior"}]) as history:
            store.return_value.context.return_value = context
            result = await searcher.build_context("org-a", "price?", prospect_id="buyer-1")
        store.return_value.context.assert_called_once_with("org-a", "price?")
        history.assert_called_once_with("org-a", "buyer-1", limit=20)
        self.assertEqual(result["history"], [{"role": "assistant", "content": "prior"}])

    async def test_closer_separates_identity_instructions_evidence_and_history(self):
        from Sleyz.agents import closer
        context = {"identity": {"exports": {"brand_passport.md": "Brand identity", "negative_constraints.md": "Never discount"}}, "knowledge": [{"content": "supporting fact"}], "products": [{"price": 29}], "history": [{"role": "assistant", "content": "prior"}]}
        with patch.object(closer, "complete_text", AsyncMock(return_value="answer")) as complete:
            self.assertEqual(await closer.generate("price?", context, "org-a", "buyer-1"), "answer")
        messages = complete.await_args.args[0]
        self.assertIn("Never discount", messages[0]["content"])
        self.assertIn("supporting fact", messages[1]["content"])
        self.assertEqual(messages[-2], {"role": "assistant", "content": "prior"})
        self.assertEqual(messages[-1], {"role": "user", "content": "price?"})
        self.assertEqual(complete.await_args.kwargs["operation"], "reasoning")


class SalesPublisherTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from Sleyz.agents import reporter
        self.reporter = reporter
        self.repo = InMemoryRepository()
        self.repo.client = object()
        self.draft = await self.repo.create_draft("org-a", "sleyz", "price?", "", prospect_id="buyer-1")
        self.draft = await self.repo.transition_draft("org-a", self.draft["id"], "ready", 1, "ready", edited_content="original")
        self.draft = await self.repo.transition_draft("org-a", self.draft["id"], "edit", self.draft["revision"], "edit", edited_content="authoritative final")

    async def test_publication_ignores_caller_text_and_destination_and_uses_shared_publisher(self):
        target = {"bot_token": "test-token", "chat_id": 42, "business_connection_id": "authoritative-connection"}
        with patch.object(self.reporter.db, "get_repository", return_value=self.repo), patch("services.workflow.publication.load_telegram_target", AsyncMock(return_value=target)) as load, patch("services.workflow.publication.publish_telegram", AsyncMock(return_value={**self.draft, "status": "PUBLISHED"})) as publish, patch.object(self.reporter.db, "log_message") as log, patch.object(self.reporter, "report_done", AsyncMock()):
            result = await self.reporter.send_approved_reply(self.draft["id"], "spoofed", 999, "spoofed", "org-a", "buyer-1")
        self.assertEqual(result["status"], "PUBLISHED")
        self.assertEqual(publish.await_args.kwargs["chat_id"], 42)
        self.assertEqual(publish.await_args.kwargs["business_connection_id"], "authoritative-connection")
        self.assertEqual(publish.await_args.kwargs["repo"], self.repo)
        self.assertNotIn("spoofed", str(publish.await_args))
        self.assertEqual(log.call_args.args[3], "authoritative final")
        load.assert_awaited_once_with(self.repo.client, "org-a", self.draft)

    async def test_missing_destination_preserves_durable_delivery_failure(self):
        with patch.object(self.reporter.db, "get_repository", return_value=self.repo), patch("services.workflow.publication.load_telegram_target", AsyncMock(side_effect=ValueError("Prospect has no configured Telegram destination"))), patch("services.workflow.publication.publish_telegram", AsyncMock()) as publish:
            result = await self.reporter.send_approved_reply(self.draft["id"], "copy", 42, None, "org-a", "buyer-1")
        self.assertEqual(result["status"], "EDITED")
        self.assertEqual(result["delivery_status"], "failed")
        self.assertIn("destination", result["delivery_error"])
        publish.assert_not_awaited()

    async def test_wrong_org_cannot_publish(self):
        with patch.object(self.reporter.db, "get_repository", return_value=self.repo), patch.object(self.reporter, "deliver_telegram_draft", AsyncMock()) as publish:
            with self.assertRaises(KeyError):
                await self.reporter.send_approved_reply(self.draft["id"], "copy", 42, None, "other", "buyer-1")
        publish.assert_not_awaited()


class SalesDatabaseTests(unittest.TestCase):
    def setUp(self):
        from Sleyz.db import client
        self.db = client
        self.query = Mock()
        self.query.select.return_value = self.query
        self.query.eq.return_value = self.query
        self.query.limit.return_value = self.query
        self.query.update.return_value = self.query
        self.query.upsert.return_value = self.query
        self.query.insert.return_value = self.query
        self.query.order.return_value = self.query
        self.client = Mock()
        self.client.table.return_value = self.query

    def test_ambiguous_sales_token_or_business_connection_fails_closed(self):
        self.query.execute.return_value = SimpleNamespace(data=[{"org_id": "a"}, {"org_id": "b"}])
        with patch.object(self.db, "get_client", return_value=self.client):
            self.assertIsNone(self.db.get_org_by_sales_token("shared-token"))
            self.assertIsNone(self.db.get_org_by_business_connection("ambiguous"))
        self.query.limit.assert_called_with(2)

    def test_prospect_upsert_uses_evidenced_org_platform_identity_and_route(self):
        self.query.execute.return_value = SimpleNamespace(data=[{"id": "buyer", "conversation_id": "conversation"}])
        with patch.object(self.db, "get_client", return_value=self.client):
            result = self.db.upsert_prospect("org-a", 11, "name", "First", 42, business_connection_id="biz-1")
        self.assertEqual(result["id"], "buyer")
        payload = self.query.upsert.call_args.args[0]
        self.assertEqual(payload, {"org_id": "org-a", "platform": "telegram", "external_id": "11", "metadata": {"username": "name", "first_name": "First"}, "tg_chat_id": 42, "business_connection_id": "biz-1"})
        self.assertEqual(self.query.upsert.call_args.kwargs["on_conflict"], "org_id,platform,external_id")

    def test_latest_history_is_filtered_by_organization_and_prospect_then_reversed(self):
        self.query.execute.return_value = SimpleNamespace(data=[{"role": "assistant", "content": "latest"}, {"role": "user", "content": "previous"}])
        with patch.object(self.db, "get_client", return_value=self.client):
            rows = self.db.get_history("org-a", "buyer", limit=20)
        self.assertEqual(rows, [{"role": "user", "content": "previous"}, {"role": "assistant", "content": "latest"}])
        self.query.eq.assert_any_call("org_id", "org-a")
        self.query.eq.assert_any_call("prospect_id", "buyer")
        self.query.order.assert_called_once_with("created_at", desc=True)

    def test_log_rejects_prospect_from_another_tenant(self):
        with patch.object(self.db, "get_prospect", return_value=None), patch.object(self.db, "get_client", return_value=self.client):
            with self.assertRaises(KeyError):
                self.db.log_message("org-a", "other-buyer", "user", "private", "human")
        self.query.insert.assert_not_called()


class SalesWebhookTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from Sleyz.sales_main import app
        from Sleyz.routers import webhook
        self.webhook = webhook
        self.client = TestClient(app)
        self.message = {"message": {"message_id": 7, "date": 1000, "text": "hello", "from": {"id": 11, "is_bot": False}, "chat": {"id": 42, "type": "private"}}}

    def tearDown(self):
        self.client.close()

    def test_authentication_required_before_enqueueing(self):
        with patch.dict(os.environ, {"SALES_WEBHOOK_SECRET": "test-secret"}), patch.object(self.webhook.db, "get_org_by_sales_token", return_value={"org_id":"org-a"}), patch.object(self.webhook, "accept_inbound", AsyncMock()) as accept:
            self.assertEqual(self.client.post("/webhook", json=self.message).status_code, 403)
            accept.assert_not_awaited()
            response = self.client.post("/webhook", headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"}, json=self.message)
        self.assertEqual(response.status_code, 200)
        accept.assert_awaited_once()
        self.assertEqual(accept.await_args.args[0]["customer_id"], "11")
        self.assertEqual(accept.await_args.args[0]["tg_chat_id"], 42)

    def test_bot_and_group_messages_do_not_become_buyer_conversations(self):
        with patch.dict(os.environ, {"SALES_WEBHOOK_SECRET": "test-secret"}), patch.object(self.webhook, "handle_direct_message", AsyncMock()) as handler:
            self.message["message"]["from"]["is_bot"] = True
            self.client.post("/webhook", headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"}, json=self.message)
            self.message["message"]["from"]["is_bot"] = False
            self.message["message"]["chat"]["type"] = "group"
            self.client.post("/webhook", headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"}, json=self.message)
        handler.assert_not_awaited()


class SalesDirectDestinationTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_direct_route_does_not_fall_back_to_business_connection(self):
        from Sleyz.agents import reporter
        repo = InMemoryRepository()
        query = Mock()
        for method in ("select", "eq", "limit"):
            getattr(query, method).return_value = query
        query.execute.side_effect = [SimpleNamespace(data=[{"id":"buyer","tg_chat_id":42,"business_connection_id":None}]), SimpleNamespace(data=[{"org_id":"org-a","bot_token":"test","business_connection_id":"business-mode"}])]
        repo.client = Mock()
        repo.client.table.return_value = query
        draft = await repo.create_draft("org-a", "sleyz", "message", "", prospect_id="buyer")
        draft = await repo.transition_draft("org-a", draft["id"], "ready", 1, "ready", edited_content="answer")
        draft = await repo.transition_draft("org-a", draft["id"], "approve", draft["revision"], "approve")
        with patch.object(reporter.db, "get_repository", return_value=repo), patch("services.workflow.publication.publish_telegram", AsyncMock(return_value=draft)) as publish:
            await reporter.send_approved_reply(draft["id"], "untrusted", 999, "untrusted", "org-a", "buyer")
        self.assertIsNone(publish.await_args.kwargs["business_connection_id"])
