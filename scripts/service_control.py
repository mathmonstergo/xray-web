"""Control only the console process created by scripts/start.sh."""

import argparse
import fcntl
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import json
import base64
import http.client

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import config
from core.persistence import atomic_write_json

MAIN = PROJECT / "main.py"


def process_record(pid, *, proc_root=Path("/proc")):
    if not isinstance(pid, int) or pid <= 1:
        return None
    process = proc_root / str(pid)
    try:
        if process.stat().st_uid != os.getuid():
            return None
        argv = process.joinpath("cmdline").read_bytes().split(b"\0")
        if str(MAIN).encode() not in argv:
            return None
        if process.joinpath("cwd").resolve() != PROJECT:
            return None
        stats = process.joinpath("stat").read_text()
        fields = stats[stats.rfind(")") + 2:].split()
        if fields[0] == "Z":
            return None
        return {"pid": pid, "start_ticks": fields[19], "main": str(MAIN)}
    except (OSError, IndexError, ValueError):
        return None


def owned_record(pid_file):
    try:
        record = json.loads(pid_file.read_text())
        if not isinstance(record, dict):
            return None
        current = process_record(record.get("pid"))
        return current if current is not None and current == record else None
    except (OSError, ValueError):
        return None


def ensure_port_available():
    addresses = socket.getaddrinfo(config.WEB_HOST, config.WEB_PORT, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE)
    family, kind, protocol, _, address = addresses[0]
    with socket.socket(family, kind, protocol) as probe:
        try:
            probe.bind(address)
        except OSError as exc:
            raise RuntimeError(f"{config.WEB_HOST}:{config.WEB_PORT} 无法监听，请检查占用和地址配置；未终止任何进程") from exc


def process_is_ready(host, pid):
    headers = {}
    if config.WEB_PASSWORD:
        token = base64.b64encode(f"{config.WEB_USERNAME}:{config.WEB_PASSWORD}".encode()).decode()
        headers["Authorization"] = "Basic " + token
    if config.WEB_ALLOWED_HOSTS:
        allowed = config.WEB_ALLOWED_HOSTS[0]
        headers["Host"] = f"[{allowed}]:{config.WEB_PORT}" if ":" in allowed else f"{allowed}:{config.WEB_PORT}"
    connection = http.client.HTTPConnection(host, config.WEB_PORT, timeout=0.3)
    try:
        connection.request("GET", "/api/health", headers=headers)
        response = connection.getresponse()
        data = json.loads(response.read(4096))
        return response.status == 200 and isinstance(data, dict) and data.get("pid") == pid
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def start(pid_file):
    record = owned_record(pid_file)
    if record:
        print(f"Xray Web 已运行 (PID {record['pid']})")
        return
    ensure_port_available()
    log_path = config.DATA_DIR / "web.log"
    fd = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "ab") as log:
        process = subprocess.Popen([sys.executable, str(MAIN)], cwd=PROJECT,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   start_new_session=True, close_fds=True)
    host = "127.0.0.1" if config.WEB_HOST == "0.0.0.0" else "::1" if config.WEB_HOST == "::" else config.WEB_HOST
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"启动失败，请查看 {log_path}")
        if process_is_ready(host, process.pid):
            record = process_record(process.pid)
            if record and process.poll() is None:
                try:
                    atomic_write_json(pid_file, record)
                except OSError:
                    process.terminate()
                    process.wait(timeout=3)
                    raise
                print(f"Xray Web 已启动：http://{config.WEB_HOST}:{config.WEB_PORT} (PID {process.pid})")
                return
        time.sleep(0.1)
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)
    raise RuntimeError(f"启动超时，请查看 {log_path}")


def stop(pid_file):
    record = owned_record(pid_file)
    if record is None:
        print("未找到由本脚本启动且身份匹配的控制台进程；systemd 部署请使用 systemctl 管理")
        return
    pid = record["pid"]
    # A detached console owns its process group, including temporary test cores.
    if os.getpgid(pid) == pid:
        os.killpg(pid, signal.SIGTERM)
    else:
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 6
    while process_record(pid) == record and time.monotonic() < deadline:
        time.sleep(0.1)
    if process_record(pid) == record:
        if os.getpgid(pid) == pid:
            os.killpg(pid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
    pid_file.unlink(missing_ok=True)
    print("Xray Web 已停止")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop"])
    args = parser.parse_args()
    pid_file = config.DATA_DIR / "web.pid"
    with (config.DATA_DIR / "web.pid.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            (start if args.action == "start" else stop)(pid_file)
        except (RuntimeError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
