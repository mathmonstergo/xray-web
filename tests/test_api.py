from tests.support import node

from contextlib import ExitStack
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import main
from core import xray_manager as xm
from core.routing_manager import RoutingManager
from core.store import DataStore
from tests.test_configuration import FakeRuntime


@unittest.skipUnless(importlib.util.find_spec("httpx"), "Install requirements-dev.txt for API tests")
class APITests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.store = DataStore(root / "store.json", bootstrap=False)
        self.rules = RoutingManager(root / "rules.json")
        self.rules.rules = []
        self.rules.save()
        self.runtime = FakeRuntime(b"{}")
        for module in (main, xm):
            self.stack.enter_context(patch.object(module, "store", self.store))
            self.stack.enter_context(patch.object(module, "routing_manager", self.rules))
        self.stack.enter_context(patch.object(xm.XrayManager, "_runtime", self.runtime))
        self.client = self.stack.enter_context(TestClient(main.app, base_url="http://127.0.0.1:2017"))

    def test_health_and_import_work_locally(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        result = self.client.post("/api/nodes/import", json={"text": node()["raw_link"]})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(len(self.client.get("/api/nodes").json()["nodes"]), 1)

    def test_app_rejects_untrusted_host_and_cross_origin(self):
        self.assertEqual(self.client.get("/api/nodes", headers={"Host": "untrusted.example"}).status_code, 400)
        self.assertEqual(self.client.post("/api/nodes/import", json={"text": node()["raw_link"]}, headers={"Origin": "https://untrusted.example"}).status_code, 403)
        self.assertEqual(self.store.get_nodes(), [])

    def test_invalid_rule_does_not_change_persisted_rules(self):
        before = self.rules.file_path.read_bytes()
        result = self.client.put("/api/routing/categories", json={"direct": ["192.0.2.0/99"]})
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.rules.file_path.read_bytes(), before)

    def test_invalid_action_is_rejected_by_schema(self):
        result = self.client.post("/api/routing/rules", json={"type": "domain", "values": ["example.net"], "action": "unknown"})
        self.assertEqual(result.status_code, 422)

    def test_missing_rule_preserves_404(self):
        result = self.client.delete("/api/routing/rules/missing")
        self.assertEqual(result.status_code, 404)

    def test_partial_subscription_update_preserves_existing_nodes(self):
        subscription = self.store.add_subscription("Fixture", "https://subscription.example/fixture")
        self.store.add_node(node(), subscription["id"])
        before = self.store.file_path.read_bytes()
        with patch.object(main.SubscriptionManager, "fetch_subscription", return_value=node()["raw_link"] + "\nss://bad"):
            response = self.client.post(f"/api/subscriptions/{subscription['id']}/update")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.store.file_path.read_bytes(), before)

    def test_explicit_empty_batch_does_not_test_all_nodes(self):
        self.store.add_node(node())
        with patch.object(main.XrayManager, "speed_test_single_node") as test:
            response = self.client.post("/api/nodes/speed-test-batch?stream=false", json={"node_ids": []})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["tested"], 0)
        test.assert_not_called()

    def test_reimporting_same_subscription_does_not_duplicate_nodes(self):
        reality_link_1 = "vless://11111111-1111-4111-8111-111111111111@192.0.2.10:443?encryption=none&security=reality&pbk=xN2pTxbx0RR9YHayUL9madREQuc8v2UtBePPTxFO8ig&sid=1111&sni=example.com#Node1"
        reality_link_2 = "vless://11111111-1111-4111-8111-111111111111@192.0.2.10:443?encryption=none&security=reality&pbk=xN2pTxbx0RR9YHayUL9madREQuc8v2UtBePPTxFO8ig&sid=2222&sni=example.com#Node1"

        with patch.object(main.SubscriptionManager, "fetch_subscription", return_value=reality_link_1):
            res1 = self.client.post("/api/nodes/import", json={"text": "https://sub.example/link"})
            self.assertEqual(res1.status_code, 200)

        self.assertEqual(len(self.store.get_subscriptions()), 1)
        self.assertEqual(len(self.store.get_nodes()), 1)
        first_id = self.store.get_nodes()[0]["id"]

        with patch.object(main.SubscriptionManager, "fetch_subscription", return_value=reality_link_2):
            res2 = self.client.post("/api/nodes/import", json={"text": "https://sub.example/link"})
            self.assertEqual(res2.status_code, 200)

        self.assertEqual(len(self.store.get_subscriptions()), 1)
        self.assertEqual(len(self.store.get_nodes()), 1)
        self.assertEqual(self.store.get_nodes()[0]["id"], first_id)
        self.assertEqual(
            self.store.get_nodes()[0]["outbound"]["streamSettings"]["realitySettings"]["shortId"],
            "2222"
        )
