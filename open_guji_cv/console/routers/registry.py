# -*- coding: utf-8 -*-
"""控制台 · 注册表 ＋ 前端入口。

books / pipelines / steps / kinds / index

路由体只做「解析参数 → 调库 → 返回」；领域逻辑在 `console/` 之外
（控制台重构 C2/C3）。四个 Store 从 `console/deps.py` 取。
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from ..static_path import STATIC
from ...core.book import list_books, load_book
from ...core.pipeline import list_pipelines, load_pipeline
from ...core.step import KINDS, STEPS
from ... import steps as _steps  # noqa: F401  —— 注册全部 Step 与产物种类

router = APIRouter()



# ── 注册表 ───────────────────────────────────────────────────────────
@router.get("/api/books")
def api_books() -> list[dict]:
    return [load_book(b).to_dict() for b in list_books()]



@router.get("/api/pipelines")
def api_pipelines() -> list[dict]:
    return [load_pipeline(p).to_dict() for p in list_pipelines()]



@router.get("/api/steps")
def api_steps() -> list[dict]:
    import open_guji_cv.steps  # noqa: F401
    return [s.describe() for s in STEPS.values()]



@router.get("/api/kinds")
def api_kinds() -> list[dict]:
    import open_guji_cv.steps  # noqa: F401
    return [{"id": k.id, "title": k.title, "storage": k.storage, "unit": k.unit,
             "coord_space": k.coord_space} for k in KINDS.values()]



# ── 静态 ─────────────────────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")
