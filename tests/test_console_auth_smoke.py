# -*- coding: utf-8 -*-
"""控制台鉴权的 Playwright 冒烟：登录 → 打开一个 Step 页 → 退出。

任务书完成判据里唯一一条离不开真浏览器的：确认前端那套「未登录跳
`/auth/login`／带着会话能进／右上角退出」在真实请求-响应循环里真的接得上，
不是只在 `TestClient` 直调层面看着对（那套在 `test_console_auth.py`）。

用 `--dev-idp`（本机假登录页，不打网站真的 `/oauth/authorize`/`/oauth/token`——
那两个端点 10 月上旬才有 PR，见 overview 任务书 09-26 第二次改向）走一遍
**完整的** OAuth 授权码回调，不是绕过登录逻辑。

同 `test_console_tabs.py` 的路子——起真 uvicorn + 真 Chromium，标 `manual`
（默认不跑，见 `pyproject.toml` 的 `addopts = "-m 'not manual'"`）。**不需要
`guji-workspace`**：书用 `tests/fixtures/workspace`（冻结 fixture）。
"""
from __future__ import annotations

import os
import threading
import time
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


@pytest.fixture(scope="module")
def console_port():
    import uvicorn

    port = 8896
    env_overrides = {"GUJI_WORKSPACE": str(FIXTURE_WS)}
    saved = {k: os.environ.get(k) for k in env_overrides}
    os.environ.update(env_overrides)

    from open_guji_cv.console.app import app
    from open_guji_cv.console.auth import config as auth_config

    auth_config.reset_config()
    auth_config.set_config(dev_idp=True, id_token_secret="smoke-test-secret",
                           client_secret="smoke-test-secret")

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


def test_login_open_step_page_logout(console_port):
    from playwright.sync_api import sync_playwright

    base = f"http://127.0.0.1:{console_port}"
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROMIUM))
        context = browser.new_context()
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        # 一 · 未登录：打开控制台首页，应该被前端 (`useIdentity`) 送去
        # `/auth/login`，`--dev-idp` 下这条会再跳到假登录页表单——`goto` 本身
        # 就会跟完这条 302 链，落地时 `page.url` 已经是假登录页，不用再等一次
        # "新的" 导航（那才是超时的真正原因：这里根本不会再发生一次导航）。
        page.goto(f"{base}/", wait_until="networkidle")
        assert "/auth/dev-login" in page.url, f"未登录应该落在假登录页，实际是 {page.url}"

        # 二 · 登录：假登录页表单填 email/role，提交后走真实的
        # code→callback→会话 cookie 这一整条链路，不是走后门直接种 cookie。
        page.fill('input[name="email"]', "reviewer@example.com")
        page.select_option('select[name="role"]', "reviewer")
        page.click('button[type="submit"]')
        page.wait_for_url(f"{base}/", timeout=5000)
        assert page.locator("text=open-guji-cv 控制台").count() > 0
        assert page.locator("text=reviewer@example.com").count() > 0, "右上角（侧栏）没显示当前用户"

        # 三 · 打开一个 Step 页：书用 fixture 里的 keben（tests/fixtures/workspace）。
        before_errors = len(errors)
        page.goto(f"{base}/smoke/keben/step/step0/", wait_until="networkidle")
        time.sleep(0.8)
        assert len(errors) == before_errors, f"Step 页有 JS 报错：{errors[before_errors:]}"
        assert "/auth/login" not in page.url, "已登录不该再被赶去登录页"
        assert page.locator("nav.sidebar-steps a", has_text="Step0").count() > 0, "没看到 Step 导航——页面像是没渲染起来"

        # 四 · 退出：点侧栏「退出」，应该清会话回到首页——落地后 `useIdentity`
        # 自己就会发现没有会话、接着跳去登录页，是**同一串**导航，不用另外
        # `reload()` 去触发（试过 `reload()`：它和这条自动跳转经常撞在一起，
        # `reload()` 半路把正在跳转的 frame 干掉，报 `ERR_ABORTED`/frame
        # detached——两条都是导航，等**最终**落地的那一个就够了）。
        page.click("button.sidebar-user-logout")
        page.wait_for_load_state("networkidle", timeout=5000)
        assert "/auth/dev-login" in page.url, f"退出后该被赶去登录页，实际停在 {page.url}"

        browser.close()
