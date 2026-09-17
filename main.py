import os
import json
import asyncio
import subprocess
import threading
from typing import Optional, List, Dict, Any, Literal
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, Query
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from core.store import store
from core.parser import ProtocolParser
from core.sub_manager import SubscriptionManager
from core.xray_manager import XrayManager
from core.routing_manager import routing_manager
from core.speedtest import iter_batch_progress
from core.test_stream import test_stream_response
from core.security import LocalAccessMiddleware
from core.logs import tail_lines, follow_log

app = FastAPI(title="Xray Web Console", version="2.0.0")

app.add_middleware(
    LocalAccessMiddleware,
    host=config.WEB_HOST,
    username=config.WEB_USERNAME,
    password=config.WEB_PASSWORD,
    allowed_hosts=config.WEB_ALLOWED_HOSTS,
)

# ----------------- 请求模型定义 -----------------

class ImportRequest(BaseModel):
    text: Optional[str] = None
    subscription_url: Optional[str] = None
    subscription_name: Optional[str] = None

class RenameRequest(BaseModel):
    name: str

class RoutingRuleCreateRequest(BaseModel):
    name: Optional[str] = None
    type: Literal["domain", "ip"]
    values: List[str]
    action: Literal["direct", "proxy", "block"]
    enabled: Optional[bool] = True

class RoutingRuleUpdateRequest(BaseModel):
    name: Optional[str] = None
    type: Optional[Literal["domain", "ip"]] = None
    values: Optional[List[str]] = None
    action: Optional[Literal["direct", "proxy", "block"]] = None
    enabled: Optional[bool] = None

class DefaultOutboundRequest(BaseModel):
    outbound: Literal["proxy", "direct"]

class CategoryUpdateRequest(BaseModel):
    lines: List[str]

class CategoriesBatchUpdateRequest(BaseModel):
    direct: Optional[List[str]] = None
    proxy: Optional[List[str]] = None
    block: Optional[List[str]] = None

class SubscriptionCreateRequest(BaseModel):
    name: str
    url: str

class SubscriptionUpdateRequest(BaseModel):
    name: str

class PortsUpdateRequest(BaseModel):
    socks: int
    http: int
    routing: int

# ----------------- 分流规则 API -----------------

def _routing_change(edit, apply=True):
    try:
        return XrayManager.change_routing(edit, apply=apply)
    except HTTPException:
        raise
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/routing/categories")
def get_routing_categories():
    return {**routing_manager.get_categories_dict(),
            "default_outbound": routing_manager.default_outbound,
            "priority": ["block", "proxy", "direct"]}


@app.put("/api/routing/categories")
def update_all_routing_categories(req: CategoriesBatchUpdateRequest, apply: bool = True):
    def edit(rules):
        for action in ("direct", "proxy", "block"):
            values = getattr(req, action)
            if values is not None:
                rules.set_category_lines(action, values)
    return _routing_change(edit, apply)


@app.put("/api/routing/categories/{action}")
def update_routing_category(action: str, req: CategoryUpdateRequest, apply: bool = True):
    return _routing_change(lambda rules: rules.set_category_lines(action, req.lines), apply)


@app.get("/api/routing/rules")
def get_routing_rules():
    ports = store.get_ports()
    return {"rules": routing_manager.get_rules(),
            "ports": {"direct": [ports["socks"], ports["http"]], "routing": ports["routing"]}}


@app.post("/api/routing/rules")
def add_routing_rule(req: RoutingRuleCreateRequest, apply: bool = True):
    result = _routing_change(lambda rules: rules.add_rule(
        req.name or "", req.type, req.values, req.action,
        req.enabled if req.enabled is not None else True), apply)
    result["rule"] = result.pop("value")
    return result


@app.put("/api/routing/rules/{rule_id}")
def update_routing_rule(rule_id: str, req: RoutingRuleUpdateRequest, apply: bool = True):
    result = _routing_change(lambda rules: rules.update_rule(
        rule_id, req.dict(exclude_unset=True, exclude_none=True)), apply)
    result["rule"] = result.pop("value")
    return result


@app.delete("/api/routing/rules/{rule_id}")
def delete_routing_rule(rule_id: str, apply: bool = True):
    def edit(rules):
        if not rules.delete_rule(rule_id):
            raise HTTPException(status_code=404, detail="规则不存在")
    return _routing_change(edit, apply)


@app.post("/api/routing/rules/{rule_id}/toggle")
def toggle_routing_rule(rule_id: str, apply: bool = True):
    result = _routing_change(lambda rules: rules.toggle_rule(rule_id), apply)
    result["rule"] = result.pop("value")
    return result


