import urllib.parse
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.speedtest import iter_batch_progress
from core.test_stream import test_stream_response
from routers.deps import get_store, get_xray_manager, get_sub_manager

router = APIRouter(tags=["nodes"])


class ImportRequest(BaseModel):
    text: Optional[str] = None
    subscription_url: Optional[str] = None
    subscription_name: Optional[str] = None


class RenameRequest(BaseModel):
    name: str


class NodeBatchActionRequest(BaseModel):
    node_ids: Optional[List[str]] = None


def _sse_test_stream(node_ids: List[str], speed: bool):
    return test_stream_response(node_ids, speed=speed, worker=iter_batch_progress)


@router.get("/api/nodes")
def get_nodes():
    return {"nodes": get_store().get_nodes()}


@router.post("/api/nodes/import")
def import_nodes(req: ImportRequest):
    imported_nodes = []
    sub_id = None
    import_type = "nodes"
    target_name = req.subscription_name.strip() if req.subscription_name else None

    raw_text = (req.text or "").strip()
    raw_sub_url = (req.subscription_url or "").strip()
    st = get_store()
    sub_mgr = get_sub_manager()

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
            parsed = urllib.parse.urlparse(raw_sub_url)
            target_name = parsed.hostname or "新订阅"

        try:
            raw_content = sub_mgr.fetch_subscription(raw_sub_url)
            imported_nodes = sub_mgr.parse_raw_text(raw_content)
            if not imported_nodes:
                raise ValueError("订阅内容未能解析出任何有效节点")

            existing_subs = st.get_subscriptions()
            existing_sub = next((s for s in existing_subs if s["url"] == raw_sub_url.strip()), None)
            is_duplicate_sub = existing_sub is not None
            if is_duplicate_sub:
                target_name = existing_sub.get("name") or target_name

            sub = st.add_subscription(name=target_name, url=raw_sub_url)
            sub_id = sub["id"]
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"订阅拉取解析失败: {str(e)}")

    # 2. 节点链接 / Base64 处理
    elif raw_text:
        try:
            imported_nodes = sub_mgr.parse_raw_text(raw_text)
            if target_name and len(imported_nodes) == 1:
                imported_nodes[0]["name"] = target_name
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"节点文本解析失败: {str(e)}")

    if not imported_nodes:
        raise HTTPException(status_code=400, detail="未检测到有效节点链接或订阅地址，请检查格式")

    if sub_id:
        before_sub_ids = {n["id"] for n in st.get_nodes() if n.get("subscription_id") == sub_id}
        count = st.sync_subscription_nodes(sub_id, imported_nodes)
        after_sub_ids = {n["id"] for n in st.get_nodes() if n.get("subscription_id") == sub_id}
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
        count = st.add_nodes_batch(imported_nodes, subscription_id=None)
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


@router.post("/api/nodes/{node_id}/switch")
def switch_node(node_id: str):
    """轻量快速无阻断切换节点"""
    try:
        res = get_xray_manager().switch_node(node_id)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/nodes/{node_id}/test")
def test_node(node_id: str, stream: bool = False):
    if stream:
        return _sse_test_stream([node_id], speed=False)
    try:
        res = get_xray_manager().test_single_node(node_id)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/nodes/{node_id}/speed-test")
def speed_test_node(node_id: str, stream: bool = True):
    if stream:
        return _sse_test_stream([node_id], speed=True)
    try:
        res = get_xray_manager().speed_test_single_node(node_id)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/nodes/test-all")
def test_all_nodes(stream: bool = True):
    st = get_store()
    xm = get_xray_manager()
    ids = [n["id"] for n in st.get_nodes()]
    if stream:
        return _sse_test_stream(ids, speed=False)
    results = []
    for n_id in ids:
        try:
            res = xm.test_single_node(n_id, persist=False)
            res["node_id"] = n_id
        except Exception as e:
            res = {"success": False, "latency": -1, "node_id": n_id, "message": str(e)}
        results.append(res)
    st.save()
    return {"success": True, "tested": len(results), "results": results}


@router.post("/api/nodes/test-batch")
def test_nodes_batch(req: NodeBatchActionRequest, stream: bool = True):
    st = get_store()
    xm = get_xray_manager()
    all_nodes = st.get_nodes()
    target_ids = req.node_ids if req.node_ids is not None else [n["id"] for n in all_nodes]
    if stream:
        return _sse_test_stream(target_ids or [], speed=False)
    if not target_ids:
        return {"success": True, "tested": 0, "results": []}
    results = []
    for n_id in target_ids:
        try:
            res = xm.test_single_node(n_id, persist=False)
            res["node_id"] = n_id
        except Exception as e:
            res = {"success": False, "latency": -1, "node_id": n_id, "message": str(e)}
        results.append(res)
    st.save()
    return {"success": True, "tested": len(results), "results": results}


@router.post("/api/nodes/speed-test-batch")
def speed_test_nodes_batch(req: NodeBatchActionRequest, stream: bool = True):
    st = get_store()
    xm = get_xray_manager()
    all_nodes = st.get_nodes()
    target_ids = req.node_ids if req.node_ids is not None else [n["id"] for n in all_nodes]
    if stream:
        return _sse_test_stream(target_ids or [], speed=True)
    if not target_ids:
        return {"success": True, "tested": 0, "results": []}
    results = []
    for n_id in target_ids:
        try:
            res = xm.speed_test_single_node(n_id, persist=False)
            res["node_id"] = n_id
        except Exception as e:
            res = {"success": False, "speed": "超时", "node_id": n_id, "message": str(e)}
        results.append(res)
    st.save()
    return {"success": True, "tested": len(results), "results": results}


@router.post("/api/nodes/batch-delete")
def batch_delete_nodes(req: NodeBatchActionRequest):
    if not req.node_ids:
        return {"success": True, "deleted": 0}
    deleted = get_store().delete_nodes_batch(req.node_ids)
    return {"success": True, "deleted": deleted, "message": f"已成功删除 {deleted} 个节点"}


@router.put("/api/nodes/{node_id}")
def rename_node(node_id: str, req: RenameRequest):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="节点名称不能为空")
    ok = get_store().update_node_name(node_id, req.name.strip())
    if not ok:
        raise HTTPException(status_code=404, detail="节点不存在")
    return {"success": True, "message": "重命名成功"}


@router.delete("/api/nodes/{node_id}")
def delete_node(node_id: str):
    try:
        ok = get_store().delete_node(node_id)
        if not ok:
            raise HTTPException(status_code=404, detail="节点不存在")
        return {"success": True, "message": "节点已删除"}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
