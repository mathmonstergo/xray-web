from tests.support import node

import json
from pathlib import Path
import shutil
import unittest
from urllib.parse import quote, urlencode

from core.parser import ProtocolParser, safe_b64encode
from core.routing_manager import classify_rule_item
from core.sub_manager import SubscriptionManager
from core.runtime import XrayRuntime
import config


class ParserTests(unittest.TestCase):
    def test_vless_transport_roundtrips(self):
        for network in ("tcp", "raw", "ws", "grpc", "httpupgrade", "xhttp", "splithttp"):
            params = {"type": network, "security": "tls", "sni": "cdn.example.net", "path": "/fixture", "host": "cdn.example.net", "alpn": "h2,http/1.1"}
            if network in ("xhttp", "splithttp"):
                params.update(mode="packet-up", extra=json.dumps({"noGRPCHeader": True}))
            if network == "grpc": params.update(serviceName="fixture", mode="multi")
            link = "vless://11111111-1111-4111-8111-111111111111@[2001:db8::1]:443?" + urlencode(params)
            with self.subTest(network=network):
                parsed = ProtocolParser.parse_link(link)
                exported = ProtocolParser.outbound_to_link(parsed["outbound"])
                self.assertEqual(ProtocolParser.parse_link(exported)["outbound"], parsed["outbound"])

    def test_reality_and_encryption_fields_are_preserved(self):
        params = {"security": "reality", "pbk": "fixture-key", "sid": "0123", "spx": "/fixture", "pqv": "fixture-pq-key", "sni": "example.net", "fp": "chrome", "encryption": "mlkem768x25519plus.native.fixture+key", "flow": "xtls-rprx-vision"}
        link = node()["raw_link"].split("?", 1)[0] + "?" + urlencode(params)
        parsed = ProtocolParser.parse_link(link)
        exported = ProtocolParser.outbound_to_link(parsed["outbound"])
        self.assertEqual(ProtocolParser.parse_link(exported)["outbound"], parsed["outbound"])
        self.assertEqual(parsed["encryption"], params["encryption"])

    def test_trojan_special_password_ipv6_and_xhttp_roundtrip(self):
        password = "fixture#pass@word:/?"
        link = f"trojan://{quote(password,safe='')}@[2001:db8::1]:443?type=xhttp&security=tls&path=%2Ftest&mode=stream-up"
        parsed = ProtocolParser.parse_link(link)
        self.assertEqual(parsed["outbound"]["settings"]["servers"][0]["password"], password)
        self.assertEqual(ProtocolParser.parse_link(ProtocolParser.outbound_to_link(parsed["outbound"]))["outbound"], parsed["outbound"])

    def test_shadowsocks_formats_and_ipv6(self):
        links = [
            "ss://" + safe_b64encode("aes-128-gcm:fixture") + "@[2001:db8::1]:8388",
            "ss://" + safe_b64encode("aes-128-gcm:fixture@192.0.2.10:8388"),
            "ss://2022-blake3-aes-128-gcm:MDEyMzQ1Njc4OWFiY2RlZg%3D%3D@[2001:db8::1]:8388",
        ]
        for link in links:
            with self.subTest(link=link):
                parsed = ProtocolParser.parse_link(link)
                self.assertEqual(ProtocolParser.parse_link(ProtocolParser.outbound_to_link(parsed["outbound"]))["outbound"], parsed["outbound"])

    def test_unknown_transport_and_malformed_extra_are_rejected(self):
        for query in ("type=not-supported", "type=xhttp&extra=not-json", "type=xhttp&extra=[]"):
            with self.assertRaises(ValueError):
                ProtocolParser.parse_link(node()["raw_link"].split("?", 1)[0] + "?" + query)

    def test_partial_subscription_is_rejected_instead_of_deleting_old_nodes(self):
        content = node()["raw_link"] + "\nss://bad"
        nodes, errors = SubscriptionManager.parse_with_diagnostics(content)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(errors[0]["line"], 2)
        with self.assertRaisesRegex(ValueError, "第 2 行"):
            SubscriptionManager.parse_raw_text(content)

    def test_base64_subscription_and_comments(self):
        content = "# comment\n" + node()["raw_link"]
        self.assertEqual(len(SubscriptionManager.parse_raw_text(safe_b64encode(content))), 1)

    def test_ipv6_and_regex_routing_classification(self):
        self.assertEqual(classify_rule_item("2001:db8:1:2:3:4:5:6"), "ip")
        self.assertEqual(classify_rule_item("regexp:example.com/path"), "domain")

    @unittest.skipUnless(Path(config.XRAY_BIN).is_file(), "Xray binary is not installed")
    def test_xhttp_config_passes_native_xray_validation(self):
        link = node()["raw_link"].split("?", 1)[0] + "?type=xhttp&path=%2Ffixture&host=cdn.example.net&mode=packet-up"
        outbound = ProtocolParser.parse_link(link)["outbound"]
        self.assertEqual(outbound["streamSettings"]["xhttpSettings"]["path"], "/fixture")
        XrayRuntime().validate({"log": {"loglevel": "none"}, "outbounds": [outbound]})
