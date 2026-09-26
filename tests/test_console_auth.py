# -*- coding: utf-8 -*-
"""控制台鉴权（2026-09-26 接入网站账号体系）。

不自建账号——身份委托给网站的 `GET /api/auth/me`（见
`console/auth/identity.py` 头注与 overview 任务书「09-26 改向」一节）。
这里测的是**这一侧**：路由分级、缓存、身份接口挂掉不放行、`--no-auth`
只在本机允许、裁决记人、复核队列。不打真网站——用 `httpx.MockTransport`
假一个身份接口。
"""
from __future__ import annotations

import time

import httpx
import pytest
from fastapi.testclient import TestClient

# ⚠️ 不在模块顶层绑 `app`/`console_auth`/`auth_config`/`auth_identity`/`Identity`
# 这几个名字。`test_console_routes.py` 会在**它自己被 collect 时**把
# `open_guji_cv.console*` 整棵子树从 `sys.modules` 删掉再重 import（拿到全新的
# 模块/类对象，供它自己的「行为快照」用）。pytest 收集测试文件是按文件名排的，
# 本文件名字排在它前面（"auth" < "routes"），如果在模块顶层 `from ... import app`，
# 绑的就是**收集本文件那一刻**的旧一代对象；`test_console_routes.py` 随后再一换代，
# 本文件手上的 `app` 与当时才动态 import 出来的 `console_auth.get_identity`
# 就成了两代不同的对象——`app.dependency_overrides[key]` 按对象比对，
# 对不上会静默不生效（2026-09-26 实测：全仓一起跑才红，单跑本文件不红）。
# 改成在 `_reset_auth_state`（autouse，每条测试**真正执行时**才跑，
# 这时所有测试文件早就收集完、换代已经全部发生过）里现取，一次绑定给全模块用。


@pytest.fixture(autouse=True)
def _reset_auth_state():
    """鉴权是模块级单例（配置 + 身份缓存），不清干净会漏给下一条测试；
    顺带把 `app`/`console_auth`/... 这几个名字重新解析到「当前这一代」。"""
    import importlib

    global app, console_auth, auth_config, auth_identity, Identity, fetch_identity, tier_of
    app = importlib.import_module("open_guji_cv.console.app").app
    console_auth = importlib.import_module("open_guji_cv.console.auth")
    auth_config = importlib.import_module("open_guji_cv.console.auth.config")
    auth_identity = importlib.import_module("open_guji_cv.console.auth.identity")
    Identity = auth_identity.Identity
    fetch_identity = auth_identity.fetch_identity
    tier_of = auth_identity.tier_of

    auth_config.reset_config()
    auth_identity.clear_cache()
    auth_identity.set_client(None)
    yield
    auth_config.reset_config()
    auth_identity.clear_cache()
    auth_identity.set_client(None)


@pytest.fixture
def client():
    return TestClient(app)


# ── 角色映射 ─────────────────────────────────────────────────────────
def test_tier_of_maps_website_roles():
    assert tier_of("reviewer") == "reviewer"
    assert tier_of("editor") == "reviewer"
    assert tier_of("admin") == "admin"
    assert tier_of("reader") is None       # 网站现在不发这个角色，见不到就当够不上任何一级
    assert tier_of("") is None


