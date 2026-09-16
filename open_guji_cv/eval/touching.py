# -*- coding: utf-8 -*-
"""粘连格线（R2s）用例：给「拖切线」卡片与 touching-cuts 评测共用。

R2s 的判据与 `eval/rulers.py` 完全一致（格线处墨占比 > INK_ON_LINE 且 ±12px 内无
≤ STUCK_FLOOR 的墨谷）。每条用例带：现役切点、上下两格的格位/类型/期望字（整理本
对齐金标）、给卡片裁图用的 y 范围、列图高度（坐标系 = 现役 Step2 列图）。

用户 2026-09-05：「先让我添加一些金标，确定理想位置，再想算法。主要支持第一册正文。」
"""
from __future__ import annotations

import random

SHARD = "char-segmentation/touching-cuts"


def _pages_of_type(book: str, types: frozenset[str]) -> list[int]:
    """page-type 裁决表里属于 `types` 的页。

    读 **workspace 裁决表**的 `page-type` 分片（`guji gold export page-type` 从测试集仓
    复制过来，是「这本书的事实」），不读 open-guji-dataset——出卡是运行时（2026-09-13）。"""
    from ..feedback.consumers import verdict_store
    try:
        items = verdict_store().list("page-type", legacy=False)
    except Exception:
        return []
    return sorted(int(i.anchor.page) for i in items
                  if str(i.anchor.book) == book and i.anchor.page is not None
                  and (i.expected or {}).get("page_type") in types)


def body_pages(book: str) -> list[int]:
    """严格的正文页。标定（`utils/calibrate`）、对勘报告、抽查用它——那些口径要「纯正文」。"""
    return _pages_of_type(book, frozenset({"body"}))


#: **21 格标准版式**的页型：正文与目录同一个待遇（2026-09-16 用户定）。
#: 实测 vol01：目录 99/108 列通过、每列格数 21 为主（20–23），与正文（108/108、全 21）基本一致。
#: `roster` 职名页**不在此列**——它是「大字官职 + 小字『臣某某』」混排，周期估计器锁到小字的 80px
#: （正文 115），44 页里 37 页有列切失败、20 多页整页 9 列全废。那是 Step3 周期估计要单独修的活，
#: 不是人裁能解决的，出卡也没有意义（0 格的列产生不了切点）。
STD_GRID_TYPES = frozenset({"body", "toc", "colophon", "edict"})


def std_grid_pages(book: str) -> list[int]:
    """走 21 格标准版式的页——切线出卡用这个口径，见 `STD_GRID_TYPES`。"""
    return _pages_of_type(book, STD_GRID_TYPES)


def _cell_ink_mass(store, book: str, page: int, col: int, cell, med: float) -> float | None:
    """一格的**绝对墨量**：墨像素 ÷（列格高中位 × 格宽）。

    分母用**中位格高**而不是本格高——要问的正是「这一格里的墨够不够一个整字」，
    拿本格高做分母会把矮格自动归一化掉，正是要避免的（见 split_char_boundaries）。
    """
    import cv2

    from ..products.cache import ImageCache
    from ..core.spec import column_key

    p = ImageCache().get(book, "column_image", column_key(page, col))
    if p is None:
        return None
    img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    y0, y1 = max(0, int(cell.y0)), min(img.shape[0], int(cell.y1))
    x0, x1 = max(0, int(cell.x0)), min(img.shape[1], int(cell.x1))
    if y1 <= y0 or x1 <= x0:
        return None
    ink = int((img[y0:y1, x0:x1] < 128).sum())
    denom = med * (x1 - x0)
    return ink / denom if denom > 0 else None


