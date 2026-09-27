# -*- coding: utf-8 -*-
"""OAuth 客户端这一侧的活：拼 authorize URL、PKCE、拿 code 换 `id_token`、验签。

网站那边的两个端点（`/oauth/authorize`、`/oauth/token`）不是这里的事——
那是网站总管的活（网站侧规格见 overview 任务书 09-26 第二次改向一节 + 网站总管
09-26 18:45 回单）。这里只当**客户端**。
"""
from __future__ import annotations

import secrets
import time
from urllib.parse import urlencode

import httpx

from . import config as _config
from . import jwt_util
from .identity import Identity, tier_of


class OAuthError(Exception):
    """携带一句给用户/日志看的话——state 不符、code 用过、id_token 验不过，都走这个。"""


_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=5.0)
    return _client


def set_client(client: httpx.Client | None) -> None:
    """测试用：换成指向假 `token_url` 的 client；传 `None` 下次用时按默认重建。"""
    global _client
    _client = client


def new_pkce_pair() -> tuple[str, str]:
    """`(code_verifier, code_challenge)`——S256，见 `jwt_util.pkce_challenge`。"""
    verifier = secrets.token_urlsafe(48)
    return verifier, jwt_util.pkce_challenge(verifier)


def build_authorize_url(*, redirect_uri: str, state: str, code_challenge: str,
                        prompt: str | None = None) -> str:
    cfg = _config.get()
    params = {"client_id": cfg.client_id, "redirect_uri": redirect_uri, "state": state,
              "code_challenge": code_challenge, "code_challenge_method": "S256",
              "response_type": "code"}
    if prompt:
        params["prompt"] = prompt
    return f"{cfg.authorize_url}?{urlencode(params)}"


def _identity_from_id_token(id_token: str) -> Identity:
    cfg = _config.get()
    try:
        payload = jwt_util.decode(id_token, cfg.id_token_secret, audience=cfg.client_id,
                                  issuer=cfg.expected_issuer)
    except jwt_util.TokenError as e:
        raise OAuthError(f"id_token 验证不过：{e}") from e
    email, role = payload.get("email"), payload.get("role")
    if not email or not role:
        raise OAuthError("id_token 里没有 email/role")
    tier = tier_of(role)
    if tier is None:
        raise OAuthError("access_denied")
    return Identity(email=email, role=role, tier=tier)


def exchange_code(*, code: str, verifier: str, redirect_uri: str) -> Identity:
    """服务器对服务器：拿一次性 `code` + PKCE `verifier` 换 `id_token`，验签/验
    `aud`/`exp`/`iss`，映射角色。任何一步不对 → `OAuthError`（调用方接住转 403，
    不能让整个回调 500——网站总管规格第 3 条：「被停用的成员……平台要把它当
    无权限提示，不是崩」，同一个判断这里也适用于其它失败形态）。"""
    cfg = _config.get()
    try:
        resp = _get_client().post(cfg.token_url, data={
            "grant_type": "authorization_code", "code": code, "client_id": cfg.client_id,
            "client_secret": cfg.client_secret, "code_verifier": verifier,
            "redirect_uri": redirect_uri,
        })
    except httpx.HTTPError as e:
        raise OAuthError(f"token 端点打不通：{e}") from e
    if resp.status_code != 200:
        raise OAuthError(f"token 端点返回 {resp.status_code}")
    try:
        id_token = resp.json()["id_token"]
    except (ValueError, KeyError, TypeError) as e:
        raise OAuthError("token 端点响应里没有 id_token") from e
    return _identity_from_id_token(id_token)


# ── `--dev-idp`：本机假登录页，不打任何网络 ──────────────────────────
#
# 网站那两个端点要 10 月上旬才有 PR（网站总管 09-26 回单）。这里让「登录流程
# 本身对不对」不用等——`code` 照样 60 秒单次、`id_token` 照样过 `_identity_from_id_token`
# 那同一条验签路径，只是「谁、什么角色」由假登录页表单直接填，不用真 token_url。

_DEV_CODES: dict[str, dict] = {}


def dev_issue_code(*, email: str, role: str) -> str:
    code = secrets.token_urlsafe(16)
    _DEV_CODES[code] = {"email": email, "role": role, "exp": time.time() + 60, "used": False}
    return code


def dev_exchange_code(code: str) -> Identity:
    entry = _DEV_CODES.get(code)
    if entry is None or entry["used"] or time.time() > entry["exp"]:
        raise OAuthError("code 无效、已用过或已过期")
    entry["used"] = True
    cfg = _config.get()
    now = time.time()
    id_token = jwt_util.encode({
        "sub": entry["email"], "email": entry["email"], "role": entry["role"],
        "aud": cfg.client_id, "iss": cfg.expected_issuer or "dev-idp",
        "iat": now, "exp": now + 600,
    }, cfg.id_token_secret)
    return _identity_from_id_token(id_token)


def dev_reset() -> None:
    """测试隔离用。"""
    _DEV_CODES.clear()
