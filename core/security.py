"""Same-origin access for the single-user local console."""

import base64
import binascii
import ipaddress
import secrets
from urllib.parse import urlsplit

from starlette.responses import JSONResponse


def is_loopback(host):
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def authority(value, scheme):
    parsed = urlsplit(f"{scheme}://{value}")
    if not parsed.hostname or parsed.username is not None or parsed.path or parsed.query or parsed.fragment:
        raise ValueError("Invalid Host")
    return parsed.hostname.lower().rstrip("."), parsed.port or (443 if scheme == "https" else 80)


class LocalAccessMiddleware:
    def __init__(self, app, *, host="127.0.0.1", username="admin", password="", allowed_hosts=None):
        self.app = app
        self.username = username.encode("utf-8")
        self.password = password.encode("utf-8")
        if not is_loopback(host) and not password:
            raise ValueError("Web 监听非本机地址时必须设置 WEB_PASSWORD")
        defaults = ["localhost", "127.0.0.1", "::1"]
        if host not in ("0.0.0.0", "::"):
            defaults.append(host)
        self.allowed_hosts = {h.lower().strip("[]").rstrip(".") for h in (allowed_hosts or defaults)}
        if any(not h or "*" in h or "/" in h for h in self.allowed_hosts):
            raise ValueError("WEB_ALLOWED_HOSTS 必须是具体主机名或 IP")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.lower(): v for k, v in scope.get("headers", [])}

        async def reject(status, detail, extra=None):
            response = JSONResponse({"detail": detail}, status_code=status, headers={"Cache-Control": "no-store", **(extra or {})})
            await response(scope, receive, send)

        try:
            if sum(k.lower() == b"host" for k, _ in scope.get("headers", [])) != 1:
                raise ValueError("Invalid Host")
            scheme = scope.get("scheme", "http")
            host, port = authority(headers.get(b"host", b"").decode("ascii"), scheme)
            if host not in self.allowed_hosts:
                return await reject(400, "不允许的 Host，请检查 WEB_ALLOWED_HOSTS")
            origin = headers.get(b"origin")
            if origin:
                parsed = urlsplit(origin.decode("ascii"))
                if parsed.scheme not in ("http", "https") or parsed.path or parsed.query or parsed.fragment:
                    raise ValueError("Invalid Origin")
                origin_host, origin_port = authority(parsed.netloc, parsed.scheme)
                if (parsed.scheme, origin_host, origin_port) != (scheme, host, port):
                    return await reject(403, "不允许跨域访问本地控制台")
            if scope.get("path", "").startswith("/api/") and headers.get(b"sec-fetch-site") == b"cross-site":
                return await reject(403, "不允许跨站访问本地控制台")
        except (ValueError, UnicodeError):
            return await reject(400, "无效的 Host 或 Origin")

        if self.password:
            valid = False
            try:
                kind, token = headers.get(b"authorization", b"").split(None, 1)
                username, password = base64.b64decode(token, validate=True).split(b":", 1)
                valid = (kind.lower() == b"basic") & secrets.compare_digest(username, self.username) & secrets.compare_digest(password, self.password)
            except (ValueError, binascii.Error):
                pass
            if not valid:
                return await reject(401, "需要认证", {"WWW-Authenticate": 'Basic realm="Xray Web", charset="UTF-8"'})

        async def secure_send(message):
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.extend([(b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"), (b"referrer-policy", b"same-origin")])
                if scope.get("path", "").startswith("/api/"):
                    response_headers = [(k, v) for k, v in response_headers if k.lower() != b"cache-control"]
                    response_headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": response_headers}
            await send(message)

        await self.app(scope, receive, secure_send)
