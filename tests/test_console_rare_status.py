# -*- coding: utf-8 -*-
"""`GET /api/rare/status`（任务书-K-控制台常驻内存，2026-09-28）：字体候选索引
现在能不能用，供控制台前端提示「字体候选暂不可用」。

只测路由薄转发对不对（返回 `rare_panel.font_index_status()` 原样），引擎逻辑
（`warm_font_index()` 的推迟判断）测在 `tests/test_font_candidates.py`。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_auth_state():
    """同 `test_console_auth.py`：重新解析到当前这一代模块，避免拿到收集时
    绑死的旧模块对象（见该文件模块头的说明）。"""
    import importlib

    global app, console_auth, auth_config, oauth, Identity
    app = importlib.import_module("open_guji_cv.console.app").app
    console_auth = importlib.import_module("open_guji_cv.console.auth")
    auth_config = importlib.import_module("open_guji_cv.console.auth.config")
    oauth = importlib.import_module("open_guji_cv.console.auth.oauth")
    Identity = importlib.import_module("open_guji_cv.console.auth.identity").Identity

    auth_config.reset_config()
    oauth.set_client(None)
    oauth.dev_reset()
    yield
    auth_config.reset_config()
    oauth.set_client(None)
    oauth.dev_reset()


@pytest.fixture
def client():
    return TestClient(app, follow_redirects=False)


def _as_reviewer():
    app.dependency_overrides[console_auth.get_identity] = lambda: Identity(
        email="r@example.com", role="reviewer", tier="reviewer")


def test_rare_status_reports_font_index_state(client, monkeypatch):
    from open_guji_cv.clustering import rare_panel

    monkeypatch.setitem(rare_panel.FONT_INDEX_STATE, "deferred", True)
    monkeypatch.setitem(rare_panel.FONT_INDEX_STATE, "ready", False)
    _as_reviewer()
    try:
        r = client.get("/api/rare/status")
        assert r.status_code == 200
        assert r.json() == {"deferred": True, "ready": False}
    finally:
        app.dependency_overrides.clear()


def test_rare_status_requires_reviewer(client):
    r = client.get("/api/rare/status")
    assert r.status_code == 401
