"""Generate a private local config and user systemd units, without installing them."""

import argparse
import json
from pathlib import Path
import shlex
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from core.persistence import atomic_write_bytes, atomic_write_json


def unit_value(value):
    value = str(value)
    if any(c in value for c in "\n\r\0"):
        raise ValueError("服务路径不能含控制字符")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def prepare(output, *, project=PROJECT, python=None, xray="/usr/local/bin/xray"):
    output = Path(output).expanduser().resolve()
    project = Path(project).resolve()
    python = Path(python or project / ".venv/bin/python").absolute()
    files = [output / name for name in ("xray.json", "xray-web.env", "xray-web.service", "xray-web-core.service")]
    if any(path.exists() for path in files):
        raise ValueError("生成目标已有配置；为保护现有数据，请使用新的输出目录")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    logs = output / "logs"
    logs.mkdir(exist_ok=True, mode=0o700)
    configuration = {
        "log": {"loglevel": "warning", "access": str(logs / "access.log"), "error": str(logs / "error.log")},
        "inbounds": [
            {"tag": "socks-in", "listen": "127.0.0.1", "port": 20170, "protocol": "socks", "settings": {"auth": "noauth", "udp": True}},
            {"tag": "http-in-20171", "listen": "127.0.0.1", "port": 20171, "protocol": "http", "settings": {}},
            {"tag": "http-in-20172", "listen": "127.0.0.1", "port": 20172, "protocol": "http", "settings": {}},
        ],
        "outbounds": [{"tag": "proxy", "protocol": "blackhole"}, {"tag": "direct", "protocol": "freedom"}, {"tag": "block", "protocol": "blackhole"}],
        "routing": {"domainStrategy": "AsIs", "rules": [{"type": "field", "inboundTag": ["socks-in", "http-in-20171", "http-in-20172"], "outboundTag": "proxy"}]},
    }
    env = {
        "WEB_HOST": "127.0.0.1", "WEB_PORT": "2017", "PROXY_LISTEN_HOST": "127.0.0.1",
        "XRAY_CONFIG_PATH": str(files[0]), "XRAY_BACKUP_PATH": str(output / "xray.json.bak"),
        "XRAY_LOG_DIR": str(logs), "XRAY_BIN": str(Path(xray).absolute()),
        "XRAY_SERVICE_NAME": "xray-web-core", "XRAY_SYSTEMD_USER": "1",
        "XRAY_WEB_DATA_DIR": str(project / "data"),
    }
    atomic_write_json(files[0], configuration)
    atomic_write_bytes(files[1], ("\n".join(key + "=" + shlex.quote(value) for key, value in env.items()) + "\n").encode())
    replacements = {
        "@PROJECT@": unit_value(project), "@PYTHON@": unit_value(python),
        "@MAIN@": unit_value(project / "main.py"), "@ENV@": unit_value(files[1]),
        "@XRAY@": unit_value(Path(xray).absolute()), "@CONFIG@": unit_value(files[0]),
    }
    for destination in files[2:]:
        template = (PROJECT / "service" / destination.name).read_text()
        for key, value in replacements.items():
            template = template.replace(key, value)
        atomic_write_bytes(destination, template.encode(), mode=0o644)
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT / "data/deploy")
    parser.add_argument("--python", type=Path)
    parser.add_argument("--xray", default="/usr/local/bin/xray")
    args = parser.parse_args()
    try:
        for path in prepare(args.output, python=args.python, xray=args.xray):
            print(path)
    except (ValueError, OSError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
