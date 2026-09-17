from typing import Optional, List, Dict, Any, Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from routers.deps import get_store, get_routing_manager, get_xray_manager

router = APIRouter(tags=["routing"])


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


def _routing_change(edit, apply=True):
    try:
        return get_xray_manager().change_routing(edit, apply=apply)
    except HTTPException:
        raise
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/routing/categories")
def get_routing_categories():
    rm = get_routing_manager()
    return {
        **rm.get_categories_dict(),
        "default_outbound": rm.default_outbound,
        "priority": ["block", "proxy", "direct"]
    }


@router.put("/api/routing/categories")
def update_all_routing_categories(req: CategoriesBatchUpdateRequest, apply: bool = True):
    def edit(rules):
        for action in ("direct", "proxy", "block"):
            values = getattr(req, action)
            if values is not None:
                rules.set_category_lines(action, values)
    return _routing_change(edit, apply)


@router.put("/api/routing/categories/{action}")
def update_routing_category(action: str, req: CategoryUpdateRequest, apply: bool = True):
    return _routing_change(lambda rules: rules.set_category_lines(action, req.lines), apply)


@router.get("/api/routing/rules")
def get_routing_rules():
    ports = get_store().get_ports()
    rm = get_routing_manager()
    return {
        "rules": rm.get_rules(),
        "ports": {"direct": [ports["socks"], ports["http"]], "routing": ports["routing"]}
    }


@router.post("/api/routing/rules")
def add_routing_rule(req: RoutingRuleCreateRequest, apply: bool = True):
    result = _routing_change(lambda rules: rules.add_rule(
        req.name or "", req.type, req.values, req.action,
        req.enabled if req.enabled is not None else True), apply)
    result["rule"] = result.pop("value")
    return result


@router.put("/api/routing/rules/{rule_id}")
def update_routing_rule(rule_id: str, req: RoutingRuleUpdateRequest, apply: bool = True):
    result = _routing_change(lambda rules: rules.update_rule(
        rule_id, req.dict(exclude_unset=True, exclude_none=True)), apply)
    result["rule"] = result.pop("value")
    return result


@router.delete("/api/routing/rules/{rule_id}")
def delete_routing_rule(rule_id: str, apply: bool = True):
    def edit(rules):
        if not rules.delete_rule(rule_id):
            raise HTTPException(status_code=404, detail="规则不存在")
    return _routing_change(edit, apply)


@router.post("/api/routing/rules/{rule_id}/toggle")
def toggle_routing_rule(rule_id: str, apply: bool = True):
    result = _routing_change(lambda rules: rules.toggle_rule(rule_id), apply)
    result["rule"] = result.pop("value")
    return result


@router.post("/api/routing/default-outbound")
def set_default_outbound(req: DefaultOutboundRequest, apply: bool = True):
    return _routing_change(lambda rules: rules.set_default_outbound(req.outbound), apply)


@router.post("/api/routing/apply")
def apply_routing():
    return _routing_change(lambda _: None)


@router.post("/api/routing-mode")
def set_routing_mode(req: Dict[str, Any]):
    mode = req.get("mode", "bypass_cn")
    if mode not in ("global_proxy", "global_direct", "bypass_cn"):
        raise HTTPException(status_code=400, detail="无效分流模式")
    result = _routing_change(lambda rules: rules.set_default_outbound(
        "direct" if mode == "global_direct" else "proxy"))
    return {**result, "mode": mode}
