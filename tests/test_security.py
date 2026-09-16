from tests import support

import base64
import unittest

from core.security import LocalAccessMiddleware


class SecurityTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, *, host="127.0.0.1:2017", origin=None, auth=None, password="", method="GET", site=None):
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})
        middleware = LocalAccessMiddleware(app, password=password)
        headers = [(b"host", host.encode())]
        for key, value in ((b"origin", origin), (b"authorization", auth), (b"sec-fetch-site", site)):
            if value is not None: headers.append((key, value.encode()))
        messages = []
        async def receive(): return {"type": "http.request", "body": b""}
        async def send(event): messages.append(event)
        await middleware({"type": "http", "scheme": "http", "path": "/api/nodes", "method": method, "headers": headers}, receive, send)
        return next(m for m in messages if m["type"] == "http.response.start")

    async def test_local_default_remains_passwordless(self):
        self.assertEqual((await self.request())["status"], 200)

    async def test_configured_password_rejects_anonymous_and_wrong_password(self):
        for auth in (None, "Basic " + base64.b64encode(b"admin:wrong").decode(), "Basic !!"):
            with self.subTest(auth=auth):
                response = await self.request(password="fixture", auth=auth)
                self.assertEqual(response["status"], 401)
                self.assertIn(b"www-authenticate", dict(response["headers"]))

    async def test_basic_auth_and_same_origin_work(self):
        auth = "Basic " + base64.b64encode(b"admin:fixture").decode()
        response = await self.request(password="fixture", auth=auth, origin="http://127.0.0.1:2017", method="POST")
        self.assertEqual(response["status"], 200)
        self.assertEqual(dict(response["headers"])[b"cache-control"], b"no-store")

    async def test_cross_origin_read_write_and_preflight_are_rejected(self):
        for method in ("GET", "POST", "OPTIONS"):
            self.assertEqual((await self.request(origin="https://untrusted.example", method=method))["status"], 403)

    async def test_untrusted_host_and_null_origin_are_rejected(self):
        self.assertEqual((await self.request(host="untrusted.example:2017"))["status"], 400)
        self.assertEqual((await self.request(origin="null"))["status"], 400)

    async def test_cross_site_request_without_origin_is_rejected(self):
        self.assertEqual((await self.request(site="cross-site"))["status"], 403)

    def test_remote_bind_requires_password(self):
        with self.assertRaises(ValueError):
            LocalAccessMiddleware(None, host="0.0.0.0")
        LocalAccessMiddleware(None, host="0.0.0.0", password="fixture")
