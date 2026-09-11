# -*- coding: utf-8 -*-
"""控制台 · 拖切线。

用例 / 裁决回读（列图裁段在 products.py）

路由体只做「解析参数 → 调库 → 返回」；领域逻辑在 `console/` 之外
（控制台重构 C2/C3）。四个 Store 从 `console/deps.py` 取。
"""
from __future__ import annotations

from fastapi import APIRouter

from .. import deps
from ..errors import maps_http
from ...core.book import load_book
from ...review.verdict_view import cutline_verdicts

router = APIRouter()



# ── 拖切线：粘连格线的理想切点金标 ─────────────────────────────────
#
# 用户 2026-09-05：「先让我添加一些金标，确定理想位置，再想算法。」
# R2s（真粘连）格线两侧都没有墨谷，投影法无解；要优化它先得有"该切在哪"的金标。
# 卡片 = 上下两格的列图裁片 + 一条可拖的横线（初值 = 现役切点）；裁决落 `cutline`
# 事件 → gold_add → char-segmentation/touching-cuts。坐标系 = 现役 Step2 列图。
_cutline_expected_cache: dict = {}



@router.get("/api/cutline/cases")
def api_cutline_cases(book: str = "vol01", pages: str = "body", limit: int = 250,
                      seed: int = 0, batch: str | None = None, skip_done: bool = True,
                      kind: str = "r2s") -> dict:
    """切线用例。pages='body' = page-type 金标判为正文的页（职名/目录页稍后）。

    `kind`：`r2s` 真粘连（切点有墨、附近无墨谷，投影法无解）；`split_char`
    切进字里（一矮一高 + 切点落在字**内部**的零墨空隙，2026-09-08 新增，
    见 `eval/touching.split_char_boundaries`）；`all` 两者都出。
    """
    from ...eval import touching as T

    bk = load_book(book)
    if pages == "body":
        pg = [p for p in T.body_pages(book)]
    else:
        pg = bk.resolve_pages(pages)
    st = deps.product_store()
    if kind == "split_char":
        cases = T.split_char_boundaries(book, pg, st)
    elif kind == "all":
        cases = T.r2s_boundaries(book, pg, st) + T.split_char_boundaries(book, pg, st)
    else:
        cases = T.r2s_boundaries(book, pg, st)
    n_all = len(cases)
    done: set[str] = set()
    if skip_done:
        done |= T.gold_ids()
        if batch:
            done |= {e.target.key for e in deps.event_log().read(batch) if e.kind == "cutline"}
    cases = [c for c in cases if c["id"] not in done]
    picked = T.pick_cases(cases, limit, seed=seed)
    # 期望字：整理本对齐金标（按页缓存，对齐 60 页约 1 分钟）
    key = (book, tuple(sorted({c["page"] for c in picked})))
    if key not in _cutline_expected_cache:
        T.attach_expected(picked, book, st)
        _cutline_expected_cache[key] = {c["id"]: (c.get("char_above", ""), c.get("char_below", "")) for c in picked}
    else:
        for c in picked:
            c["char_above"], c["char_below"] = _cutline_expected_cache[key].get(c["id"], ("", ""))
    _attach_candidates(st, book, picked)
    for c in picked:
        pad = 6
        c["crop_y0"] = max(0, c["y0"] - pad)
        c["crop_y1"] = min(c["col_h"], c["y1"] + pad)
        c["img"] = (f"/api/cutline/img/{book}/{c['page']}/{c['col']}.png"
                    f"?y0={c['crop_y0']}&y1={c['crop_y1']}")
    return {"book": book, "pages": pg, "n_r2s": n_all, "n_done": len(done),
            "n": len(picked), "cases": picked}


def _attach_candidates(st, book: str, picked: list[dict]) -> None:
    """把 row_segment 产物里的多切分候选挂到用例上（用户 2026-09-10：先让候选露出来）。

    产物只对**跑过的页**存在；没产物的页留空，面板就只显示现役缝，与改动前一致。
    配对按 (页, 列, 上格格位)：`r2s_boundaries` 用 up.slot 定名，`CutPointCandidates`
    用 slot_above —— 本用例这一列恰好就是产物里那个上格，唯一命中。
    候选的 y 是**列图坐标**（从内容窗口 x0 起，每 x 一个），与 case.seam 同口径。
    """
    from ...core.step import page_key

    per_page: dict[int, dict] = {}
    for c in picked:
        pg = c["page"]
        if pg not in per_page:
            cells = st.read(book, "row_segment", page_key(pg), "cells")
            m: dict = {}
            for cc in (cells.columns if cells else []):
                for cp in (getattr(cc, "cut_candidates", None) or []):
                    m[(cc.col, cp.slot_above)] = cp
            per_page[pg] = m
        cp = per_page[pg].get((c["col"], c["slot_above"]))
        # 坐标起点：本用例的 x0/宽度（现役缝同源），与产物列宽不一致时下游自己兜
        c["candidates"] = ([] if cp is None else
                           [dict(kind=x.kind, y=x.y, seam_ink=x.seam_ink, dev_max=x.dev_max)
                            for x in cp.candidates])
        c["chosen"] = None if cp is None else cp.chosen



@router.get("/api/cutline/verdicts")
def api_cutline_verdicts(batch: str) -> dict:
    """读回本批已拖过的切线（刷新不重做；同 id 后到覆盖）。装配在 `review/verdict_view.py`。"""
    return cutline_verdicts(batch, deps.event_log())
