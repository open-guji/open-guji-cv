# -*- coding: utf-8 -*-
"""控制台 · 定字审查。

待审卡片 / 裁决回读 / 一列的上下文

路由体只做「解析参数 → 调库 → 返回」；领域逻辑在 `console/` 之外
（控制台重构 C2/C3）。四个 Store 从 `console/deps.py` 取。
"""
from __future__ import annotations

import cv2
from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel

from .. import deps
from ..errors import maps_http
from ...core.book import load_book
from ...core.spec import column_key, page_key
from ...core.step import RunContext
from ...errors import EncodeFailed, ImageMissing
from ...review.cards import cards
from ...review.verdict_view import review_verdicts

router = APIRouter()



# ── 定字审查（C2：审查搬进控制台，不再走外部 artifact）────────────────
#
# 用户 2026-09-04 定：「审查也放控制台。之前的审查页需要复用的话，也迁移到
# 控制台。」这一组 API 就是那件事的后端：待审卡片从 `seed_admit` 产物来，
# 裁决直接 POST /api/events（既有接口），再走既有的路由 → glyphdb_admit。
# **不新造协议**——事件信封、批次登记、路由表全部沿用。


@router.get("/api/review/cards")
def api_review_cards(book: str, pages: str = "dev_set", limit: int = 400,
                     only: str = "review", gate_cut: bool = True) -> dict:
    """待审卡片：一格一张，带图块 URL、库/OCR/上下文三路证据与疑问。

    装配在 `review/cards.py`（C2 搬出去的，云端道与 CLI 直接能调）。

    `gate_cut`：顺序闸——格位旁边那条切分线有**多种切法**且还没 review 时，
    这个字位先不出卡（用户 2026-09-10：先 review 切分线，再 review 字符）。
    被挡下的在返回值的 `blocked` 里，面板显示剩余条数。
    """
    return cards(book, pages, limit, only, deps.product_store(), gate_cut=gate_cut)



@router.get("/api/review/verdicts")
def api_review_verdicts(batch: str) -> dict:
    """读回某批次已经裁过的字位——**刷新页面不该重审一遍**。装配在 `review/verdict_view.py`。"""
    return review_verdicts(batch, deps.event_log())



def _page_maps(st, book: str, page: int, cache: dict):
    """一页四路产物 + 按 id 建好的查找表，供列/跨列上下文共用。

    `cache` 由调用方（单条或批量端点）持有生命周期——**批量请求里同一页会被
    相邻好几个待审位重复问到**，21 格一列，不缓存就是同一页读 21 次产物。
    """
    key = (book, page)
    if key not in cache:
        d = st.read(book, "context_decide", page_key(page), "context_decision")
        m = st.read(book, "glyph_match", page_key(page), "glyph_match")
        o = st.read(book, "ocr_candidates", page_key(page), "ocr_candidates")
        a = st.read(book, "seed_admit", page_key(page), "seed_admit")
        dm = {r.id: r for cc in (d.columns if d else []) for r in cc.chars}
        om = {r.id: r for cc in (o.columns if o else []) for r in cc.chars}
        am = {r.id: r for cc in (a.columns if a else []) for r in cc.chars}
        cache[key] = (d, m, o, a, dm, om, am)
    return cache[key]


def _column_slots(st, book: str, page: int, col: int, cache: dict) -> list[dict] | None:
    """一列的定字串：见 `api_review_column` 说明——逐级兜底、标出待审位。"""
    d, m, o, a, dm, om, am = _page_maps(st, book, page, cache)
    if d is None and m is None:
        return None
    src_col = (m.column(col) if m else None) or (d.column(col) if d else None)
    if src_col is None:
        return None
    out = []
    for r in sorted(src_col.chars, key=lambda x: (x.slot, x.sub or "")):
        dd, oo, aa = dm.get(r.id), om.get(r.id), am.get(r.id)
        ch, src = None, ""
        if dd is not None and dd.char:
            ch, src = dd.char, (dd.source or "context")
        elif getattr(r, "candidates", None):
            ch, src = r.candidates[0][0], "db"
        elif oo is not None and oo.topk:
            ch, src = oo.topk[0][0], "ocr"
        out.append({"slot": r.slot, "sub": r.sub, "id": r.id, "page": page, "col": col,
                    "char": ch, "source": src,
                    # 待审 = seed_admit 没放行；前端据此高亮
                    "review": bool(aa is not None and not aa.admit)})
    return out