@app.post("/api/routing/default-outbound")
def set_default_outbound(req: DefaultOutboundRequest, apply: bool = True):
    return _routing_change(lambda rules: rules.set_default_outbound(req.outbound), apply)


@app.post("/api/routing/apply")
def apply_routing():
    return _routing_change(lambda _: None)


@app.post("/api/routing-mode")
def set_routing_mode(req: Dict[str, Any]):
    mode = req.get("mode", "bypass_cn")
    if mode not in ("global_proxy", "global_direct", "bypass_cn"):
        raise HTTPException(status_code=400, detail="无效分流模式")
    result = _routing_change(lambda rules: rules.set_default_outbound(
        "direct" if mode == "global_direct" else "proxy"))
    return {**result, "mode": mode}

# ----------------- 核心状态 API -----------------

@app.get("/api/health")
def get_health():
    """Local process readiness; does not contact a node or inspect systemd."""
    return {"running": True, "pid": os.getpid(), "version": app.version}

@app.get("/api/ports")
def get_ports():
    """获取当前配置的代理服务端口"""
    return {"ports": store.get_ports()}

@app.put("/api/ports")
def update_ports(req: PortsUpdateRequest):
    """修改并应用代理服务端口配置，自动重载 Xray"""
    try:
        res = XrayManager.apply_ports(req.socks, req.http, req.routing)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/status")
def get_status():
    """获取系统状态、运行节点信息与出口真实 IP"""
    service_status = XrayManager.get_service_status()
    active_node = store.get_active_node()
    outbound_ip = XrayManager.get_outbound_ip() if service_status["active"] else {"success": False, "ip": "", "country": ""}

    return {
        "service": service_status,
        "active_node": active_node,
        "outbound_network": outbound_ip
    }

# ----------------- 节点操作 API -----------------

@app.get("/api/nodes")
def get_nodes():
    return {"nodes": store.get_nodes()}

@app.post("/api/nodes/import")
def import_nodes(req: ImportRequest):
    """
    智能统一导入：
    自动识别输入的是单行 HTTP/HTTPS 订阅链接，还是多行节点链接/Base64。
    如果是订阅链接，自动拉取并存为持久化订阅源；
    如果是节点链接，自动解析并批量存入节点列表。
    """
    imported_nodes = []
    sub_id = None
    import_type = "nodes"
    target_name = req.subscription_name.strip() if req.subscription_name else None

    raw_text = (req.text or "").strip()
    raw_sub_url = (req.subscription_url or "").strip()

    # 智能探测：如果 text 是单行且以 http/https 开头且不包含节点协议头，自动识别为订阅链接
    if not raw_sub_url and raw_text:
        lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
        if len(lines) == 1 and (lines[0].startswith("http://") or lines[0].startswith("https://")):
            if not any(proto in lines[0] for proto in ["vless://", "vmess://", "trojan://", "ss://"]):
                raw_sub_url = lines[0]

    # 1. 订阅链接处理
    if raw_sub_url:
        import_type = "subscription"
        if not target_name:
            import urllib.parse
            parsed = urllib.parse.urlparse(raw_sub_url)
            target_name = parsed.hostname or "新订阅"
        try:
            raw_content = SubscriptionManager.fetch_subscription(raw_sub_url)
            imported_nodes = SubscriptionManager.parse_raw_text(raw_content)
            if not imported_nodes:
                raise ValueError("订阅内容未能解析出任何有效节点")

            existing_subs = store.get_subscriptions()
            existing_sub = next((s for s in existing_subs if s["url"] == raw_sub_url.strip()), None)
            is_duplicate_sub = existing_sub is not None
            if is_duplicate_sub:
                target_name = existing_sub.get("name") or target_name

            sub = store.add_subscription(name=target_name, url=raw_sub_url)
            sub_id = sub["id"]
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"订阅拉取解析失败: {str(e)}")

    # 2. 节点链接 / Base64 处理
    elif raw_text:
        try:
            imported_nodes = SubscriptionManager.parse_raw_text(raw_text)
            if target_name and len(imported_nodes) == 1:
                imported_nodes[0]["name"] = target_name
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"节点文本解析失败: {str(e)}")

    if not imported_nodes:
        raise HTTPException(status_code=400, detail="未检测到有效节点链接或订阅地址，请检查格式")

    if sub_id:
        before_sub_ids = {n["id"] for n in store.get_nodes() if n.get("subscription_id") == sub_id}
        count = store.sync_subscription_nodes(sub_id, imported_nodes)
        after_sub_ids = {n["id"] for n in store.get_nodes() if n.get("subscription_id") == sub_id}
        new_count = len(after_sub_ids - before_sub_ids)
        dup_count = len(after_sub_ids & before_sub_ids)
        total_in_sub = len(after_sub_ids)

        if is_duplicate_sub:
            if new_count > 0:
                msg = f"已识别为已有订阅「{target_name}」（链接重复）：划分至「{target_name}」标签，更新 {dup_count} 个重复节点，新增 {new_count} 个节点（共 {total_in_sub} 个）！"
            else:
                msg = f"已识别为已有订阅「{target_name}」（链接重复）：划分至「{target_name}」标签，就地更新 {dup_count} 个节点，无新增！"
        else:
            msg = f"已识别为新订阅：成功添加「{target_name}」标签，并同步拉取 {total_in_sub} 个节点！"

        return {
            "success": True,
            "type": import_type,
            "target_tab": sub_id,
            "target_tab_name": target_name,
            "is_duplicate": is_duplicate_sub,
            "new_count": new_count,
            "duplicate_count": dup_count,
            "total_count": total_in_sub,
            "count": total_in_sub,
            "message": msg,
        }
    else:
        before_nodes = len(store.get_nodes())
        count = store.add_nodes_batch(imported_nodes, subscription_id=None)
        total = len(imported_nodes)
        dup_count = total - count

        if dup_count == total:
            msg = f"已识别为节点链接：导入的 {total} 个节点均已存在（重复），已就地更新，归入「节点导入」标签下！"
        elif dup_count > 0:
            msg = f"已识别为节点链接：成功导入 {count} 个新节点，更新 {dup_count} 个重复节点，已归入「节点导入」标签下！"
        else:
            msg = f"已识别为节点链接：成功导入 {count} 个新节点，已归入「节点导入」标签下！"

        return {
            "success": True,
            "type": import_type,
            "target_tab": "manual",
            "target_tab_name": "节点导入",
            "new_count": count,
            "duplicate_count": dup_count,
            "total_count": total,
            "count": count,
            "message": msg,
        }

