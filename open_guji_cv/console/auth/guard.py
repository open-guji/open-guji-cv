# -*- coding: utf-8 -*-
"""FastAPI 依赖注入：`Depends(require_reviewer)` / `Depends(require_admin)`。

统一挂在这里，router 只 import、不用各自写鉴权逻辑（任务书 §做什么·3：
「路由分级：每个 router 标注所需角色（依赖注入统一挂，别每条路由各写一遍）」）。
"""
from __future__ import annotations

import time

from fastapi import Depends, HTTPException, Request

from . import config as _config
from . import session as _session
from .identity import Identity

#: `--no-auth` 本机开发用的假身份——固定给管理员权限，什么都能点开。
_NO_AUTH_IDENTITY = Identity(email="local-dev@127.0.0.1", role="admin", tier="admin")


def get_identity(request: Request) -> Identity:
    """本请求是谁。`--no-auth` 开着就是本机固定身份；否则读平台自己的会话
    cookie（`console/auth/session.py`，OAuth 回调时种下的）。

    cookie 缺失／签名不对／过期，或者**会话建立超过 `role_refresh_seconds`**
    （网站那边角色变了要在这段时间内生效——任务书「角色刷新到期后重新授权」），
    一律当未登录：401，不放行。前端的 `useIdentity` 见到 401 会重新走
    `/auth/login`（角色刷新场景下带 `prompt=none`，网站那边如果登录态还在，
    静默换一轮新 `id_token` 回来，用户无感）。"""
    cfg = _config.get()
    if cfg.no_auth:
        return _NO_AUTH_IDENTITY
    hit = _session.read_session(request.cookies.get(_session.SESSION_COOKIE))
    if hit is None:
        raise HTTPException(status_code=401, detail="未登录")
    identity, iat = hit
    if time.time() - iat > cfg.role_refresh_seconds:
        raise HTTPException(status_code=401, detail="会话需要刷新")
    return identity


def require_reviewer(identity: Identity = Depends(get_identity)) -> Identity:
    """校对者（含管理员）能进。`get_identity` 已经把「够不上 reviewer/admin
    任一级」的身份挡在 401 里了（角色映射见 identity.py），这里直接放行。"""
    return identity


def require_admin(identity: Identity = Depends(get_identity)) -> Identity:
    """只有管理员能进。"""
    if identity.tier != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return identity
