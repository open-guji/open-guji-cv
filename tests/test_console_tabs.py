"""控制台前端切分（C4）的验收关：8 个 tab 的 Playwright 冒烟快照。

前端没有现成的路由快照测试可用（那是 C0 的 tests/test_console_routes.py，测的是
后端路由实现体），这一关是本道自己立的——任务书要求「切分前后跑两次，
「8 个 tab × DOM id 集合 + 逐 tab JS 错误数」零差异」。

BASELINE 是切分前（2,331 行单文件 index.html，commit e33a6457）实测出的基线，
用本文件同一套采集逻辑跑一次就得到（见下面 _collect()）。切分后重跑，
应当逐 tab 零差异——这就是这份测试要断言的东西。

跑它需要：
  - `uv pip install playwright fastapi uvicorn`（都不在 pyproject 依赖里）
  - Chromium 在 `/opt/pw-browsers/chromium-1194/`（云端环境已预装，不要 `playwright install`）
  - `GUJI_WORKSPACE` 指到真书工作区，且 vol01 的 24/42 两页已经跑过 v2 管线：
    `python -m open_guji_cv glyph-db rebuild &&
     python -m open_guji_cv pipeline keben_body_v2 vol01 --pages 24,42`
    （子会话须知 §五：`pytest` 必须带 `-s`，不带会崩）
没有这些前提就跳过，不误报失败。
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
PROBE_PRODUCT = REPO / "products" / "vol01" / "border_detect" / "p0024.json"

playwright_sync = pytest.importorskip("playwright.sync_api", reason="需要 `uv pip install playwright`")
pytest.importorskip("uvicorn", reason="需要 `uv pip install uvicorn`")
pytest.importorskip("fastapi", reason="需要 `uv pip install fastapi`")

pytestmark = [
    pytest.mark.skipif(not CHROMIUM.exists(), reason=f"没有预装的 Chromium：{CHROMIUM}"),
    pytest.mark.skipif(not os.environ.get("GUJI_WORKSPACE"), reason="需要设 GUJI_WORKSPACE（子会话须知 §一）"),
    pytest.mark.skipif(
        not PROBE_PRODUCT.exists(),
        reason=(
            "需要先跑：python -m open_guji_cv glyph-db rebuild && "
            "python -m open_guji_cv pipeline keben_body_v2 vol01 --pages 24,42"
        ),
    ),
]

TABS = ["overview", "run", "products", "review", "cutline", "jiazhu", "evals", "variants"]

# 切分前（e33a6457，单文件 2,331 行 index.html）用本文件同一套 _collect() 逻辑
# 实测出的基线：8 个 tab 全部 active、DOM id 集合、逐 tab 新增 JS 错误数。
BASELINE = {
    "overview": {
        "ids": ["dag", "legend", "llm_online_note", "matrix", "notes",
                "params_note", "rl_go", "rl_out"],
    },
    "run": {
        "ids": ["force", "from_step", "jobs", "llm_enable", "llm_provider",
                "log", "logtitle", "params", "run_pages", "runform",
                "runmsg", "to_step"],
    },
    "products": {
        "ids": ["p_img", "p_json", "p_load", "p_meta", "p_page", "p_step"],
    },
    "review": {
        "ids": ["batches", "bmsg", "goldout", "goldtbl", "h_batch", "h_go", "h_out",
                "h_text", "q_go", "q_out", "r_dry", "r_go", "rd_go", "rd_out",
                "rv_batch", "rv_book", "rv_cards", "rv_load", "rv_msg", "rv_only",
                "rv_pages", "rv_run", "rv_send", "rv_todo"],
    },
    "cutline": {
        "ids": ["cl_batch", "cl_book", "cl_cards", "cl_kind", "cl_limit",
                "cl_load", "cl_msg", "cl_pages", "cl_todo"],
    },
    "jiazhu": {
        "ids": ["jz_batch", "jz_book", "jz_cards", "jz_load", "jz_msg",
                "jz_only", "jz_pages", "jz_submit"],
    },
    "evals": {
        "ids": ["ev_all", "ev_msg", "evout", "evtbl"],
    },
    "variants": {
        "ids": ["var_edition", "var_q", "var_reload", "var_stat", "var_tbl",
                "var_unknown", "vg_actions", "vg_grid", "vg_groups", "vg_load",
                "vg_msg", "vg_pages", "vg_send_all", "vg_send_changed",
                "vg_stale", "vg_stat"],
    },
}
BASELINE_TOTAL_404 = 0


def _collect(port: int) -> dict:
    """采集逻辑：8 个 tab 依次点开，记 active / DOM id 集合 / 新增 JS 错误数 / 总 404 数。

    与切分前测基线时用的是同一段逻辑（仓外 `/tmp/.../snapshot_tabs.py`，未入库）——
    这里重写一遍是为了让基线可以在这份测试里被复现，而不是只信一次性脚本的输出。
    """
    from playwright.sync_api import sync_playwright

    result = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROMIUM))
        page = browser.new_page()
        errors_total = []
        page.on("pageerror", lambda exc: errors_total.append(str(exc)))
        page.on("console", lambda msg: errors_total.append(msg.text) if msg.type == "error" else None)
        failed_404 = []
        page.on("response", lambda resp: failed_404.append(resp.url) if resp.status == 404 else None)

        page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
        time.sleep(1.0)

        for tab in TABS:
            before = len(errors_total)
            page.click(f'nav.tabs button[data-view="{tab}"]')
            time.sleep(0.8)
            active = page.eval_on_selector(f"#view-{tab}", "el => el.classList.contains('active')")
            ids = page.eval_on_selector_all(f"#view-{tab} [id]", "els => els.map(e => e.id).sort()")
            result[tab] = {
                "active": active,
                "ids": ids,
                "n_new_js_errors": len(errors_total) - before,
            }
        result["_total_404"] = len(failed_404)
        browser.close()
    return result


@pytest.fixture(scope="module")
def console_port():
    import uvicorn

    from open_guji_cv.console.app import app

    port = 8899
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    time.sleep(0.5)
    yield port
    server.should_exit = True
    thread.join(timeout=5)


def test_eight_tabs_match_baseline(console_port):
    got = _collect(console_port)

    for tab in TABS:
        assert got[tab]["active"] is True, f"{tab}: 切到这个 tab 后 section 没有 active"
        assert got[tab]["ids"] == BASELINE[tab]["ids"], f"{tab}: DOM id 集合与基线不一致"
        assert got[tab]["n_new_js_errors"] == 0, f"{tab}: 新增 {got[tab]['n_new_js_errors']} 条 JS 错误"

    assert got["_total_404"] <= BASELINE_TOTAL_404, (
        f"静态资源 404 从基线 {BASELINE_TOTAL_404} 条涨到了 {got['_total_404']} 条"
    )
