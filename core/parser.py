import json
import base64
import urllib.parse
from copy import deepcopy
from typing import Dict, Any, Tuple, Optional

def safe_b64decode(s: str) -> str:
    """自动补全 padding 的 Base64 解码"""
    s = ''.join(s.split()).replace('-', '+').replace('_', '/')
    missing_padding = len(s) % 4
    if missing_padding:
        s += '=' * (4 - missing_padding)
    return base64.b64decode(s, validate=True).decode('utf-8')

def safe_b64encode(s: str) -> str:
    return base64.b64encode(s.encode('utf-8')).decode('utf-8')

def clean_node_address(raw_addr: str, default_port: Optional[int] = None) -> Tuple[str, Optional[int]]:
    """
    清洗并规范化节点主机地址：
    完美兼容纯 IPv4、IPv6、域名主机、带 http/https 协议头的 URL、带路径的地址、host:port 等。
    返回纯净的 (hostname_or_ip, port)。
    """
    if not raw_addr:
        return "", default_port

    addr = str(raw_addr).strip().rstrip("/")
    port = default_port

    # 处理协议前缀 (例如 http://, https://, tcp://, ws://)
    if "://" in addr:
        parsed = urllib.parse.urlparse(addr)
        if parsed.hostname:
            addr = parsed.hostname
            if parsed.port:
                port = parsed.port
        else:
            addr = addr.split("://", 1)[1].split("/", 1)[0]

    # 去除尾部路径 (例如 node.example.com/vless)
    if "/" in addr and not addr.startswith("["):
        addr = addr.split("/", 1)[0]

    # 处理形如 [2001:db8::1]:443 的 IPv6 + 端口
    if addr.startswith("[") and "]:" in addr:
        parts = addr.rsplit("]:", 1)
        addr = parts[0].lstrip("[")
        if parts[1].isdigit():
            port = int(parts[1])
    elif addr.startswith("[") and addr.endswith("]"):
        addr = addr[1:-1]
    # 处理普通 host:port (只有一个冒号的情况，排除多冒号的纯 IPv6)
    elif ":" in addr and addr.count(":") == 1:
        host_part, port_part = addr.split(":", 1)
        if port_part.isdigit():
            addr = host_part
            port = int(port_part)

    addr = addr.strip().strip("[]")
    return addr, port

def build_stream_settings(query, network, security, address=''):
    if network not in ('tcp', 'raw', 'ws', 'grpc', 'httpupgrade', 'xhttp', 'splithttp'):
        raise ValueError(f"暂不支持传输协议：{network}")
    if security not in ('none', 'tls', 'reality'):
        raise ValueError(f"暂不支持安全类型：{security}")
    stream = {'network': network, 'security': security}
    sni = query.get('sni') or query.get('serverName') or address
    fp = query.get('fp') or query.get('fingerprint') or 'chrome'
    if security == 'reality':
        settings = {'serverName': sni, 'fingerprint': fp}
        for target, aliases in {
            'publicKey': ('pbk', 'publicKey'), 'shortId': ('sid', 'shortId'),
            'spiderX': ('spx', 'spiderX'), 'mldsa65Verify': ('pqv', 'mldsa65Verify'),
        }.items():
            value = next((query[key] for key in aliases if query.get(key)), None)
            if value is not None:
                settings[target] = value
        stream['realitySettings'] = settings
    elif security == 'tls':
        settings = {'serverName': sni, 'fingerprint': fp}
        if query.get('alpn'):
            alpn = query['alpn']
            settings['alpn'] = alpn if isinstance(alpn, list) else [x.strip() for x in alpn.split(',') if x.strip()]
        if 'allowInsecure' in query or 'insecure' in query:
            settings['allowInsecure'] = str(query.get('allowInsecure', query.get('insecure'))).lower() in ('true', '1')
        stream['tlsSettings'] = settings
    path, host = query.get('path') or '/', query.get('host') or ''
    if network == 'ws':
        settings = {'path': path}
        if host:
            settings['headers'] = {'Host': host}
        if query.get('ed'):
            settings['maxEarlyData'] = int(query['ed'])
        if query.get('eh'):
            settings['earlyDataHeaderName'] = query['eh']
        stream['wsSettings'] = settings
    elif network == 'grpc':
        stream['grpcSettings'] = {'serviceName': query.get('serviceName') or query.get('path', ''), 'multiMode': query.get('mode') == 'multi'}
        if query.get('authority') or host:
            stream['grpcSettings']['authority'] = query.get('authority') or host
    elif network == 'httpupgrade':
        stream['httpupgradeSettings'] = {'path': path, 'host': host}
    elif network in ('xhttp', 'splithttp'):
        settings = {'path': path, 'host': host, 'mode': query.get('mode') or 'auto'}
        if query.get('extra'):
            extra = query['extra']
            if isinstance(extra, str):
                try:
                    extra = json.loads(extra)
                except ValueError as exc:
                    raise ValueError('XHTTP extra 必须是有效 JSON') from exc
            if not isinstance(extra, dict):
                raise ValueError('XHTTP extra 必须是 JSON 对象')
            settings['extra'] = deepcopy(extra)
        stream[network + 'Settings'] = settings
    elif query.get('headerType') not in (None, '', 'none'):
        header = {'type': query['headerType'], 'request': {'path': [path]}}
        if host:
            header['request']['headers'] = {'Host': [h.strip() for h in host.split(',') if h.strip()]}
        stream['tcpSettings'] = {'header': header}
    return stream


