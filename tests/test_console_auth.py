# -*- coding: utf-8 -*-
"""控制台鉴权（2026-09-26 第二次改向：OAuth2 授权码 + PKCE，平台与网站解耦）。

平台暂时直连服务器 IP，不挂网站域名下，浏览器带不到网站的 Cookie——不能再
转发 Cookie 问网站，改标准 OAuth2 授权码流程：`/auth/login` 302 到网站
`/oauth/authorize`（带 PKCE `code_challenge`）→ 网站确认身份后 302 回
`/auth/callback?code=...&state=...` → 平台服务器对服务器拿 `code` 换
`id_token`（网站 `/oauth/token`）→ 验签/`aud`/`exp` → 发平台自己的会话 cookie。

**不打真网站**：用 `httpx.MockTransport` 假 `token_url`，覆盖「真流程」的验证
逻辑（state/PKCE 换 code 这段 `oauth.exchange_code`）；另外 `--dev-idp` 那条完全
不碰网络的本地假登录路径单独测（`test_dev_idp_full_round_trip` 等）。
"""
from __future__ import annotations

import time

import httpx
import pytest
from fastapi.testclient import TestClient

# ⚠️ 不在模块顶层绑 `app`/`console_auth`/`auth_config`/`Identity` 这几个名字，
# 原因见 `_reset_auth_state`——`test_console_routes.py` 会在**它自己被 collect 时**
# 把 `open_guji_cv.console*` 整棵子树从 `sys.modules` 删掉再重 import
# （拿到全新的模块/类对象，供它自己的「行为快照」用）。pytest 收集测试文件按
# 文件名排序，本文件排它前面，若在模块顶层 import 绑的就是收集本文件那一刻
# 的旧一代对象，`app.dependency_overrides[key]` 按对象比对，跟后来才动态
# import 出来的东西对不上会静默不生效（2026-09-26 实测：全仓一起跑才红）。


@pytest.fixture(autouse=True)
def _reset_auth_state():
    """重新解析到「当前这一代」模块，并把鉴权配置/一次性 code 表清干净。"""
    import importlib

    global app, console_auth, auth_config, oauth, session, jwt_util, Identity
    app = importlib.import_module("open_guji_cv.console.app").app
    console_auth = importlib.import_module("open_guji_cv.console.auth")
    auth_config = importlib.import_module("open_guji_cv.console.auth.config")
    oauth = importlib.import_module("open_guji_cv.console.auth.oauth")
    session = importlib.import_module("open_guji_cv.console.auth.session")
    jwt_util = importlib.import_module("open_guji_cv.console.auth.jwt_util")
    Identity = importlib.import_module("open_guji_cv.console.auth.identity").Identity

    auth_config.reset_config()
    auth_config.set_config(id_token_secret="test-id-token-secret", client_secret="test-client-secret")
    oauth.set_client(None)
    oauth.dev_reset()
    yield
    auth_config.reset_config()
    oauth.set_client(None)
    oauth.dev_reset()


@pytest.fixture
def client():
    return TestClient(app, follow_redirects=False)


def _mint_id_token(*, email: str, role: str, secret: str | None = None, aud: str | None = None,
                   iss: str | None = None, exp_in: float = 600.0) -> str:
    cfg = auth_config.get()
    now = time.time()
    return jwt_util.encode({
        "email": email, "role": role, "aud": aud if aud is not None else cfg.client_id,
        "iss": iss if iss is not None else cfg.expected_issuer, "iat": now, "exp": now + exp_in,
    }, secret if secret is not None else cfg.id_token_secret)


def _mock_token_endpoint(id_token_by_code: dict[str, str], *, status: int = 200):
    """假 `token_url`：`code` → 直接回一个现成的 `id_token`（跳过真授权页，
    只测「平台这一侧」怎么用换回来的 `id_token`）。"""
    def handler(request: httpx.Request) -> httpx.Response:
        body = dict(x.split("=", 1) for x in request.content.decode().split("&"))
        from urllib.parse import unquote_plus
        code = unquote_plus(body.get("code", ""))
        id_token = id_token_by_code.get(code)
        if id_token is None:
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(status, json={"id_token": id_token})
    return httpx.Client(transport=httpx.MockTransport(handler))


