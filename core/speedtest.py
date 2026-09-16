"""节点延迟与下行测速。

分层对齐 v2rayN：
- TCP Ping：直连节点 IP:Port 的三次握手 RTT（廉价端口探测）
- Real Ping：临时拉起 Xray，经本地代理请求 generate_204，测真实代理延迟
- Speed Test：经代理持续下载，抛弃暖身窗口，每秒上报瞬时峰值

延迟测试走 Real Ping（TCP Ping 仅作端口预检）。
速度测试先 Real Ping，通路有效才下载；纯测速并发默认为 1。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
import tempfile
from pathlib import Path
from functools import wraps
from contextlib import contextmanager
from queue import Queue
from typing import Any, Callable, Dict, Generator, Iterator, List, Optional, Tuple

import requests

import config
from core.store import store
from core.persistence import atomic_write_json

ProgressCallback = Callable[[Dict[str, Any]], None]


class CancelledError(RuntimeError):
    """测速/延迟测试被用户取消。"""


def _cancelled(cancel_event: Optional[threading.Event]) -> bool:
    return bool(cancel_event and cancel_event.is_set())


def _raise_if_cancelled(cancel_event: Optional[threading.Event]) -> None:
    if _cancelled(cancel_event):
        raise CancelledError("已取消")


def format_speed(bytes_per_sec: float) -> str:
    if bytes_per_sec <= 0:
        return "0 KB/s"
    if bytes_per_sec >= 1024 * 1024:
        return f"{bytes_per_sec / (1024 * 1024):.1f} MB/s"
    if bytes_per_sec >= 1024:
        kb = bytes_per_sec / 1024
        return f"{kb:.1f} KB/s" if kb < 100 else f"{int(kb)} KB/s"
    return f"{int(bytes_per_sec)} B/s"


def _normalize_host(host: str) -> str:
    clean = str(host).strip().strip("[]")
    if "://" in clean:
        clean = clean.split("://", 1)[1].split("/", 1)[0]
    if clean.count(":") == 1 and not clean.startswith("["):
        # host:port 形式，剥端口；IPv6 含多个冒号，不处理
        host_part, maybe_port = clean.rsplit(":", 1)
        if maybe_port.isdigit():
            clean = host_part
    return clean


def tcp_ping(host: str, port: int, timeout: float = None, count: int = 3) -> int:
    """直连节点地址的 TCP 三次握手 RTT（毫秒），失败返回 -1。"""
    if not host or not port:
        return -1
    timeout = config.TCP_PING_TIMEOUT if timeout is None else timeout
    clean_host = _normalize_host(host)
    delays: List[int] = []
    for i in range(count):
        t0 = time.monotonic()
        try:
            with socket.create_connection((clean_host, int(port)), timeout=timeout):
                delays.append(int((time.monotonic() - t0) * 1000))
        except Exception:
            pass
        if i < count - 1:
            time.sleep(0.04)
    return int(sum(delays) / len(delays)) if delays else -1


class _PortAllocator:
    """线程安全的临时测速端口分配，避免并发 TOCTOU 抢同一端口。"""

    def __init__(self, start: int, end: int):
        self._start = start
        self._end = end
        self._lock = threading.Lock()
        self._held: set = set()

    def acquire(self) -> int:
        with self._lock:
            for port in range(self._start, self._end + 1):
                if port in self._held:
                    continue
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    try:
                        s.bind(("127.0.0.1", port))
                    except OSError:
                        continue
                self._held.add(port)
                return port
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]
            self._held.add(port)
            return port

    def release(self, port: int) -> None:
        with self._lock:
            self._held.discard(port)


_ports = _PortAllocator(config.TEST_PORT_START, config.TEST_PORT_END)


def _wait_port_ready(port: int, timeout: float, proc=None, cancel_event=None) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _raise_if_cancelled(cancel_event)
        if proc is not None and proc.poll() is not None:
            return False
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.05)
    return False


def _active_http_proxy() -> Dict[str, str]:
    ports = store.get_ports() if hasattr(store, "get_ports") else {}
    http_port = int(ports.get("http", config.HTTP_PROXY_PORT))
    url = f"http://127.0.0.1:{http_port}"
    return {"http": url, "https": url}


def _build_temp_config(node: Dict[str, Any], port: int) -> Dict[str, Any]:
    outbound = dict(node.get("outbound") or {})
    outbound["tag"] = "proxy"
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{
            "tag": "http-in",
            "port": port,
            "listen": "127.0.0.1",
            "protocol": "http",
            "settings": {"allowTransparent": False},
        }],
        "outbounds": [
            outbound,
            {"protocol": "freedom", "tag": "direct"},
            {"protocol": "blackhole", "tag": "block"},
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [{"type": "field", "inboundTag": ["http-in"], "outboundTag": "proxy"}],
        },
    }


@contextmanager
def _temporary_core(node, cancel_event=None):
    """Isolate every probe from switches to the active system core."""
    if not node.get("outbound"):
        raise RuntimeError("节点缺少 outbound 配置，无法测代理通路")
    _raise_if_cancelled(cancel_event)
    port = _ports.acquire()
    try:
        with tempfile.TemporaryDirectory(prefix="xray-web-probe-") as directory:
            path = Path(directory) / "config.json"
            atomic_write_json(path, _build_temp_config(node, port))
            with tempfile.TemporaryFile() as errors:
                proc = subprocess.Popen(
                    [config.XRAY_BIN, "run", "-c", str(path)],
                    stdout=subprocess.DEVNULL, stderr=errors)
                try:
                    if not _wait_port_ready(port, config.CORE_START_TIMEOUT, proc, cancel_event):
                        errors.seek(0)
                        detail = errors.read(2048).decode("utf-8", errors="replace").strip()
                        raise RuntimeError(detail or "临时核心启动超时，本地端口未就绪")
                    url = f"http://127.0.0.1:{port}"
                    yield {"http": url, "https": url}
                    if proc.poll() is not None:
                        raise RuntimeError("临时核心在测试期间退出")
                finally:
                    if proc.poll() is None:
                        try:
                            proc.terminate()
                        except ProcessLookupError:
                            pass
                        try:
                            proc.wait(timeout=1.5)
                        except subprocess.TimeoutExpired:
                            try:
                                proc.kill()
                            except ProcessLookupError:
                                pass
                            proc.wait(timeout=2)
    finally:
        _ports.release(port)


@contextmanager
def _proxies_for_node(node, cancel_event=None):
    with _temporary_core(node, cancel_event) as proxies:
        yield proxies


def real_ping(proxies: Dict[str, str], timeout: float = None, cancel_event=None) -> Tuple[int, str]:
    """经代理请求 generate_204，返回 (延迟ms, 错误信息)。失败延迟为 -1。"""
    timeout = config.REAL_PING_TIMEOUT if timeout is None else timeout
    last_error = "连接超时"
    for url in config.TEST_CONNECTIVITY_URLS:
        _raise_if_cancelled(cancel_event)
        t0 = time.monotonic()
        try:
            resp = requests.get(
                url,
                proxies=proxies,
                timeout=timeout,
                allow_redirects=False,
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            )
            cost = int((time.monotonic() - t0) * 1000)
            resp.close()
            _raise_if_cancelled(cancel_event)
            # 204 / 200 / 301 / 302 都视为通路有效
            if resp.status_code in (200, 204, 301, 302, 307, 308) and cost >= 0:
                return cost, ""
            last_error = f"HTTP {resp.status_code}"
        except CancelledError:
            raise
        except requests.exceptions.Timeout:
            last_error = "连接超时"
        except requests.exceptions.ProxyError:
            last_error = "代理握手失败"
        except requests.exceptions.ConnectionError:
            last_error = "连接失败"
        except Exception as exc:
            last_error = str(exc) or "请求异常"
    return -1, last_error


def _iter_speed_urls() -> List[str]:
    urls = [u for u in (config.SPEED_TEST_URLS or []) if u]
    return urls or ["https://speed.cloudflare.com/__down?bytes=100000000"]


def stream_speed(
    proxies: Dict[str, str],
    on_progress: Optional[ProgressCallback] = None,
    timeout: float = None,
    warmup: float = None,
    cancel_event: Optional[threading.Event] = None,
) -> Tuple[bool, str, str]:
    """持续下载并取暖身后瞬时峰值。

    返回 (成功, 速度字符串, 错误信息)。
    on_progress 每秒收到 {speed, peak, bytes, elapsed, done}。
    """
    timeout = config.SPEED_TEST_TIMEOUT if timeout is None else timeout
    warmup = config.SPEED_TEST_WARMUP if warmup is None else warmup
    connect_timeout = min(5.0, max(2.0, timeout / 5))
    last_error = "测速超时"

    for url in _iter_speed_urls():
        _raise_if_cancelled(cancel_event)
        t_start = time.monotonic()
        total_bytes = 0
        window_bytes = 0
        window_t = t_start
        last_report = t_start
        peak = 0.0
        warmed = False
        try:
            with requests.get(
                url,
                proxies=proxies,
                stream=True,
                timeout=(connect_timeout, min(timeout + 2, 2.0)),
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            ) as resp:
                if resp.status_code != 200:
                    last_error = f"HTTP {resp.status_code}"
                    continue
                for chunk in resp.iter_content(chunk_size=16384):
                    _raise_if_cancelled(cancel_event)
                    now = time.monotonic()
                    elapsed = now - t_start
                    if elapsed >= timeout:
                        break
                    if not chunk:
                        continue
                    n = len(chunk)
                    total_bytes += n
                    window_bytes += n

                    if not warmed and elapsed >= warmup:
                        warmed = True
                        window_bytes = 0
                        window_t = now
                        last_report = now
                        continue

                    window_elapsed = now - window_t
                    if warmed and window_elapsed >= 1.0:
                        inst = window_bytes / window_elapsed
                        if inst > peak:
                            peak = inst
                        if on_progress and now - last_report >= 0.5:
                            on_progress({
                                "speed": format_speed(max(peak, inst)),
                                "peak": format_speed(peak) if peak > 0 else format_speed(inst),
                                "instant": format_speed(inst),
                                "bytes": total_bytes,
                                "elapsed": round(elapsed, 2),
                                "done": False,
                            })
                            last_report = now
                        window_bytes = 0
                        window_t = now

            _raise_if_cancelled(cancel_event)
            elapsed = time.monotonic() - t_start
            # 末窗残余
            tail = time.monotonic() - window_t
            if warmed and tail > 0.15 and window_bytes > 0:
                inst = window_bytes / tail
                if inst > peak:
                    peak = inst

            if peak <= 0 and total_bytes > 0 and elapsed > 0:
                # 样本不足时报告真实全程平均，不虚构暖身后的峰值。
                peak = total_bytes / elapsed

            if peak > 0:
                speed_str = format_speed(peak)
                if on_progress:
                    on_progress({
                        "speed": speed_str,
                        "peak": speed_str,
                        "bytes": total_bytes,
                        "elapsed": round(elapsed, 2),
                        "done": True,
                    })
                return True, speed_str, ""
            last_error = "未下载到有效数据"
        except CancelledError:
            raise
        except requests.exceptions.Timeout:
            last_error = "测速超时"
        except requests.exceptions.ProxyError:
            last_error = "代理握手失败"
        except requests.exceptions.ConnectionError:
            last_error = "连接失败"
        except Exception as exc:
            last_error = str(exc) or "测速异常"
    _raise_if_cancelled(cancel_event)
    return False, "超时", last_error


def _emit(on_progress: Optional[ProgressCallback], payload: Dict[str, Any]) -> None:
    if on_progress:
        on_progress(payload)


_test_slots = {
    False: threading.BoundedSemaphore(max(1, config.DELAY_TEST_CONCURRENCY)),
    True: threading.BoundedSemaphore(max(1, config.SPEED_TEST_CONCURRENCY)),
}


def limited_test(speed):
    def decorate(function):
        @wraps(function)
        def run(node_id, persist=True, on_progress=None, cancel_event=None):
            semaphore = _test_slots[speed]
            while True:
                _raise_if_cancelled(cancel_event)
                if semaphore.acquire(timeout=0.1):
                    break
            try:
                _raise_if_cancelled(cancel_event)
                return function(node_id, persist=persist, on_progress=on_progress, cancel_event=cancel_event)
            finally:
                semaphore.release()
        return run
    return decorate


@limited_test(False)
def test_node_delay(node_id: str, persist: bool = True, on_progress: Optional[ProgressCallback] = None, cancel_event: Optional[threading.Event] = None) -> Dict[str, Any]:
    """Real Ping：经代理测真实延迟。TCP Ping 仅作端口预检，失败不阻断。"""
    node = store.get_node(node_id)
    if not node:
        raise ValueError("节点不存在")
    host, port = node.get("address"), node.get("port")
    if not host or not port:
        raise ValueError("节点缺少地址或端口")

    _raise_if_cancelled(cancel_event)
    _emit(on_progress, {
        "node_id": node_id,
        "phase": "tcp",
        "message": "TCP 探测中",
        "done": False,
    })
    tcp = tcp_ping(host, port, count=1)
    _raise_if_cancelled(cancel_event)

    _emit(on_progress, {
        "node_id": node_id,
        "phase": "ping",
        "tcp_latency": tcp if tcp > 0 else None,
        "message": "代理延迟测试中" if tcp > 0 else "TCP 未通，继续测代理通路",
        "done": False,
    })
    try:
        with _proxies_for_node(node, cancel_event) as proxies:
            _raise_if_cancelled(cancel_event)
            delay, err = real_ping(proxies, cancel_event=cancel_event)
    except CancelledError:
        raise
    except Exception as exc:
        delay, err = -1, str(exc) or "临时核心启动失败"

    _raise_if_cancelled(cancel_event)
    if delay >= 0:
        store.update_node_delay(node_id, delay, persist=persist)
        result = {
            "success": True,
            "latency": delay,
            "tcp_latency": tcp if tcp > 0 else None,
            "proxy_latency": max(0, delay - tcp) if (delay >= 0 and tcp > 0) else None,
            "node_id": node_id,
            "message": "",
            "done": True,
        }
    else:
        store.update_node_delay(node_id, -1, persist=persist)
        result = {
            "success": False,
            "latency": -1,
            "tcp_latency": tcp if tcp > 0 else -1,
            "node_id": node_id,
            "message": err or "代理延迟超时",
            "done": True,
        }
    _emit(on_progress, result)
    return result


@limited_test(True)
def test_node_speed(node_id: str, persist: bool = True, on_progress: Optional[ProgressCallback] = None, cancel_event: Optional[threading.Event] = None) -> Dict[str, Any]:
    """Mixed：Real Ping 成功后持续下载，上报瞬时峰值。TCP 失败不阻断。"""
    node = store.get_node(node_id)
    if not node:
        raise ValueError("节点不存在")
    if not node.get("outbound"):
        raise ValueError("节点缺少 outbound 配置")

    def progress(extra: Dict[str, Any]) -> None:
        payload = {"node_id": node_id, **extra}
        _emit(on_progress, payload)

    _raise_if_cancelled(cancel_event)
    progress({"phase": "tcp", "message": "TCP 探测中", "done": False})
    tcp = tcp_ping(node.get("address"), node.get("port"), count=1)
    _raise_if_cancelled(cancel_event)

    progress({
        "phase": "ping",
        "message": "代理延迟测试中" if tcp > 0 else "TCP 未通，继续测代理通路",
        "tcp_latency": tcp if tcp > 0 else None,
        "done": False,
    })
    try:
        with _proxies_for_node(node, cancel_event) as proxies:
            _raise_if_cancelled(cancel_event)
            delay, ping_err = real_ping(proxies, cancel_event=cancel_event)
            if delay < 0:
                store.update_node_speed(node_id, "超时", persist=persist)
                result = {
                    "success": False,
                    "speed": "超时",
                    "latency": -1,
                    "tcp_latency": tcp if tcp > 0 else -1,
                    "node_id": node_id,
                    "message": ping_err or "代理通路无效，跳过测速",
                    "phase": "done",
                    "done": True,
                }
                progress(result)
                return result

            store.update_node_delay(node_id, delay, persist=persist)
            progress({
                "phase": "speed",
                "message": "下载测速中",
                "latency": delay,
                "tcp_latency": tcp if tcp > 0 else None,
                "speed": "测速中",
                "done": False,
            })

            def _speed_tick(info: Dict[str, Any]) -> None:
                progress({
                    "phase": "speed",
                    "latency": delay,
                    "tcp_latency": tcp if tcp > 0 else None,
                    "message": "下载测速中",
                    **info,
                    "done": False,
                })

            ok, speed_str, err = stream_speed(proxies, on_progress=_speed_tick, cancel_event=cancel_event)
            if ok:
                store.update_node_speed(node_id, speed_str, persist=persist)
                result = {
                    "success": True,
                    "speed": speed_str,
                    "latency": delay,
                    "tcp_latency": tcp if tcp > 0 else None,
                    "proxy_latency": max(0, delay - tcp) if (delay >= 0 and tcp > 0) else None,
                    "node_id": node_id,
                    "message": "",
                    "phase": "done",
                    "done": True,
                }
            else:
                store.update_node_speed(node_id, "超时", persist=persist)
                result = {
                    "success": False,
                    "speed": "超时",
                    "latency": delay,
                    "tcp_latency": tcp if tcp > 0 else None,
                    "proxy_latency": max(0, delay - tcp) if (delay >= 0 and tcp > 0) else None,
                    "node_id": node_id,
                    "message": err or "测速超时",
                    "phase": "done",
                    "done": True,
                }
            progress(result)
            return result
    except CancelledError:
        raise
    except Exception as exc:
        store.update_node_speed(node_id, "超时", persist=persist)
        result = {
            "success": False,
            "speed": "超时",
            "latency": -1,
            "node_id": node_id,
            "message": str(exc) or "测速异常",
            "phase": "done",
            "done": True,
        }
        progress(result)
        return result

    store.update_node_speed(node_id, "超时", persist=persist)
    result = {
        "success": False,
        "speed": "超时",
        "latency": -1,
        "node_id": node_id,
        "message": "测速失败",
        "phase": "done",
        "done": True,
    }
    progress(result)
    return result


def iter_batch_progress(
    node_ids: List[str],
    speed: bool = False,
    persist: bool = False,
    cancel_event: Optional[threading.Event] = None,
) -> Iterator[Dict[str, Any]]:
    """按并发限制跑延迟或测速，实时产出进度事件，最后一条 type=complete。"""
    ids = list(dict.fromkeys(n for n in node_ids if n))
    if not ids:
        yield {"type": "complete", "tested": 0, "results": []}
        return

    cancel_event = cancel_event or threading.Event()
    worker_fn = test_node_speed if speed else test_node_delay
    concurrency = (
        max(1, int(config.SPEED_TEST_CONCURRENCY))
        if speed
        else max(1, int(config.DELAY_TEST_CONCURRENCY))
    )
    concurrency = min(concurrency, len(ids))
    events: Queue = Queue()
    results: List[Dict[str, Any]] = []
    results_lock = threading.Lock()

    def _put(event: Dict[str, Any]) -> None:
        events.put(event)

    def _cancelled_result(n_id: str) -> Dict[str, Any]:
        res = {
            "success": False,
            "node_id": n_id,
            "done": True,
            "phase": "done",
            "cancelled": True,
            "message": "已取消",
            "latency": -1,
        }
        if speed:
            res["speed"] = "超时"
        return res

    def _run(n_id: str) -> None:
        if cancel_event.is_set():
            res = _cancelled_result(n_id)
            with results_lock:
                results.append(res)
            _put({"type": "result", **res, "done": True})
            return

        def _on_progress(payload: Dict[str, Any]) -> None:
            if payload.get("done"):
                return
            _put({"type": "progress", **payload, "node_id": n_id, "done": False})

        try:
            res = worker_fn(n_id, persist=persist, on_progress=_on_progress, cancel_event=cancel_event)
            res["node_id"] = n_id
        except CancelledError:
            res = _cancelled_result(n_id)
        except Exception as exc:
            res = {
                "success": False,
                "node_id": n_id,
                "done": True,
                "phase": "done",
                "message": str(exc) or "测试异常",
            }
            if speed:
                res["speed"] = "超时"
                res["latency"] = -1
            else:
                res["latency"] = -1
        with results_lock:
            results.append(res)
        _put({"type": "result", **res, "done": True})

    pending = list(ids)
    active: List[threading.Thread] = []
    sentinel = {"type": "__finished__"}

    def _pump() -> None:
        try:
            while pending or active:
                if cancel_event.is_set():
                    while pending:
                        _run(pending.pop(0))
                active[:] = [t for t in active if t.is_alive()]
                while pending and len(active) < concurrency:
                    n_id = pending.pop(0)
                    t = threading.Thread(target=_run, args=(n_id,), daemon=True)
                    t.start()
                    active.append(t)
                time.sleep(0.05)
            if not persist:
                store.save()
            events.put(sentinel)
        except Exception as exc:
            events.put({"type": "error", "message": str(exc)})
            events.put(sentinel)

    threading.Thread(target=_pump, daemon=True).start()
    try:
        while True:
            event = events.get()
            if event.get("type") == "__finished__":
                break
            yield event
    except GeneratorExit:
        cancel_event.set()
        raise
    yield {"type": "complete", "total": len(ids), "tested": len(results), "results": results, "cancelled": cancel_event.is_set()}
