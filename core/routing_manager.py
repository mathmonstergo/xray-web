import json
import uuid
import time
import ipaddress
import threading
from copy import deepcopy
from pathlib import Path
from typing import List, Dict, Any, Optional
import config
from core.persistence import atomic_write_json, synchronized

ROUTING_STORE_FILE = config.DATA_DIR / "custom_rules.json"

def classify_rule_item(item: str) -> str:
    """自动智能判断单项是 domain 还是 ip"""
    item = item.strip()
    if item.startswith(("domain:", "full:", "geosite:", "regexp:")):
        return "domain"
    if item.startswith("geoip:"):
        return "ip"
    try:
        ipaddress.ip_network(item, strict=False)
        return "ip"
    except ValueError:
        if "/" in item or ":" in item:
            return "ip"
    return "domain"


def clean_values(values, rule_type=None):
    cleaned = []
    for value in values:
        value = value.strip()
        if not value or value.startswith("#"):
            continue
        if value.startswith("*."):
            value = "domain:" + value[2:]
        kind = rule_type or classify_rule_item(value)
        if kind == "ip" and not value.startswith("geoip:"):
            try:
                ipaddress.ip_network(value, strict=False)
            except ValueError as exc:
                raise ValueError(f"无效的 IP 或网段：{value}") from exc
        if "://" in value and not value.startswith("regexp:"):
            raise ValueError("分流规则请填写域名或 IP，而不是完整 URL")
        if value not in cleaned:
            cleaned.append(value)
    return cleaned

def auto_name_rule(rule_type: str, action: str, values: List[str]) -> str:
    if not values:
        return "自定义规则"
    first = values[0]
    if "geosite:google" in first:
        return "Google 服务"
    if "geosite:cn" in first:
        return "中国大陆常用域名"
    if "geoip:cn" in first or "geoip:private" in first:
        return "私网与大陆IP"
    if "apple" in first.lower():
        return "Apple 服务"
    if len(values) == 1:
        return first
    return f"{first} 等 {len(values)} 项"

