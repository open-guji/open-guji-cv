# -*- coding: utf-8 -*-
"""吞吐量、通道占比、performance 三件套：`guji check throughput` 的事实源。

补的是 `rate_history.py` 之外的三类统计（overview 仓 2026-09-11 审阅指出的缺口，
见 `open-guji-dataset/STEP_MAP.md` 「已知空白」一节）：

1. **每册每页多少输入多少输出**——`per_page()`，逐页 `n_total / n_auto / n_review / n_excluded`。
2. **多个通道各占百分之多少**——`channel_breakdown()`，按 `AdmitRec.channel` 分组计数与占比。
3. **performance**——`step_timing()`，从各 Step 的 `_manifest.jsonl` 读 `elapsed`，
   给每步的每页平均/中位/p90 耗时。**只读已经跑过的产物，不重新计时、不跑管线。**

三者都是**只读聚合**，不产生新的判据、不接入判据 A-F 的绿黄红——它们回答的是
"发生了什么"，不是"对不对"，见 `doc/data-taxonomy.md` 对 statistics 的定义。
"""

from __future__ import annotations

import json
import statistics as _stats
from collections import Counter
from pathlib import Path

from ..core.book import load_book
from ..core.spec import page_key
from ..products import kinds as _kinds  # noqa: F401  触发产物种类注册（kind_of("seed_admit") 需要）
from ..products.store import ProductStore


def per_page(book: str, pages: list[int] | None, st: ProductStore) -> dict:
    """逐页输入输出表：这一页过闸多少字位、自动放行多少、人审多少、排除多少。

    "输入"取 `seed_admit` 该页的全部字位（含被排除的），"输出"拆成
    自动放行 / 人审 / 排除三档，与 `rate_history.measure()` 的 `t0/r0` 同源，
    但这里逐页留痕不只汇总——`rate_history` 只回一个全书数，回答不了
    "第几页开始人审率飙升"这类问题。
    """
    pg_list = load_book(book).resolve_pages(pages) if pages else _all_pages(book, st)
    rows = []
    for pg in pg_list:
        a = st.read(book, "seed_admit", page_key(pg), "seed_admit")
        if a is None:
            continue
        n_total = n_auto = n_review = n_excluded = 0
        for cc in a.columns:
            if not cc.ok:
                continue
            for r in cc.chars:
                if "excluded" in (r.doubts or []):
                    n_excluded += 1
                    continue
                n_total += 1
                if r.admit:
                    n_auto += 1
                else:
                    n_review += 1
        rows.append({
            "page": pg, "n_total": n_total, "n_auto": n_auto,
            "n_review": n_review, "n_excluded": n_excluded,
            "review_rate": round(n_review / n_total, 6) if n_total else None,
        })
    return {"book": book, "pages": rows}


def channel_breakdown(book: str, pages: list[int] | None, st: ProductStore) -> dict:
    """自动放行的通道占比：dual / match_ref / match_solo_cnn / context / … 各占多少。

    只统计 `admit=True` 的记录——人审位没有 channel（走的是人裁不是通道）。
    口径与 `模块测试与现状.md` §2.7 "通道占比 dual 84.7%" 那类数字一致，
    区别是这里是可复现查询，不是审阅时的一次性手算。
    """
    pg_list = load_book(book).resolve_pages(pages) if pages else _all_pages(book, st)
    counts: Counter[str] = Counter()
    total_auto = 0
    for pg in pg_list:
        a = st.read(book, "seed_admit", page_key(pg), "seed_admit")
        if a is None:
            continue
        for cc in a.columns:
            if not cc.ok:
                continue
            for r in cc.chars:
                if "excluded" in (r.doubts or []) or not r.admit:
                    continue
                total_auto += 1
                counts[r.channel or "(none)"] += 1
    breakdown = [
        {"channel": ch, "n": n, "pct": round(n / total_auto, 6) if total_auto else 0.0}
        for ch, n in counts.most_common()
    ]
    return {"book": book, "total_auto": total_auto, "channels": breakdown}


#: `step_timing` 覆盖的步骤。顺序即管线顺序，跟 `流程与模块.md` 的 Step0-8 对齐。
_STEPS = [
    "preclean", "border_detect", "column_warp", "row_segment", "cell_shrink",
    "glyph_match", "ocr_candidates", "align_ref", "context_decide", "seed_admit",
]


def step_timing(book: str, st: ProductStore) -> dict:
    """各步 performance：每页耗时的 mean / median / p90，从 `_manifest.jsonl` 读。

    **只读现有产物的 `elapsed` 字段，不重新跑一遍计时**——跑一遍会把 cache
    命中也算进去，数字虚低；`_manifest.jsonl` 记的是真实执行那一次的耗时
    （cache 命中的页 `Engine` 根本不会写新的 manifest 行，天然只统计到真跑的）。
    """
    per_step = []
    for sid in _STEPS:
        mf = st.manifest(book, sid)
        elapsed = [e.elapsed for e in mf.all().values() if e.status == "ok" and e.elapsed]
        if not elapsed:
            per_step.append({"step": sid, "n_pages": 0})
            continue
        elapsed.sort()
        per_step.append({
            "step": sid, "n_pages": len(elapsed),
            "mean_s": round(_stats.mean(elapsed), 3),
            "median_s": round(_stats.median(elapsed), 3),
            "p90_s": round(elapsed[int(len(elapsed) * 0.9)], 3) if len(elapsed) > 1 else elapsed[0],
            "total_s": round(sum(elapsed), 1),
        })
    return {"book": book, "steps": per_step}


def _all_pages(book: str, st: ProductStore) -> list[int]:
    d = st.root / book / "seed_admit"
    return sorted(int(p.stem[1:]) for p in d.glob("p*.json")) if d.exists() else []


def full_report(book: str, pages: list[int] | None = None, st: ProductStore | None = None) -> dict:
    """三件套一次性打包，`guji check throughput` 默认动作。"""
    st = st or ProductStore()
    return {
        "per_page": per_page(book, pages, st),
        "channels": channel_breakdown(book, pages, st),
        "timing": step_timing(book, st),
    }
