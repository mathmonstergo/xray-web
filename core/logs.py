"""Bounded local log reads without privileged tail subprocesses."""

import asyncio
import json
import os
from pathlib import Path
import time

READ_SIZE = 65536


def tail_lines(path, count=100):
    with Path(path).open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = max(0, handle.tell() - READ_SIZE)
        handle.seek(position)
        data = handle.read(READ_SIZE)
    if position:
        data = data.partition(b"\n")[2]
    return [line.decode("utf-8", errors="replace") for line in data.splitlines()[-count:]]


async def follow_log(path):
    path = Path(path)
    identity = None
    position = 0
    pending = b""
    last_error = None
    heartbeat = time.monotonic()
    while True:
        try:
            with path.open("rb") as handle:
                info = os.fstat(handle.fileno())
                current = (info.st_dev, info.st_ino)
                initial = current != identity
                if initial:
                    position = max(0, info.st_size - READ_SIZE)
                    pending = b""
                elif info.st_size < position:
                    position = 0
                    pending = b""
                handle.seek(position)
                chunk = handle.read(READ_SIZE)
                if initial and position:
                    chunk = chunk.partition(b"\n")[2]
                position = handle.tell()
                identity = current
            lines = (pending + chunk).split(b"\n")
            pending = lines.pop()[-READ_SIZE:]
            if initial:
                lines = lines[-30:]
            if last_error is not None:
                yield 'data: {"ready": true}\n\n'
                last_error = None
            for line in lines:
                if line.strip():
                    yield f"data: {json.dumps({'line': line.decode('utf-8', errors='replace').strip()}, ensure_ascii=False)}\n\n"
        except OSError as exc:
            message = f"日志暂不可读：{type(exc).__name__}；请检查 XRAY_LOG_DIR 和文件权限"
            if message != last_error:
                yield f"event: stream-error\ndata: {json.dumps({'message': message}, ensure_ascii=False)}\n\n"
                last_error = message
        if time.monotonic() - heartbeat >= 15:
            yield ": keep-alive\n\n"
            heartbeat = time.monotonic()
        await asyncio.sleep(0.3)
