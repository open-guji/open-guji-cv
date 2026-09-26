# -*- coding: utf-8 -*-
"""身份的数据形状 + 角色映射。

**不存密码、不建账号表**——网站已有邀请制账号，OAuth 授权码流程
（`console/auth/oauth.py`）换来的 `id_token` 里带 `email`/`role`；平台自己
只把它签进会话 cookie（`console/auth/session.py`），不另外问网站。

角色映射（网站 21 号文档 §三）：`reviewer` / `editor` → 校对者，`admin` → 管理员。
`reader` 网站现在不发，见到了当无权限处理（不是我们两级里的任何一级）。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

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