class NodeBatchActionRequest(BaseModel):
    node_ids: Optional[List[str]] = None

@app.post("/api/nodes/{node_id}/switch")
def switch_node(node_id: str):
    """
    轻量快速无阻断切换节点（无需模态遮罩与长时间外网阻断测试）
    """
    try:
        res = XrayManager.switch_node(node_id)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

def _sse_test_stream(node_ids: List[str], speed: bool):
    return test_stream_response(node_ids, speed=speed, worker=iter_batch_progress)


@app.post("/api/nodes/{node_id}/test")
def test_node(node_id: str, stream: bool = False):
    if stream:
        return _sse_test_stream([node_id], speed=False)
    try:
        res = XrayManager.test_single_node(node_id)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/nodes/{node_id}/speed-test")
def speed_test_node(node_id: str, stream: bool = True):
    if stream:
        return _sse_test_stream([node_id], speed=True)
    try:
        res = XrayManager.speed_test_single_node(node_id)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/nodes/test-all")
def test_all_nodes(stream: bool = True):
    ids = [n["id"] for n in store.get_nodes()]
    if stream:
        return _sse_test_stream(ids, speed=False)
    results = []
    for n_id in ids:
        try:
            res = XrayManager.test_single_node(n_id, persist=False)
            res["node_id"] = n_id
        except Exception as e:
            res = {"success": False, "latency": -1, "node_id": n_id, "message": str(e)}
        results.append(res)
    store.save()
    return {"success": True, "tested": len(results), "results": results}


@app.post("/api/nodes/test-batch")
def test_nodes_batch(req: NodeBatchActionRequest, stream: bool = True):
    all_nodes = store.get_nodes()
    target_ids = req.node_ids if req.node_ids is not None else [n["id"] for n in all_nodes]
    if stream:
        return _sse_test_stream(target_ids or [], speed=False)
    if not target_ids:
        return {"success": True, "tested": 0, "results": []}
    results = []
    for n_id in target_ids:
        try:
            res = XrayManager.test_single_node(n_id, persist=False)
            res["node_id"] = n_id
        except Exception as e:
            res = {"success": False, "latency": -1, "node_id": n_id, "message": str(e)}
        results.append(res)
    store.save()
    return {"success": True, "tested": len(results), "results": results}


@app.post("/api/nodes/speed-test-batch")
def speed_test_nodes_batch(req: NodeBatchActionRequest, stream: bool = True):
    all_nodes = store.get_nodes()
    target_ids = req.node_ids if req.node_ids is not None else [n["id"] for n in all_nodes]
    if stream:
        return _sse_test_stream(target_ids or [], speed=True)
    if not target_ids:
        return {"success": True, "tested": 0, "results": []}
    results = []
    for n_id in target_ids:
        try:
            res = XrayManager.speed_test_single_node(n_id, persist=False)
            res["node_id"] = n_id
        except Exception as e:
            res = {"success": False, "speed": "超时", "node_id": n_id, "message": str(e)}
        results.append(res)
    store.save()
    return {"success": True, "tested": len(results), "results": results}

