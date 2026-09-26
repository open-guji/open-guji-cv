# -*- coding: utf-8 -*-
"""控制台鉴权：不自建账号，身份委托给开源古籍网站的 OAuth 授权码 + PKCE 流程
（见 overview 任务书 `进度/控制台统一/任务书-C-登录与权限.md` 09-26 第二次改向）。"""
from __future__ import annotations

from . import config, oauth, session
from .guard import get_identity, require_admin, require_reviewer
from .identity import Identity, Tier, tier_of

__all__ = [
    "config",
    "oauth",
    "session",
    "get_identity",
    "require_admin",
    "require_reviewer",
    "Identity",
    "Tier",
    "tier_of",
]
