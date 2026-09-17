import json
import os
import socket
import subprocess
import time
import threading
from copy import deepcopy
import requests
from typing import Dict, Any, Optional, List
import config
from core.store import store
from core.routing_manager import routing_manager
from core.speedtest import test_node_delay, test_node_speed
from core.persistence import atomic_write_bytes
from core.runtime import XrayRuntime, create_runtime

def get_local_bridge_ip() -> str:
    """获取本机首选局域网桥接 IP（例如 WSL 桥接给宿主机的 IP）"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

class XrayManager:
    @classmethod
    def get_service_status(cls) -> Dict[str, Any]:
        """获取 Xray 核心运行状态与路由架构（适配 systemd 或独立进程）"""
        is_active = False
        try:
            is_active = cls._runtime.is_active()
        except Exception:
            pass

        version_str = "Unknown"
        try:
            v_res = subprocess.run([config.XRAY_BIN, "version"], capture_output=True, text=True, timeout=config.COMMAND_TIMEOUT)
            if v_res.returncode == 0:
                first_line = v_res.stdout.splitlines()[0]
                version_str = first_line.split("(")[0].strip()
        except Exception:
            pass

        rules = routing_manager.get_rules()
        enabled_rules_count = sum(1 for r in rules if r.get("enabled", True))
        current_ports = store.get_ports() if hasattr(store, "get_ports") else {"socks": config.SOCKS_PORT, "http": config.HTTP_PROXY_PORT, "routing": config.HTTP_ROUTING_PORT}

        return {
            "active": is_active,
            "version": version_str,
            "bridge_ip": get_local_bridge_ip(),
            "ports": {
                "direct": [current_ports["socks"], current_ports["http"]],
                "routing": current_ports["routing"]
            },
            "rules_count": len(rules),
            "rules_enabled_count": enabled_rules_count
        }

    _outbound_ip_cache: Dict[str, Any] = {}
    _outbound_ip_cache_time: float = 0
    _outbound_ip_cache_node_id: Optional[str] = None

    @classmethod
    def get_outbound_ip(cls, force: bool = False, timeout: int = 3) -> Dict[str, Any]:
        """通过当前主运行端口获取出口公网 IP 与地理位置（带节点级智能缓存，避免高频轮询污染日志与触发限频）"""
        active_node = store.get_active_node()
        current_node_id = active_node.get("id") if active_node else None

        # 如果当前节点未变且在 5 分钟缓存期内，且已有成功结果，直接复用缓存
        if not force and cls._outbound_ip_cache.get("success") and cls._outbound_ip_cache_node_id == current_node_id:
            if time.time() - cls._outbound_ip_cache_time < 300:
                return cls._outbound_ip_cache

        ports = store.get_ports() if hasattr(store, "get_ports") else {}
        proxy = config.http_proxy_url(ports.get("http"))
        proxies = {"http": proxy, "https": proxy}
        result = None
        try:
            resp = requests.get("http://ip-api.com/json/", proxies=proxies, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                ip = data.get("query", "")
                if data.get("status") != "success" or not ip:
                    raise ValueError("出口地址查询未成功")
                country = f"{data.get('country', '')} {data.get('city', '')}".strip()
                result = {"ip": ip, "country": country, "success": True}
        except Exception:
            pass

        if not result:
            try:
                resp = requests.get(config.IP_CHECK_URL, proxies=proxies, timeout=timeout)
                if resp.status_code == 200:
                    ip = resp.text.strip()
                    result = {"ip": ip, "country": "海外节点", "success": True}
            except Exception:
                pass

        if not result:
            result = {"ip": "检测中", "country": "-", "success": False}

        if result.get("success"):
            cls._outbound_ip_cache = result
            cls._outbound_ip_cache_time = time.time()
            cls._outbound_ip_cache_node_id = current_node_id

        return result

    @classmethod
    def test_single_node(cls, node_id: str, persist: bool = True, on_progress=None) -> Dict[str, Any]:
        """Real Ping：经代理测真实延迟。"""
        return test_node_delay(node_id, persist=persist, on_progress=on_progress)

    @classmethod
    def speed_test_single_node(cls, node_id: str, persist: bool = True, on_progress=None) -> Dict[str, Any]:
        """Mixed：Real Ping 成功后持续下载，上报瞬时峰值。"""
        return test_node_speed(node_id, persist=persist, on_progress=on_progress)

    _operation_lock = threading.RLock()
    _runtime = create_runtime()

    @classmethod
    def restart_service(cls):
        cls._runtime.restart()

    @classmethod
    def _build_config(cls, original, candidate_store, candidate_routing):
        main_cfg = deepcopy(original)
        ports = candidate_store.get_ports()
        main_cfg["inbounds"] = cls._ensure_inbounds(
            main_cfg.get("inbounds", []), ports["socks"], ports["http"], ports["routing"])
        active = candidate_store.get_active_node()
        outbounds = deepcopy(main_cfg.get("outbounds", []))
        if active and not active.get("outbound"):
            raise ValueError("节点缺少 outbound 配置")
        proxy = deepcopy(active["outbound"]) if active else None
        if proxy is not None:
            proxy["tag"] = "proxy"
            outbounds = [ob for ob in outbounds if ob.get("tag") != "proxy"]
            outbounds.insert(0, proxy)
        defaults = [("proxy", "blackhole"), ("direct", "freedom"), ("block", "blackhole")]
        for tag, protocol in defaults:
            if not any(ob.get("tag") == tag for ob in outbounds):
                outbounds.append({"tag": tag, "protocol": protocol})
        main_cfg["outbounds"] = outbounds
        main_cfg.setdefault("log", {"loglevel": "warning"})
        main_cfg.setdefault("routing", {}).update({
            "rules": candidate_routing.build_xray_routing_rules(
                active.get("address", "") if active else "",
                active.get("port", "") if active else ""),
            "domainStrategy": "AsIs",
            "domainMatcher": "mph",
        })
        return main_cfg

    @staticmethod
    def _read_state_file(path):
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None

    @classmethod
    def _apply_change(cls, edit=None, *, apply_core=True):
        # All three entry points share this boundary. Store locks also prevent
        # a failed operation from overwriting concurrent imports or test results.
        with cls._operation_lock, store._lock, routing_manager._lock:
            before_store = store.snapshot()
            before_rules = routing_manager.snapshot()
            candidate_store = store.fork()
            candidate_rules = routing_manager.fork()
            value = edit(candidate_store, candidate_rules) if edit else None
            old_config = cls._runtime.read()
            original = json.loads(old_config) if old_config is not None else {}
            if not isinstance(original, dict):
                raise ValueError("Xray 主配置必须是 JSON 对象")
            candidate = cls._build_config(original, candidate_store, candidate_rules)
            cls._runtime.validate(candidate)
            state_files = {
                path: cls._read_state_file(path)
                for path in (store.file_path, routing_manager.file_path)
            }
            was_active = cls._runtime.is_active() if apply_core else False
            installed = False
            write_attempted = False
            try:
                if apply_core:
                    cls._runtime.backup(old_config)
                    write_attempted = True
                    cls._runtime.write((json.dumps(candidate, indent=2, ensure_ascii=False) + "\n").encode())
                    installed = True
                    cls.restart_service()
                store.commit(candidate_store)
                routing_manager.commit(candidate_rules)
            except Exception as exc:
                recovery_errors = []
                try:
                    changed = installed or (write_attempted and cls._runtime.read() != old_config)
                except Exception:
                    changed = write_attempted
                if changed:
                    try:
                        cls._runtime.restore(old_config)
                        if was_active:
                            cls.restart_service()
                        else:
                            cls._runtime.stop()
                    except Exception as recovery:
                        recovery_errors.append(f"核心恢复失败：{recovery}")
                for path, content in state_files.items():
                    try:
                        if cls._read_state_file(path) != content:
                            if content is None:
                                path.unlink(missing_ok=True)
                            else:
                                atomic_write_bytes(path, content)
                    except Exception as recovery:
                        recovery_errors.append(f"{path.name} 恢复失败：{recovery}")
                store.restore(before_store)
                routing_manager.restore(before_rules)
                detail = "；".join(recovery_errors) if recovery_errors else "已恢复原状态"
                raise RuntimeError(f"配置应用失败：{exc}；{detail}") from exc
            cls._outbound_ip_cache = {}
            cls._outbound_ip_cache_node_id = None
            return {
                "success": True, "applied": apply_core, "value": value,
                "categories": candidate_rules.get_categories_dict(),
                "ports": candidate_store.get_ports(),
                "rules_count": len(candidate_rules.get_rules()),
            }

    @classmethod
    def switch_node(cls, node_id):
        def edit(candidate_store, _):
            node = candidate_store.get_node(node_id)
            if not node:
                raise ValueError("节点不存在")
            candidate_store.set_active_node(node_id)
            return node
        result = cls._apply_change(edit)
        node = result.pop("value")
        return {**result, "node_id": node_id,
                "message": f"已切换至「{node['name']}」", "latency": node.get("last_delay")}

    @classmethod
    def change_routing(cls, edit, *, apply=True):
        result = cls._apply_change(lambda _, rules: edit(rules), apply_core=apply)
        result["message"] = "分流规则已保存并生效" if apply else "分流规则已保存，尚未应用"
        return result

    @classmethod
    def apply_routing(cls):
        return cls.change_routing(lambda _: None)

    @classmethod
    def apply_ports(cls, socks_port, http_port, routing_port):
        result = cls._apply_change(lambda candidate, _: candidate.set_ports(socks_port, http_port, routing_port))
        result["message"] = "代理端口已更新并生效"
        result["ports"] = {"direct": [socks_port, http_port], "routing": routing_port}
        return result

    @staticmethod
    def _ensure_inbounds(existing_inbounds: List[Dict[str, Any]], socks_port: int = None, http_port: int = None, routing_port: int = None) -> List[Dict[str, Any]]:
        """确保三端口入站配置健全（socks直通, http直通, http规则分流）"""
        current_ports = store.get_ports() if hasattr(store, "get_ports") else {}
        sp = socks_port or current_ports.get("socks", config.SOCKS_PORT)
        hp = http_port or current_ports.get("http", config.HTTP_PROXY_PORT)
        rp = routing_port or current_ports.get("routing", config.HTTP_ROUTING_PORT)

        existing_inbounds = deepcopy(existing_inbounds)
        listen = config.PROXY_LISTEN_HOST or "127.0.0.1"
        by_tag = {}
        extras = []
        for ib in existing_inbounds:
            tag = ib.get("tag", "")
            if tag in ("socks-in", "http-in-20171", "http-in-20172"):
                by_tag[tag] = ib
            else:
                extras.append(ib)

        socks = by_tag.get("socks-in") or {
            "tag": "socks-in",
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": True},
            "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]}
        }
        socks.update({"port": sp, "tag": "socks-in", "listen": listen, "protocol": "socks"})

        http_direct = by_tag.get("http-in-20171") or {
            "tag": "http-in-20171",
            "protocol": "http",
            "settings": {},
            "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]}
        }
        http_direct.update({"port": hp, "tag": "http-in-20171", "listen": listen, "protocol": "http"})

        http_routing = by_tag.get("http-in-20172") or {
            "tag": "http-in-20172",
            "protocol": "http",
            "settings": {},
            "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]}
        }
        http_routing.update({"port": rp, "tag": "http-in-20172", "listen": listen, "protocol": "http"})

        return [socks, http_direct, http_routing, *extras]
