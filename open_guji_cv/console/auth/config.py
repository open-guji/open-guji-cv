# -*- coding: utf-8 -*-
"""OAuth 客户端配置：一律环境变量 > 默认值（跟 `core/workspace.py` 一个路数）。

**不自建账号**——密码、成员表都在网站那边；这里只存「去哪授权、用什么
client_id/secret、验 id_token 的密钥」。**`client_secret`/`id_token_secret`/
`session_secret` 都不进 git**，服务器本地环境变量注入。

09-26 第二次改向：从「转发 Cookie 问网站」换成标准 OAuth2 授权码 + PKCE——
平台暂时直连服务器 IP，不挂网站域名下，浏览器带不到网站的 Cookie，见 overview
任务书「09-26 第二次改向」一节。
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, replace

DEFAULT_AUTHORIZE_URL = "https://www.kaiyuanguji.com/oauth/authorize"
DEFAULT_TOKEN_URL = "https://www.kaiyuanguji.com/oauth/token"
DEFAULT_CLIENT_ID = "collate"
DEFAULT_ISSUER = "https://www.kaiyuanguji.com"
DEFAULT_SESSION_TTL = 8 * 3600.0
DEFAULT_ROLE_REFRESH_SECONDS = 3600.0
DEFAULT_FLOW_TTL = 300.0     # /auth/login → /auth/callback 这一趟往返，5 分钟够了


@dataclass(frozen=True)
class AuthConfig:
    authorize_url: str = DEFAULT_AUTHORIZE_URL
    token_url: str = DEFAULT_TOKEN_URL
    client_id: str = DEFAULT_CLIENT_ID
    #: 生产必填（服务器本地环境变量，不进 git）；`--dev-idp`/`--no-auth` 场景用不到。
    client_secret: str = ""
    #: 验 `id_token` 签名的 HS256 密钥，**与网站自己的 `AUTH_JWT_SECRET` 是两把不同的钥匙**
    #: （网站总管确认的规格第 3 条）。
    id_token_secret: str = ""
    expected_issuer: str | None = DEFAULT_ISSUER
    #: 不设就按请求现拼 `{scheme}://{netloc}{root_path}/auth/callback`；
    #: 网站那边是「redirect_uri 精确匹配白名单」，如果服务器在代理/多个域名后面
    #: 现拼可能对不上，这时才需要显式配置成对方白名单里那个精确值。
    redirect_uri: str | None = None
    session_ttl: float = DEFAULT_SESSION_TTL
    role_refresh_seconds: float = DEFAULT_ROLE_REFRESH_SECONDS
    flow_ttl: float = DEFAULT_FLOW_TTL
    #: 签平台自己的会话 cookie 与「登录中间态」cookie 用。不设就进程启动时随机
    #: 生成一个——会话本来就是这个进程的运行时状态，重启要求重新登录是可接受的
    #: （`JobRunner` 那套单例也是同一个哲学：进程内状态，不跨重启持久化）。
    session_secret: str = ""
    #: `--dev-idp`：本机假登录页（不打真的 authorize_url/token_url）。
    dev_idp: bool = False
    #: 关掉鉴权（本机开发用）。只允许在 host=127.0.0.1/localhost 时打开，
    #: 由 `guji console --no-auth` 或 `GUJI_CONSOLE_NO_AUTH=1` 设置，`cmd_console` 负责校验。
    no_auth: bool = False
    #: 挂在反向代理前缀下时的 root_path（如 `/collate`），传给 uvicorn 也传给前端。
    root_path: str = ""


_config: AuthConfig | None = None


def _from_env() -> AuthConfig:
    ttl = os.environ.get("GUJI_SESSION_TTL")
    refresh = os.environ.get("GUJI_ROLE_REFRESH_SECONDS")
    return AuthConfig(
        authorize_url=os.environ.get("GUJI_OAUTH_AUTHORIZE_URL", DEFAULT_AUTHORIZE_URL),
        token_url=os.environ.get("GUJI_OAUTH_TOKEN_URL", DEFAULT_TOKEN_URL),
        client_id=os.environ.get("GUJI_OAUTH_CLIENT_ID", DEFAULT_CLIENT_ID),
        client_secret=os.environ.get("GUJI_OAUTH_CLIENT_SECRET", ""),
        id_token_secret=os.environ.get("GUJI_OAUTH_ID_TOKEN_SECRET", ""),
        expected_issuer=os.environ.get("GUJI_OAUTH_EXPECTED_ISS", DEFAULT_ISSUER) or None,
        redirect_uri=os.environ.get("GUJI_OAUTH_REDIRECT_URI") or None,
        session_ttl=float(ttl) if ttl else DEFAULT_SESSION_TTL,
        role_refresh_seconds=float(refresh) if refresh else DEFAULT_ROLE_REFRESH_SECONDS,
        session_secret=os.environ.get("GUJI_SESSION_SECRET") or secrets.token_urlsafe(32),
        dev_idp=os.environ.get("GUJI_CONSOLE_DEV_IDP") == "1",
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