def _max_col(st, book: str, page: int, cache: dict) -> int | None:
    """这一页最后一列的列号（右→左、从 1）——跨列取上下文要知道页边界在哪。"""
    d, m, *_ = _page_maps(st, book, page, cache)
    cols = [cc.col for src in (m, d) if src for cc in src.columns]
    return max(cols) if cols else None


def _around(st, book: str, page: int, col: int, slot: int,
           before: int, after: int, cache: dict) -> dict:
    """跨列/跨页拼够前后各 N 个字——单条与批量端点共用这一份装配。

    本位所在列本身可能就有一大截「本位前」「本位后」的字（21 格一列，本位
    常常不挨着列边）——本列内够的部分先切出来，缺口才向邻列/邻页去补，
    不是「本列整段 + 邻列整段」地拼，否则本位前后各留 1 个能拼出 4 个字。
    """
    cur = _column_slots(st, book, page, col, cache)
    if cur is None:
        return {"text": "", "slots": [], "at": -1}
    idx = next((k for k, r in enumerate(cur) if r["slot"] == slot), None)
    if idx is None:
        return {"text": "", "slots": [], "at": -1}

    def _prev_col(pg: int, cl: int) -> tuple[int, int] | None:
        if cl > 1:
            return pg, cl - 1
        pg2 = pg - 1
        if pg2 < 1:
            return None
        mc = _max_col(st, book, pg2, cache)
        return (pg2, mc) if mc else None

    def _next_col(pg: int, cl: int) -> tuple[int, int]:
        mc = _max_col(st, book, pg, cache)
        if mc and cl < mc:
            return pg, cl + 1
        return pg + 1, 1

    before_slots: list[dict] = cur[:idx]
    pg, cl = page, col
    while len(before_slots) < before:
        nxt = _prev_col(pg, cl)
        if nxt is None:
            break
        pg, cl = nxt
        chunk = _column_slots(st, book, pg, cl, cache)
        if not chunk:
            break
        before_slots = chunk + before_slots

    after_slots: list[dict] = cur[idx + 1:]
    pg, cl = page, col
    while len(after_slots) < after:
        pg, cl = _next_col(pg, cl)
        chunk = _column_slots(st, book, pg, cl, cache)
        if not chunk:
            break
        after_slots += chunk

    slots = before_slots[-before:] + [cur[idx]] + after_slots[:after]
    at = len(before_slots[-before:])
    return {"text": "".join(x["char"] or "□" for x in slots), "slots": slots, "at": at}


@router.get("/api/review/column/{book}/{page}/{col}")
def api_review_column(book: str, page: int, col: int) -> dict:
    """一列的上下文：定字串 + 每格的 slot，供审查页显示「这个字在哪句话里」。

    单看一个裁紧图块判不出形近字——`confusable-context` 154 题实测，字形层
    top-1 只有 64.3%，而 n-gram 95.5%、大模型 98.7%。人也一样需要上下文。

    ## 空位要用库/OCR 兜底填上（2026-09-04 改）

    原先只印 Step6 的定字，弃权位一律「□」。可**待审的位恰恰全是弃权位**
    ——人看到的就是一串「□□□」，等于没有上下文，读文定字也就无从谈起。
    现在逐级兜底：定字 → 库 top1 → OCR top1，并逐位标出它是不是待审、
    以及字从哪来，前端据此把待审位高亮、把兜底字标灰。

    ⚠️ 只看「这一列」——字在列头/列尾时前/后没东西可看。要跨列/跨页凑够前
    后各 N 个字，用 `/api/review/around` 或批量版 `/api/review/around/batch`。
    """
    out = _column_slots(deps.product_store(), book, page, col, {})
    if out is None:
        return {"text": "", "slots": []}
    return {"text": "".join(x["char"] or "□" for x in out), "slots": out}



