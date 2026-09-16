import os
from pathlib import Path
import tempfile

ROOT = tempfile.TemporaryDirectory(prefix="xray-web-tests-")
os.environ.update({
    "XRAY_WEB_DATA_DIR": str(Path(ROOT.name) / "data"),
    "XRAY_CONFIG_PATH": str(Path(ROOT.name) / "xray.json"),
    "XRAY_BACKUP_PATH": str(Path(ROOT.name) / "xray.json.bak"),
    "XRAY_LOG_DIR": str(Path(ROOT.name) / "logs"),
    "WEB_HOST": "127.0.0.1", "WEB_PASSWORD": "", "WEB_ALLOWED_HOSTS": "",
    "PROXY_LISTEN_HOST": "127.0.0.1", "XRAY_SYSTEMD_USER": "0",
    "SOCKS_PORT": "20170", "HTTP_PROXY_PORT": "20171", "HTTP_ROUTING_PORT": "20172",
})

from core.parser import ProtocolParser


def node(host="192.0.2.10", name="Fixture"):
    return ProtocolParser.parse_link(
        f"vless://11111111-1111-4111-8111-111111111111@{host}:443?encryption=none&security=none#{name}")
