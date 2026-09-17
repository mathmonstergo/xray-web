import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from routers.deps import get_store, get_xray_manager

router = APIRouter(tags=["system"])

APP_VERSION = "2.0.0"


class PortsUpdateRequest(BaseModel):
    socks: int
    http: int
    routing: int


@router.get("/api/health")
def get_health():
    """Local process readiness; does not contact a node or inspect systemd."""
    return {"running": True, "pid": os.getpid(), "version": APP_VERSION}


@router.get("/api/ports")
def get_ports():
    """获取当前配置的代理服务端口"""
    return {"ports": get_store().get_ports()}


@router.put("/api/ports")
def update_ports(req: PortsUpdateRequest):
    """修改并应用代理服务端口配置，自动重载 Xray"""
    try:
        res = get_xray_manager().apply_ports(req.socks, req.http, req.routing)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/status")
def get_status():
    """获取系统状态、运行节点信息与出口真实 IP"""
    xm = get_xray_manager()
    st = get_store()
    service_status = xm.get_service_status()
    active_node = st.get_active_node()
    outbound_ip = xm.get_outbound_ip() if service_status["active"] else {"success": False, "ip": "", "country": ""}

    return {
        "service": service_status,
        "active_node": active_node,
        "outbound_network": outbound_ip
    }