# ── 角色映射 ─────────────────────────────────────────────────────────
def test_tier_of_maps_website_roles():
    from open_guji_cv.console.auth.identity import tier_of
    assert tier_of("reviewer") == "reviewer"
    assert tier_of("editor") == "reviewer"
    assert tier_of("admin") == "admin"
    assert tier_of("reader") is None
    assert tier_of("") is None


# ── HTTP 层：未登录 401、角色不够 403、公开路由不挡 ──────────────────
def test_unauthenticated_gets_401(client):
    assert client.get("/api/books").status_code == 401


def test_healthz_and_shell_stay_public(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/healthz").json() == {"ok": True}
    assert client.get("/").status_code == 200
    assert client.get("/v1/").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_reviewer_forbidden_on_admin_route(client):
    app.dependency_overrides[console_auth.get_identity] = lambda: Identity(
        email="r@example.com", role="reviewer", tier="reviewer")
    try:
        assert client.get("/api/status", params={"book": "vol01"}).status_code == 403
        assert client.get("/api/gold").status_code == 403
        assert client.get("/api/books").status_code == 200
        # 工作区列表不是 admin 专属：选工作区/选书是校对者进控制台的第一步。
        assert client.get("/api/workspace").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_admin_allowed_on_admin_route(client):
    app.dependency_overrides[console_auth.get_identity] = lambda: Identity(
        email="a@example.com", role="admin", tier="admin")
    try:
        assert client.get("/api/gold").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_no_auth_bypasses_session(client):
    auth_config.set_config(no_auth=True)
    assert client.get("/api/gold").status_code == 200


# ── --no-auth 只在本机允许 ───────────────────────────────────────────
def test_no_auth_refused_on_public_host(monkeypatch, capsys):
    import argparse
    from open_guji_cv import cli_v2
    from open_guji_cv.console import app as console_app_mod

    monkeypatch.setattr(console_app_mod, "serve", lambda **kw: pytest.fail("不该走到 serve()"))
    args = argparse.Namespace(port=8640, no_browser=True, host="0.0.0.0", no_auth=True,
                              root_path="", dev_idp=False)
    with pytest.raises(SystemExit) as exc:
        cli_v2.cmd_console(args)
    assert exc.value.code != 0
    assert "127.0.0.1" in capsys.readouterr().err


def test_no_auth_allowed_on_loopback_host(monkeypatch):
    from open_guji_cv import cli_v2
    from open_guji_cv.console import app as console_app_mod

    calls = {}
    monkeypatch.setattr(console_app_mod, "serve", lambda **kw: calls.update(kw))
    import argparse
    args = argparse.Namespace(port=8640, no_browser=True, host="127.0.0.1", no_auth=True,
                              root_path="/collate", dev_idp=True)
    cli_v2.cmd_console(args)
    assert calls == {"port": 8640, "open_browser": False, "host": "127.0.0.1",
                     "root_path": "/collate"}
    assert auth_config.get().no_auth is True
    assert auth_config.get().root_path == "/collate"
    assert auth_config.get().dev_idp is True


# ── OAuth 授权码 + PKCE：真流程（假 token_url），不打真网站 ──────────
def test_login_redirects_to_authorize_with_pkce(client):
    r = client.get("/auth/login")
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith(auth_config.get().authorize_url)
    assert "code_challenge=" in loc and "code_challenge_method=S256" in loc
    assert f"client_id={auth_config.get().client_id}" in loc
    assert "guji_oauth_flow" in r.cookies


def test_callback_state_mismatch_rejected(client):
    r = client.get("/auth/login")
    client.cookies.set("guji_oauth_flow", r.cookies["guji_oauth_flow"])
    r2 = client.get("/auth/callback", params={"code": "whatever", "state": "not-the-real-state"})
    assert r2.status_code == 400


def test_callback_without_flow_cookie_rejected(client):
    r2 = client.get("/auth/callback", params={"code": "whatever", "state": "whatever"})
    assert r2.status_code == 400


def test_full_authorization_code_round_trip(client):
    r = client.get("/auth/login")
    flow_cookie = r.cookies["guji_oauth_flow"]
    state = r.headers["location"].split("state=")[1].split("&")[0]
    client.cookies.set("guji_oauth_flow", flow_cookie)

    id_token = _mint_id_token(email="reviewer@example.com", role="reviewer")
    oauth.set_client(_mock_token_endpoint({"good-code": id_token}))

    r2 = client.get("/auth/callback", params={"code": "good-code", "state": state})
    assert r2.status_code == 302
    assert r2.headers["location"] == "/"
    session_cookie = r2.cookies["guji_session"]
    assert session_cookie

    client.cookies.set("guji_session", session_cookie)
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json() == {"email": "reviewer@example.com", "role": "reviewer", "tier": "reviewer"}


def test_code_replay_rejected(client):
    """`code` 只认一次——第二次拿同一个 code 换 token，假 token 端点会认得出
    （这里直接模拟"假 token_url 对已消费的 code 报 400"，因为 code 的单次性
    是网站那边（`/oauth/token`）的职责，不是平台验的；平台这一侧要验证的是
    「token 端点说不行，我就把这次登录当失败处理，不能悄悄放行」。"""
    r = client.get("/auth/login")
    flow_cookie = r.cookies["guji_oauth_flow"]
    state = r.headers["location"].split("state=")[1].split("&")[0]
    client.cookies.set("guji_oauth_flow", flow_cookie)

    oauth.set_client(_mock_token_endpoint({}))   # 空表：任何 code 都当"已用过/不认识"
    r2 = client.get("/auth/callback", params={"code": "replayed-code", "state": state})
    assert r2.status_code == 403


def test_id_token_wrong_signature_rejected(client):
    r = client.get("/auth/login")
    flow_cookie = r.cookies["guji_oauth_flow"]
    state = r.headers["location"].split("state=")[1].split("&")[0]
    client.cookies.set("guji_oauth_flow", flow_cookie)

    bad_token = _mint_id_token(email="x@example.com", role="reviewer", secret="wrong-secret")
    oauth.set_client(_mock_token_endpoint({"c1": bad_token}))
    r2 = client.get("/auth/callback", params={"code": "c1", "state": state})
    assert r2.status_code == 403


def test_id_token_expired_rejected(client):
    r = client.get("/auth/login")
    flow_cookie = r.cookies["guji_oauth_flow"]
    state = r.headers["location"].split("state=")[1].split("&")[0]
    client.cookies.set("guji_oauth_flow", flow_cookie)

    expired = _mint_id_token(email="x@example.com", role="reviewer", exp_in=-10)
    oauth.set_client(_mock_token_endpoint({"c1": expired}))
    r2 = client.get("/auth/callback", params={"code": "c1", "state": state})
    assert r2.status_code == 403


def test_id_token_wrong_audience_rejected(client):
    r = client.get("/auth/login")
    flow_cookie = r.cookies["guji_oauth_flow"]
    state = r.headers["location"].split("state=")[1].split("&")[0]
    client.cookies.set("guji_oauth_flow", flow_cookie)

    wrong_aud = _mint_id_token(email="x@example.com", role="reviewer", aud="someone-else")
    oauth.set_client(_mock_token_endpoint({"c1": wrong_aud}))
    r2 = client.get("/auth/callback", params={"code": "c1", "state": state})
    assert r2.status_code == 403


def test_id_token_unrecognized_role_treated_as_access_denied(client):
    r = client.get("/auth/login")
    flow_cookie = r.cookies["guji_oauth_flow"]
    state = r.headers["location"].split("state=")[1].split("&")[0]
    client.cookies.set("guji_oauth_flow", flow_cookie)

    weird_role = _mint_id_token(email="x@example.com", role="reader")
    oauth.set_client(_mock_token_endpoint({"c1": weird_role}))
    r2 = client.get("/auth/callback", params={"code": "c1", "state": state})
    assert r2.status_code == 403


def test_website_access_denied_error_is_403_not_crash(client):
    """网站直接在回调上带 `error=access_denied`（被停用的成员）——平台把它当
    无权限提示，不崩（网站总管规格第 3 条）。"""
    r = client.get("/auth/login")
    client.cookies.set("guji_oauth_flow", r.cookies["guji_oauth_flow"])
    r2 = client.get("/auth/callback", params={"error": "access_denied"})
    assert r2.status_code == 403


def test_login_required_with_prompt_none_redirects_to_real_login(client):
    """`prompt=none` 的静默刷新失败（网站登录态也没了）——不能死循环，
    改发一次不带 `prompt` 的真登录，`next` 保留。"""
    r = client.get("/auth/login", params={"next": "/x/keben/", "prompt": "none"})
    client.cookies.set("guji_oauth_flow", r.cookies["guji_oauth_flow"])
    r2 = client.get("/auth/callback", params={"error": "login_required"})
    assert r2.status_code == 302
    assert r2.headers["location"].startswith("/auth/login")
    assert "prompt=none" not in r2.headers["location"]
    assert "next=" in r2.headers["location"]


def test_role_refresh_expires_session(client):
    """会话建立超过 `role_refresh_seconds` → 当未登录处理（401），
    逼前端重新走一遍 authorize（角色变了要在这段时间内生效）。"""
    auth_config.set_config(role_refresh_seconds=0.05)
    cfg = auth_config.get()
    old_token = session.build_session_token(email="a@example.com", role="reviewer",
                                            tier="reviewer", ttl=cfg.session_ttl,
                                            secret=cfg.session_secret)
    client.cookies.set("guji_session", old_token)
    assert client.get("/api/auth/me").status_code == 200
    time.sleep(0.08)
    assert client.get("/api/auth/me").status_code == 401


def test_logout_clears_session_cookie(client):
    cfg = auth_config.get()
    token = session.build_session_token(email="a@example.com", role="reviewer", tier="reviewer",
                                        ttl=cfg.session_ttl, secret=cfg.session_secret)
    client.cookies.set("guji_session", token)
    r = client.get("/auth/logout")
    assert r.status_code == 302
    set_cookie = r.headers.get("set-cookie", "")
    assert "guji_session=" in set_cookie and "Max-Age=0" in set_cookie


# ── `--dev-idp`：本机假登录页，全程不碰网络 ──────────────────────────
def test_dev_idp_full_round_trip(client):
    auth_config.set_config(dev_idp=True)
    r = client.get("/auth/login", params={"next": "/x/keben/"})
    assert r.status_code == 302
    assert "/auth/dev-login" in r.headers["location"]
    client.cookies.set("guji_oauth_flow", r.cookies["guji_oauth_flow"])

    page = client.get(r.headers["location"])
    assert page.status_code == 200
    import re
    state = re.search(r'name="state" value="([^"]+)"', page.text).group(1)
    redirect_uri = re.search(r'name="redirect_uri" value="([^"]+)"', page.text).group(1)

    submit = client.get("/auth/dev-login-submit", params={
        "state": state, "redirect_uri": redirect_uri,
        "email": "dev-reviewer@example.com", "role": "admin",
    })
    assert submit.status_code == 302
    from urllib.parse import urlsplit
    u = urlsplit(submit.headers["location"])

    callback = client.get(u.path, params=dict(p.split("=") for p in u.query.split("&")))
    assert callback.status_code == 302
    assert callback.headers["location"] == "/x/keben/"
    client.cookies.set("guji_session", callback.cookies["guji_session"])

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json() == {"email": "dev-reviewer@example.com", "role": "admin", "tier": "admin"}


def test_dev_idp_code_is_single_use(client):
    auth_config.set_config(dev_idp=True)
    code = oauth.dev_issue_code(email="x@example.com", role="reviewer")
    ident1 = oauth.dev_exchange_code(code)
    assert ident1.email == "x@example.com"
    with pytest.raises(oauth.OAuthError):
        oauth.dev_exchange_code(code)


# ── 裁决记人（不受这次改向影响，仍然是 events.py 的可选字段）─────────
def test_events_are_tagged_with_reviewer_email(tmp_path, monkeypatch):
    from open_guji_cv.console import deps

    for key in ("feedback", "batches", "dataset"):
        monkeypatch.setitem(deps._roots, key, tmp_path / key)
    for cached in ("_log", "_batches", "_gold"):
        monkeypatch.setattr(deps, cached, None)

    app.dependency_overrides[console_auth.get_identity] = lambda: Identity(
        email="reviewer1@example.com", role="reviewer", tier="reviewer")
    try:
        c = TestClient(app)
        body = {"batch": "t", "step": "seed_admit", "unit": "cell", "kind": "confirm",
                "consume": False,
                "events": [{"id": "vol01:4:1:3", "v": "confirm", "shape": "一"}]}
        r = c.post("/api/events", json=body)
        assert r.status_code == 200
        evs = c.get("/api/events", params={"batch": "t"}).json()
        assert len(evs) == 1 and evs[0]["reviewer"] == "reviewer1@example.com"
        assert evs[0]["actor"] == "user"
    finally:
        app.dependency_overrides.clear()


def test_old_events_without_reviewer_field_still_parse():
    from open_guji_cv.feedback.events import Event, EventTarget
    e = Event.model_validate({
        "id": "evt_b_000001", "ts": "2026-01-01T00:00:00Z", "batch": "b", "seq": 1,
        "actor": "user", "kind": "confirm",
        "target": {"step": "seed_admit", "unit": "cell", "key": "vol01:1:1:1"},
        "payload": {},
    })
    assert e.reviewer is None
    assert isinstance(e.target, EventTarget)


def test_conflicting_verdicts_both_kept_and_flagged(tmp_path, monkeypatch):
    from open_guji_cv.console import deps

    for key in ("feedback", "batches", "dataset"):
        monkeypatch.setitem(deps._roots, key, tmp_path / key)
    for cached in ("_log", "_batches", "_gold"):
        monkeypatch.setattr(deps, cached, None)

    c = TestClient(app)

    def post_as(email: str, char: str):
        app.dependency_overrides[console_auth.get_identity] = lambda e=email: Identity(
            email=e, role="reviewer", tier="reviewer")
        try:
            body = {"batch": "conflict-batch", "step": "seed_admit", "unit": "cell",
                    "kind": "confirm", "consume": False,
                    "events": [{"id": "vol01:9:1:1", "v": "confirm", "shape": char}]}
            assert c.post("/api/events", json=body).status_code == 200
        finally:
            app.dependency_overrides.clear()

    post_as("alice@example.com", "一")
    post_as("bob@example.com", "二")

    app.dependency_overrides[console_auth.get_identity] = lambda: Identity(
        email="alice@example.com", role="reviewer", tier="reviewer")
    try:
        conflicts = c.get("/api/review/conflicts", params={"batch": "conflict-batch"}).json()
        all_events = c.get("/api/events", params={"batch": "conflict-batch"}).json()
    finally:
        app.dependency_overrides.clear()

    assert len(conflicts) == 1
    row = conflicts[0]
    assert row["key"] == "vol01:9:1:1"
    reviewers = {r["reviewer"]: r["payload"]["shape"] for r in row["reviewers"]}
    assert reviewers == {"alice@example.com": "一", "bob@example.com": "二"}
    assert len(all_events) == 2


def test_agreeing_verdicts_are_not_a_conflict(tmp_path, monkeypatch):
    from open_guji_cv.console import deps

    for key in ("feedback", "batches", "dataset"):
        monkeypatch.setitem(deps._roots, key, tmp_path / key)
    for cached in ("_log", "_batches", "_gold"):
        monkeypatch.setattr(deps, cached, None)

    c = TestClient(app)

    def post_as(email: str):
        app.dependency_overrides[console_auth.get_identity] = lambda e=email: Identity(
            email=e, role="reviewer", tier="reviewer")
        try:
            body = {"batch": "agree-batch", "step": "seed_admit", "unit": "cell",
                    "kind": "confirm", "consume": False,
                    "events": [{"id": "vol01:9:1:2", "v": "confirm", "shape": "三"}]}
            assert c.post("/api/events", json=body).status_code == 200
        finally:
            app.dependency_overrides.clear()

    post_as("alice@example.com")
    post_as("bob@example.com")

    app.dependency_overrides[console_auth.get_identity] = lambda: Identity(
        email="alice@example.com", role="reviewer", tier="reviewer")
    try:
        conflicts = c.get("/api/review/conflicts", params={"batch": "agree-batch"}).json()
    finally:
        app.dependency_overrides.clear()
    assert conflicts == []
