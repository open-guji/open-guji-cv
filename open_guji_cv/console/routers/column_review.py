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
from fastapi import APIRouter, HTTPException

from ...core.book import load_book
from ...core.spec import column_key, page_key
from ...utils.column_triage import BLOCKING, REVIEW, triage_column
from .. import deps

router = APIRouter()


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
        try:
            wins = st.read(book, "column_warp", page_key(pg), "column_windows")
        except Exception:                                    # noqa: BLE001
            continue
        for w in wins.columns:
            t = w.triage.model_dump() if w.triage else None
            if t is None:
                continue
            rec = {
                "id": f"{book}:{pg}:{w.col}",
                "book": book, "page": pg, "col": w.col,
                "triage": t,
                "band": list(w.band),
                "trim_top": w.trim_top.model_dump(),
                "trim_bottom": w.trim_bottom.model_dump(),
                "size": list(w.warped_size),
                "raised": bool(w.raised),
                "img": f"/api/cache/{book}/column_raw/{column_key(pg, w.col)}.png",
            }
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
    g = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
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
