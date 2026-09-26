# -*- coding: utf-8 -*-
"""控制台 · 注册表 ＋ 前端入口。

books / pipelines / steps / kinds / index

路由体只做「解析参数 → 调库 → 返回」；领域逻辑在 `console/` 之外
（控制台重构 C2/C3）。四个 Store 从 `console/deps.py` 取。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from ..auth import require_reviewer
from ..static_path import STATIC
from ...core.book import list_books, load_book
from ...core.pipeline import list_pipelines, load_pipeline
from ...core.step import KINDS, STEPS
from ... import steps as _steps  # noqa: F401  —— 注册全部 Step 与产物种类

router = APIRouter()
#: 「/」「/v1/」是 SPA 外壳，**不挂鉴权**——未登录时前端要能加载出这层壳，
#: 才能拿到 JS 去判断「没登录，跳网站登录页」；反过来给壳本身鉴权会死循环。
_auth = Depends(require_reviewer)



# ── 注册表 ───────────────────────────────────────────────────────────
@router.get("/api/books", dependencies=[_auth])
def api_books() -> list[dict]:
    return [load_book(b).to_dict() for b in list_books()]



@router.get("/api/pipelines", dependencies=[_auth])
def api_pipelines() -> list[dict]:
    return [load_pipeline(p).to_dict() for p in list_pipelines()]



@router.get("/api/steps", dependencies=[_auth])
def api_steps() -> list[dict]:
    import open_guji_cv.steps  # noqa: F401
    return [s.describe() for s in STEPS.values()]



@router.get("/api/kinds", dependencies=[_auth])
def api_kinds() -> list[dict]:
    import open_guji_cv.steps  # noqa: F401
    return [{"id": k.id, "title": k.title, "storage": k.storage, "unit": k.unit,
             "coord_space": k.coord_space} for k in KINDS.values()]



# ── 静态 ─────────────────────────────────────────────────────────────
#
# v2（控制台重构v2，overview 仓 进度/控制台重构v2/方案.md）：React + 按
# <book>/step/<step>/ 的 URL 路由取代 v1 的单页 8-tab。`/` 发 v2 的
# `static/dist/index.html`；SPA 兜底路由在 `spa_fallback.py`（独立文件，
# `app.py` 里放在 ROUTERS 最后 include——它注册一个吃掉所有路径的
# `/{full_path:path}`，必须最后注册，否则会抢在其他 router 的 /api/* 前面）。
# v1 页面**没有删**，先保留在 /v1/（旧的 index.html + js/css 原样在 static/ 下），
# 供对照与回滚；v2 功能覆盖齐全后再退役。
_V2_INDEX = STATIC / "dist" / "index.html"


@router.get("/v1/", response_class=HTMLResponse)
def index_v1() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@router.get("/", response_class=HTMLResponse)
def index() -> str:
    return _V2_INDEX.read_text(encoding="utf-8")
