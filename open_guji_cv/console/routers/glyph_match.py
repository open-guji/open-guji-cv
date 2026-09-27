# -*- coding: utf-8 -*-
"""控制台 · Step5-a 字形库匹配调试视图。

正本见 overview 仓 项目进展/图片初步数字化/进度/Step5-字符识别/
08-5a方案-字形库匹配调试视图.md——这一路（`clustering/match.py::GlyphMatcher`）
此前完全没有独立查询/查看方式，排查 unsure/diff 判定对不对时人没处可看。

路由体只做「解析参数 → 调库 → 返回」；matcher 缓存与查询逻辑在
`clustering/seeding.py::cached_matcher_from_db`（与 `GlyphMatchStep` 共用
同一份缓存，不重复维护）。**不改 `clustering/match.py` 本身**——算法一行
不动，只加只读查询接口。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from .. import deps
from ..auth import require_reviewer
from ..errors import maps_http
from ...core.book import load_book
from ...errors import ImageMissing
from ...utils.image_io import imread as cv_imread

router = APIRouter(dependencies=[Depends(require_reviewer)])


def _params_for_book(book: str, k: int):
    """这册书跑 `glyph_match` 时实际用的参数：管线 yaml 的 `params.glyph_match`
    覆盖在 `GlyphMatchParams` 默认值上，再补 Step 自己对现代书的 edition 缺省。
    台上看到的证据必须与管线判的是同一次匹配，否则人裁的是幻觉。"""
    from ...core.pipeline import default_pipeline_id, load_pipeline
    from ...steps.glyph_match import GlyphMatchParams

    b = load_book(book)
    overrides: dict = {}
    try:
        overrides = dict(load_pipeline(default_pipeline_id(b)).params.get("glyph_match") or {})
    except Exception:
        pass                      # 管线读不出来就退回裸默认值，不让调试视图整个挂掉
    overrides["knn_k"] = k
    p = GlyphMatchParams(**overrides)
    if p.edition is None and getattr(b, "edition", "keben") == "modern":
        p = p.model_copy(update={"edition": f"modern:{b.id}"})
    return p


@router.get("/api/glyph-match/{book}/{page}/{col}/{slot}")
@maps_http
def api_glyph_match_query(book: str, page: int, col: int, slot: int,
                          sub: str = "", k: int = 10) -> dict:
    """**字形库匹配调试视图**：查一个字位跟库里已验证刻例的完整 top-k
    比对结果——不是 `glyph_match` 产物里落盘的那份被 `max_candidates`
    截断、且 same/diff 档候选不全的版本，是现场对 `GlyphMatcher` 重新
    查询拿到的完整证据。

    `matched_id` 只在 same 档命中时有值（`GlyphMatcher.match()` 的
    `candidates` 字段本身是「字 → cov」的字典形态，归并到字的粒度，不是
    具体刻例——除了 same 档命中的第一名，其余候选字没有唯一对应的
    instance_id，前端据此只给第一名配缩略图，其余候选只显字+cov）。

    不传 `exclude_id`：调试视图要看的恰恰是「这个字位在库里查会不会查到
    自己」，跟正式识别流程摘除自身的防自证需求不同（见 `match.py`
    `GlyphMatcher.match` 的 `exclude_id` 说明）。

    **参数取自这册书实际走的管线**（`pipelines/<pid>.yaml` 的 `params.glyph_match`），
    不是 `GlyphMatchParams` 的裸默认值（2026-09-15 修）。此前写死默认值，现代印刷链
    在台上看到的是另一把尺子——管线跑的是笔宽归一 3px、库域 `modern:<book>`，调试视图
    却拿不归一的全库比，人照着台上的证据判，判的是不存在的那次匹配。
    """
    from ...clustering.normalize import normalize_patch
    from ...clustering.seeding import cached_matcher_from_db
    from ...steps.glyph_match import GlyphMatchParams, db_fingerprint

    ck = f"p{page:04d}c{col:02d}s{slot}{sub or ''}"
    path = deps.image_cache().get(book, "char_patch", ck)
    if path is None:
        raise ImageMissing(f"没有字块 p{page:04d}c{col:02d}s{slot}{sub or ''}")
    import cv2
    img = cv_imread(str(path), cv2.IMREAD_GRAYSCALE)

    p = _params_for_book(book, k)
    matcher, _chars = cached_matcher_from_db(
        p.db_path, db_fingerprint(p.db_path), edition=p.edition, knn_k=k,
        norm_stroke=p.norm_stroke)
    m = matcher.match(normalize_patch(img, stroke_width=p.norm_stroke))
    return {
        "id": f"{book}:{page}:{col}:{slot}{sub or ''}",
        "verdict": m.verdict, "char": m.char, "matched_id": m.matched_id,
        "cov": round(float(m.cov), 4), "wmax": round(float(m.wmax), 2),
        "guard": m.guard, "n_verified": int(m.n_verified),
        "edition": p.edition, "norm_stroke": p.norm_stroke,
        "candidates": [{"char": c, "cov": round(float(v), 4)}
                       for c, v in m.candidates],
    }


@router.get("/api/glyph-match/exemplar/{instance_id}.png")
@maps_http
def api_glyph_match_exemplar(instance_id: str) -> Response:
    """same 档候选第一名的缩略图——库里那个具体刻例的归一化图，供前端
    「这是谁 vs 库里像谁」两栏并排比对。直接读 `glyph.db` 的 `derived`
    表（`kind='norm'`），数据本身就是 PNG blob，不必再解码/重编码。
    """
    from ...clustering.glyph_db import GlyphDB
    from ...core.workspace import glyph_db_path

    db = GlyphDB(str(glyph_db_path()))
    row = db.conn.execute(
        "SELECT data FROM derived WHERE instance_id=? AND kind='norm'",
        (instance_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"库里没有这个实例的归一化图: {instance_id}")
    return Response(bytes(row[0]), media_type="image/png")


@router.get("/api/glyph-match/{book}/summary")
@maps_http
def api_glyph_match_summary(book: str, pages: str | None = None) -> dict:
    """板块②聚合数字：匹配档位分布（same/unsure/diff 计数）+ 护栏触发计数。
    见 `steps.glyph_match.glyph_match_summary`。
    """
    from ...steps.glyph_match import glyph_match_summary

    b = load_book(book)
    page_list = b.resolve_pages(pages) if pages else None
    return glyph_match_summary(book, page_list, deps.product_store())
