# -*- coding: utf-8 -*-
"""身份委托：把请求带来的 Cookie 转发给网站的身份接口，换回 `{email, role}`。

**不存密码、不建账号表**——网站已有邀请制账号（JWT cookie + `AUTH_KV` 成员表），
这里只做「问一下、按 60 秒缓存、翻译成本服务认的两级角色」。

角色映射（网站 21 号文档 §三）：`reviewer` / `editor` → 校对者，`admin` → 管理员。
`reader` 网站现在不发，见到了当无权限处理（不是我们两级里的任何一级）。
"""
from __future__ import annotations

import time
from typing import Literal

import httpx
from pydantic import BaseModel

from . import config as _config

Tier = Literal["reviewer", "admin"]

#: 网站角色 → 本服务的两级角色。不在这张表里的角色（包括未来新增的、拼错的）
#: 一律当「够不上任何一级」，而不是猜一个默认值——宁可拒绝，不要误放行。
_ROLE_TIER: dict[str, Tier] = {"reviewer": "reviewer", "editor": "reviewer", "admin": "admin"}


class Identity(BaseModel):
    email: str
    role: str     # 网站原始角色（reviewer / editor / admin），日志与「谁裁的」用这个
    tier: Tier    # 映射后的两级角色，路由分级判的是这个


def tier_of(role: str) -> Tier | None:
    return _ROLE_TIER.get(role)


#: 按 Cookie 值缓存的最近一次身份结果。`None` 也缓存（未登录/角色不认得），
#: 免得每个匿名请求都去打身份接口。
_cache: dict[str, tuple[float, Identity | None]] = {}
_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=5.0)
    return _client


def set_client(client: httpx.Client | None) -> None:
    """测试用：换成指向假身份接口的 client；传 None 则下次用时按默认重建。"""
    global _client
    _client = client


def clear_cache() -> None:
    """测试隔离用；生产不必调用——缓存本来就按 TTL 自然过期。"""
    _cache.clear()


def fetch_identity(cookie_header: str | None) -> Identity | None:
    """转发 `cookie_header`（整条 Cookie 请求头原样转发，不解析里面的字段）到
    身份接口，`cache_ttl` 秒内同一个 Cookie 值不重复问。

    身份接口打不通 / 非 200 / JSON 里没有认得出的 email+role → `None`
    （按未登录处理，**不放行**——见任务书完成判据「身份接口挂掉 → 401 不放行」）。
    """
    if not cookie_header:
        return None
    now = time.monotonic()
    hit = _cache.get(cookie_header)
    cfg = _config.get()
    if hit is not None and now - hit[0] < cfg.cache_ttl:
        return hit[1]
    ident = _fetch_live(cookie_header, cfg.auth_me_url)
    _cache[cookie_header] = (now, ident)
    return ident


def _fetch_live(cookie_header: str, auth_me_url: str) -> Identity | None:
    try:
        resp = _get_client().get(auth_me_url, headers={"Cookie": cookie_header})
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
        email = data["email"]
        role = data["role"]
    except (ValueError, KeyError, TypeError):
        return None
    tier = tier_of(role)
    if tier is None:
        return None
    return Identity(email=email, role=role, tier=tier)
