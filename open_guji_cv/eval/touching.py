# -*- coding: utf-8 -*-
"""粘连格线（R2s）用例：给「拖切线」卡片与 touching-cuts 评测共用。

R2s 的判据与 `eval/rulers.py` 完全一致（格线处墨占比 > INK_ON_LINE 且 ±12px 内无
≤ STUCK_FLOOR 的墨谷）。每条用例带：现役切点、上下两格的格位/类型/期望字（整理本
对齐金标）、给卡片裁图用的 y 范围、列图高度（坐标系 = 现役 Step2 列图）。

用户 2026-09-05：「先让我添加一些金标，确定理想位置，再想算法。主要支持第一册正文。」
"""
from __future__ import annotations

import json
import random
from pathlib import Path

DATASET = Path(__file__).resolve().parent.parent.parent.parent / "open-guji-dataset"
SHARD = "char-segmentation/touching-cuts"


def body_pages(book: str) -> list[int]:
    """page-type 金标里判为正文的页（职名页 / 目录页不用 21 格先验，先不出卡片）。"""
    f = DATASET / "page-type" / "items.jsonl"
    if not f.exists():
        return []
    rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()]
    return sorted(int(r["anchor"]["page"]) for r in rows
                  if str(r.get("anchor", {}).get("book")) == book
                  and (r.get("expected") or {}).get("page_type") == "body")


