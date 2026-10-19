import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


class Store:
    def identity(self, org_id):
        return {"org_id": org_id, "revision": 2, "passport": {}, "exports": {"voice_rules.md": "Warm."}}

    def products(self, org_id):
        return [{"id": "product-1", "org_id": org_id, "price": "12.50", "currency": "USD"}]

    def create_product(self, org_id, payload):
        return {"id": "product-1", "org_id": org_id, **payload}

    def search(self, org_id, query, **kwargs):
        return [{"source_id": "source-1", "org_id": org_id, "content": query}]


class MemoryRoutesTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        main.app.dependency_overrides[main.require_authenticated_user] = lambda: main.AuthContext(user_id="owner")
        self.owner = patch.object(main, "_assert_user_owns_org")
        self.assert_owner = self.owner.start()
        self.store_patch = patch.object(main, "get_memory_store", return_value=Store(), create=True)
        self.store_patch.start()

    def tearDown(self):
        main.app.dependency_overrides.clear()
        self.owner.stop()
        self.store_patch.stop()

    def test_identity_checks_owner_and_exports_named_document(self):
        result = self.client.get("/api/memory/org-1/identity")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["org_id"], "org-1")
        self.assert_owner.assert_called_with("owner", "org-1")
        exported = self.client.get("/api/memory/org-1/identity/export/voice_rules.md")
        self.assertEqual(exported.text, "Warm.")
        self.assertIn("voice_rules.md", exported.headers["content-disposition"])

    def test_products_validate_prices_before_write(self):
        result = self.client.post("/api/memory/org-1/products", json={"name": "Pilot", "price": "12.50", "currency": "USD"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["price"], "12.50")
        for price in ("-1", "NaN", "Infinity"):
            invalid = self.client.post("/api/memory/org-1/products", json={"name": "Pilot", "price": price, "currency": "USD"})
            self.assertEqual(invalid.status_code, 422)

    def test_search_and_exports_are_org_scoped(self):
        result = self.client.get("/api/memory/org-1/search", params={"q": "refund"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["results"][0]["content"], "refund")
        self.assertEqual(self.client.get("/api/memory/org-1/identity/export/not-a-document").status_code, 404)

    def test_receipt_route_is_not_exposed_to_user_proxy(self):
        result = self.client.post("/api/internal/drafts/draft-1/receipt", json={})
        self.assertIn(result.status_code, (401, 403))
