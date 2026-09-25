# -*- coding: utf-8 -*-
"""控制台 · 字形库总览（`/:ws/glyphlib/`）。

正本见 overview 仓 项目进展/图片初步数字化/进度/字形库/02-控制台字形库总览.md。
此前字形库页只嵌了一个要先跑任务才出内容的异体组视图，打开是空的；这里给它
「这本书收了哪些字形」的只读口径。

口径全在 `clustering/glyph_ledger.py`（CLI `glyph-db stats` 同一份）：一个
glyph.db 的全部非字体来源 = 本书套，按字聚合、按格去重。路由体只做
「解析工作区 → 调 ledger → 返回」。全部只读打开 db，不跟跑批抢写锁。

跨书：单字页顺带列出**兄弟工作区**（`discover_workspaces()`，与工作区下拉框
同一份白名单）库里同一个字的刻例，图片 URL 带对方的 `ws=`，由中间件切过去取。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from ..errors import maps_http

router = APIRouter()


def _paths():
    from ...core.workspace import glyph_db_path, glyph_store_path
    db = glyph_db_path()
    if not Path(db).exists():
        raise HTTPException(404, f"这个工作区没有字形库：{db}")
    return db, glyph_store_path()


def _siblings() -> list[dict]:
    """其它工作区的字形库：[{ws, name, db}]，不含当前这个。"""
    from ...core.workspace import GLYPH_DB_REL, workspace_root
    from .workspace import discover_workspaces
    cur = workspace_root()
    cur = cur.resolve() if cur else None
    out = []
    for w in discover_workspaces():
        p = Path(w["path"])
        if cur is not None and p.resolve() == cur:
            continue
        db = p / GLYPH_DB_REL
        if db.exists():
            out.append({"ws": w["id"], "name": w["name"], "db": db})
    return out


@router.get("/api/glyphlib/summary")
@maps_http
def api_glyphlib_summary() -> dict:
    """总账：各来源、本书套（字种/刻例/来路/单例）、字体覆盖、store 漂移。
    另附兄弟工作区的字种数与共有字数（跨书比对的素材量）。"""
    from ...clustering.glyph_ledger import char_table, library_summary
    db, store = _paths()
    s = library_summary(db, store)
    mine = {r["char"] for r in char_table(db)}
    others = []
    for o in _siblings():
        try:
            theirs = {r["char"] for r in char_table(o["db"])}
        except Exception as e:           # 别的库坏了不该拖垮本页
            others.append({"ws": o["ws"], "name": o["name"], "error": str(e)})
            continue
        others.append({"ws": o["ws"], "name": o["name"], "chars": len(theirs),
                       "common": len(mine & theirs)})
    s["others"] = others
    return s


@router.get("/api/glyphlib/chars")
@maps_http
def api_glyphlib_chars() -> dict:
    """字表：一字一行（刻例数按格去重、来路分布、字头所在来源、字体里有没有）。
    过滤与排序在前端做——两本书都只有几千行。另附兄弟工作区的字集，
    供「只看本书独有 / 与某书共有」过滤。"""
    from ...clustering.glyph_ledger import char_table
    db, _ = _paths()
    rows = char_table(db)
    shared: dict[str, list[str]] = {}
    for o in _siblings():
        try:
            for r in char_table(o["db"]):
                shared.setdefault(r["char"], []).append(o["ws"])
        except Exception:
            continue
    for r in rows:
        r["also_in"] = shared.get(r["char"], [])
    return {"chars": rows}


@router.get("/api/glyphlib/char/{char}")
@maps_http
def api_glyphlib_char(char: str, others: int = 12) -> dict:
    """单字页：本书全部刻例（按来路）＋ 字体渲染 ＋ 兄弟工作区同字刻例（各取前 N）。"""
    from ...clustering.glyph_ledger import char_detail
    db, _ = _paths()
    d = char_detail(db, char)
    d["others"] = []
    for o in _siblings():
        try:
            od = char_detail(o["db"], char)
        except Exception:
            continue
        if od["exemplars"]:
            d["others"].append({"ws": o["ws"], "name": o["name"],
                                "n": len(od["exemplars"]),
                                "exemplars": od["exemplars"][:others]})
    return d


@router.get("/api/glyphlib/patch/{instance_id}.png")
@maps_http
def api_glyphlib_patch(instance_id: str) -> Response:
    """刻例图块（库里存的 canonical 原图，不是归一化图——人看的是原形）。"""
    import sqlite3
    db, _ = _paths()
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = c.execute("SELECT patch_png FROM instances WHERE instance_id=?",
                        (instance_id,)).fetchone()
    finally:
        c.close()
    if row is None:
        raise HTTPException(404, f"库里没有这个实例：{instance_id}")
    return Response(bytes(row[0]), media_type="image/png",
                    headers={"Cache-Control": "max-age=300"})
