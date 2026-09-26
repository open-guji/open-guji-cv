# -*- coding: utf-8 -*-
"""平台自己的两种 cookie：登录会话、OAuth 授权码往返中间态。

都用 `jwt_util`（HS256，`config.session_secret` 签）自己签，**不是网站发的
`id_token`**——那个只在 `/auth/callback` 里验一次，验完就把 claims 抄进这里
自己的会话 cookie，往后请求不再碰 `id_token`。
"""
from __future__ import annotations

import time

from fastapi import Response

from . import config as _config
from . import jwt_util
from .identity import Identity

SESSION_COOKIE = "guji_session"
FLOW_COOKIE = "guji_oauth_flow"


def build_session_token(*, email: str, role: str, tier: str, ttl: float, secret: str) -> str:
    now = time.time()
    return jwt_util.encode({"email": email, "role": role, "tier": tier, "iat": now, "exp": now + ttl}, secret)


def read_session(raw: str | None) -> tuple[Identity, float] | None:
    """返回 `(identity, iat)`；cookie 缺失／签名不对／过期 → `None`。

    `iat`（会话建立时刻）交回给 `guard.get_identity` 去跟
    `role_refresh_seconds` 比——是不是要求重新走一遍 authorize 由那边判，
    这里只负责「这张 cookie 本身有效吗」。
    """
    if not raw:
        return None
    cfg = _config.get()
    try:
        payload = jwt_util.decode(raw, cfg.session_secret)
    except jwt_util.TokenError:
        return None
    email, role, tier, iat = (payload.get(k) for k in ("email", "role", "tier", "iat"))
    if not (email and role and tier and iat is not None):
        return None
    return Identity(email=email, role=role, tier=tier), float(iat)


def set_session_cookie(response: Response, *, email: str, role: str, tier: str, secure: bool) -> None:
    cfg = _config.get()
    token = build_session_token(email=email, role=role, tier=tier, ttl=cfg.session_ttl,
                                secret=cfg.session_secret)
    response.set_cookie(SESSION_COOKIE, token, max_age=int(cfg.session_ttl), httponly=True,
                        samesite="lax", secure=secure, path="/")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def build_flow_token(*, state: str, verifier: str, next_url: str, prompt: str | None,
                     ttl: float, secret: str) -> str:
    now = time.time()
    return jwt_util.encode({"state": state, "verifier": verifier, "next": next_url,
                            "prompt": prompt, "exp": now + ttl}, secret)


def read_flow(raw: str | None) -> dict | None:
    """`/auth/login` 那次 set 的中间态：`state`／PKCE `verifier`／登录完回哪／
    是不是 `prompt=none` 这一轮。cookie 缺失/签名不对/过期 → `None`
    （`/auth/callback` 据此判 400，见该路由）。"""
    if not raw:
        return None
    cfg = _config.get()
    try:
        return jwt_util.decode(raw, cfg.session_secret)
    except jwt_util.TokenError:
        return None


def set_flow_cookie(response: Response, token: str, *, secure: bool) -> None:
    cfg = _config.get()
    response.set_cookie(FLOW_COOKIE, token, max_age=int(cfg.flow_ttl), httponly=True,
                        samesite="lax", secure=secure, path="/auth")


def clear_flow_cookie(response: Response) -> None:
    response.delete_cookie(FLOW_COOKIE, path="/auth")
