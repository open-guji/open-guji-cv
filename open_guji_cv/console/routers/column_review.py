# -*- coding: utf-8 -*-
"""Step2 列清理的人裁：左右文字带 + 上下端部类别。

两个方向、两种裁法（用户 2026-09-17 定）：

| 方向 | 裁什么 | 为什么 |
|---|---|---|
| 左右 | 拖两条竖线出 `human_left/right` | 边界是**一条走廊**不是一个点，人拖到的位置是保守端 |
| 上下 | 只选**类别**（none/clean/glued/idk），**不给可拖的线** | 金标 README 明写：「印上去会把人的判断带偏，而要量的正是人怎么分类」 |

抽样按分诊类别分层（`utils/column_triage`），**故意超采样难例**——
`eat`/`glued` 全量出，`mixed`/`clean` 随机抽。所以这批**不能当全书比例的估计**，
只能用来找失败形态（同 column-warp README 的「选列规则」一节）。

裁决走既有事件链路（`POST /api/events` → 路由 → 金标），`kind="column_band"`，
不新造协议。
"""
from __future__ import annotations

import random

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Response

from ...core.book import load_book
from ...core.spec import column_key, page_key
from ...utils.column_triage import BLOCKING, REVIEW, triage_column
from .. import deps
from ..auth import require_reviewer
from ...utils.image_io import imread as cv_imread, imwrite as cv_imwrite

router = APIRouter(dependencies=[Depends(require_reviewer)])


def _case_rec(book: str, pg: int, w) -> dict | None:
    """一列的卡片记录。抽样出卡与「跳到指定列」共用，免得两处字段漂。"""
    t = w.triage.model_dump() if w.triage else None
    if t is None:
        return None
    return {
        "id": f"{book}:{pg}:{w.col}",
        "book": book, "page": pg, "col": w.col,
        "triage": t,
        "band": list(w.band),
        "trim_top": w.trim_top.model_dump(),
        "trim_bottom": w.trim_bottom.model_dump(),
        # 削完之后端部还剩不剩框墨（闸2 `frame_residue` 判据的量）。
        # 裁决台只显示「算法判了哪一档」时会误导人——bxgb:16:17 下端判 c
        # 「没带进版框」，而下版框明明在列图里（行墨占比 1.000）。
        # 把验后的量一起摆出来，人一眼能看出判据和图对不上。
        "frame_residue": [int(w.frame_residue_top), int(w.frame_residue_bottom)],
        "size": list(w.warped_size),
        "raised": bool(w.raised),
        "img": f"/api/cache/{book}/column_raw/{column_key(pg, w.col)}.png",
    }


