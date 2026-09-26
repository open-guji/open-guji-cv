# -*- coding: utf-8 -*-
"""FastAPI 依赖注入：`Depends(require_reviewer)` / `Depends(require_admin)`。

统一挂在这里，router 只 import、不用各自写鉴权逻辑（任务书 §做什么·3：
「路由分级：每个 router 标注所需角色（依赖注入统一挂，别每条路由各写一遍）」）。
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from . import config as _config
from .identity import Identity, fetch_identity

#: `--no-auth` 本机开发用的假身份——固定给管理员权限，什么都能点开。
_NO_AUTH_IDENTITY = Identity(email="local-dev@127.0.0.1", role="admin", tier="admin")


def get_identity(request: Request) -> Identity:
    """本请求是谁。`--no-auth` 开着就是本机固定身份；否则转发 Cookie 问身份接口，
    问不出 → 401（未登录，不放行，见任务书完成判据）。"""
    if _config.get().no_auth:
        return _NO_AUTH_IDENTITY
    ident = fetch_identity(request.headers.get("cookie"))
    if ident is None:
        raise HTTPException(status_code=401, detail="未登录")
    return ident


def require_reviewer(identity: Identity = Depends(get_identity)) -> Identity:
    """校对者（含管理员）能进。`get_identity` 已经把「够不上 reviewer/admin
    任一级」的身份挡在 401 里了（`tier_of` 见 identity.py），这里直接放行。"""
    return identity


def require_admin(identity: Identity = Depends(get_identity)) -> Identity:
    """只有管理员能进。"""
    if identity.tier != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return identity
