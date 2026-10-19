"""Route contracts over the real in-memory state machine; no remote services."""
import asyncio
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from lib.repository import InMemoryRepository
from lib.workflow_routes import create_workflow_router


async def authenticate(authorization: str | None = Header(None), x_supabase_access_token: str | None = None, access_token: str | None = None):
    if authorization != "Bearer user-a":
        raise HTTPException(401, "Authentication required")
    return SimpleNamespace(user_id="user-a")


def owner(user_id, org_id):
    if (user_id, org_id) != ("user-a", "org-a"):
        raise HTTPException(403, "Organization access denied")


class WorkflowRouteTests(unittest.TestCase):
    def setUp(self):
        self.repo = InMemoryRepository()
        async def seed():
            draft = await self.repo.create_draft("org-a", "sleyz", "Too expensive", "", prospect_id="buyer-1")
            return await self.repo.transition_draft("org-a", draft["id"], "ready", 1, "ready", edited_content="Current answer")
        self.draft = asyncio.run(seed())
        self.id = self.draft["id"]
        self.router = create_workflow_router(lambda: self.repo, authenticate, owner)
        self.app = FastAPI()
        self.app.include_router(self.router)
        self.client = TestClient(self.app)
        self.headers = {"authorization": "Bearer user-a", "idempotency-key": "decision-1"}

    def tearDown(self):
        self.client.close()

    def decision(self, action, revision=2, key="decision-1", **body):
        return self.client.post(f"/api/hitl/{self.id}/{action}", headers={**self.headers, "idempotency-key": key}, json={"expected_revision": revision, **body})

    def publisher(self, route, revision, key, **body):
        return self.client.post(f"/api/internal/drafts/{self.id}/{route}", headers={"x-publisher-key": "publisher-test", "idempotency-key": key}, json={"org_id": "org-a", "expected_revision": revision, **body})

    def test_requires_authentication_and_organization_ownership(self):
        self.assertEqual(self.client.get(f"/api/drafts/{self.id}").status_code, 401)
        self.assertEqual(self.client.get("/api/drafts?org_id=org-b", headers=self.headers).status_code, 403)
        self.assertEqual(self.client.get("/api/drafts/missing", headers=self.headers).status_code, 404)
        self.assertEqual(self.client.get(f"/api/drafts/{self.id}", headers=self.headers).json()["status"], "AWAITING_HITL")
        other = asyncio.run(self.repo.create_draft("org-b", "sleyz", "private", ""))
        self.assertEqual(self.client.get(f"/api/drafts/{other['id']}", headers=self.headers).status_code, 403)

    def test_revision_and_idempotency_required_and_conflicts_are_409(self):
        url = f"/api/hitl/{self.id}/approve"
        self.assertEqual(self.client.post(url, headers=self.headers, json={}).status_code, 422)
        self.assertEqual(self.client.post(url, headers={"authorization": "Bearer user-a"}, json={"expected_revision": 2}).status_code, 422)
        self.assertEqual(self.decision("approve", revision=1).status_code, 409)
        approved = self.decision("approve")
        self.assertEqual(approved.status_code, 200)
        self.assertEqual((approved.json()["status"], approved.json()["revision"]), ("APPROVED", 3))
        duplicate = self.decision("approve")
        self.assertEqual(duplicate.json(), approved.json())
        self.assertEqual(self.decision("reject", revision=3, key="another").status_code, 409)
        self.assertEqual(self.decision("edit", revision=2, final_content="changed").status_code, 409)

    def test_empty_edit_fails_and_hydration_keeps_authoritative_content(self):
        self.assertEqual(self.decision("edit", final_content="  ").status_code, 422)
        edited = self.decision("edit", final_content="Exact final copy")
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.json()["status"], "EDITED")
        response = self.client.get("/api/drafts?org_id=org-a", headers=self.headers)
        self.assertEqual(response.json()["drafts"][0]["final_content"], "Exact final copy")

    def test_only_service_can_receipt_and_receipt_needs_matching_attempt(self):
        self.assertEqual(self.decision("approve").status_code, 200)
        url = f"/api/internal/drafts/{self.id}/receipt"
        body = {"org_id": "org-a", "expected_revision": 3, "receipt": {"channel": "telegram", "message_id": 7}}
        with patch.dict(os.environ, {"PUBLISHER_API_KEY": "publisher-test"}):
            self.assertEqual(self.client.post(url, headers=self.headers, json=body).status_code, 403)
            self.assertEqual(self.client.post(url, headers={"x-publisher-key": "wrong", "idempotency-key": "wrong"}, json=body).status_code, 403)
            self.assertEqual(self.publisher("receipt", 3, "no-attempt", receipt=body["receipt"]).status_code, 409)
            began = self.publisher("delivery", 3, "begin", action="begin_delivery", receipt={"attempt_id": "attempt-1"})
            self.assertEqual(began.status_code, 200)
            bad = self.publisher("receipt", 4, "bad", receipt={"channel": "telegram", "message_id": 7, "attempt_id": "other"})
            self.assertEqual(bad.status_code, 409)
            sent = self.publisher("receipt", 4, "receipt", receipt={"channel": "telegram", "message_id": 7, "attempt_id": "attempt-1"})
            self.assertEqual(sent.status_code, 200)
            self.assertEqual(sent.json()["status"], "PUBLISHED")
            self.assertIsNone(sent.json()["resolved_at"])
            duplicate = self.publisher("receipt", 4, "receipt", receipt={"channel": "telegram", "message_id": 7, "attempt_id": "attempt-1"})
            self.assertEqual(duplicate.json(), sent.json())
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.client.post(url, headers={"x-publisher-key": "publisher-test", "idempotency-key": "missing-config"}, json=body).status_code, 403)

    def test_resolution_requires_successful_delivery_and_buyer_source(self):
        url = f"/api/drafts/{self.id}/resolve"
        self.assertEqual(self.client.post(url, headers=self.headers, json={"expected_revision": 2}).status_code, 409)
        self.decision("approve")
        with patch.dict(os.environ, {"PUBLISHER_API_KEY": "publisher-test"}):
            self.publisher("delivery", 3, "begin", receipt={"attempt_id": "attempt-1"})
            self.publisher("receipt", 4, "receipt", receipt={"channel": "telegram", "message_id": 7, "attempt_id": "attempt-1"})
        response = self.client.post(url, headers={**self.headers, "idempotency-key": "resolve"}, json={"expected_revision": 5})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["resolved_at"])
        self.assertEqual(response.json()["status"], "PUBLISHED")
        self.repo.drafts[0]["agent_slug"] = "milo"
        self.assertEqual(self.client.post(url, headers={**self.headers, "idempotency-key": "resolve-milo"}, json={"expected_revision": 6}).status_code, 422)


    def test_owner_generated_copy_without_prospect_cannot_be_resolved(self):
        self.repo.drafts[0].update(status="PUBLISHED", delivered_at="2026-10-19T00:00:00+00:00", delivery_receipt={"channel": "telegram", "message_id": 7}, prospect_id=None)
        response = self.client.post(f"/api/drafts/{self.id}/resolve", headers=self.headers, json={"expected_revision": 2})
        self.assertEqual(response.status_code, 422)
        self.assertIsNone(self.repo.drafts[0]["resolved_at"])


class WorkflowStreamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.repo = InMemoryRepository()
        await self.repo.insert_squad_message("org-a", "owner", "first")
        await self.repo.insert_squad_message("org-b", "owner", "private")
        await self.repo.insert_squad_message("org-a", "milo", "second")
        self.router = create_workflow_router(lambda: self.repo, authenticate, owner)
        self.endpoint = next(route.endpoint for route in self.router.routes if route.path == "/api/squad/stream")

    async def collect(self, cursor=None, last_event_id=None):
        request = SimpleNamespace(is_disconnected=AsyncMock(side_effect=[False, True]), headers={}, query_params={})
        response = await self.endpoint(request, org_id="org-a", cursor=cursor, last_event_id=last_event_id, auth=SimpleNamespace(user_id="user-a"))
        self.assertEqual(response.media_type, "text/event-stream")
        with patch("lib.workflow_routes.asyncio.sleep", AsyncMock()):
            return [part async for part in response.body_iterator]

    async def test_initial_snapshot_is_scoped_and_has_sse_id(self):
        chunks = await self.collect()
        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0].startswith("id: 2\n"))
        event = json.loads(chunks[0].split("data: ", 1)[1])
        self.assertEqual(event["type"], "snapshot")
        self.assertEqual(event["schema_version"], 1)
        self.assertEqual([row["content"] for row in event["messages"]], ["first", "second"])
        self.assertNotIn("private", chunks[0])

    async def test_resume_replays_only_new_events_and_header_takes_precedence(self):
        chunks = await self.collect(cursor=0, last_event_id="1")
        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0].startswith("id: 2\n"))
        event = json.loads(chunks[0].split("data: ", 1)[1])
        self.assertEqual(event["type"], "squad_message")
        self.assertEqual(event["row"]["content"], "second")
        self.assertNotIn("snapshot", chunks[0])

    async def test_future_and_expired_gap_cursor_get_fresh_snapshot(self):
        self.assertIn('"type": "snapshot"', (await self.collect(cursor=99))[0])
        self.repo.events = [event for event in self.repo.events if event["org_id"] != "org-a" or event["id"] > 1]
        self.assertIn('"type": "snapshot"', (await self.collect(cursor=0))[0])

    async def test_expired_cursor_with_empty_retention_gets_snapshot(self):
        snapshot = await self.repo.snapshot("org-a")
        self.repo.snapshot = AsyncMock(return_value=snapshot)
        self.repo.read_events = AsyncMock(return_value=[])
        chunks = await self.collect(cursor=1)
        self.assertEqual(len(chunks), 1)
        self.assertIn('"type": "snapshot"', chunks[0])

    async def test_malformed_last_event_id_rejected(self):
        with self.assertRaises(HTTPException) as error:
            await self.collect(last_event_id="not-a-number")
        self.assertEqual(error.exception.status_code, 422)


class WorkflowStreamLifetimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_expired_authentication_stops_stream_with_error(self):
        repo = InMemoryRepository()
        refresh_auth = AsyncMock(side_effect=HTTPException(401, "Token expired"))
        router = create_workflow_router(lambda: repo, refresh_auth, owner)
        endpoint = next(route.endpoint for route in router.routes if route.path == "/api/squad/stream")
        request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False), headers={"authorization": "Bearer expired"}, query_params={})
        response = await endpoint(request, org_id="org-a", cursor=None, last_event_id=None, auth=SimpleNamespace(user_id="user-a"))
        clock = SimpleNamespace(monotonic=iter([0, 0, 61]).__next__)
        with patch("lib.workflow_routes.time", clock):
            chunks = [part async for part in response.body_iterator]
        self.assertEqual(len(chunks), 2)
        self.assertIn('"type": "snapshot"', chunks[0])
        self.assertIn('"type":"error"', chunks[1])
        refresh_auth.assert_awaited_once()

    async def test_heartbeat_is_comment_and_disconnect_ends_iterator(self):
        repo = InMemoryRepository()
        router = create_workflow_router(lambda: repo, authenticate, owner)
        endpoint = next(route.endpoint for route in router.routes if route.path == "/api/squad/stream")
        request = SimpleNamespace(is_disconnected=AsyncMock(side_effect=[False, True]), headers={}, query_params={})
        response = await endpoint(request, org_id="org-a", cursor=0, last_event_id=None, auth=SimpleNamespace(user_id="user-a"))
        clock = SimpleNamespace(monotonic=iter([0, 0, 16, 16, 16]).__next__)
        with patch("lib.workflow_routes.time", clock), patch("lib.workflow_routes.asyncio.sleep", AsyncMock()):
            chunks = [part async for part in response.body_iterator]
        self.assertEqual(chunks, [": heartbeat\n\n"])
        self.assertEqual(request.is_disconnected.await_count, 2)


class MemoryRouteSecurityTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import Mock
        from lib.memory_routes import create_memory_router
        self.store = Mock()
        self.store.identity.return_value = {"passport": {"brand_name": "Brand"}, "exports": {"brand_passport.md": "# Brand"}}
        self.store.products.return_value = []
        self.store.create_product.return_value = {"id": "product-1", "org_id": "org-a"}
        self.store.create_knowledge.return_value = {"id": "knowledge-1", "org_id": "org-a"}
        app = FastAPI()
        app.include_router(create_memory_router(lambda: self.store, authenticate, owner))
        self.client = TestClient(app)
        self.headers = {"authorization": "Bearer user-a"}

    def tearDown(self):
        self.client.close()

    def test_all_store_access_requires_owner_and_export_filename_is_allowlisted(self):
        self.assertEqual(self.client.get("/api/memory/org-a/identity").status_code, 401)
        self.assertEqual(self.client.get("/api/memory/org-b/identity", headers=self.headers).status_code, 403)
        self.store.identity.assert_not_called()
        self.assertEqual(self.client.get("/api/memory/org-a/identity/export/secret.md", headers=self.headers).status_code, 404)
        exported = self.client.get("/api/memory/org-a/identity/export/brand_passport.md", headers=self.headers)
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(exported.text, "# Brand")
        self.assertIn('filename="brand_passport.md"', exported.headers["content-disposition"])
        self.store.identity.assert_called_once_with("org-a")

    def test_product_validation_and_tenant_fields_cannot_be_injected(self):
        valid = {"name": "Starter", "price": "29.95", "currency": "USD"}
        for changes in ({"org_id": "org-b"}, {"price": "NaN"}, {"price": -1}, {"currency": "usd"}):
            response = self.client.post("/api/memory/org-a/products", headers=self.headers, json={**valid, **changes})
            self.assertEqual(response.status_code, 422)
        self.store.create_product.assert_not_called()
        self.assertEqual(self.client.post("/api/memory/org-a/products", headers=self.headers, json=valid).status_code, 200)
        self.assertEqual(self.store.create_product.call_args.args[0], "org-a")

    def test_human_knowledge_cannot_inject_objection_and_search_is_bounded(self):
        response = self.client.post("/api/memory/org-a/knowledge", headers=self.headers, json={"kind": "objection", "title": "fake", "content": "fake buyer"})
        self.assertEqual(response.status_code, 422)
        self.store.create_knowledge.assert_not_called()
        self.assertEqual(self.client.get("/api/memory/org-a/search?q=price&limit=1000", headers=self.headers).status_code, 422)
        self.store.search.assert_not_called()
