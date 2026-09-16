# -*- coding: utf-8 -*-
"""控制台 · 拖切线。

用例 / 裁决回读（列图裁段在 products.py）

路由体只做「解析参数 → 调库 → 返回」；领域逻辑在 `console/` 之外
（控制台重构 C2/C3）。四个 Store 从 `console/deps.py` 取。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

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
    st = deps.product_store()
    drift_skipped: dict = {}
    drift = pages in ("drift", "stale") or pages.startswith("list:")
    only_ids: set[str] | None = None
    if pages.startswith("list:"):
        # 复核清单模式（2026-09-14）：页码框填 list:<名字>，读 workspace feedback/lists/<名字>.txt
        # （一行一个金标 id，# 开头是注释），按 id 出卡、不管过没过期。用途：机器筛出「多候选卡上
        # 按了 ok，可能本想选切法」之类的可疑条目，让人回头只看这几张。
        from ...core.workspace import feedback_root
        lp = feedback_root() / "lists" / f"{pages[5:].strip()}.txt"
        if not lp.exists():
            raise HTTPException(404, f"清单不存在：{lp}")
        only_ids = {ln.strip() for ln in lp.read_text(encoding="utf-8").splitlines()
                    if ln.strip() and not ln.startswith("#")}
    if drift:
        # 「坐标过期重标」模式（2026-09-14）：页码框填 drift，出**金标 col_h 与当前列图高不一致**
        # 的那批切点（按 slot 对回当前 cells，id 沿用金标 id）。它们本来就在金标里，所以
        # 这一档不按 gold_ids 跳过、也不按批次事件跳过（重裁过的 col_h 已是当前值，自己出池）；`kind` 忽略。
        # 「只看未裁」取消时把本批次已重标的也出出来（col_h 已换成当前，否则找不回），供 U 重做。
        # 「已重标」= 本批次里有一条切线事件的 col_h 就是当前列高；不按批次名判（批次框留空时
        # 事件落进 vol03-cutline 这种老批次，按名字算全成了「已裁」，2026-09-14 实测只剩 4 条可裁）。
        relabeled: dict[str, set[int]] = {}
        if batch and not skip_done:
            for e in deps.event_log().read(batch):
                if e.kind == "cutline" and e.payload.get("col_h"):
                    relabeled.setdefault(e.target.key, set()).add(int(e.payload["col_h"]))
        cases, drift_skipped = T.drifted_boundaries(book, st, include_relabeled=relabeled or None, only_ids=only_ids)
        pg = sorted({c["page"] for c in cases})
    elif pages in ("escalated", "esc"):
        # 升级切点模式（2026-09-15，10 卡 L5）：直接读 Step3 产物里 `escalate=True` 的切点——
        # L2′/L0′ 说「本层拿不准」的那些，池里已由 L3 补过 unet_seam / period_* 候选。
        # 与 `list:` 模式的区别：那个只能出**已在裁决表里**的金标 id（152 条升级点里只有 7 条），
        # 这个直接从产物出，新切点也能出卡。
        # 口径是「21 格标准版式」（正文 + 目录 + 牌记/诏令），不是纯正文——2026-09-16：
        # vol01 近一半页是目录/职名，只取 body 会把 201 条升级切点挡掉 166 条。
        # 职名页仍排除在外（大小字混排，列切本身是坏的，见 STD_GRID_TYPES 注释）。
        pg = [p for p in T.std_grid_pages(book)]
    else:
        pg = bk.resolve_pages(pages)
    if drift:
        pass
    elif pages in ("escalated", "esc"):
        cases, esc_skipped = T.escalated_boundaries(book, pg, st)
        drift_skipped = {**drift_skipped, **esc_skipped}
    elif scope == "blocking":
        cases = blocking_cutline_cases(book, pg, st)
    elif kind == "split_char":
        cases = T.split_char_boundaries(book, pg, st)
    elif kind == "all":
        cases = T.r2s_boundaries(book, pg, st) + T.split_char_boundaries(book, pg, st)
    else:
        cases = T.r2s_boundaries(book, pg, st)
    n_all = len(cases)
    done: set[str] = set()
    esc_mode = pages in ("escalated", "esc")
    if skip_done and scope != "blocking" and not drift and not esc_mode:
        # blocking 的 cases 已经是「待办」，不用再滤一遍；drift 那批重裁后 col_h 变成当前值、
        # 自己出池，也不能按批次事件滤（老批次里的历史事件会把整批都算成已裁）
        done |= T.gold_ids()
        if batch:
            done |= {e.target.key for e in deps.event_log().read(batch) if e.kind == "cutline"}
    elif skip_done and esc_mode and batch:
        # 升级模式：**不按 gold_ids 滤**（152 条升级切点里只有 7 条在金标里，滤了就几乎全没了），
        # 只按本批次已裁的事件滤——人裁完一条它就从「未裁」里消失。
        done |= {e.target.key for e in deps.event_log().read(batch) if e.kind == "cutline"}
    cases = [c for c in cases if c["id"] not in done]
    picked = T.pick_cases(cases, limit, seed=seed)
    # 期望字：整理本对齐金标（按页缓存，对齐 60 页约 1 分钟）。
    # 缓存的字段清单要与 `attach_expected` 写出的那批**一致**——少列一个，
    # 缓存命中的那条路径就会静默丢字段（首次请求有、刷新一次就没了）。
    _EXP_KEYS = ("char_above", "char_below", "shape_above", "shape_below",
                 "conv_above", "conv_below")
    key = (book, tuple(sorted({c["page"] for c in picked})))
    if drift:
        # 期望字沿用金标里的（06 卡人裁洗过），不再重新对齐整理本
        for c in picked:
            for k in _EXP_KEYS:
                c.setdefault(k, "")
    elif key not in _cutline_expected_cache:
        T.attach_expected(picked, book, st)
        _cutline_expected_cache[key] = {c["id"]: {k: c.get(k, "") for k in _EXP_KEYS} for c in picked}
    else:
        for c in picked:
            c.update(_cutline_expected_cache[key].get(c["id"], {k: "" for k in _EXP_KEYS}))
    _attach_candidates(st, book, picked)
    for c in picked:
        pad = 6
        c["crop_y0"] = max(0, c["y0"] - pad)
        c["crop_y1"] = min(c["col_h"], c["y1"] + pad)
        c["img"] = (f"/api/cutline/img/{book}/{c['page']}/{c['col']}.png"
                    f"?y0={c['crop_y0']}&y1={c['crop_y1']}")
    # 语料读错了（控制台进程没带 GUJI_WORKSPACE）→ 整理本锚不上，卡片上
    # 「整理本期望」那两个字是拿 6000 字样本硬锚出来的噪声。这种情况下页面
    # 照常渲染、没有任何报错，人只会觉得「附带信息不准确」而不会想到是环境
    # 变量——所以必须把它摆到返回值里，让面板显式警告。2026-09-12 实锤。
    from ...core.workspace import corpus_path, using_sample_corpus
    warn = None
    if using_sample_corpus():
        warn = (f"读到的是仓内小样本语料（{corpus_path('zongmu_wenyuange_wikisource.txt')}），"
                "整理本锚不上，「整理本期望」不可信。"
                "起控制台前 export GUJI_WORKSPACE=/path/to/siku-zongmu-workspace")
    n_expect = sum(1 for c in picked if c.get("char_above") and c.get("char_below"))
    return {"book": book, "pages": pg, "n_r2s": n_all, "n_done": len(done),
            "n": len(picked), "n_expect": n_expect, "warn": warn, "cases": picked,
            "drift_skipped": drift_skipped}


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
    match_cache: dict[tuple[int, int, int], dict] = {}  # (page, col, slot) → {side: {cand_idx: MatchRec-ish dict}}

    def _match_map(pg: int, col: int, slot: int) -> dict:
        """这一格的候选匹配结果，外加它自己**当前**（chosen 那条）的匹配结果
        ——chosen 候选没有 `cand_variants`（Step4 不重复切它），它的识别信息
        就是这一格正式的 `MatchRec` 本身，存在 `out["chosen"]` 里，拼候选列表
        时按 `i == cp.chosen` 取用，不与其他候选混进同一个 side 字典。

        ⚠️ 格位是 `(col, slot)` 两维，**只按 slot 找会串列**。2026-09-13 实锤：
        这里一度漏了 `cc.col != col` 这一句，`break` 又只跳出内层，于是外层
        逐列覆盖 `out`，最后留下的是**同页最后一列**那个同 slot 格的识别结果。
        vol02:152:5:9（列图上明明是「史/本」，产物里也是「史/本」）卡片上显示
        成 彖/象/家 与 象/彖/篆——那是 col9 的候选池。页面照常渲染、无任何报错，
        人看到的现象是「候选与这两个字毫无关系，坐标好像乱了」。
        `match_cache` 的 key 同理必须带 col，否则第一列的结果会被后面各列复用。

        产物是外部磁盘状态，读取/解析失败（旧版本 schema 的存量产物、跑到
        一半的文件……）都不该让整个请求 500——候选信息本就是"有则显示、
        没有不算错"的增强项，见模块头。实测踩过一次：`glyph_match`
        `CandidateMatch` 加 `side` 字段前跑出的旧产物，pydantic 拿新
        schema 读会直接报 `Field required`。
        """
        key = (pg, col, slot)
        if key in match_cache:
            return match_cache[key]
        out: dict = {"above": {}, "below": {}, "chosen": None}
        try:
            mrec = st.read(book, "glyph_match", page_key(pg), "glyph_match")
        except Exception:
            mrec = None
        for cc in (mrec.columns if mrec else []):
            if cc.col != col:
                continue
            for r in cc.chars:
                if r.slot != slot or r.sub:
                    continue
                out["chosen"] = {"verdict": r.verdict, "char": r.char,
                                 "cov": r.cov, "wmax": r.wmax,
                                 "candidates": r.candidates[:3]}
                for cv in (r.cand_variants or []):
                    out[cv.side][cv.cand_idx] = {
                        "verdict": cv.verdict, "char": cv.char,
                        "cov": cv.cov, "wmax": cv.wmax,
                        "candidates": cv.candidates[:3]}
                break
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
        above_map = _match_map(pg, c["col"], c["slot_above"])
        below_map = _match_map(pg, c["col"], c["slot_below"])

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
