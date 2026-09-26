# -*- coding: utf-8 -*-
"""控制台 · 鉴权自身的两条路由。

`/api/auth/me`：前端探测「我是谁」；未登录时 `Depends(get_identity)` 自己就会
抛 401（见 `console/auth/guard.py`），不用另挂角色依赖。
`/api/auth/config`：前端跳转登录/登出用的地址，公开、不含机密。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import Identity, config as auth_config, get_identity

router = APIRouter()


@router.get("/api/auth/me")
def api_auth_me(identity: Identity = Depends(get_identity)) -> dict:
    return identity.model_dump()


@router.get("/api/auth/config")
def api_auth_config() -> dict:
    cfg = auth_config.get()
    return {"login_url": cfg.login_url, "logout_url": cfg.logout_url or cfg.login_url,
            "root_path": cfg.root_path}