# ── 身份委托：转发 cookie、缓存、接口挂掉不放行 ──────────────────────
def _mock_transport(responses: dict[str, tuple[int, dict | None]]):
    """`{cookie值: (status, body)}`——`httpx.MockTransport` 不碰真网络。"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        cookie = request.headers.get("cookie", "")
        status, body = responses.get(cookie, (401, None))
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def test_fetch_identity_forwards_cookie_and_maps_role():
    c, calls = _mock_transport({"sid=alice": (200, {"email": "alice@example.com", "role": "editor"})})
    auth_identity.set_client(c)
    ident = fetch_identity("sid=alice")
    assert ident == Identity(email="alice@example.com", role="editor", tier="reviewer")
    assert calls["n"] == 1


def test_fetch_identity_no_cookie_is_unauthenticated_without_network_call():
    c, calls = _mock_transport({})
    auth_identity.set_client(c)
    assert fetch_identity(None) is None
    assert fetch_identity("") is None
    assert calls["n"] == 0     # 没带 cookie，本来就不用问身份接口


def test_fetch_identity_unrecognized_role_is_none():
    c, calls = _mock_transport({"sid=x": (200, {"email": "x@example.com", "role": "reader"})})
    auth_identity.set_client(c)
    assert fetch_identity("sid=x") is None


def test_fetch_identity_endpoint_down_is_none_not_raise():
    """身份接口打不通（连接被拒）→ 401 不放行，不是 500。"""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    auth_identity.set_client(httpx.Client(transport=httpx.MockTransport(handler)))
    assert fetch_identity("sid=whatever") is None


def test_fetch_identity_caches_within_ttl():
    c, calls = _mock_transport({"sid=alice": (200, {"email": "alice@example.com", "role": "admin"})})
    auth_identity.set_client(c)
    auth_config.set_config(cache_ttl=60.0)
    for _ in range(5):
        fetch_identity("sid=alice")
    assert calls["n"] == 1, "60 秒内同一个 cookie 不该重复问身份接口"


def test_fetch_identity_ttl_expiry_asks_again(monkeypatch):
    c, calls = _mock_transport({"sid=alice": (200, {"email": "alice@example.com", "role": "admin"})})
    auth_identity.set_client(c)
    auth_config.set_config(cache_ttl=0.05)
    fetch_identity("sid=alice")
    time.sleep(0.08)
    fetch_identity("sid=alice")
    assert calls["n"] == 2, "网站改角色要在 TTL 之后一分钟内生效，缓存过期就该重新问"


# ── HTTP 层：未登录 401、角色不够 403、公开路由不挡 ──────────────────
def test_unauthenticated_gets_401(client):
    r = client.get("/api/books")
    assert r.status_code == 401


def test_reviewer_forbidden_on_admin_route(client):
    app.dependency_overrides[console_auth.get_identity] = lambda: Identity(
        email="r@example.com", role="reviewer", tier="reviewer")
    try:
        assert client.get("/api/status", params={"book": "vol01"}).status_code == 403  # runs 整个 admin 专属
        assert client.get("/api/gold").status_code == 403       # 金标：admin 专属
        assert client.get("/api/books").status_code == 200          # reviewer 能看的普通信息
        # 工作区列表**不是** admin 专属：选工作区/选书是校对者进控制台的第一步
        # （根路径的 WorkspacePickerPage 挂在这个接口上），谁登录进来都要经过它。
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


def test_public_routes_stay_public(client):
    """SPA 外壳与鉴权自身的两条路由不挂门禁——未登录也要能加载出「跳去登录」的那层壳。"""
    assert client.get("/").status_code == 200
    assert client.get("/v1/").status_code == 200
    assert client.get("/api/auth/config").status_code == 200
    assert client.get("/api/auth/me").status_code == 401     # 这条本身就是鉴权探针，未登录就是 401


def test_no_auth_bypasses_identity_fetch(client):
    auth_config.set_config(no_auth=True)
    r = client.get("/api/gold")   # --no-auth 给固定 admin 身份，admin 路由也进得去
    assert r.status_code == 200


# ── --no-auth 只在本机允许 ───────────────────────────────────────────
def test_no_auth_refused_on_public_host(monkeypatch, capsys):
    import argparse
    from open_guji_cv import cli_v2
    from open_guji_cv.console import app as console_app_mod

    # `cmd_console` 局部 `from .console.app import serve`——patch 源头，不是 cli_v2 自己的属性。
    monkeypatch.setattr(console_app_mod, "serve", lambda **kw: pytest.fail("不该走到 serve()"))
    args = argparse.Namespace(port=8640, no_browser=True, host="0.0.0.0",
                              no_auth=True, root_path="")
    with pytest.raises(SystemExit) as exc:
        cli_v2.cmd_console(args)
    assert exc.value.code != 0
    assert "127.0.0.1" in capsys.readouterr().err


def test_no_auth_allowed_on_loopback_host(monkeypatch):
    from open_guji_cv import cli_v2
    from open_guji_cv.console import app as console_app_mod

    calls = {}

    def fake_serve(**kw):
        calls.update(kw)

    monkeypatch.setattr(console_app_mod, "serve", fake_serve)
    import argparse
    args = argparse.Namespace(port=8640, no_browser=True, host="127.0.0.1",
                              no_auth=True, root_path="/collate")
    cli_v2.cmd_console(args)
    assert calls == {"port": 8640, "open_browser": False, "host": "127.0.0.1",
                     "root_path": "/collate"}
    assert auth_config.get().no_auth is True
    assert auth_config.get().root_path == "/collate"


# ── 裁决记人 ─────────────────────────────────────────────────────────
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
        assert evs[0]["actor"] == "user"     # actor 语义不变
    finally:
        app.dependency_overrides.clear()


def test_old_events_without_reviewer_field_still_parse():
    """老事件没有 `reviewer` 键——只加字段，不是破坏性改动。"""
    from open_guji_cv.feedback.events import Event, EventTarget
    e = Event.model_validate({
        "id": "evt_b_000001", "ts": "2026-01-01T00:00:00Z", "batch": "b", "seq": 1,
        "actor": "user", "kind": "confirm",
        "target": {"step": "seed_admit", "unit": "cell", "key": "vol01:1:1:1"},
        "payload": {},
    })
    assert e.reviewer is None
    assert isinstance(e.target, EventTarget)


# ── 复核队列：同一格不同人裁法不一致 ──────────────────────────────────
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
            r = c.post("/api/events", json=body)
            assert r.status_code == 200
        finally:
            app.dependency_overrides.clear()

    post_as("alice@example.com", "一")
    post_as("bob@example.com", "二")     # 同一个格，两人裁成不同字

    app.dependency_overrides[console_auth.get_identity] = lambda: Identity(
        email="alice@example.com", role="reviewer", tier="reviewer")
    try:
        conflicts = c.get("/api/review/conflicts", params={"batch": "conflict-batch"}).json()
    finally:
        app.dependency_overrides.clear()

    assert len(conflicts) == 1
    row = conflicts[0]
    assert row["key"] == "vol01:9:1:1"
    reviewers = {r["reviewer"]: r["payload"]["shape"] for r in row["reviewers"]}
    assert reviewers == {"alice@example.com": "一", "bob@example.com": "二"}

    # 事件日志里两条**都在**，谁也没覆盖谁——`/api/events` 是只追加的日志
    app.dependency_overrides[console_auth.get_identity] = lambda: Identity(
        email="alice@example.com", role="reviewer", tier="reviewer")
    try:
        all_events = c.get("/api/events", params={"batch": "conflict-batch"}).json()
    finally:
        app.dependency_overrides.clear()
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
