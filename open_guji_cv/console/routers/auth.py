# -*- coding: utf-8 -*-
"""控制台 · OAuth 客户端 + 鉴权自身的路由。

`/auth/login` → `/auth/callback` 是标准 OAuth2 授权码 + PKCE 的两段（另一段
`/oauth/authorize`、`/oauth/token` 在网站那边，见 overview 任务书 09-26 第二次
改向）。`/auth/logout` 只清平台自己的会话。`/api/auth/me` 是前端探测「我是谁」
用的，未登录时 `Depends(get_identity)` 自己就会抛 401。`/healthz` 免鉴权，给
部署健康检查（网站两个真端点还没上线时，这条至少能证明控制台本身活着）。

`--dev-idp` 开着时，`/auth/login` 把人带去本文件自己出的假登录页
（`/auth/dev-login`），不打任何网络——网站的两个端点预计 10 月上旬才有 PR
（网站总管 09-26 18:45 回单），本机开发/测试不等它。
"""
from __future__ import annotations

import secrets
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from ..auth import Identity, config as auth_config, get_identity, oauth, session

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@router.get("/api/auth/me")
def api_auth_me(identity: Identity = Depends(get_identity)) -> dict:
    return identity.model_dump()


def _redirect_uri(request: Request, cfg) -> str:
    if cfg.redirect_uri:
        return cfg.redirect_uri
    return f"{request.url.scheme}://{request.url.netloc}{cfg.root_path}/auth/callback"


def _app_path(cfg, path: str) -> str:
    """本应用自己的相对跳转（登录页/回调本身之外的地方）——挂在 `--root-path`
    前缀下时要带上，跟前端 `client.ts::withRoot` 是同一个约定。"""
    return f"{cfg.root_path}{path}"


@router.get("/auth/login")
def auth_login(request: Request, next: str = "/", prompt: str | None = None) -> RedirectResponse:
    cfg = auth_config.get()
    state = secrets.token_urlsafe(24)
    verifier, challenge = oauth.new_pkce_pair()
    redirect_uri = _redirect_uri(request, cfg)
    secure = request.url.scheme == "https"

    if cfg.dev_idp:
        target = (f"{_app_path(cfg, '/auth/dev-login')}?state={quote(state)}"
                 f"&redirect_uri={quote(redirect_uri)}")
    else:
        target = oauth.build_authorize_url(redirect_uri=redirect_uri, state=state,
                                           code_challenge=challenge, prompt=prompt)

    resp = RedirectResponse(target, status_code=302)
    token = session.build_flow_token(state=state, verifier=verifier, next_url=next,
                                     prompt=prompt, ttl=cfg.flow_ttl, secret=cfg.session_secret)
    session.set_flow_cookie(resp, token, secure=secure)
    return resp


@router.get("/auth/callback", response_model=None)
def auth_callback(request: Request, code: str | None = None, state: str | None = None,
                  error: str | None = None) -> RedirectResponse | PlainTextResponse:
    cfg = auth_config.get()
    secure = request.url.scheme == "https"
    flow = session.read_flow(request.cookies.get(session.FLOW_COOKIE))

    if flow is None:
        return PlainTextResponse("登录会话已过期，请重新开始登录。", status_code=400)

    if error:
        resp: RedirectResponse | PlainTextResponse
        if error == "login_required" and flow.get("prompt") == "none":
            # 静默刷新失败（网站那边登录态也没了）——退回真的交互式登录，
            # 不是当场报错卡住用户（网站总管规格第 4 条：未登录时网站自己会提示
            # 「请先用邀请链接登录」，那是网站页面上的事；这里只负责别在
            # prompt=none 这条路上死循环，改发一次不带 prompt 的登录）。
            resp = RedirectResponse(f"{_app_path(cfg, '/auth/login')}?next={quote(flow['next'])}",
                                    status_code=302)
        else:
            # access_denied（被停用的成员）之类——当无权限提示，不崩
            # （网站总管规格第 3 条）。
            resp = PlainTextResponse(f"登录被拒绝：{error}", status_code=403)
        session.clear_flow_cookie(resp)
        return resp

    if not code or not state or state != flow.get("state"):
        resp = PlainTextResponse("state 不匹配，拒绝这次回调（可能是重放或跨站请求）。",
                                 status_code=400)
        session.clear_flow_cookie(resp)
        return resp

    redirect_uri = _redirect_uri(request, cfg)
    try:
        if cfg.dev_idp:
            identity = oauth.dev_exchange_code(code)
        else:
            identity = oauth.exchange_code(code=code, verifier=flow["verifier"],
                                           redirect_uri=redirect_uri)
    except oauth.OAuthError as e:
        resp = PlainTextResponse(f"登录失败：{e}", status_code=403)
        session.clear_flow_cookie(resp)
        return resp

    resp = RedirectResponse(_app_path(cfg, flow.get("next") or "/"), status_code=302)
    session.clear_flow_cookie(resp)
    session.set_session_cookie(resp, email=identity.email, role=identity.role,
                               tier=identity.tier, secure=secure)
    return resp


@router.get("/auth/logout")
def auth_logout(request: Request, next: str = "/") -> RedirectResponse:
    cfg = auth_config.get()
    resp = RedirectResponse(_app_path(cfg, next), status_code=302)
    session.clear_session_cookie(resp)
    return resp


# ── `--dev-idp` 假登录页：只在 `dev_idp` 开着时有意义，没开时访问也不报错，
# 只是正常流程根本不会把人带到这里（`auth_login` 只在 `dev_idp` 时才生成这个链接）。
_DEV_LOGIN_FORM = """<!doctype html><html><body>
<h3>--dev-idp 假登录页（本机开发用，不是真的网站登录）</h3>
<form method="get" action="{action}">
  <input type="hidden" name="state" value="{state}">
  <input type="hidden" name="redirect_uri" value="{redirect_uri}">
  <label>email <input name="email" value="dev@example.com"></label><br>
  <label>role <select name="role">
    <option value="reviewer">reviewer</option>
    <option value="editor">editor</option>
    <option value="admin">admin</option>
  </select></label><br>
  <button type="submit">登录</button>
</form>
</body></html>"""


@router.get("/auth/dev-login")
def auth_dev_login(state: str, redirect_uri: str) -> HTMLResponse:
    cfg = auth_config.get()
    action = _app_path(cfg, "/auth/dev-login-submit")
    return HTMLResponse(_DEV_LOGIN_FORM.format(action=action, state=state, redirect_uri=redirect_uri))


@router.get("/auth/dev-login-submit")
def auth_dev_login_submit(state: str, redirect_uri: str, email: str, role: str) -> RedirectResponse:
    code = oauth.dev_issue_code(email=email.strip(), role=role.strip())
    return RedirectResponse(f"{redirect_uri}?code={quote(code)}&state={quote(state)}",
                            status_code=302)