def split_char_boundaries(book: str, pages: list[int], store=None,
                          short_ratio: float = 0.80, tall_ratio: float = 1.18,
                          gap_frac: float = 0.06) -> list[dict]:
    """「切进字里」的格线：一矮一高相邻、切点又落在**零墨空隙**上。

    与 `r2s_boundaries` 互补，两者互斥：R2s 是「切点上有墨、附近没有墨谷」（真粘连，
    投影法无解）；这里是「切点上没什么墨」——正因为有个零墨空隙，DP 才乐意切在那儿，
    而那个空隙是**字内部的**（「書」的横画之间、「辩」的左右部件之间），不是字距。

    2026-09-08：这类占了剩余切分缺陷的主要部分（辩/書/廢/敘/亦），但**一条也不在
    R2s 候选里**，所以攒了 250 条 R2s 金标也标不到它。判据（都相对本列格高中位数）：
    相邻两格一个 ≤`short_ratio`、一个 ≥`tall_ratio`，且切点周围 ±`gap_frac`×格高内
    最低墨 ≤ INK_ON_LINE——三条合起来才算，单看格高会把「留白 + 字」的首格全捞进来。
    """
    from ..core.step import page_key
    from ..products import kinds as _k  # noqa: F401
    from ..products.store import ProductStore
    from .rulers import INK_ON_LINE, _col_profile

    st = store or ProductStore()
    out: list[dict] = []
    for pg in pages:
        cells = st.read(book, "row_segment", page_key(pg), "cells")
        if cells is None:
            continue
        for cc in cells.columns:
            if not cc.ok or len(cc.cells) != len(cc.boundaries) - 1:
                continue
            prof = _col_profile(st, book, pg, cc.col)
            if prof is None:
                continue
            h = len(prof)
            chars = [c for c in cc.cells if c.kind == "char"]
            if len(chars) < 5:
                continue
            hs = sorted(c.y1 - c.y0 for c in chars)
            med = float(hs[len(hs) // 2])
            if med <= 0:
                continue
            col_w = int(max(c.x1 for c in cc.cells) + min(c.x0 for c in cc.cells))
            for bi, b in enumerate(cc.boundaries[1:-1], start=1):
                up, dn = cc.cells[bi - 1], cc.cells[bi]
                if up.kind != "char" or dn.kind != "char":
                    continue
                hu, hd = up.y1 - up.y0, dn.y1 - dn.y0
                pair = ((hu <= short_ratio * med and hd >= tall_ratio * med)
                        or (hd <= short_ratio * med and hu >= tall_ratio * med))
                if not pair:
                    continue
                y = int(round(b))
                if not (0 <= y < h):
                    continue
                w = max(2, int(gap_frac * med))
                lo, hi = max(0, y - w), min(h, y + w + 1)
                if float(prof[lo:hi].min()) > INK_ON_LINE:
                    continue          # 切点附近没有零墨空隙 → 是别的毛病
                out.append(dict(
                    id=f"{book}:{pg}:{cc.col}:{up.slot}",
                    book=book, page=pg, col=cc.col, bi=bi, y=y,
                    ink=round(float(prof[y]), 3), best=round(float(prof[lo:hi].min()), 3),
                    h_above=int(hu), h_below=int(hd), h_med=int(med),
                    slot_above=up.slot, slot_below=dn.slot,
                    y0=int(round(up.y0)), y1=int(round(dn.y1)),
                    x0=int(round(min(up.x0, dn.x0))), x1=int(round(max(up.x1, dn.x1))),
                    col_h=h, col_w=col_w,
                    seam=list(getattr(up, "seam_bottom", None) or []) or None,
                    kind="split_char",
                ))
    return out


def r2s_boundaries(book: str, pages: list[int], store=None) -> list[dict]:
    """所有 R2s 格线（只看有现役 cells 产物的页）。"""
    from ..core.step import page_key
    from ..products import kinds as _k  # noqa: F401
    from ..products.store import ProductStore
    from .rulers import INK_ON_LINE, STUCK_FLOOR, _col_profile

    st = store or ProductStore()
    out: list[dict] = []
    for pg in pages:
        cells = st.read(book, "row_segment", page_key(pg), "cells")
        if cells is None:
            continue
        for cc in cells.columns:
            if not cc.ok or len(cc.cells) != len(cc.boundaries) - 1:
                continue
            prof = _col_profile(st, book, pg, cc.col)
            if prof is None:
                continue
            h = len(prof)
            col_w = int(max(c.x1 for c in cc.cells) + min(c.x0 for c in cc.cells)) if cc.cells else 0
            for bi, b in enumerate(cc.boundaries[1:-1], start=1):
                y = int(round(b))
                if not (0 <= y < h) or prof[y] <= INK_ON_LINE:
                    continue
                lo, hi = max(0, y - 12), min(h, y + 13)
                best = float(prof[lo:hi].min())
                if best <= STUCK_FLOOR:
                    continue
                up, dn = cc.cells[bi - 1], cc.cells[bi]
                if up.kind != "char" or dn.kind != "char":
                    continue          # 夹注 / 空白旁的切线另案
                seam = getattr(up, "seam_bottom", None)      # 现役折线缝（列图坐标，从内容窗口 x0 起）
                out.append(dict(
                    id=f"{book}:{pg}:{cc.col}:{up.slot}",   # 以上格格位定名，parse_card_id 可解析
                    book=book, page=pg, col=cc.col, bi=bi, y=y,
                    ink=round(float(prof[y]), 3), best=round(best, 3),
                    slot_above=up.slot, slot_below=dn.slot,
                    y0=int(round(up.y0)), y1=int(round(dn.y1)),
                    x0=int(round(min(up.x0, dn.x0))), x1=int(round(max(up.x1, dn.x1))),
                    col_h=h, col_w=col_w,
                    seam=list(seam) if seam else None,
                ))
    return out


def polyline_to_seam(points: list, x0: int, x1: int) -> list[int]:
    """人标的折线（列图坐标 [[x, y], …]，按 x 递增）→ 每个 x∈[x0, x1) 一个 y（线性插值；
    两端之外取端点的 y，即水平延伸）。与 `Cell.seam_*` 同口径，可直接比。"""
    pts = sorted((float(x), float(y)) for x, y in points)
    if not pts:
        return []
    xs = [x for x, _ in pts]; ys = [y for _, y in pts]
    out = []
    for x in range(int(x0), int(x1)):
        if x <= xs[0]:
            out.append(int(round(ys[0]))); continue
        if x >= xs[-1]:
            out.append(int(round(ys[-1]))); continue
        j = 1
        while xs[j] < x:
            j += 1
        xa, ya, xb, yb = xs[j - 1], ys[j - 1], xs[j], ys[j]
        t = (x - xa) / (xb - xa) if xb > xa else 0.0
        out.append(int(round(ya + t * (yb - ya))))
    return out


def seam_deviation(a: list, b: list) -> tuple[float, float]:
    """两条缝（每 x 一个 y，同起点）的 (最大, 平均) 纵向偏差，按公共长度算。"""
    n = min(len(a), len(b))
    if n == 0:
        return float("nan"), float("nan")
    d = [abs(float(a[i]) - float(b[i])) for i in range(n)]
    return max(d), sum(d) / n


def attach_expected(cases: list[dict], book: str, store=None) -> None:
    """把整理本对齐金标的期望字挂到 char_above / char_below（没有就留空）。"""
    from ..gold.v2_align import align_book
    from ..products.store import ProductStore

    pages = sorted({c["page"] for c in cases})
    if not pages:
        return
    st = store or ProductStore()
    gold = {c.id: c for g in align_book(book, pages, st) if g.anchored for c in g.chars}
    for c in cases:
        gu = gold.get(f"{book}:{c['page']}:{c['col']}:{c['slot_above']}")
        gd = gold.get(f"{book}:{c['page']}:{c['col']}:{c['slot_below']}")
        c["char_above"] = gu.shape if gu else ""
        c["char_below"] = gd.shape if gd else ""


def pick_cases(cases: list[dict], limit: int, seed: int = 0, per_page: int | None = None) -> list[dict]:
    """确定性抽样：打乱后按页轮转取，避免 250 条全落在两三页挤排页上。"""
    rng = random.Random(seed)
    by_page: dict[int, list[dict]] = {}
    for c in cases:
        by_page.setdefault(c["page"], []).append(c)
    for v in by_page.values():
        rng.shuffle(v)
    order = sorted(by_page)
    rng.shuffle(order)
    out: list[dict] = []
    taken = {p: 0 for p in order}
    while len(out) < limit:
        progressed = False
        for p in order:
            if per_page is not None and taken[p] >= per_page:
                continue
            if taken[p] < len(by_page[p]):
                out.append(by_page[p][taken[p]])
                taken[p] += 1
                progressed = True
                if len(out) >= limit:
                    break
        if not progressed:
            break
    return out


def gold_ids() -> set[str]:
    """已经有 touching-cuts 金标的格线 id（含 uncertain），出卡片时跳过。"""
    from ..gold.store import GoldStore
    try:
        return {i.id for i in GoldStore().list(SHARD)}
    except Exception:
        return set()
