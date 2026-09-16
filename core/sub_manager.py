"""Fetch plain/Base64 subscriptions and report every unparsed node line."""

from typing import List, Dict, Any
from urllib.parse import urlsplit

import requests

import config
from core.parser import ProtocolParser, safe_b64decode
from core.store import store


class SubscriptionManager:
    @staticmethod
    def fetch_subscription(url: str, proxy_url: str = None, timeout: int = 10) -> str:
        parsed = urlsplit(url.strip())
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("订阅地址必须是有效的 HTTP/HTTPS URL")
        proxy_url = proxy_url or config.http_proxy_url(store.get_ports().get("http"))
        headers = {"User-Agent": "v2rayN/6.39 (Xray-Web; Linux x86_64)"}
        last_error = "订阅内容为空"
        with requests.Session() as session:
            # Direct really means direct, even if the launching shell exports a proxy.
            session.trust_env = False
            for proxies in (None, {"http": proxy_url, "https": proxy_url}):
                try:
                    with session.get(url.strip(), headers=headers, proxies=proxies,
                                     timeout=timeout, stream=True) as response:
                        if response.status_code != 200:
                            last_error = f"HTTP {response.status_code}"
                            continue
                        content = bytearray()
                        for chunk in response.iter_content(chunk_size=65536):
                            content.extend(chunk)
                            if len(content) > 8 * 1024 * 1024:
                                raise ValueError("订阅内容超过 8 MiB 限制")
                        text = content.decode("utf-8-sig").strip()
                        if text:
                            return text
                except requests.RequestException as exc:
                    # Requests exception strings can contain subscription tokens.
                    last_error = type(exc).__name__
        raise RuntimeError(f"订阅直连和本地代理拉取均失败：{last_error}")

    @staticmethod
    def parse_with_diagnostics(content):
        content = content.strip().lstrip("\ufeff")
        if not content:
            return [], []
        if "://" not in content:
            try:
                decoded = safe_b64decode(content)
                if "://" in decoded:
                    content = decoded
            except (ValueError, UnicodeError):
                pass
        nodes, errors = [], []
        for number, raw in enumerate(content.splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith(("#", "//")):
                continue
            try:
                nodes.append(ProtocolParser.parse_link(line))
            except (ValueError, TypeError, KeyError, IndexError) as exc:
                errors.append({"line": number, "message": str(exc)})
        return nodes, errors

    @staticmethod
    def parse_raw_text(content: str, *, strict: bool = True) -> List[Dict[str, Any]]:
        nodes, errors = SubscriptionManager.parse_with_diagnostics(content)
        if strict and errors:
            lines = "、".join(str(error["line"]) for error in errors[:8])
            raise ValueError(f"第 {lines} 行无法解析，共 {len(errors)} 行失败；未导入或更新节点。{errors[0]['message']}")
        return nodes
