import json
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

import config
from core.parser import ProtocolParser
from core.persistence import atomic_write_json, synchronized


def node_signature(node):
    """Credentials and transport settings distinguish nodes sharing an endpoint."""
    outbound = deepcopy(node.get("outbound", {}))
    outbound.pop("tag", None)
    stream = outbound.get("streamSettings")
    if isinstance(stream, dict):
        reality = stream.get("realitySettings")
        if isinstance(reality, dict):
            reality.pop("shortId", None)
    return (
        node.get("address", "").strip().lower(),
        int(node.get("port", 0)),
        node.get("protocol", "").strip().lower(),
        json.dumps(outbound, sort_keys=True, separators=(",", ":")),
    )


class DataStore:
    def __init__(self, file_path: Optional[Path] = None, *, bootstrap: bool = True):
        self.file_path = Path(file_path or config.STORE_FILE)
        self._lock = threading.RLock()
        self._memory_only = False
        self.nodes: List[Dict[str, Any]] = []
        self.subscriptions: List[Dict[str, Any]] = []
        self.routing_mode = "bypass_cn"
        self.load()
        if bootstrap:
            self.bootstrap_from_current_config()

    @synchronized
    def load(self):
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"无法读取节点数据，请检查或恢复文件：{self.file_path}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("nodes", []), list) or not isinstance(data.get("subscriptions", []), list):
            raise ValueError(f"节点数据结构无效：{self.file_path}")
        self.nodes = data.get("nodes", [])
        self.subscriptions = data.get("subscriptions", [])
        self.routing_mode = data.get("routing_mode", "bypass_cn")
        self.ports = data.get("ports", {
            "socks": config.SOCKS_PORT,
            "http": config.HTTP_PROXY_PORT,
            "routing": config.HTTP_ROUTING_PORT
        })
        config.SOCKS_PORT = int(self.ports.get("socks", config.SOCKS_PORT))
        config.HTTP_PROXY_PORT = int(self.ports.get("http", config.HTTP_PROXY_PORT))
        config.HTTP_ROUTING_PORT = int(self.ports.get("routing", config.HTTP_ROUTING_PORT))
        self._enforce_consistency()

    def _enforce_consistency(self):
        valid_sub_ids = {sub["id"] for sub in self.subscriptions}
        unique = {}
        for node in self.nodes:
            if node.get("subscription_id") not in valid_sub_ids:
                node["subscription_id"] = None
            signature = node_signature(node)
            existing = unique.get(signature)
            if existing is None:
                unique[signature] = node
                continue
            # Keep the active node's ID and merge a valid subscription association.
            winner, other = (node, existing) if node.get("is_active") else (existing, node)
            if not winner.get("subscription_id"):
                winner["subscription_id"] = other.get("subscription_id")
            unique[signature] = winner

        self.nodes = list(unique.values())
        active_found = False
        for node in self.nodes:
            node["is_active"] = bool(node.get("is_active")) and not active_found
            active_found = active_found or node["is_active"]
        # Importing a node does not make it the running Xray configuration.
        for sub in self.subscriptions:
            sub["node_count"] = sum(n.get("subscription_id") == sub["id"] for n in self.nodes)

    @synchronized
    def save(self):
        self._enforce_consistency()
        if self._memory_only:
            return
        atomic_write_json(self.file_path, {
            "nodes": self.nodes,
            "subscriptions": self.subscriptions,
            "routing_mode": self.routing_mode,
            "ports": getattr(self, "ports", {
                "socks": config.SOCKS_PORT,
                "http": config.HTTP_PROXY_PORT,
                "routing": config.HTTP_ROUTING_PORT
            }),
            "updated_at": int(time.time()),
        })

    @synchronized
    def snapshot(self):
        return deepcopy({"nodes": self.nodes, "subscriptions": self.subscriptions,
                         "routing_mode": self.routing_mode, "ports": self.get_ports()})

    @synchronized
    def fork(self):
        candidate = object.__new__(DataStore)
        candidate.file_path = self.file_path
        candidate._lock = threading.RLock()
        candidate._memory_only = True
        candidate.restore(self.snapshot())
        return candidate

    @synchronized
    def restore(self, state):
        for key, value in deepcopy(state).items():
            setattr(self, key, value)
        if not self._memory_only:
            config.SOCKS_PORT = self.ports["socks"]
            config.HTTP_PROXY_PORT = self.ports["http"]
            config.HTTP_ROUTING_PORT = self.ports["routing"]

    @synchronized
    def commit(self, candidate):
        state = candidate.snapshot()
        if state == self.snapshot():
            return
        atomic_write_json(self.file_path, {**state, "updated_at": int(time.time())})
        self.restore(state)

    @synchronized
    def get_ports(self) -> Dict[str, int]:
        if not hasattr(self, "ports") or not isinstance(self.ports, dict):
            self.ports = {
                "socks": config.SOCKS_PORT,
                "http": config.HTTP_PROXY_PORT,
                "routing": config.HTTP_ROUTING_PORT
            }
        return dict(self.ports)

    @synchronized
    def set_ports(self, socks: int, http: int, routing: int) -> Dict[str, int]:
        for p in (socks, http, routing):
            if not isinstance(p, int) or not (1 <= p <= 65535):
                raise ValueError(f"端口号必须在 1 到 65535 之间: {p}")
        if len({socks, http, routing}) != 3:
            raise ValueError("三个代理端口不能重复")
        if config.WEB_PORT in {socks, http, routing}:
            raise ValueError(f"端口不能与控制台 Web 端口 ({config.WEB_PORT}) 冲突")

        self.ports = {
            "socks": socks,
            "http": http,
            "routing": routing
        }
        if not self._memory_only:
            config.SOCKS_PORT = socks
            config.HTTP_PROXY_PORT = http
            config.HTTP_ROUTING_PORT = routing
        self.save()
        return dict(self.ports)

    @synchronized
    def get_routing_mode(self):
        return self.routing_mode

    @synchronized
    def set_routing_mode(self, mode):
        self.routing_mode = mode
        self.save()

    @synchronized
    def bootstrap_from_current_config(self):
        try:
            xray_cfg = json.loads(config.XRAY_CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        outbound = next((ob for ob in xray_cfg.get("outbounds", []) if ob.get("tag") == "proxy"), None)
        if not outbound:
            return
        try:
            link = ProtocolParser.outbound_to_link(outbound, "当前运行节点")
            if not link:
                return
            current = ProtocolParser.parse_link(link)
        except (ValueError, KeyError, IndexError, TypeError):
            return
        # The original outbound remains authoritative, including advanced fields.
        current["outbound"] = deepcopy(outbound)
        before = deepcopy(self.nodes)
        signature = node_signature(current)
        matched = next((n for n in self.nodes if node_signature(n) == signature), None)
        if matched is None:
            matched = self._upsert_node(current)
        for node in self.nodes:
            node["is_active"] = node["id"] == matched["id"]
        if self.nodes != before:
            self.save()

    @synchronized
    def get_nodes(self):
        return deepcopy(self.nodes)

    def _find_node(self, node_id):
        return next((node for node in self.nodes if node["id"] == node_id), None)

    @synchronized
    def get_node(self, node_id):
        return deepcopy(self._find_node(node_id))

    @synchronized
    def get_active_node(self):
        return deepcopy(next((n for n in self.nodes if n.get("is_active")), None))

    @synchronized
    def set_active_node(self, node_id):
        if not self._find_node(node_id):
            raise ValueError("节点不存在")
        for node in self.nodes:
            node["is_active"] = node["id"] == node_id
        self.save()

    def _upsert_node(self, node_data, subscription_id=None):
        data = deepcopy(node_data)
        data["address"] = data.get("address", "").strip()
        data["port"] = int(data.get("port", 443))
        data["protocol"] = data.get("protocol", "vless").strip()
        if not data["address"] or not 1 <= data["port"] <= 65535:
            raise ValueError("节点地址或端口无效")
        signature = node_signature(data)
        for existing in self.nodes:
            if node_signature(existing) != signature:
                continue
            if data.get("name") and existing.get("name") in ("当前运行节点", "未命名节点"):
                existing["name"] = data["name"]
            if subscription_id:
                existing["subscription_id"] = subscription_id
            for key in ("outbound", "raw_link", "tags", "security", "network", "encryption", "sni"):
                if key in data:
                    existing[key] = data[key]
            return existing

        node = {
            "id": str(uuid.uuid4()),
            "name": data.get("name") or "未命名节点",
            "protocol": data["protocol"],
            "address": data["address"],
            "port": data["port"],
            "security": data.get("security", "none"),
            "network": data.get("network", "tcp"),
            "encryption": data.get("encryption", ""),
            "sni": data.get("sni", ""),
            "raw_link": data.get("raw_link", ""),
            "tags": data.get("tags", []),
            "outbound": data.get("outbound", {}),
            "is_active": False,
            "last_delay": None,
            "created_at": int(time.time()),
            "subscription_id": subscription_id,
        }
        self.nodes.append(node)
        return node

    @synchronized
    def add_node(self, node_data, subscription_id=None):
        node = self._upsert_node(node_data, subscription_id)
        self.save()
        return deepcopy(node)

    @synchronized
    def add_nodes_batch(self, nodes_data, subscription_id=None):
        before = deepcopy(self.nodes)
        try:
            for data in nodes_data:
                self._upsert_node(data, subscription_id)
            self.save()
        except Exception:
            self.nodes = before
            raise
        return len(self.nodes) - len(before)

    @synchronized
    def delete_node(self, node_id):
        node = self._find_node(node_id)
        if node is None:
            return False
        if node.get("is_active"):
            raise ValueError("不能删除当前正在使用的活动节点")
        self.nodes.remove(node)
        self.save()
        return True

    @synchronized
    def update_node_name(self, node_id, new_name):
        if not new_name.strip():
            raise ValueError("节点名称不能为空")
        node = self._find_node(node_id)
        if node is None:
            return False
        node["name"] = new_name.strip()
        self.save()
        return True

    @synchronized
    def update_node_delay(self, node_id, delay, *, persist=True):
        node = self._find_node(node_id)
        if node is not None:
            node.update(last_delay=delay, last_test_time=int(time.time()))
            if persist:
                self.save()

    @synchronized
    def update_node_speed(self, node_id, speed, *, persist=True):
        node = self._find_node(node_id)
        if node is not None:
            node.update(last_speed=speed, last_speed_time=int(time.time()))
            if persist:
                self.save()

    @synchronized
    def delete_nodes_batch(self, node_ids):
        target_ids = set(node_ids)
        before = len(self.nodes)
        self.nodes = [n for n in self.nodes if n["id"] not in target_ids or n.get("is_active")]
        self.save()
        return before - len(self.nodes)

    @synchronized
    def get_subscriptions(self):
        return deepcopy(self.subscriptions)

    @synchronized
    def add_subscription(self, name, url):
        url = url.strip()
        existing = next((s for s in self.subscriptions if s["url"] == url), None)
        if existing:
            return deepcopy(existing)
        sub = {
            "id": str(uuid.uuid4()),
            "name": name.strip() or "未命名订阅",
            "url": url,
            "node_count": 0,
            "updated_at": int(time.time()),
        }
        self.subscriptions.append(sub)
        self.save()
        return deepcopy(sub)

    @synchronized
    def delete_subscription(self, sub_id, delete_nodes=False):
        self.subscriptions = [s for s in self.subscriptions if s["id"] != sub_id]
        if delete_nodes:
            self.nodes = [
                n for n in self.nodes
                if n.get("subscription_id") != sub_id or n.get("is_active")
            ]
        for node in self.nodes:
            if node.get("subscription_id") == sub_id:
                node["subscription_id"] = None
        self.save()

    @synchronized
    def sync_subscription_nodes(self, sub_id, new_nodes_data):
        if not any(s["id"] == sub_id for s in self.subscriptions):
            raise ValueError("订阅不存在")
        previous = deepcopy(self.nodes)
        try:
            retained = {self._upsert_node(data, sub_id)["id"] for data in new_nodes_data}
            surviving = []
            for node in self.nodes:
                if node.get("subscription_id") == sub_id and node["id"] not in retained:
                    if not node.get("is_active"):
                        continue
                    # A removed active node remains usable as a manual node.
                    node["subscription_id"] = None
                surviving.append(node)
            self.nodes = surviving
            self.update_sub_meta(sub_id)
        except Exception:
            self.nodes = previous
            raise
        return sum(n.get("subscription_id") == sub_id for n in self.nodes)

    @synchronized
    def update_subscription_name(self, sub_id: str, new_name: str) -> bool:
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("订阅名称不能为空")
        sub = next((s for s in self.subscriptions if s["id"] == sub_id), None)
        if sub is None:
            return False
        sub["name"] = new_name
        self.save()
        return True

    @synchronized
    def update_sub_meta(self, sub_id, node_count=None):
        for sub in self.subscriptions:
            if sub["id"] == sub_id:
                sub["updated_at"] = int(time.time())
        self.save()


store = DataStore()
