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
                      kind: str = "r2s", scope: str = "all") -> dict:
    """切线用例。pages='body' = page-type 金标判为正文的页（职名/目录页稍后）。

    `kind`：`r2s` 真粘连（切点有墨、附近无墨谷，投影法无解）；`split_char`
    切进字里（一矮一高 + 切点落在字**内部**的零墨空隙，2026-09-08 新增，
    见 `eval/touching.split_char_boundaries`）；`all` 两者都出。

    `scope`：`all`（默认，Step3 用）= 上面 `kind` 决定的全量用例；`blocking`
    （Step7「切分裁决」板块用）= 只出**顺序闸正在挡住字卡**的那批（`kind`
    参数被忽略——挡卡的判据本就是 r2s+split_char 两者都要查，见
    `review/cards.py::blocking_cutline_cases`）。两处共用同一份判据，
    不重新发明一套（那样两边会对不上号，见该函数 docstring 里踩过的坑）。
    """
    from ...eval import touching as T
    from ...review.cards import blocking_cutline_cases

    bk = load_book(book)
    if pages == "body":
        pg = [p for p in T.body_pages(book)]
    else:
        pg = bk.resolve_pages(pages)
    st = deps.product_store()
    if scope == "blocking":
        cases = blocking_cutline_cases(book, pg, st)
    elif kind == "split_char":
        cases = T.split_char_boundaries(book, pg, st)
    elif kind == "all":
        cases = T.r2s_boundaries(book, pg, st) + T.split_char_boundaries(book, pg, st)
    else:
        cases = T.r2s_boundaries(book, pg, st)
    n_all = len(cases)
    done: set[str] = set()
    if skip_done and scope != "blocking":  # blocking 的 cases 已经是「待办」，不用再滤一遍
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

    每个候选再挂上 Step4/5 打通的识别信息（overview 2026-09-11 下发）：选这个
    候选切法，上格/下格分别被库匹配认成什么字。数据来自 `char_index`
    （`CharRec.cand_variants`，给出候选试切字块）与 `glyph_match`
    （`MatchRec.cand_variants`，给出该字块的库匹配结果），按 `(side, cand_idx)`
    与 `cut_candidates[k].candidates` 的下标配对——上格用它的 `below` 候选，
    下格用它的 `above` 候选（`side` 是**格位视角**：见 `cell_shrink.py`
    `multi_above`/`multi_below` 的模块内注释，上格"往下看"这条切点用 below）。
    没跑过 Step4/5、或该格位/候选没有匹配结果时留空，前端按"没有识别信息"处理，
    不是错误。
    """
    from ...core.step import page_key

    per_page: dict[int, dict] = {}
    match_cache: dict[tuple[int, int], dict] = {}   # (page, slot) → {side: {cand_idx: MatchRec-ish dict}}

    def _match_map(pg: int, slot: int) -> dict:
        """这一格的候选匹配结果，外加它自己**当前**（chosen 那条）的匹配结果
        ——chosen 候选没有 `cand_variants`（Step4 不重复切它），它的识别信息
        就是这一格正式的 `MatchRec` 本身，存在 `out["chosen"]` 里，拼候选列表
        时按 `i == cp.chosen` 取用，不与其他候选混进同一个 side 字典。

        产物是外部磁盘状态，读取/解析失败（旧版本 schema 的存量产物、跑到
        一半的文件……）都不该让整个请求 500——候选信息本就是"有则显示、
        没有不算错"的增强项，见模块头。实测踩过一次：`glyph_match`
        `CandidateMatch` 加 `side` 字段前跑出的旧产物，pydantic 拿新
        schema 读会直接报 `Field required`。
        """
        key = (pg, slot)
        if key in match_cache:
            return match_cache[key]
        out: dict = {"above": {}, "below": {}, "chosen": None}
        try:
            mrec = st.read(book, "glyph_match", page_key(pg), "glyph_match")
        except Exception:
            mrec = None
        for cc in (mrec.columns if mrec else []):
            for r in cc.chars:
                if r.slot != slot or r.sub:
                    continue
                out["chosen"] = {"verdict": r.verdict, "char": r.char,
                                 "cov": r.cov, "wmax": r.wmax}
                for cv in (r.cand_variants or []):
                    out[cv.side][cv.cand_idx] = {
                        "verdict": cv.verdict, "char": cv.char,
                        "cov": cv.cov, "wmax": cv.wmax}
                break
        match_cache[key] = out
        return out

    for c in picked:
        pg = c["page"]
        if pg not in per_page:
            try:
                cells = st.read(book, "row_segment", page_key(pg), "cells")
            except Exception:
                cells = None
            m: dict = {}
            for cc in (cells.columns if cells else []):
                for cp in (getattr(cc, "cut_candidates", None) or []):
                    m[(cc.col, cp.slot_above)] = cp
            per_page[pg] = m
        cp = per_page[pg].get((c["col"], c["slot_above"]))
        if cp is None:
            c["candidates"], c["chosen"] = [], None
            continue
        # 上格（slot_above）的 below 候选 = 上格"往下看"这条切点；
        # 下格（slot_below）的 above 候选 = 下格"往上看"这条切点。两者
        # 是同一批候选的两个视角，逐 cand_idx 一一对应；chosen 那条没有
        # cand_variants（Step4 不重切它），改取这一格正式的 MatchRec。
        above_map = _match_map(pg, c["slot_above"])
        below_map = _match_map(pg, c["slot_below"])

        def _pick(m: dict, side: str, i: int) -> dict | None:
            return m["chosen"] if i == cp.chosen else m[side].get(i)

        c["candidates"] = [
            dict(kind=x.kind, y=x.y, seam_ink=x.seam_ink, dev_max=x.dev_max,
                 match_above=_pick(above_map, "below", i),
                 match_below=_pick(below_map, "above", i))
            for i, x in enumerate(cp.candidates)]
        c["chosen"] = cp.chosen



@router.get("/api/cutline/verdicts")
def api_cutline_verdicts(batch: str) -> dict:
    """读回本批已拖过的切线（刷新不重做；同 id 后到覆盖）。装配在 `review/verdict_view.py`。"""
    return cutline_verdicts(batch, deps.event_log())