def stream_query(stream):
    network = stream.get('network', 'tcp')
    security = stream.get('security', 'none')
    params = {'type': network, 'security': security}
    settings = stream.get('realitySettings' if security == 'reality' else 'tlsSettings', {})
    for field, key in [('serverName', 'sni'), ('fingerprint', 'fp'), ('publicKey', 'pbk'), ('shortId', 'sid'), ('spiderX', 'spx'), ('mldsa65Verify', 'pqv')]:
        if settings.get(field):
            params[key] = settings[field]
    if security == 'reality' and not params.get('pbk') and settings.get('password'):
        params['pbk'] = settings['password']
    if settings.get('alpn'):
        params['alpn'] = ','.join(settings['alpn'])
    if 'allowInsecure' in settings:
        params['allowInsecure'] = '1' if settings['allowInsecure'] else '0'
    transport = stream.get(network + 'Settings', {})
    if network == 'ws':
        params.update(path=transport.get('path', '/'), host=transport.get('headers', {}).get('Host', ''))
        if transport.get('maxEarlyData'):
            params['ed'] = transport['maxEarlyData']
        if transport.get('earlyDataHeaderName'):
            params['eh'] = transport['earlyDataHeaderName']
    elif network == 'grpc':
        params['serviceName'] = transport.get('serviceName', '')
        if transport.get('multiMode'):
            params['mode'] = 'multi'
        if transport.get('authority'):
            params['authority'] = transport['authority']
    elif network in ('xhttp', 'splithttp', 'httpupgrade'):
        params.update(path=transport.get('path', '/'), host=transport.get('host', ''))
        if network != 'httpupgrade':
            params['mode'] = transport.get('mode', 'auto')
            if transport.get('extra'):
                params['extra'] = json.dumps(transport['extra'], separators=(',', ':'), ensure_ascii=False)
    elif network in ('tcp', 'raw'):
        header = stream.get('rawSettings', stream.get('tcpSettings', {})).get('header', {})
        if header.get('type') not in (None, 'none'):
            params['headerType'] = header['type']
            params['path'] = ','.join(header.get('request', {}).get('path', ['/']))
            params['host'] = ','.join(header.get('request', {}).get('headers', {}).get('Host', []))
    return params


def link_host(address):
    address = address.strip('[]')
    return f'[{address}]' if ':' in address else address