def split_char_boundaries(book: str, pages: list[int], store=None,
                          short_ratio: float = 0.79, tall_ratio: float = 1.05,
                          gap_frac: float = 0.06,
                          ink_mass_min: float = 0.100) -> list[dict]:
    """「切进字里」的格线：一矮一高相邻、切点又落在**零墨空隙**上。

    与 `r2s_boundaries` 互补，两者互斥：R2s 是「切点上有墨、附近没有墨谷」（真粘连，
    投影法无解）；这里是「切点上没什么墨」——正因为有个零墨空隙，DP 才乐意切在那儿，
    而那个空隙是**字内部的**（「書」的横画之间、「辩」的左右部件之间），不是字距。

    2026-09-08：这类占了剩余切分缺陷的主要部分（辩/書/廢/敘/亦），但**一条也不在
    R2s 候选里**，所以攒了 250 条 R2s 金标也标不到它。判据（都相对本列格高中位数）：
    相邻两格一个 ≤`short_ratio`、一个 ≥`tall_ratio`，切点周围 ±`gap_frac`×格高内
    最低墨 ≤ INK_ON_LINE，且**矮格的绝对墨量** ≥ `ink_mass_min`。

    最后一条是 47 条人裁金标标定出来的**决定性判据**（2026-09-08）：矮格里若装的是
    「一」「二」这类扁字，那是真的矮，切点没错；若装的是被劈开的半个字，格子虽矮、
    墨量却还是一个整字的量。绝对墨量 = 矮格墨像素 ÷（列格高中位 × 格宽），金标实测
    **ok 0.034~0.066、moved 0.105~0.195**，中间空着一半，取 0.085。

    ⚠️ 这个量**只能用在矮格上**：正常字格 97.8% 都 ≥0.08（中位 0.175），单用必然全误报。
    「格子矮 + 墨够一个整字」两条**合起来**才是信号。格高门槛也据金标放宽到 0.92/1.05
    ——原来的 0.80/1.18 把 109:3:17（0.83）、119:6:4（0.83）、106:4:3（0.87）这些真缺陷
    挡在门外，而放宽后的误报由绝对墨量兜住。
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
                short = up if hu <= hd else dn
                mass = _cell_ink_mass(st, book, pg, cc.col, short, med)
                if mass is not None and mass < ink_mass_min:
                    continue          # 矮格里是真的扁字（一/二），不是被劈的半个字
                out.append(dict(
                    id=f"{book}:{pg}:{cc.col}:{up.slot}",
                    book=book, page=pg, col=cc.col, bi=bi, y=y,
                    ink=round(float(prof[y]), 3), best=round(float(prof[lo:hi].min()), 3),
                    ink_mass=None if mass is None else round(mass, 3),
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


def drifted_boundaries(book: str, store=None, tol: int = 2,
                       include_relabeled: dict[str, set[int]] | None = None,
                       only_ids: set[str] | None = None) -> tuple[list[dict], dict]:
    """金标**坐标系过期**的切点：裁决表里 `col_h` 与当前列图高度差 > tol 的条目。

    2026-09-14 实测 982 条 active 金标里 **381 条**（vol01 120 / vol02 167 / vol03 94，
    即 vol02、vol03 的全部）的列图在标注后被 Step2 重矫正过，`y`/`polyline` 落在旧
    坐标系，偏 30–80px 且不是简单缩放——离线实验只能把它们过滤掉（见 overview
    `Step3-逐字切分/05-高级切分算法.md`「金标坐标系过期」）。这里把它们**按 slot**
    对回当前 cells 出成与 `r2s_boundaries` 同形的用例，卡片 id 沿用金标 id，人重裁后
    `cutline` 事件经 gold_add **按 id upsert**，`y`/`col_h`/`polyline` 就换成当前坐标系。

    只按 `(slot_above, slot_below)` 对位，不按 y 找最近格线——坐标系都变了，y 不可信。
    对不上（格数结构变了、列被拒）的条目计入返回的 `skipped` 供人查。
    `char_above/char_below` 直接沿用金标（已由 06 卡洗过），不再重新对齐整理本。

    `include_relabeled`：重裁一落定，条目的 col_h 就是当前值、不再「过期」，刷新后在这一档
    里找不回来（用户 2026-09-14：标错一张想改）。传 {金标 id: 本批次切线事件里出现过的 col_h}，
    其中有一条 col_h ≈ 当前列高的（= 对着当前坐标系裁过）就也出出来（`redo=True`，
    `drift_from_col_h=None`），前端按批次裁决把它们显示成已裁，人可以按 U 重做。
    **不按批次名前缀判**：用户把批次框留空时事件落进 `vol03-cutline` 这种老批次，那里面
    历史事件（旧坐标系）成百上千，按名字算全是「已裁」——实测 vol03 94 条只剩 4 条可裁。
    同理这一档**不按批次事件跳过**已裁：重裁过的条目 col_h 已是当前值，自己就出池了。

    `only_ids`：只出这些金标 id，**不管过没过期**（复核清单模式，控制台页码框 `list:<名字>`）。
    没过期的按 `redo=True` 出，前端照批次裁决显示成已裁/未裁。
    """
    import cv2

    from ..core.step import page_key
    from ..feedback.consumers import verdict_store
    from ..products import kinds as _k  # noqa: F401
    from ..products.cache import ImageCache
    from ..products.store import ProductStore
    from .rulers import INK_ON_LINE, _col_profile

    st = store or ProductStore()
    ic = ImageCache()
    items = [i for i in verdict_store().list(SHARD)
             if i.anchor.book == book and getattr(i, "status", "active") == "active"]
    out: list[dict] = []
    skipped: dict[str, int] = {}
    cells_cache: dict[int, object] = {}
    h_cache: dict[tuple[int, int], int | None] = {}

    def col_height(pg: int, col: int) -> int | None:
        k = (pg, col)
        if k not in h_cache:
            p = ic.get(book, "column_image", f"p{pg:04d}c{col:02d}")
            img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) if p else None
            h_cache[k] = None if img is None else int(img.shape[0])
        return h_cache[k]

    for it in items:
        if only_ids is not None and it.id not in only_ids:
            continue
        a, ex = it.anchor, it.expected
        pg, col = int(a.page), int(a.col)
        h = col_height(pg, col)
        if h is None:
            skipped["no_column_image"] = skipped.get("no_column_image", 0) + 1
            continue
        gold_h = ex.get("col_h")
        if not gold_h:
            # 没记 col_h 的是 2026-09-13 起「选切分方案」卡的裁决（只有 cand 没有 y），
            # 本来就是对当前候选裁的，不算过期
            skipped["no_col_h(cand-verdict)"] = skipped.get("no_col_h(cand-verdict)", 0) + 1
            continue
        drifted = abs(int(gold_h) - h) > tol
        redo = (not drifted and bool(include_relabeled)
                and any(abs(int(v) - h) <= tol for v in include_relabeled.get(it.id, ())))
        if only_ids is not None and not drifted:
            redo = True
        if not drifted and not redo:
            continue                                  # 坐标系没变，不用重裁
        if pg not in cells_cache:
            cells_cache[pg] = st.read(book, "row_segment", page_key(pg), "cells")
        cells = cells_cache[pg]
        cc = cells.column(col) if cells is not None else None
        if cc is None or not cc.ok or len(cc.cells) != len(cc.boundaries) - 1:
            skipped["column_not_ok"] = skipped.get("column_not_ok", 0) + 1
            continue
        sa, sb = ex.get("slot_above"), ex.get("slot_below")
        bi = next((i for i in range(1, len(cc.cells))
                   if cc.cells[i - 1].slot == sa and cc.cells[i].slot == sb), None)
        if bi is None:
            skipped["slots_not_found"] = skipped.get("slots_not_found", 0) + 1
            continue
        up, dn = cc.cells[bi - 1], cc.cells[bi]
        if up.kind != "char" or dn.kind != "char":
            skipped["not_char_char"] = skipped.get("not_char_char", 0) + 1
            continue
        prof = _col_profile(st, book, pg, col)
        y = int(round(cc.boundaries[bi]))
        col_w = int(max(c.x1 for c in cc.cells) + min(c.x0 for c in cc.cells))
        seam = getattr(up, "seam_bottom", None)
        out.append(dict(
            id=it.id, book=book, page=pg, col=col, bi=bi, y=y,
            ink=round(float(prof[y]), 3) if prof is not None and 0 <= y < len(prof) else None,
            best=None,
            slot_above=up.slot, slot_below=dn.slot,
            y0=int(round(up.y0)), y1=int(round(dn.y1)),
            x0=int(round(min(up.x0, dn.x0))), x1=int(round(max(up.x1, dn.x1))),
            col_h=h, col_w=col_w,
            seam=list(seam) if seam else None,
            kind="drift",
            drift_from_col_h=int(gold_h) if drifted else None,
            redo=redo,
            gold_verdict=ex.get("verdict"),
            char_above=ex.get("char_above", ""), char_below=ex.get("char_below", ""),
        ))
    return out, skipped


def escalated_boundaries(book: str, pages: list[int], store=None,
                         include_pending: bool = True) -> tuple[list[dict], dict]:
    """**升级切点**（`CutPointCandidates.escalate`）：Step3 的 L2′/L0′ 探针说「本层拿不准」的那些。

    与 `r2s_boundaries` / `split_char_boundaries` 的区别：那两个是按图像判据**重新找**用例，这里直接读
    Step3 产物里已经标好的 `escalate`，因此**含 L0′ 的 split_suspect（直线不穿墨、一矮一高且矮格墨满）
    与 L3 扩池后的全部候选**（unet_seam / period_up / period_dn）。2026-09-15 加，见 overview
    `Step3-逐字切分/10-切点梯次裁决设计.md`。出的用例与另两个同形，控制台切线 tab 页码框填 `escalated` 即可。
    """
    from ..core.step import page_key
    from ..products import kinds as _k  # noqa: F401
    from ..products.store import ProductStore
    from .rulers import _col_profile
    import cv2
    from ..core.spec import column_key
    from ..products.cache import ImageCache
    st = store or ProductStore()
    ic = ImageCache()
    out: list[dict] = []
    skipped: dict[str, int] = {}
    h_cache: dict[tuple[int, int], int | None] = {}

    def col_height(pg_: int, col_: int) -> int | None:
        k_ = (pg_, col_)
        if k_ not in h_cache:
            p_ = ic.get(book, "column_image", column_key(pg_, col_))
            img = cv2.imread(str(p_), cv2.IMREAD_GRAYSCALE) if p_ else None
            h_cache[k_] = None if img is None else int(img.shape[0])
        return h_cache[k_]

    for pg in pages:
        cells = st.read(book, "row_segment", page_key(pg), "cells")
        if cells is None:
            continue
        for cc in cells.columns:
            if not cc.ok or len(cc.cells) != len(cc.boundaries) - 1:
                continue
            # 出卡的口径与顺序闸一致（2026-09-15）：`escalate`（L2′ 说拿不准）+ 多候选且所选与 U-Net
            # 分歧 ≥ PENDING_BLOB 的（60 条抽样标定：这一档坏率 35%，<20 的一条都不坏）。
            # 人裁过的不出（人是终审）。`include_pending=False` 只出 escalate 那几条。
            from ..utils.cut_select import PENDING_BLOB
            esc = []
            for cp in (cc.cut_candidates or []):
                if getattr(cp, "chosen_by", None) == "human":
                    continue
                if getattr(cp, "escalate", False):
                    esc.append(cp)
                elif include_pending and len(cp.candidates) >= 2 and cp.chosen is not None:
                    d = getattr(cp.candidates[cp.chosen], "dis_unet", None)
                    if d is None or d >= PENDING_BLOB:
                        esc.append(cp)
            if not esc:
                continue
            ch = col_height(pg, cc.col)
            if ch is None:
                skipped["no_column_image"] = skipped.get("no_column_image", 0) + 1
                continue
            prof = _col_profile(st, book, pg, cc.col)
            cmap = {c.slot: c for c in cc.cells if c.sub is None}
            for cp in esc:
                up, dn = cmap.get(cp.slot_above), cmap.get(cp.slot_below)
                if up is None or dn is None:
                    skipped["slots_not_found"] = skipped.get("slots_not_found", 0) + 1
                    continue
                y = int(round(cp.y))
                col_w = int(max(c.x1 for c in cc.cells) + min(c.x0 for c in cc.cells))
                out.append(dict(
                    id=f"{book}:{pg}:{cc.col}:{cp.slot_above}", book=book, page=pg, col=cc.col,
                    bi=cp.k, y=y,
                    ink=round(float(prof[y]), 3) if prof is not None and 0 <= y < len(prof) else None,
                    best=None, slot_above=up.slot, slot_below=dn.slot,
                    y0=int(round(up.y0)), y1=int(round(dn.y1)),
                    x0=int(round(min(up.x0, dn.x0))), x1=int(round(max(up.x1, dn.x1))),
                    col_h=ch, col_w=col_w,
                    seam=list(up.seam_bottom) if getattr(up, "seam_bottom", None) else None,
                    kind="escalated", escalate_reason=cp.escalate_reason or
                        f"pending dis_unet={getattr(cp.candidates[cp.chosen], 'dis_unet', None)}",
                    origin=getattr(cp, "origin", "touching"),
                ))
    return out, skipped


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
    """把整理本对齐金标的期望字挂到 char_above / char_below（没有就留空）。

    取 `reading`（整理本给的文意读法），**不是** `shape`（v2 定字认的刻本形）
    ——卡片上那栏写着「整理本期望」，就得真是整理本说的字。2026-09-13 实锤：
    vol02:33:2:9 语料原文是「大象引何**妥**說」，卡片却显示「何**安**」，因为
    这里一直取的是 `shape`：那条金标 `shape='安' reading='妥' conversion=True
    source='fallback'`——v2 定字自己就没把握（fallback 兜底），定出来的形还被
    当成「整理本期望」摆给人看，等于拿一个更不可信的来源冒充金标。

    两层都留着（`shape_above`/`shape_below`），差异由前端显式呈现为一次转换
    （见 `v2_align` 模块头「字形 / 释读分开记」）；`conversion` 位也一并带出，
    省得前端拿两个字符串比对再猜。
    """
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
        c["char_above"] = gu.reading if gu else ""
        c["char_below"] = gd.reading if gd else ""
        c["shape_above"] = gu.shape if gu else ""
        c["shape_below"] = gd.shape if gd else ""
        c["conv_above"] = bool(gu.conversion) if gu else False
        c["conv_below"] = bool(gd.conversion) if gd else False


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
    """已经裁过的格线 id（含 uncertain），出卡片时跳过。

    读的是 **workspace 裁决表**（`feedback/verdicts/`），不是 open-guji-dataset
    ——面板是运行时，不读测试集仓（2026-09-13）。裁决表是事件的派生物，
    `review/cards.py` 另外还按事件日志去重，两层兜着。"""
    from ..feedback.consumers import verdict_store
    try:
        return {i.id for i in verdict_store().list(SHARD)}
    except Exception:
        return set()
