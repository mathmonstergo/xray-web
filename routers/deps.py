import sys
from typing import Any

import core.store as _default_store_mod
import core.routing_manager as _default_routing_mod
import core.xray_manager as _default_xm_mod
import core.sub_manager as _default_sub_mod


def get_store() -> Any:
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "store"):
        return getattr(main_mod, "store")
    return _default_store_mod.store


def get_routing_manager() -> Any:
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "routing_manager"):
        return getattr(main_mod, "routing_manager")
    return _default_routing_mod.routing_manager


def get_xray_manager() -> Any:
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "XrayManager"):
        return getattr(main_mod, "XrayManager")
    return _default_xm_mod.XrayManager


def get_sub_manager() -> Any:
    main_mod = sys.modules.get("main")
    if main_mod and hasattr(main_mod, "SubscriptionManager"):
        return getattr(main_mod, "SubscriptionManager")
    return _default_sub_mod.SubscriptionManager
