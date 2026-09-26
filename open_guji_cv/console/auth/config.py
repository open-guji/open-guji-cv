# -*- coding: utf-8 -*-
"""身份委托的配置：一律环境变量 > 默认值（跟 `core/workspace.py` 一个路数）。

**不自建账号**（2026-09-26 用户改向，见 overview 任务书）：这里只存「去哪问身份」，
不存密码、不存成员表、不碰网站的 `AUTH_JWT_SECRET`。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace

DEFAULT_AUTH_ME_URL = "https://www.kaiyuanguji.com/api/auth/me"
DEFAULT_LOGIN_URL = "https://www.kaiyuanguji.com/join"
DEFAULT_CACHE_TTL = 60.0


@dataclass(frozen=True)
class AuthConfig:
    #: 身份接口——带着请求人的 Cookie 去问「你是谁」。`GUJI_AUTH_ME_URL`。
    auth_me_url: str = DEFAULT_AUTH_ME_URL
    #: 未登录时前端跳去哪。`GUJI_LOGIN_URL`。
    login_url: str = DEFAULT_LOGIN_URL
    #: 退出时前端跳去哪；不设就退回 `login_url`（重新走一遍登录）。`GUJI_LOGOUT_URL`。
    logout_url: str | None = None
    #: 同一个 Cookie 值这么多秒内不重复问身份接口（网站那边改角色，这段时间内不生效）。
    #: `GUJI_AUTH_CACHE_TTL`。
    cache_ttl: float = DEFAULT_CACHE_TTL
    #: 关掉鉴权（本机开发用）。只允许在 host=127.0.0.1/localhost 时打开，
    #: 由 `guji console --no-auth` 或 `GUJI_CONSOLE_NO_AUTH=1` 设置，`cmd_console` 负责校验。
    no_auth: bool = False
    #: 挂在反向代理前缀下时的 root_path（如 `/collate`），传给 uvicorn 也传给前端。
    #: `GUJI_CONSOLE_ROOT_PATH`。
    root_path: str = ""


_config: AuthConfig | None = None


def _from_env() -> AuthConfig:
    ttl = os.environ.get("GUJI_AUTH_CACHE_TTL")
    return AuthConfig(
        auth_me_url=os.environ.get("GUJI_AUTH_ME_URL", DEFAULT_AUTH_ME_URL),
        login_url=os.environ.get("GUJI_LOGIN_URL", DEFAULT_LOGIN_URL),
        logout_url=os.environ.get("GUJI_LOGOUT_URL") or None,
        cache_ttl=float(ttl) if ttl else DEFAULT_CACHE_TTL,
        no_auth=os.environ.get("GUJI_CONSOLE_NO_AUTH") == "1",
        root_path=os.environ.get("GUJI_CONSOLE_ROOT_PATH", ""),
    )


def get() -> AuthConfig:
    global _config
    if _config is None:
        _config = _from_env()
    return _config


def set_config(**kwargs) -> AuthConfig:
    """显式覆盖若干字段（CLI 解析完参数后调用一次；测试里也用它）。不传的字段保持原样。"""
    global _config
    _config = replace(get(), **kwargs)
    return _config


def reset_config() -> None:
    """回到「按环境变量重新解析」。测试用例之间隔离用。"""
    global _config
    _config = None
