# -*- coding: utf-8 -*-
"""控制台鉴权的 Playwright 冒烟：登录 → 打开一个 Step 页 → 退出。

任务书完成判据里唯一一条离不开真浏览器的：确认前端那套「未登录跳网站登录页
／带着网站 cookie 能进／右上角退出」在真实请求-响应循环里真的接得上，不是
只在 `TestClient` 直调层面看着对（那套在 `test_console_auth.py`）。

同 `test_console_tabs.py` 的路子——起真 uvicorn + 真 Chromium，标 `manual`
（默认不跑，见 `pyproject.toml` 的 `addopts = "-m 'not manual'"`）。**不需要
`guji-workspace`**：书用 `tests/fixtures/workspace`（冻结 fixture，见任务书
「需要的仓」一行），身份接口用本文件自己起的假服务器，不打真网站。
"""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FIXTURE_WS = REPO / "tests" / "fixtures" / "workspace"
CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")


def _have(mod: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


_MISSING = [m for m in ("playwright.sync_api", "uvicorn", "fastapi") if not _have(m)]

pytestmark = [
    pytest.mark.manual,
    pytest.mark.skipif(bool(_MISSING),
                       reason=f"缺依赖：{_MISSING}（uv pip install playwright fastapi uvicorn）"),
    pytest.mark.skipif(not CHROMIUM.exists(), reason=f"没有预装的 Chromium：{CHROMIUM}"),
]

VALID_COOKIE = "sid=smoke-test-valid-token"
COOKIE_NAME, COOKIE_VALUE = "sid", "smoke-test-valid-token"


class _FakeAuthHandler(BaseHTTPRequestHandler):
    """假身份接口：`Cookie` 头等于 `VALID_COOKIE` 才认，其余一律 401。
    另兼两条假的登录/登出页——只用来给 Playwright 断言「跳去了这里」。"""

    def do_GET(self) -> None:  # noqa: N802 — http.server 的约定命名
        if self.path.startswith("/api/auth/me"):
            if self.headers.get("Cookie") == VALID_COOKIE:
                body = json.dumps({"email": "reviewer@example.com", "role": "reviewer"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
            else:
                body = b"{}"
                self.send_response(401)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/fake-login") or self.path.startswith("/fake-logout"):
            body = f"<html><body>{self.path}</body></html>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a) -> None:   # noqa: D102 — 安静点，别刷屏
        pass


@pytest.fixture(scope="module")
def fake_auth_server():
    server = HTTPServer(("127.0.0.1", 0), _FakeAuthHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def console_port(fake_auth_server):
    import uvicorn

    port = 8896
    auth_base = f"http://127.0.0.1:{fake_auth_server}"
    env_overrides = {
        "GUJI_AUTH_ME_URL": f"{auth_base}/api/auth/me",
        "GUJI_LOGIN_URL": f"{auth_base}/fake-login",
        "GUJI_LOGOUT_URL": f"{auth_base}/fake-logout",
        "GUJI_WORKSPACE": str(FIXTURE_WS),
    }
    saved = {k: os.environ.get(k) for k in env_overrides}
    os.environ.update(env_overrides)

    from open_guji_cv.console.app import app
    from open_guji_cv.console.auth import config as auth_config
    from open_guji_cv.console.auth import identity as auth_identity

    auth_config.reset_config()      # 逼它重新按（刚设好的）环境变量解析
    auth_identity.clear_cache()
    auth_identity.set_client(None)  # 逼它重建一个真 httpx.Client（不是别的测试留下的假 transport）

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    time.sleep(0.3)
    yield port

    server.should_exit = True
    thread.join(timeout=5)
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    auth_config.reset_config()
    auth_identity.clear_cache()
    auth_identity.set_client(None)


def test_login_open_step_page_logout(console_port):
    from playwright.sync_api import sync_playwright

    base = f"http://127.0.0.1:{console_port}"
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROMIUM))
        context = browser.new_context()
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        # 一 · 未登录：打开控制台首页，应该被前端 (`useIdentity`) 送去网站登录页
        # （这里是假的登录页，只用来证明跳转真的发生了）。
        page.goto(f"{base}/", wait_until="networkidle")
        time.sleep(0.5)
        assert "/fake-login" in page.url, f"未登录应该跳去假登录页，实际停在 {page.url}"

        # 二 · 登录：给浏览器种上假身份接口认得的 cookie（模拟网站登录成功后
        # 发的会话 cookie），再进控制台——这次不该再跳转。
        context.add_cookies([{
            "name": COOKIE_NAME, "value": COOKIE_VALUE,
            "domain": "127.0.0.1", "path": "/",
        }])
        page.goto(f"{base}/", wait_until="networkidle")
        time.sleep(0.5)
        assert page.url == f"{base}/", f"带着 cookie 还是被挡在外面：{page.url}"
        assert page.locator("text=open-guji-cv 控制台").count() > 0
        assert page.locator("text=reviewer@example.com").count() > 0, "右上角（侧栏）没显示当前用户"

        # 三 · 打开一个 Step 页：书用 fixture 里的 keben（tests/fixtures/workspace），
        # 工作区段随便写——没设 GUJI_WORKSPACE_DIRS 时白名单是空的，中间件认不出
        # 任何工作区 id，会整段忽略、退回 GUJI_WORKSPACE 本身（也就是这个 fixture）。
        before_errors = len(errors)
        page.goto(f"{base}/smoke/keben/step/step0/", wait_until="networkidle")
        time.sleep(0.8)
        assert len(errors) == before_errors, f"Step 页有 JS 报错：{errors[before_errors:]}"
        assert "/fake-login" not in page.url, "已登录不该再被赶去登录页"
        assert page.locator("nav.sidebar-steps a", has_text="Step0").count() > 0, "没看到 Step 导航——页面像是没渲染起来"

        # 四 · 退出：点侧栏「退出」，应该跳到假登出页。按钮的 onClick 自己先
        # `fetch` 一次 `/api/auth/config` 拿地址才跳，给够时间等这一趟网络往返。
        page.click("button.sidebar-user-logout")
        page.wait_for_url("**/fake-logout*", timeout=5000)
        assert "/fake-logout" in page.url, f"点退出该跳去假登出页，实际停在 {page.url}"

        browser.close()
