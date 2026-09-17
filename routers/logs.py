import os
import subprocess
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

import config
from core.logs import tail_lines, follow_log

router = APIRouter(tags=["logs"])


def get_log_file_path(log_type: str) -> str:
    filename = "error.log" if log_type == "error" else "access.log"
    return str(config.XRAY_LOG_DIR / filename)


@router.get("/api/logs")
def get_logs(type: Literal["access", "error"] = "access", lines: int = Query(100, ge=1, le=500)):
    path = get_log_file_path(type)
    if not os.path.exists(path):
        return {"logs": [], "count": 0, "type": type}
    try:
        entries = tail_lines(path, lines)
        return {"logs": entries, "count": len(entries), "type": type}
    except OSError as exc:
        raise HTTPException(status_code=500, detail="日志不可读，请检查 XRAY_LOG_DIR 和文件权限") from exc


@router.post("/api/logs/clear")
def clear_logs(type: Literal["access", "error"] = "access"):
    try:
        path = get_log_file_path(type)
        if os.path.exists(path):
            try:
                with open(path, "w", encoding="utf-8"):
                    pass
            except PermissionError:
                res = subprocess.run(["sudo", "-n", "truncate", "-s", "0", str(path)], capture_output=True, text=True)
                if res.returncode != 0:
                    raise
        return {"success": True, "message": f"{type}.log 已清空"}
    except OSError as exc:
        raise HTTPException(status_code=500, detail="无法清空日志，请检查文件写权限") from exc


@router.get("/api/logs/stream")
async def stream_logs(type: Literal["access", "error"] = "access"):
    return StreamingResponse(
        follow_log(get_log_file_path(type)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