class ProtocolParser:
    @staticmethod
    def parse_link(link: str) -> Dict[str, Any]:
        """
        解析单条分享链接（vless / trojan / vmess / ss），
        返回统一格式的节点数据对象。
        """
        link = link.strip()
        if not link:
            raise ValueError("链接为空")
            
        if link.startswith("vless://"):
            node = ProtocolParser.parse_vless(link)
        elif link.startswith("trojan://"):
            node = ProtocolParser.parse_trojan(link)
        elif link.startswith("vmess://"):
            node = ProtocolParser.parse_vmess(link)
        elif link.startswith("ss://"):
            node = ProtocolParser.parse_ss(link)
        else:
            raise ValueError(f"不支持的链接协议: {link[:10]}...")
        if not node.get('address') or not 1 <= int(node.get('port', 0)) <= 65535:
            raise ValueError('节点地址或端口无效')
        return node

    @staticmethod
    def parse_vless(link: str) -> Dict[str, Any]:
        """解析支持的 VLESS 分享字段，保留 encryption 与 Reality 参数。"""
        u = urllib.parse.urlparse(link)
        if u.scheme != 'vless':
            raise ValueError("不是合法的 vless 链接")

        uuid = urllib.parse.unquote(u.username or "")
        if not uuid:
            raise ValueError('VLESS 节点缺少用户 ID')
        raw_host = u.hostname or ""
        port = 443 if u.port is None else u.port
        if not raw_host and '@' in u.netloc:
            raw_host = u.netloc.split('@', 1)[-1]
        address, port = clean_node_address(raw_host, port)
        name = urllib.parse.unquote(u.fragment) if u.fragment else f"{address}:{port}"

        # 解析 query 参数，转为普通 dict
        query = dict(urllib.parse.parse_qsl(u.query, keep_blank_values=True))

        # 加密方式（特别保护 ML-KEM 等抗量子算法）
        encryption = query.get('encryption', 'none')
        flow = query.get('flow', '')
        network = query.get('type') or query.get('net') or 'tcp'
        security = query.get('security', 'none')

        # 组装 user 配置
        user_dict = {'id': uuid}
        if encryption:
            user_dict['encryption'] = encryption
        if flow:
            user_dict['flow'] = flow

        stream_settings = build_stream_settings(query, network, security, address)

        outbound = {
            'tag': 'proxy',
            'protocol': 'vless',
            'settings': {
                'vnext': [
                    {
                        'address': address,
                        'port': int(port),
                        'users': [user_dict]
                    }
                ]
            },
            'streamSettings': stream_settings
        }

        # 提炼标签摘要供前端使用
        tags = ['VLESS']
        if security == 'reality':
            tags.append('Reality')
        elif security == 'tls':
            tags.append('TLS')
        if 'mlkem' in encryption.lower():
            tags.append('ML-KEM PQ')
        if network != 'tcp':
            tags.append(network.upper())
        if flow:
            tags.append(flow)

        return {
            'name': name,
            'protocol': 'vless',
            'address': address,
            'port': int(port),
            'security': security,
            'network': network,
            'encryption': encryption,
            'sni': query.get('sni') or query.get('serverName', ''),
            'raw_link': link,
            'tags': tags,
            'outbound': outbound
        }

    @staticmethod
    def parse_trojan(link: str) -> Dict[str, Any]:
        """解析 Trojan 链接"""
        u = urllib.parse.urlparse(link)
        password = urllib.parse.unquote(u.username or "")
        if not password:
            raise ValueError('Trojan 节点缺少密码')
        raw_host = u.hostname or ""
        port = 443 if u.port is None else u.port
        if not raw_host and '@' in u.netloc:
            raw_host = u.netloc.split('@', 1)[-1]
        address, port = clean_node_address(raw_host, port)
        name = urllib.parse.unquote(u.fragment) if u.fragment else f"{address}:{port}"
        query = dict(urllib.parse.parse_qsl(u.query, keep_blank_values=True))

        network = query.get('type') or 'tcp'
        security = query.get('security', 'tls')
        sni = query.get('sni', address)

        stream_settings = build_stream_settings(query, network, security, address)

        outbound = {
            'tag': 'proxy',
            'protocol': 'trojan',
            'settings': {
                'servers': [
                    {
                        'address': address,
                        'port': int(port),
                        'password': password
                    }
                ]
            },
            'streamSettings': stream_settings
        }

        tags = ['Trojan', security.upper()]
        if network != 'tcp': tags.append(network.upper())

        return {
            'name': name,
            'protocol': 'trojan',
            'address': address,
            'port': int(port),
            'security': security,
            'network': network,
            'encryption': '',
            'sni': sni,
            'raw_link': link,
            'tags': tags,
            'outbound': outbound
        }

    @staticmethod
    def parse_vmess(link: str) -> Dict[str, Any]:
        """解析 VMess 链接 (标准 base64 json 结构)"""
        b64_str = link[len("vmess://"):].strip()
        decoded_json = safe_b64decode(b64_str)
        data = json.loads(decoded_json)

        raw_addr = str(data.get('add', '')).strip()
        raw_port = int(data.get('port', 443)) if str(data.get('port', '')).isdigit() else 443
        address, port = clean_node_address(raw_addr, raw_port)
        uuid = str(data.get('id', '')).strip()
        alter_id = int(data.get('aid', 0)) if str(data.get('aid', '')).isdigit() else 0
        network = data.get('net') or 'tcp'
        security = data.get('tls', 'none')
        sni = data.get('sni', '')
        name = data.get('ps') or f"{address}:{port}"

        params = dict(data)
        params["headerType"] = data.get("type", "none")
        stream_settings = build_stream_settings(params, network, 'tls' if security == 'tls' else 'none', address)

        outbound = {
            'tag': 'proxy',
            'protocol': 'vmess',
            'settings': {
                'vnext': [
                    {
                        'address': address,
                        'port': port,
                        'users': [
                            {
                                'id': uuid,
                                'alterId': alter_id,
                                'security': data.get('scy', 'auto')
                            }
                        ]
                    }
                ]
            },
            'streamSettings': stream_settings
        }

        tags = ['VMess']
        if security == 'tls': tags.append('TLS')
        if network != 'tcp': tags.append(network.upper())

        return {
            'name': name,
            'protocol': 'vmess',
            'address': address,
            'port': port,
            'security': security,
            'network': network,
            'encryption': data.get('scy', 'auto'),
            'sni': sni,
            'raw_link': link,
            'tags': tags,
            'outbound': outbound
        }

    @staticmethod
    def parse_ss(link: str) -> Dict[str, Any]:
        body, _, fragment = link[len("ss://"):].partition("#")
        authority, _, query_text = body.partition("?")
        query = dict(urllib.parse.parse_qsl(query_text))
        if query.get("plugin"):
            raise ValueError("暂不支持 Shadowsocks plugin 分享链接")
        try:
            if "@" in authority:
                userinfo, host_port = authority.rsplit("@", 1)
                userinfo = urllib.parse.unquote(userinfo)
                if ":" not in userinfo:
                    userinfo = safe_b64decode(userinfo)
            else:
                decoded = safe_b64decode(urllib.parse.unquote(authority))
                userinfo, host_port = decoded.rsplit("@", 1)
            method, password = userinfo.split(":", 1)
            endpoint = urllib.parse.urlsplit("//" + host_port.rstrip("/"))
            address, port = endpoint.hostname, endpoint.port
            if not address or port is None or not 1 <= port <= 65535 or not method or not password:
                raise ValueError("缺少有效地址、端口或凭据")
        except (ValueError, UnicodeError) as exc:
            raise ValueError("Shadowsocks 链接的地址、端口或凭据编码无效") from exc
        outbound = {
            "tag": "proxy", "protocol": "shadowsocks",
            "settings": {"servers": [{"address": address, "port": port, "method": method, "password": password}]},
        }
        return {
            "name": urllib.parse.unquote(fragment) or "Shadowsocks",
            "protocol": "shadowsocks", "address": address, "port": port,
            "security": "none", "network": "tcp", "encryption": method,
            "sni": "", "raw_link": link, "tags": ["SS", method], "outbound": outbound,
        }

    @staticmethod
    def outbound_to_link(outbound: Dict[str, Any], name: str = "Node") -> str:
        """Export supported share-link fields without changing the outbound."""
        proto = outbound.get("protocol", "vless")
        stream = outbound.get("streamSettings", {})
        params = stream_query(stream)
        fragment = urllib.parse.quote(name, safe="")
        if proto == "vless":
            endpoint = outbound["settings"]["vnext"][0]
            user = endpoint["users"][0]
            params["encryption"] = user.get("encryption", "none")
            if user.get("flow"):
                params["flow"] = user["flow"]
            userinfo = urllib.parse.quote(user["id"], safe="")
            return f'vless://{userinfo}@{link_host(endpoint["address"])}:{endpoint["port"]}?{urllib.parse.urlencode(params)}#{fragment}'
        if proto == "trojan":
            endpoint = outbound["settings"]["servers"][0]
            password = urllib.parse.quote(endpoint["password"], safe="")
            return f'trojan://{password}@{link_host(endpoint["address"])}:{endpoint["port"]}?{urllib.parse.urlencode(params)}#{fragment}'
        if proto in ("shadowsocks", "ss"):
            endpoint = outbound["settings"]["servers"][0]
            method, password = endpoint["method"], endpoint["password"]
            if method.startswith("2022-"):
                userinfo = method + ":" + urllib.parse.quote(password, safe="")
            else:
                userinfo = safe_b64encode(f"{method}:{password}")
            return f'ss://{userinfo}@{link_host(endpoint["address"])}:{endpoint["port"]}#{fragment}'
        if proto == "vmess":
            endpoint = outbound["settings"]["vnext"][0]
            user = endpoint["users"][0]
            data = {
                "v": "2", "ps": name, "add": endpoint["address"], "port": endpoint["port"],
                "id": user["id"], "aid": user.get("alterId", 0), "scy": user.get("security", "auto"),
                "net": stream.get("network", "tcp"), "type": params.get("headerType", "none"),
                "host": params.get("host", ""), "path": params.get("path", params.get("serviceName", "")),
                "tls": "tls" if stream.get("security") == "tls" else "",
                "sni": params.get("sni", ""), "fp": params.get("fp", ""),
            }
            for key in ("mode", "extra", "alpn", "allowInsecure", "authority", "ed", "eh"):
                if key in params:
                    data[key] = params[key]
            return "vmess://" + safe_b64encode(json.dumps(data, separators=(",", ":"), ensure_ascii=False))
        return ""
