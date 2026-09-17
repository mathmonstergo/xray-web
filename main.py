import os
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

import config
from core.store import store
from core.routing_manager import routing_manager
from core.xray_manager import XrayManager
from core.sub_manager import SubscriptionManager
from core.security import LocalAccessMiddleware
from routers import (
    system_router,
    routing_router,
    subscriptions_router,
    nodes_router,
    logs_router,
)

app = FastAPI(title="Xray Web Console", version="2.0.0")

app.add_middleware(
    LocalAccessMiddleware,
    host=config.WEB_HOST,
    username=config.WEB_USERNAME,
    password=config.WEB_PASSWORD,
    allowed_hosts=config.WEB_ALLOWED_HOSTS,
)

# 注册模块化路由
app.include_router(system_router)
app.include_router(routing_router)
app.include_router(subscriptions_router)
app.include_router(nodes_router)
app.include_router(logs_router)

# 静态前端挂载
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