@app.post("/api/nodes/batch-delete")
def batch_delete_nodes(req: NodeBatchActionRequest):
    if not req.node_ids:
        return {"success": True, "deleted": 0}
    deleted = store.delete_nodes_batch(req.node_ids)
    return {"success": True, "deleted": deleted, "message": f"已成功删除 {deleted} 个节点"}

@app.put("/api/nodes/{node_id}")
def rename_node(node_id: str, req: RenameRequest):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="节点名称不能为空")
    ok = store.update_node_name(node_id, req.name.strip())
    if not ok:
        raise HTTPException(status_code=404, detail="节点不存在")
    return {"success": True, "message": "重命名成功"}

@app.delete("/api/nodes/{node_id}")
def delete_node(node_id: str):
    try:
        ok = store.delete_node(node_id)
        if not ok:
            raise HTTPException(status_code=404, detail="节点不存在")
        return {"success": True, "message": "节点已删除"}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

# ----------------- 订阅管理 API -----------------

@app.get("/api/subscriptions")
def get_subscriptions():
    return {"subscriptions": store.get_subscriptions()}

@app.post("/api/subscriptions")
def add_subscription(req: SubscriptionCreateRequest):
    try:
        raw_content = SubscriptionManager.fetch_subscription(req.url)
        nodes = SubscriptionManager.parse_raw_text(raw_content)
        if not nodes:
            raise ValueError("从该订阅地址未解析到任何节点")

        sub = store.add_subscription(name=req.name, url=req.url)
        count = store.sync_subscription_nodes(sub["id"], nodes)

        return {
            "success": True,
            "subscription": sub,
            "count": count,
            "message": f"订阅添加成功，解析到 {count} 个节点！"
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"订阅处理失败: {str(e)}")

@app.post("/api/subscriptions/{sub_id}/update")
def update_subscription(sub_id: str):
    subs = store.get_subscriptions()
    target_sub = next((s for s in subs if s["id"] == sub_id), None)
    if not target_sub:
        raise HTTPException(status_code=404, detail="订阅不存在")

    try:
        raw_content = SubscriptionManager.fetch_subscription(target_sub["url"])
        nodes = SubscriptionManager.parse_raw_text(raw_content)
        if not nodes:
            raise ValueError("未解析到任何有效节点")

        count = store.sync_subscription_nodes(sub_id, nodes)

        return {
            "success": True,
            "count": count,
            "message": f"订阅更新成功，已刷新 {count} 个节点！"
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"更新订阅失败: {str(e)}")

@app.put("/api/subscriptions/{sub_id}")
def rename_subscription(sub_id: str, req: SubscriptionUpdateRequest):
    """修改订阅名称"""
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="订阅名称不能为空")
    try:
        ok = store.update_subscription_name(sub_id, req.name.strip())
        if not ok:
            raise HTTPException(status_code=404, detail="订阅不存在")
        return {"success": True, "message": "订阅名称已更新"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/subscriptions/{sub_id}")
def delete_subscription(sub_id: str, delete_nodes: bool = False):
    store.delete_subscription(sub_id, delete_nodes=delete_nodes)
    return {"success": True, "message": "订阅已删除"}

# ----------------- 实时日志 API (Access & Error) -----------------

def get_log_file_path(log_type: str) -> str:
    filename = "error.log" if log_type == "error" else "access.log"
    return str(config.XRAY_LOG_DIR / filename)

@app.get("/api/logs")
def get_logs(type: Literal["access", "error"] = "access", lines: int = Query(100, ge=1, le=500)):
    path = get_log_file_path(type)
    if not os.path.exists(path):
        return {"logs": [], "count": 0, "type": type}
    try:
        entries = tail_lines(path, lines)
        return {"logs": entries, "count": len(entries), "type": type}
    except OSError as exc:
        raise HTTPException(status_code=500, detail="日志不可读，请检查 XRAY_LOG_DIR 和文件权限") from exc


@app.post("/api/logs/clear")
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


@app.get("/api/logs/stream")
async def stream_logs(type: Literal["access", "error"] = "access"):
    return StreamingResponse(follow_log(get_log_file_path(type)), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ----------------- 静态前端挂载 -----------------

if config.STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")

@app.get("/", response_class=HTMLResponse)
@app.head("/", response_class=HTMLResponse)
def index_page():
    index_file = config.STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return HTMLResponse("<h1>Xray Web Panel is Running</h1>")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.WEB_HOST, port=config.WEB_PORT, reload=False, timeout_graceful_shutdown=1)
