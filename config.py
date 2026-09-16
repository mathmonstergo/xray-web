import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("XRAY_WEB_DATA_DIR", str(BASE_DIR / "data"))).expanduser().resolve()
STATIC_DIR = BASE_DIR / "static"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# 配置文件与数据文件
STORE_FILE = DATA_DIR / "store.json"
XRAY_CONFIG_PATH = Path(os.getenv("XRAY_CONFIG_PATH", "/etc/xray/config.json"))
XRAY_BACKUP_PATH = Path(os.getenv("XRAY_BACKUP_PATH", "/etc/xray/config.json.bak"))
XRAY_BIN = os.getenv("XRAY_BIN", "/usr/local/bin/xray")

# 服务监听
WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("WEB_PORT", "2017"))
WEB_USERNAME = os.getenv("WEB_USERNAME", "admin")
WEB_PASSWORD = os.getenv("WEB_PASSWORD", "")
WEB_ALLOWED_HOSTS = [h.strip() for h in os.getenv("WEB_ALLOWED_HOSTS", "").split(",") if h.strip()]
COMMAND_TIMEOUT = float(os.getenv("COMMAND_TIMEOUT", "15"))
XRAY_SERVICE_NAME = os.getenv("XRAY_SERVICE_NAME", "xray")
XRAY_SYSTEMD_USER = os.getenv("XRAY_SYSTEMD_USER", "0").lower() in ("1", "true", "yes")

# 20170 / 20171 直通当前代理节点；20172 匹配用户分流规则。
SOCKS_PORT = int(os.getenv("SOCKS_PORT", "20170"))
HTTP_PROXY_PORT = int(os.getenv("HTTP_PROXY_PORT", "20171"))
HTTP_ROUTING_PORT = int(os.getenv("HTTP_ROUTING_PORT", "20172"))
# 共享给宿主机或局域网时显式指定监听地址。
PROXY_LISTEN_HOST = os.getenv("PROXY_LISTEN_HOST", "127.0.0.1")
HTTP_PROXY_URL = f"http://127.0.0.1:{HTTP_PROXY_PORT}"
XRAY_LOG_DIR = Path(os.getenv("XRAY_LOG_DIR", "/var/log/xray"))

# 临时测试端口分配范围
TEST_PORT_START = int(os.getenv("TEST_PORT_START", "20180"))
TEST_PORT_END = int(os.getenv("TEST_PORT_END", "20195"))

# Real Ping 目标（经代理发起 HTTP 请求测实际代理延迟）
TEST_CONNECTIVITY_URLS = [
    "http://www.gstatic.com/generate_204",
    "http://cp.cloudflare.com/generate_204",
    "https://www.gstatic.com/generate_204",
]
IP_CHECK_URL = "https://api.ipify.org"
IP_GEO_URL = "http://ip-api.com/json/"

# 下行测速：持续下载、抛弃暖身、取瞬时峰值（与 v2rayN Speed Test 同源理）
SPEED_TEST_URLS = [
    "https://speed.cloudflare.com/__down?bytes=100000000",
    "https://cachefly.cachefly.net/100mb.test",
]
SPEED_TEST_TIMEOUT = float(os.getenv("SPEED_TEST_TIMEOUT", "10"))
SPEED_TEST_WARMUP = float(os.getenv("SPEED_TEST_WARMUP", "1"))
SPEED_TEST_CONCURRENCY = int(os.getenv("SPEED_TEST_CONCURRENCY", "1"))
DELAY_TEST_CONCURRENCY = int(os.getenv("DELAY_TEST_CONCURRENCY", "4"))
REAL_PING_TIMEOUT = float(os.getenv("REAL_PING_TIMEOUT", "5"))
CORE_START_TIMEOUT = float(os.getenv("CORE_START_TIMEOUT", "3"))
TCP_PING_TIMEOUT = float(os.getenv("TCP_PING_TIMEOUT", "2"))


def http_proxy_url(port: int | None = None) -> str:
    host = PROXY_LISTEN_HOST or "127.0.0.1"
    host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host).strip("[]")
    if ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{int(port or HTTP_PROXY_PORT)}"
