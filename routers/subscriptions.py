from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from routers.deps import get_store, get_sub_manager

router = APIRouter(tags=["subscriptions"])


class SubscriptionCreateRequest(BaseModel):
    name: str
    url: str


class SubscriptionUpdateRequest(BaseModel):
    name: str


@router.get("/api/subscriptions")
def get_subscriptions():
    return {"subscriptions": get_store().get_subscriptions()}


@router.post("/api/subscriptions")
def add_subscription(req: SubscriptionCreateRequest):
    sub_mgr = get_sub_manager()
    st = get_store()
    try:
        raw_content = sub_mgr.fetch_subscription(req.url)
        nodes = sub_mgr.parse_raw_text(raw_content)
        if not nodes:
            raise ValueError("从该订阅地址未解析到任何节点")

        sub = st.add_subscription(name=req.name, url=req.url)
        count = st.sync_subscription_nodes(sub["id"], nodes)

        return {
            "success": True,
            "subscription": sub,
            "count": count,
            "message": f"订阅添加成功，解析到 {count} 个节点！"
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"订阅处理失败: {str(e)}")


@router.post("/api/subscriptions/{sub_id}/update")
def update_subscription(sub_id: str):
    st = get_store()
    sub_mgr = get_sub_manager()
    subs = st.get_subscriptions()
    target_sub = next((s for s in subs if s["id"] == sub_id), None)
    if not target_sub:
        raise HTTPException(status_code=404, detail="订阅不存在")

    try:
        raw_content = sub_mgr.fetch_subscription(target_sub["url"])
        nodes = sub_mgr.parse_raw_text(raw_content)
        if not nodes:
            raise ValueError("未解析到任何有效节点")

        count = st.sync_subscription_nodes(sub_id, nodes)

        return {
            "success": True,
            "count": count,
            "message": f"订阅更新成功，已刷新 {count} 个节点！"
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"更新订阅失败: {str(e)}")


@router.put("/api/subscriptions/{sub_id}")
def rename_subscription(sub_id: str, req: SubscriptionUpdateRequest):
    """修改订阅名称"""
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="订阅名称不能为空")
    try:
        ok = get_store().update_subscription_name(sub_id, req.name.strip())
        if not ok:
            raise HTTPException(status_code=404, detail="订阅不存在")
        return {"success": True, "message": "订阅名称已更新"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/api/subscriptions/{sub_id}")
def delete_subscription(sub_id: str, delete_nodes: bool = False):
    get_store().delete_subscription(sub_id, delete_nodes=delete_nodes)
    return {"success": True, "message": "订阅已删除"}