@router.get("/api/review/around/{book}/{page}/{col}/{slot}")
def api_review_around(book: str, page: int, col: int, slot: int,
                      before: int = 10, after: int = 10) -> dict:
    """跨列/跨页拼够前后各 N 个字的上下文——不再局限于「这一列」。

    用户 2026-09-09：「显示文字上下文的时候，现在是显示这一列，那么文字在
    第一个或最后一个字时，就看不到上下文，应该动态地加载前十个字和后十个
    字，不论是否在一行。」列内不够时，往前一列/前一页最后一列补，往后一列
    /下一页第一列补——col **右→左递增**、页内 col 到头了才翻页（沿用
    `column_windows` 「col: 右→左，从 1」的既有约定）。

    单条查询留着给调试/CLI 用；审查页一页几十上百张卡都要上下文，走下面
    批量版——不然一页 21 格一列，等于把同一页的产物重读几十遍。
    """
    return _around(deps.product_store(), book, page, col, slot, before, after, {})


class AroundBatchIn(BaseModel):
    book: str
    before: int = 10
    after: int = 10
    # 每项 {page, col, slot}；不用 "p:c:s" 字符串键——slot 可能带 sub（"3a"),
    # 用字符串拼接容易在多处 split 逻辑里出岔子，结构化更省心。
    items: list[dict]


@router.post("/api/review/around/batch")
def api_review_around_batch(req: AroundBatchIn) -> dict:
    """批量版：一页产物只读一次（`cache` 在整个请求里共用），装一批卡的上下文。

    单条版按待审卡数逐个请求，一批 400 张卡等于 400 次 HTTP + 重复读同一页
    产物 ~20 次（一列 ~21 格）——candidate 查询卡顿的教训（2026-09-07）
    在这里会重演，所以跟 `/api/rare/batch` 一样直接给批量接口。
    """
    st = deps.product_store()
    cache: dict = {}
    out = {}
    for it in req.items:
        pg, cl, sl = int(it["page"]), int(it["col"]), int(it["slot"])
        out[f"{pg}:{cl}:{sl}"] = _around(st, req.book, pg, cl, sl, req.before, req.after, cache)
    return {"around": out}



@router.get("/api/review/context-img/{book}/{page}/{col}/{slot}.png")
@maps_http
def api_review_context_img(book: str, page: int, col: int, slot: int, around: int = 2) -> Response:
    """裁切前的列图，围绕这一格上下各留 `around` 格：看「切分/收框前长什么样」。

    用户 2026-09-09：「点一下看到上下多两个字的位置的图片，我想看到切分前
    的图片的样子，防止切分和缩框等等改变了图片。」`char_patch`（审查卡片贴
    的那张）是 Step4 紧框收缩之后的图，缩框本身可能就是噪声/误判的来源，
    拿它自证看不出问题。这里改用 Step2 的 `column_image`（矫正+去噪，但
    **没有**逐字切分/紧框收缩）配 `char_index` 的 `bbox_col`，只在列图坐标
    上取一段——同一坐标系（`COLUMN_PX`），不用换算。

    ⚠️ `column_image` 是**缓存**、不是常驻产物——`ImageCache.get()` 缓存没命中
    就返回 `None`，跟 `char_patch` 一样得走 `RunContext.materialize()` 现算
    （2026-09-09 实测：vol02 页 3 那张点开「看原图」是空图标，缓存早没了，
    `/api/cache/...` 走的正是这条路才没坏）。
    """
    st = deps.product_store()
    ci = st.read(book, "cell_shrink", page_key(page), "char_index")
    cc = ci.column(col) if ci else None
    if cc is None:
        raise ImageMissing("没有这一列的字框")
    rows = sorted(cc.chars, key=lambda r: r.slot)
    idx = next((k for k, r in enumerate(rows) if r.slot == slot), None)
    if idx is None:
        raise ImageMissing("没有这一格的字框")
    lo, hi = max(0, idx - around), min(len(rows), idx + around + 1)
    ys = [r.bbox_col[1] for r in rows[lo:hi]] + [r.bbox_col[3] for r in rows[lo:hi]]
    pad = 8
    y0, y1 = int(min(ys)) - pad, int(max(ys)) + pad
    ctx = RunContext(load_book(book), st, deps.image_cache(), log=lambda s: None)
    try:
        path = ctx.materialize("column_image", column_key(page, col))
    except Exception as e:   # noqa: BLE001
        raise ImageMissing(f"列图算不出来: {e}") from e
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ImageMissing("列图读不出来")
    h = img.shape[0]
    y0 = max(0, min(h - 1, y0)); y1 = max(y0 + 1, min(h, y1))
    ok, buf = cv2.imencode(".png", img[y0:y1])
    if not ok:
        raise EncodeFailed("编码失败")
    return Response(content=buf.tobytes(), media_type="image/png")
