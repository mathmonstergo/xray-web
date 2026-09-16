from tests.support import node

from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import config
from core import xray_manager as xm
from core.persistence import atomic_write_bytes
from core.routing_manager import RoutingManager
from core.store import DataStore


class FakeRuntime:
    def __init__(self, content):
        self.content = content
        self.active = True
        self.fail_write = False
        self.fail_validate = False
        self.restart_failures = 0
        self.validated = []

    def read(self): return self.content
    def is_active(self): return self.active
    def backup(self, content): self.backup_content = content
    def validate(self, candidate):
        if self.fail_validate:
            raise RuntimeError("synthetic syntax failure")
        self.validated.append(candidate)
        time.sleep(0.005)
    def write(self, content):
        if self.fail_write:
            raise OSError("synthetic write failure")
        self.content = content
    def restart(self):
        if self.restart_failures:
            self.restart_failures -= 1
            self.active = False
            raise RuntimeError("synthetic restart failure")
        self.active = True
    def restore(self, content): self.content = content
    def stop(self): self.active = False


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        config.SOCKS_PORT, config.HTTP_PROXY_PORT, config.HTTP_ROUTING_PORT = 20170, 20171, 20172
        self.store = DataStore(self.directory / "store.json", bootstrap=False)
        self.routing = RoutingManager(self.directory / "rules.json")
        self.routing.rules = []
        self.routing.save()
        self.first = self.store.add_node(node())
        self.second = self.store.add_node(node("192.0.2.20", "Second"))
        self.store.set_active_node(self.first["id"])
        original = {"outbounds": [self.first["outbound"]], "log": {"loglevel": "none"}}
        self.original = json.dumps(original).encode()
        self.runtime = FakeRuntime(self.original)
        self.stack.enter_context(patch.object(xm, "store", self.store))
        self.stack.enter_context(patch.object(xm, "routing_manager", self.routing))
        self.stack.enter_context(patch.object(xm.XrayManager, "_runtime", self.runtime))

    def test_ports_and_node_changes_cannot_overwrite_each_other(self):
        barrier = threading.Barrier(2)
        failures = []
        def run(operation):
            try:
                barrier.wait(timeout=2)
                operation()
            except Exception as exc:
                failures.append(exc)
        threads = [threading.Thread(target=run, args=(operation,)) for operation in (
            lambda: xm.XrayManager.switch_node(self.second["id"]),
            lambda: xm.XrayManager.apply_ports(21170, 21171, 21172),
        )]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=3)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])
        running = json.loads(self.runtime.content)
        self.assertEqual([ib["port"] for ib in running["inbounds"][:3]], [21170, 21171, 21172])
        self.assertEqual(running["outbounds"][0]["settings"]["vnext"][0]["address"], "192.0.2.20")
        self.assertEqual(self.store.get_ports()["http"], 21171)
        self.assertEqual(self.store.get_active_node()["id"], self.second["id"])

    def test_validation_failure_never_persists_rule(self):
        before = self.routing.file_path.read_bytes()
        self.runtime.fail_validate = True
        with self.assertRaises(RuntimeError):
            xm.XrayManager.change_routing(lambda rules: rules.set_category_lines("block", ["geosite:fixture-missing"]))
        self.assertEqual(self.routing.file_path.read_bytes(), before)
        self.assertEqual(self.routing.get_rules(), [])
        self.assertEqual(self.runtime.content, self.original)

    def test_invalid_cidr_never_persists_rule(self):
        before = self.routing.file_path.read_bytes()
        with self.assertRaises(ValueError):
            xm.XrayManager.change_routing(lambda rules: rules.set_category_lines("direct", ["192.0.2.0/99"]))
        self.assertEqual(self.routing.file_path.read_bytes(), before)

    def test_failed_write_keeps_core_and_store(self):
        before = self.store.file_path.read_bytes()
        self.runtime.fail_write = True
        with self.assertRaisesRegex(RuntimeError, "已恢复原状态"):
            xm.XrayManager.apply_ports(21170, 21171, 21172)
        self.assertEqual(self.runtime.content, self.original)
        self.assertEqual(self.store.file_path.read_bytes(), before)
        self.assertEqual(self.store.get_ports()["http"], 20171)

    def test_write_timeout_after_replacement_is_reconciled(self):
        def uncertain_write(content):
            self.runtime.content = content
            raise RuntimeError("synthetic timeout after rename")
        with patch.object(self.runtime, "write", side_effect=uncertain_write):
            with self.assertRaisesRegex(RuntimeError, "已恢复原状态"):
                xm.XrayManager.apply_ports(21170, 21171, 21172)
        self.assertEqual(self.runtime.content, self.original)
        self.assertEqual(self.store.get_ports()["http"], 20171)

    def test_restart_failure_restores_old_core_and_rules(self):
        before = self.routing.file_path.read_bytes()
        self.runtime.restart_failures = 1
        with self.assertRaisesRegex(RuntimeError, "已恢复原状态"):
            xm.XrayManager.change_routing(lambda rules: rules.set_category_lines("block", ["domain:example.net"]))
        self.assertEqual(self.runtime.content, self.original)
        self.assertTrue(self.runtime.active)
        self.assertEqual(self.routing.file_path.read_bytes(), before)

    def test_failure_after_first_json_commit_restores_both_files(self):
        before = self.store.file_path.read_bytes()
        def edit(candidate, rules):
            candidate.set_ports(21170, 21171, 21172)
            rules.set_category_lines("block", ["domain:example.net"])
        with patch.object(self.routing, "commit", side_effect=OSError("synthetic persistence failure")):
            with self.assertRaises(RuntimeError):
                xm.XrayManager._apply_change(edit)
        self.assertEqual(self.store.file_path.read_bytes(), before)
        self.assertEqual(self.store.get_ports()["http"], 20171)
        self.assertEqual(config.HTTP_PROXY_PORT, 20171)
        self.assertEqual(self.runtime.content, self.original)

    def test_failed_recovery_is_reported(self):
        self.runtime.restart_failures = 2
        with self.assertRaisesRegex(RuntimeError, "核心恢复失败"):
            xm.XrayManager.switch_node(self.second["id"])

    def test_switch_preserves_real_ping(self):
        self.store.update_node_delay(self.second["id"], 250)
        xm.XrayManager.switch_node(self.second["id"])
        self.assertEqual(self.store.get_node(self.second["id"])["last_delay"], 250)

    def test_missing_config_gets_safe_complete_outbounds(self):
        self.runtime.content = None
        xm.XrayManager.switch_node(self.second["id"])
        running = json.loads(self.runtime.content)
        self.assertEqual({ob["tag"] for ob in running["outbounds"]}, {"proxy", "direct", "block"})
        self.assertTrue(all(ib["listen"] == "127.0.0.1" for ib in running["inbounds"]))

    def test_routing_order_is_independent_of_edit_order(self):
        self.routing.set_category_lines("block", ["domain:ads.example.net"])
        self.routing.set_category_lines("direct", ["domain:example.net", "domain:unrelated.example"])
        rules = self.routing.build_xray_routing_rules("", "")
        domain_rules = [r for r in rules if "domain" in r]
        self.assertEqual([r["outboundTag"] for r in domain_rules], ["block", "direct"])

    def test_atomic_write_failure_keeps_old_file(self):
        path = self.directory / "atomic.json"
        path.write_bytes(b"original")
        with patch("core.persistence.os.replace", side_effect=OSError("synthetic rename failure")):
            with self.assertRaises(OSError):
                atomic_write_bytes(path, b"candidate")
        self.assertEqual(path.read_bytes(), b"original")
        self.assertEqual(list(self.directory.glob(".atomic.json.*")), [])