@router.get("/api/column-review/cases")
def api_column_review_cases(book: str, pages: str = "dev_set", limit: int = 90,
                            seed: int = 0, scope: str = "all") -> dict:
    """待裁列。按分诊类别分层抽样。

    `scope`：
      `blocking` —— 只出会丢字的（左右 `eat`、上下 `glued`）。这批**必须人裁**
                    才能走下一步，与 Step7 的顺序闸同一条纪律。
      `review`   —— 只出「可疑但放行」的（`mixed`/`idk`），事后抽审。
      `all`（默认）—— 两者都出，另配平一批 `clean` 当对照（没有对照就只能
                    证明「难的确实难」，证不出容易的那批有没有错）。
    """
    st = deps.product_store()
    bk = load_book(book)
    pgs = bk.resolve_pages(pages)
    rng = random.Random(seed)

    blocking: list[dict] = []
    review: list[dict] = []
    clean: list[dict] = []
    for pg in pgs:
        # 闸1 判为 skip 的页（封面/书签/牌记）不出卡：那些页本就没有正文栏格，
        # 列图是整片灰或大块黑白，任何列级判据在上面都只会给出噪声
        # （实测 vol01 p1 cover / p2 label 贡献了 7/7 的 eat 误报）。
        try:
            gate = st.read(book, "border_detect_gate", page_key(pg),
                           "border_detect_gate_manifest")
            if getattr(gate, "page_type_policy", "") == "skip":
                continue
        except Exception:                                    # noqa: BLE001
            pass                                             # 没有闸产物就不拦，照常出卡
        try:
            wins = st.read(book, "column_warp", page_key(pg), "column_windows")
        except Exception:                                    # noqa: BLE001
            continue
        # 版心列（书口）不出卡（用户 2026-09-17 实测反馈「bxgb:28:10 是版心列，
        # 不用处理」）：那一列印的是书名/叶次/丛书名这类小字，不是正文，列清理
        # 的判据（文字带、上下框与首末字的间隙）对它没有意义。
        # `line_index` 已经把它标成 `margin`——Step1 按位置判定（版心是跨版框
        # 中点的那一列，见 project_keben_column_types），这里直接用，不重判。
        skip_cols: set[int] = set()
        try:
            li = st.read(book, "border_detect", page_key(pg), "line_index")
            skip_cols = {i for i, ln in enumerate(li.lines, 1)
                         if getattr(ln, "kind", "body") != "body"}
        except Exception:                                    # noqa: BLE001
            pass                                             # 没有 line_index 就不排除
        for w in wins.columns:
            if w.col in skip_cols:
                continue
            rec = _case_rec(book, pg, w)
            if rec is None:
                continue
            t = rec["triage"]
            hard = (t["side_class"] in BLOCKING["side"]
                    or t["top_class"] in BLOCKING["end"]
                    or t["bot_class"] in BLOCKING["end"])
            soft = (t["side_class"] in REVIEW["side"]
                    or t["top_class"] in REVIEW["end"]
                    or t["bot_class"] in REVIEW["end"])
            (blocking if hard else review if soft else clean).append(rec)

    if scope == "blocking":
        out = blocking[:limit]
    elif scope == "review":
        rng.shuffle(review)
        out = review[:limit]
    else:
        # 全量：拦的全出（它们本来就该逐条过），复审与对照按剩余额度分
        rng.shuffle(review)
        rng.shuffle(clean)
        rest = max(0, limit - len(blocking))
        n_clean = min(len(clean), max(6, rest // 4))       # 至少留几条干净的当对照
        out = blocking + review[:rest - n_clean] + clean[:n_clean]
    return {"cases": out,
            "counts": {"blocking": len(blocking), "review": len(review), "clean": len(clean)}}


@router.get("/api/column-review/case")
def api_column_review_case(book: str, page: int, col: int | None = None) -> dict:
    """跳到指定页（可指定列）——抽样出卡之外的直达入口（用户 2026-09-17）。

    不给 `col` 就出**整页所有列**，按列号排序：要看「同一页逐列切线齐不齐」
    时，抽样卡永远凑不齐一页。这里**不套 skip_cols / 分诊过滤**——人既然点名
    要看这一页，版心列也照出，由人自己判。
    """
    st = deps.product_store()
    try:
        wins = st.read(book, "column_warp", page_key(page), "column_windows")
    except Exception as e:                                   # noqa: BLE001
        raise HTTPException(404, f"没有这一页的 Step2 产物：{e}") from e
    if wins is None:            # 读不到返回 None，不抛异常
        raise HTTPException(404, f"没有 {book} p{page} 的 Step2 产物（先跑 Step2）")
    out: list[dict] = []
    for w in sorted(wins.columns, key=lambda x: x.col):
        if col is not None and w.col != col:
            continue
        rec = _case_rec(book, page, w)
        if rec is not None:
            out.append(rec)
    if not out:
        raise HTTPException(404, f"{book} p{page} 没有列 {col}")
    return {"cases": out, "counts": {"blocking": 0, "review": 0, "clean": len(out)}}


@router.get("/api/column-review/verdicts")
def api_column_review_verdicts(batch: str) -> dict:
    """读回本批已裁的列（刷新不重做；同 id 后到覆盖）。"""
    out: dict[str, dict] = {}
    try:
        for e in deps.event_log().read(batch):
            # 左右走 `band`、上下走 `border_class`（既有的受控 kind，不新造）。
            # 同一列两个方向是两条事件，这里合并回一条给面板回显。
            if e.kind not in ("band", "border_class"):
                continue
            key = (e.target.key if e.target else None) or ""
            if not key:
                continue
            cur = out.setdefault(key, {})
            p = dict(e.payload or {})
            if e.kind == "band":
                cur["side_verdict"] = p.get("band")
            else:
                for k in ("top_class", "bot_class"):
                    if p.get(k):
                        cur[k] = p[k]
    except FileNotFoundError:
        pass                                    # 批次还不存在 = 没裁过
    return {"verdicts": out}


@router.get("/api/column-review/img/{book}/{page}/{col}.png")
def api_column_review_img(book: str, page: int, col: int, src: str = "bin",
                          mark: bool = True, end: str = "all", pad: int = 90,
                          squeeze: int = 1) -> Response:
    """列图 + **把算法的线画上去**。人裁时看不到线就没法判「削到哪了对不对」。

    `src`：`bin`（缺省）用 **Sauvola k=0.10** 二值化后再画线——与字形库、定字审阅
    同一把尺子（用户 2026-09-16 定：进库的一定是二值的，审阅看二值的也更准）。
    Step2 内部的判据仍是固定阈 `<128`，两者在本书上差 15%~38% 的墨量，这正是
    要让人看二值图的理由：人判的和机器判的得是同一张图，否则裁决对不上号。
    `raw` 给原灰度，对照用。

    线（都按列图局部坐标画）：
      红 —— 文字带左右边界 `band`（Step2 已有的左右 padding）
      绿 —— 上端削到的行 `trim_top.px`
      蓝 —— 下端削到的行（从底往上量 `trim_bottom.px`）
    `end`：`top`/`bottom` 只出该端 `pad` 行的放大图，`all` 出整列。

    `squeeze`：**只压纵向**的整数倍率（用户 2026-09-17：「展示左右的切线位置时，
    需要把上下压缩到比较小，不然看不清」）。列图高 1500+px，整列塞进屏幕时浏览器
    等比缩到十几分之一，左右那两条红线连同字身一起糊成一团，判不了「红线有没有
    切进字」。纵向压 `squeeze` 倍、**横向一比一**，宽度信息一像素不丢。
    压缩必须在画线**之后**做：先压后画会让线画在压过的坐标上、位置对不上；
    而 `INTER_AREA` 压 1px 宽的线会把它抹淡，所以线加粗到 `squeeze` 像素补偿。
    """
    import cv2
    import numpy as np

    from ...utils.binarized import binarize_page
    from ...utils.column_projection import column_text_band, denoise_column

    p = deps.image_cache().get(book, "column_raw", column_key(page, col))
    if p is None:
        raise HTTPException(404, "没有这一列的矫正图（先跑 Step2）")
    g = cv_imread(str(p), cv2.IMREAD_GRAYSCALE)
    if g is None:
        raise HTTPException(404, "列图读不出来")
    shown = binarize_page(g) if src == "bin" else g
    im = cv2.cvtColor(shown, cv2.COLOR_GRAY2BGR)
    h, w = im.shape[:2]

    if mark:
        st = deps.product_store()
        lo = hi = None
        tpx = bpx = 0
        try:
            wins = st.read(book, "column_warp", page_key(page), "column_windows")
            rec = next((x for x in wins.columns if x.col == col), None)
            if rec is not None:
                lo, hi = int(rec.band[0]), int(rec.band[1])
                tpx, bpx = int(rec.trim_top.px), int(rec.trim_bottom.px)
        except Exception:                                    # noqa: BLE001
            pass
        if lo is None:                                       # 没产物就现算，别让人看空图
            lo, hi = column_text_band(denoise_column(g))
        # 横线按 squeeze 加粗：纵向压缩用 INTER_AREA 取的是区间均值，1px 的横线
        # 压 8 倍后只剩 1/8 的对比度，肉眼就没了。竖线不受影响（沿 y 连续）。
        hw = max(1, squeeze)
        for x in (lo, hi - 1):
            if 0 <= x < w:
                cv2.line(im, (x, 0), (x, h - 1), (0, 0, 220), 1)
        if tpx:
            cv2.line(im, (0, tpx), (w - 1, tpx), (0, 170, 0), hw)
        if bpx:
            y = h - 1 - bpx
            if 0 <= y < h:
                cv2.line(im, (0, y), (w - 1, y), (220, 120, 0), hw)

    if end == "top":
        im = im[:min(pad, h)]
    elif end == "bottom":
        im = im[max(0, h - pad):]
    if squeeze > 1 and im.shape[0] // squeeze >= 1:
        im = cv2.resize(im, (im.shape[1], im.shape[0] // squeeze),
                        interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", im)
    if not ok:
        raise HTTPException(500, "编码失败")
    return Response(content=buf.tobytes(), media_type="image/png")


@router.get("/api/column-review/profile/{book}/{page}/{col}")
def api_column_profile(book: str, page: int, col: int) -> dict:
    """这一列的两条投影曲线，给审阅台画参考线用。

    左右给列向（逐 x）墨占比、上下给行向（逐 y）。人拖线时看着曲线更准——
    金标 README 的走廊判据就是「拖到墨占比仍 ≈0 的最远处」。
    """
    from ...utils.column_projection import (column_profile, column_row_profile,
                                             column_text_band, denoise_column,
                                             strip_column_rules)
    ctx_cache = deps.image_cache()
    p = ctx_cache.get(book, "column_raw", column_key(page, col))
    if p is None:
        raise HTTPException(404, "没有这一列的矫正图（先跑 Step2）")
    g = cv_imread(str(p), cv2.IMREAD_GRAYSCALE)
    if g is None:
        raise HTTPException(404, "列图读不出来")
    dn = denoise_column(g)
    band = column_text_band(dn)
    col_p = column_profile(dn)
    row_p = column_row_profile(strip_column_rules(dn), band)
    t = triage_column(g)
    return {"width": int(g.shape[1]), "height": int(g.shape[0]),
            "band": [int(band[0]), int(band[1])],
            "col_profile": [round(float(v), 4) for v in col_p],
            "row_profile": [round(float(v), 4) for v in row_p],
            "triage": {k: v for k, v in t.items() if k != "band"}}
