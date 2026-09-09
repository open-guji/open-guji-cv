# -*- coding: utf-8 -*-
"""控制台 FastAPI 应用：建 app、挂中间件与静态、include 11 个 router。

**这个文件只做装配**。46 条路由在 `routers/` 下按七类事分成 11 个文件
（见 `routers/__init__.py` 的表），领域逻辑在 `console/` 之外
（`render/overlay.py`、`review/cards.py`、`eval/quality.py`、
`clustering/rare_panel.py` 等，控制台重构 C2 搬出去的）。

改一条路由 → 改 `routers/<那一类>.py`，这里不用动。
"""
from __future__ import annotations

import threading
import webbrowser
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ..clustering.rare_panel import warm_font_index
from .static_path import STATIC
from .routers import (cutline, evals, feedback, gold, jiazhu, products, rare,
                      registry, review, runs, variants)

#: include 的顺序 = OpenAPI 文档里的顺序，与 `routers/__init__.py` 那张表一致。
ROUTERS = (registry, runs, products, feedback, gold, evals,
           review, cutline, jiazhu, rare, variants)

app = FastAPI(title="open-guji-cv 控制台", version="0.1")
# 允许离线页面回传裁决（2026-09-06）：`scripts/build_char_review.py` 出的按字复核页是
# 单文件 HTML，用 file:// 打开，origin 是 "null"，向 127.0.0.1 发 POST 会被 CORS 拦下
# （preflight 没有 Access-Control-Allow-Origin）。控制台本来就只绑回环地址、只给本机用，
# 放开跨域不扩大暴露面——不放开的话，那些页面就只能看不能改判。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # 含 file:// 的 "null" origin
    allow_credentials=False,  # 与 allow_origins=* 不能并存，也用不到 cookie
    allow_methods=["*"],
    allow_headers=["*"],
)
# 前端不是单文件：`static/index.html` 之外还有 `static/js/*.js` ＋ `static/css/*.css`，
# 那些文件要有人来发。**这行不能删**——`GET /` 只把 index.html 读成文本返回，
# 没有这个挂载，切分后的 js/css 全部 404（控制台重构 C1，前端道的前置）。
app.mount("/static", StaticFiles(directory=STATIC), name="static")

for _r in ROUTERS:
    app.include_router(_r.router)


def serve(port: int = 8640, open_browser: bool = True) -> None:
    import uvicorn
    url = f"http://127.0.0.1:{port}/"
    print(f"控制台: {url}")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    threading.Thread(target=warm_font_index, name="font-index-warm",
                     daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