class RoutingManager:
    def __init__(self, file_path: Path = ROUTING_STORE_FILE):
        self.file_path = file_path
        self._lock = threading.RLock()
        self._memory_only = False
        self.rules: List[Dict[str, Any]] = []
        self.default_outbound: str = "proxy"
        self.load()

    @synchronized
    def load(self):
        if self.file_path.exists():
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
                        raise ValueError("规则数据结构无效")
                    self.rules = data.get("rules", [])
                    self.default_outbound = data.get("default_outbound", "proxy")
                    return
            except (OSError, ValueError) as exc:
                raise RuntimeError(f"无法读取分流规则，请检查或恢复文件：{self.file_path}") from exc

        # 如果没有 custom_rules.json，从现有的 rules_bypass_cn.json 导入初始化
        self.migrate_from_existing_template()

    def migrate_from_existing_template(self):
        legacy_file = config.DATA_DIR / "rules_bypass_cn.json"
        self.rules = []
        self.default_outbound = "proxy"

        if legacy_file.exists():
            try:
                with open(legacy_file, "r", encoding="utf-8") as f:
                    legacy_rules = json.load(f)

                for r in legacy_rules:
                    # 跳过节点直连规则（带20900或单IP）和兜底规则（0-65535）
                    port = str(r.get("port", ""))
                    if "0-65535" in port:
                        continue
                    if port and "ip" in r and len(r.get("ip", [])) == 1 and not r["ip"][0].startswith("geoip"):
                        continue

                    action = r.get("outboundTag", "direct")
                    if "domain" in r and r["domain"]:
                        self.rules.append({
                            "id": str(uuid.uuid4()),
                            "name": auto_name_rule("domain", action, r["domain"]),
                            "type": "domain",
                            "values": r["domain"],
                            "action": action,
                            "enabled": True
                        })
                    elif "ip" in r and r["ip"]:
                        self.rules.append({
                            "id": str(uuid.uuid4()),
                            "name": auto_name_rule("ip", action, r["ip"]),
                            "type": "ip",
                            "values": r["ip"],
                            "action": action,
                            "enabled": True
                        })
            except Exception:
                pass

        public_defaults = config.BASE_DIR / "defaults" / "routing.json"
        if not self.rules and public_defaults.is_file():
            data = json.loads(public_defaults.read_text(encoding="utf-8"))
            self.rules = data["rules"]
            self.default_outbound = data.get("default_outbound", "proxy")

        if not self.rules:
            # 基础兜底推荐规则
            self.rules = [
                {
                    "id": str(uuid.uuid4()),
                    "name": "局域网与私有IP直连",
                    "type": "ip",
                    "values": ["geoip:private", "127.0.0.1/8", "::1/128"],
                    "action": "direct",
                    "enabled": True
                },
                {
                    "id": str(uuid.uuid4()),
                    "name": "中国大陆域名直连 (geosite:cn)",
                    "type": "domain",
                    "values": ["geosite:cn"],
                    "action": "direct",
                    "enabled": True
                },
                {
                    "id": str(uuid.uuid4()),
                    "name": "中国大陆IP直连 (geoip:cn)",
                    "type": "ip",
                    "values": ["geoip:cn"],
                    "action": "direct",
                    "enabled": True
                }
            ]

        self.save()

    @synchronized
    def save(self):
        if self._memory_only:
            return
        atomic_write_json(self.file_path, {
            "default_outbound": self.default_outbound,
            "rules": self.rules,
            "updated_at": int(time.time())
        })

    @synchronized
    def snapshot(self):
        return deepcopy({"rules": self.rules, "default_outbound": self.default_outbound})

    @synchronized
    def restore(self, state):
        self.rules = deepcopy(state["rules"])
        self.default_outbound = state["default_outbound"]

    @synchronized
    def fork(self):
        candidate = object.__new__(RoutingManager)
        candidate.file_path = self.file_path
        candidate._lock = threading.RLock()
        candidate._memory_only = True
        candidate.restore(self.snapshot())
        return candidate

    @synchronized
    def commit(self, candidate):
        state = candidate.snapshot()
        if state == self.snapshot():
            return
        atomic_write_json(self.file_path, {**state, "updated_at": int(time.time())})
        self.restore(state)

    @synchronized
    def get_rules(self) -> List[Dict[str, Any]]:
        return deepcopy(self.rules)

    def _find_rule(self, rule_id: str) -> Optional[Dict[str, Any]]:
        for r in self.rules:
            if r["id"] == rule_id:
                return r
        return None

    @synchronized
    def get_rule(self, rule_id: str) -> Optional[Dict[str, Any]]:
        return deepcopy(self._find_rule(rule_id))

    @synchronized
    def get_categories_dict(self) -> Dict[str, List[str]]:
        """获取直连、代理、拦截三栏规则列表"""
        res = {"direct": [], "proxy": [], "block": []}
        for r in self.rules:
            act = r.get("action", "direct")
            if act in res:
                for v in r.get("values", []):
                    v_clean = v.strip()
                    if v_clean and v_clean not in res[act]:
                        res[act].append(v_clean)
        return res

    @synchronized
    def set_category_lines(self, action: str, lines: List[str]) -> Dict[str, List[str]]:
        """根据三栏内容框整体保存更新该动作类别的所有规则，并自动区分 domain 与 ip"""
        if action not in ("direct", "proxy", "block"):
            raise ValueError("分类必须为 direct, proxy 或 block")

        clean_lines = clean_values(lines)

        domains = [item for item in clean_lines if classify_rule_item(item) == "domain"]
        ips = [item for item in clean_lines if classify_rule_item(item) == "ip"]

        # 移除原有的该 action 规则
        self.rules = [r for r in self.rules if r.get("action") != action]

        # 重新生成规则（按类型分别组织）
        new_entries = []
        if domains:
            new_entries.append({
                "id": str(uuid.uuid4()),
                "name": auto_name_rule("domain", action, domains),
                "type": "domain",
                "values": domains,
                "action": action,
                "enabled": True
            })
        if ips:
            new_entries.append({
                "id": str(uuid.uuid4()),
                "name": auto_name_rule("ip", action, ips),
                "type": "ip",
                "values": ips,
                "action": action,
                "enabled": True
            })

        self.rules = new_entries + self.rules
        self.save()
        return self.get_categories_dict()

    @synchronized
    def add_rule(self, name: str, rule_type: str, values: List[str], action: str, enabled: bool = True) -> Dict[str, Any]:
        if rule_type not in ("domain", "ip"):
            raise ValueError("规则类型必须为 domain 或 ip")
        if action not in ("direct", "proxy", "block"):
            raise ValueError("动作必须为 direct / proxy / block")
        cleaned_values = clean_values(values, rule_type)
        if not cleaned_values:
            raise ValueError("规则内容列表不能为空")

        rule_name = name.strip() or auto_name_rule(rule_type, action, cleaned_values)

        new_rule = {
            "id": str(uuid.uuid4()),
            "name": rule_name,
            "type": rule_type,
            "values": cleaned_values,
            "action": action,
            "enabled": enabled
        }
        # 新增的自定义规则插入到列表靠前位置，方便优先匹配
        self.rules.insert(0, new_rule)
        self.save()
        return deepcopy(new_rule)

    @synchronized
    def update_rule(self, rule_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        rule = self._find_rule(rule_id)
        if not rule:
            raise ValueError("规则未找到")

        if data.get("name") and data["name"].strip():
            rule["name"] = data["name"].strip()
        if "type" in data and data["type"] in ("domain", "ip"):
            rule["type"] = data["type"]
        if "action" in data and data["action"] in ("direct", "proxy", "block"):
            rule["action"] = data["action"]
        if "enabled" in data:
            rule["enabled"] = bool(data["enabled"])
        if "values" in data:
            cleaned = clean_values(data["values"] or [], rule["type"])
            if not cleaned:
                raise ValueError("规则内容列表不能为空")
            rule["values"] = cleaned

        self.save()
        return deepcopy(rule)

    @synchronized
    def delete_rule(self, rule_id: str) -> bool:
        idx = next((i for i, r in enumerate(self.rules) if r["id"] == rule_id), -1)
        if idx != -1:
            self.rules.pop(idx)
            self.save()
            return True
        return False

    @synchronized
    def toggle_rule(self, rule_id: str, enabled: Optional[bool] = None) -> Dict[str, Any]:
        rule = self._find_rule(rule_id)
        if not rule:
            raise ValueError("规则未找到")
        rule["enabled"] = (not rule["enabled"]) if enabled is None else bool(enabled)
        self.save()
        return deepcopy(rule)

    @synchronized
    def set_default_outbound(self, outbound: str):
        if outbound not in ("proxy", "direct"):
            raise ValueError("默认出站必须为 proxy 或 direct")
        self.default_outbound = outbound
        self.save()

    @synchronized
    def build_xray_routing_rules(self, active_node_ip: str, active_node_port: Any) -> List[Dict[str, Any]]:
        """
        编译 Xray routing rules：
        1. 节点直连防回环
        2. 20170 (socks) 和 20171 (http) 不走分流规则，直通 proxy 节点
        3. 20172 (http) 走分流规则：匹配用户自定义分流规则
        4. 兜底出站规则 (默认 proxy)
        """
        rules: List[Dict[str, Any]] = []

        # 1. 节点自身防回环（直连）
        if active_node_ip:
            clean_host = str(active_node_ip).strip().strip("[]")
            if "://" in clean_host:
                clean_host = clean_host.split("://", 1)[1].split("/", 1)[0]
            if ":" in clean_host and clean_host.count(":") == 1:
                clean_host = clean_host.split(":", 1)[0]

            is_ip = False
            try:
                import ipaddress
                ipaddress.ip_address(clean_host)
                is_ip = True
            except ValueError:
                is_ip = False

            node_rule = {
                "type": "field",
                "outboundTag": "direct"
            }
            if is_ip:
                node_rule["ip"] = [clean_host]
            else:
                domain_val = clean_host if clean_host.startswith(("full:", "domain:", "geosite:")) else f"full:{clean_host}"
                node_rule["domain"] = [domain_val]
            if active_node_port:
                node_rule["port"] = str(active_node_port)
            rules.append(node_rule)

        # 2. 20170 (socks) 与 20171 (http) 不走规则分流，直接走 proxy 出口
        rules.append({
            "type": "field",
            "inboundTag": ["socks-in", "http-in-20171"],
            "outboundTag": "proxy"
        })

        # 3. 20172 走分流规则（匹配域名与 IP）
        priority = {"block": 0, "proxy": 1, "direct": 2}
        for r in sorted(self.rules, key=lambda rule: priority.get(rule.get("action"), 3)):
            if not r.get("enabled", True):
                continue
            rule_entry = {
                "type": "field",
                "outboundTag": r.get("action", "direct")
            }
            target_type = r.get("type", "domain")
            vals = r.get("values", [])
            if not vals:
                continue
            if target_type == "domain":
                rule_entry["domain"] = vals
            else:
                rule_entry["ip"] = vals
            rules.append(rule_entry)

        # 4. 兜底出站规则 (默认 proxy)
        rules.append({
            "type": "field",
            "outboundTag": self.default_outbound or "proxy",
            "port": "0-65535"
        })

        return rules

routing_manager = RoutingManager()
