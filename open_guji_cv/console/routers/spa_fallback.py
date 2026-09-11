# -*- coding: utf-8 -*-
"""控制台 · v2 前端路由兜底。

**这个文件必须最后一个 include**（见 `app.py` 的 `ROUTERS`）——它注册一个
`/{full_path:path}` 吃掉所有未匹配的 GET 请求，放前面会抢走别的 router 的
`/api/*` 路由。

存在的原因：v2 用 React Router 的 BrowserRouter（history 模式），
`/vol01/step/step3/` 这类地址在浏览器里直接刷新时是一次真实的 HTTP GET，
FastAPI 没有为它注册过路由，不兜底就是 404。命中这里的请求一律发 v2 的
`static/dist/index.html`，交给前端路由接管。
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from ..static_path import STATIC

router = APIRouter()

_V2_INDEX = STATIC / "dist" / "index.html"


@router.get("/{full_path:path}", response_class=HTMLResponse, include_in_schema=False)
def spa_fallback(full_path: str) -> str:
    return _V2_INDEX.read_text(encoding="utf-8")
