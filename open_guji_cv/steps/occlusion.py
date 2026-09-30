"""印章／大片污损遮挡的字格检测（`occluded`，2026-09-28，D 道 overview#195）。

## 起因

用户 09-28：vol03 第 3 页右上盖了一方大印章，背景满是污点，那一块的格人裁很费劲，
而且**太脏、全都不能入库**。要求把这一块摘出来：一律不进字形库，人审卡默认用整理本
的字（`align_ref` 的坐标对位），排在一起一次过。

## 判据：页面上「中等大小墨点」的空间密度

1-bit 扫描件上，印章不是一片灰，而是**成片的小墨点/短划**（印泥斑驳 + 篆文残笔），
散布在字与字之间、字与界行之间。正常页的空白处几乎是干净的。所以：

1. 整页二值化（扫描本身就是双值，`< 128` 即墨），取连通块，只留面积在
   `[OCC_AREA_MIN, OCC_AREA_MAX]` 像素的「中等墨点」——太小的是扫描噪声、太大的是
   字的笔画主体；
2. 每个格（Step3 `cells` 的 `quad_page`，整页坐标）**向四周各扩半格**，数框里中等
   墨点的质心个数，除以面积（每万像素）——扩框是为了把字间、字与界行之间的空白算进来，
   印章的斑点主要落在那里；
3. 密度 ≥ `min_density` 的格记为「热格」；热格按（列 ±1，slot ±1）连通成块，
   **块内 ≥ `min_cells` 格且横跨 ≥ `min_cols` 列**才算遮挡——单格墨点多（版框角、
   抬头框边、下版框残墨）成不了块；
4. 每列里块的最上、最下两格之间的格一并算进来（补洞：印章中间压着字身的格，墨点被
   字挡住，自己的密度反而不高）。

## 标定（vol03 全册 104 页、19,236 格，`cloud-20260927-4e2e0b7-iron` 快照）

| | 热格密度分位（每万像素） |
|---|---|
| 全书 中位 / 90% / 99% / 99.9% | 0.54 / 1.99 / 6.13 / 10.4 |
| p3 印章区内 | 4 ~ 13 |
| 正常页的高值 | 只出现在第 1 格／第 21 格（版框上下沿残墨）与抬头格，孤立 |

阈值扫描（密度门槛 × 块大小，横跨 ≥3 列）：

| 门槛 | 块 ≥6 格 | 块 ≥8 格 | 块 ≥12 格 |
|---|---|---|---|
| 4 | p3 + 9 页误报 | p3 + 5 页误报 | **只有 p3（126 格）** |
| 5 | p3(98) + 3 页 | p3 + p60 | 只有 p3（98 格，漏 28） |

取 **4 / 12 / 3**：全册只命中 p3，补洞后覆盖印章区 1–14 行的全部字格。
样本只有一页真印章，阈值是在「全册零误报」这一侧定的；换书（或同书别的印章页）
若漏报，先看 `evidence.occluded.density`，别急着降门槛（降到 6 格块就有 9 页误报）。

## 十册复核（同日，四庫 vol01–vol10 快照全部 Step3 产物，共 1,892 页）

只用上面三条，十册命中 15 页：各册首叶（p2/p3，藏书印）10 页 + 卷端 4 页
（vol04 p130、vol09 p70/p164、vol10 p88）逐页看图**都是真印章**（vol09 p68 是一方小印，
12 格刚好过线）；**vol05 p68 是误报**——那页没有印，是整页印得虚、笔画断成碎块、界行
断成虚线，中等墨点处处都是。块级统计把它分得很开：

| | 块内最高密度 | 块内中位 / 页内其余中位 |
|---|---|---|
| 14 页真印章 | 9.2 ~ 20.2 | 3.1 ~ 11 倍 |
| vol05 p68（碎笔画） | **6.1** | **1.9 倍** |

于是加两道块级闸：峰值 ≥ 8、对比 ≥ 2.5 倍（两者都要过）。加闸后十册命中 14 页全是真印章。
"""

from __future__ import annotations

import numpy as np

OCC_AREA_MIN = 3
OCC_AREA_MAX = 150
OCC_GROW = 0.5


def _slot_rank(slot: int) -> int:
    """抬头格 slot=-1 与 slot=1 相邻（中间没有 slot 0）。"""
    return 0 if slot < 0 else slot


def cell_densities(gray: np.ndarray, cells) -> dict[tuple[int, int, str], float]:
    """每格（扩半格）中等墨点密度，{(col, slot, sub): 每万像素个数}。"""
    import cv2
    b = (gray < 128).astype(np.uint8)
    _n, _lab, st, cen = cv2.connectedComponentsWithStats(b, connectivity=8)
    a = st[:, cv2.CC_STAT_AREA]
    keep = (a >= OCC_AREA_MIN) & (a <= OCC_AREA_MAX)
    keep[0] = False
    pts = cen[keep]
    H, W = b.shape
    cnt = np.zeros((H + 1, W + 1), np.int32)
    if len(pts):
        xi = np.clip(pts[:, 0].astype(int), 0, W - 1)
        yi = np.clip(pts[:, 1].astype(int), 0, H - 1)
        np.add.at(cnt, (yi + 1, xi + 1), 1)
    integ = cnt.cumsum(0).cumsum(1)
    out: dict[tuple[int, int, str], float] = {}
    for c in cells.columns:
        for x in c.cells:
            if not x.quad_page:
                continue
            q = np.asarray(x.quad_page, dtype=float)
            x0, y0 = q.min(0)
            x1, y1 = q.max(0)
            w, h = x1 - x0, y1 - y0
            X0, X1 = int(max(0, x0 - OCC_GROW * w)), int(min(W, x1 + OCC_GROW * w))
            Y0, Y1 = int(max(0, y0 - OCC_GROW * h)), int(min(H, y1 + OCC_GROW * h))
            if X1 <= X0 or Y1 <= Y0:
                continue
            k = integ[Y1, X1] - integ[Y0, X1] - integ[Y1, X0] + integ[Y0, X0]
            out[(c.col, x.slot, x.sub or "")] = float(k) / ((X1 - X0) * (Y1 - Y0)) * 1e4
    return out


def occluded_cells(dens: dict[tuple[int, int, str], float], *, min_density: float = 4.0,
                   min_cells: int = 12, min_cols: int = 3, min_peak: float = 8.0,
                   min_contrast: float = 2.5) -> dict[tuple[int, int, str], float]:
    """热格连通成块 → 遮挡格（含补洞）。返回 {(col, slot, sub): 密度}。

    块还要过两道块级闸（见模块头「十册复核」）：块内最高密度 ≥ `min_peak`（印章芯子是
    实打实的一大片斑点）；块内密度中位 ≥ `min_contrast` × 本页其余格的密度中位（整页
    印得虚、笔画断成碎块的页，块内外一样脏，比不出来）。"""
    hot = [k for k, v in dens.items() if v >= min_density]
    hot_set = set(hot)
    seen: set = set()
    blocks: list[list[tuple[int, int, str]]] = []
    for k in hot:
        if k in seen:
            continue
        seen.add(k)
        stack, comp = [k], []
        while stack:
            c = stack.pop()
            comp.append(c)
            for o in hot_set:
                if o not in seen and abs(o[0] - c[0]) <= 1 \
                        and abs(_slot_rank(o[1]) - _slot_rank(c[1])) <= 1:
                    seen.add(o)
                    stack.append(o)
        if len(comp) >= min_cells and len({c[0] for c in comp}) >= min_cols:
            blocks.append(comp)
    if blocks:
        import statistics
        in_any = {c for comp in blocks for c in comp}
        rest = [v for k, v in dens.items() if k not in in_any]
        rest_med = statistics.median(rest) if rest else 0.0
        blocks = [comp for comp in blocks
                  if max(dens[c] for c in comp) >= min_peak
                  and statistics.median(dens[c] for c in comp) >= min_contrast * rest_med]
    out: dict[tuple[int, int, str], float] = {}
    for comp in blocks:
        span: dict[int, tuple[int, int]] = {}
        for col, slot, _sub in comp:
            r = _slot_rank(slot)
            lo, hi = span.get(col, (r, r))
            span[col] = (min(lo, r), max(hi, r))
        for key, v in dens.items():
            col, slot, _sub = key
            if col in span and span[col][0] <= _slot_rank(slot) <= span[col][1]:
                out[key] = v
    return out


def page_occluded(ctx, page: int, p) -> dict[tuple[int, int, str], float]:
    """本页的遮挡格 {(col, slot, sub): 密度}——**判据的唯一入口**。

    `seed_admit` 的 `occluded_gate` 与 `feedback.consumers.glyphdb_admit` 的入库闸都走这里
    （2026-09-30，H-seal：人裁「确认」事件的 `no_glyph_lib` 可能是 false，闸不能只信事件）。
    `p` 是带 `occluded_min_*` 五个字段的参数对象（`SeedAdmitParams`）。读不到 Step3 字格
    或原图就当没有遮挡（返回空表）。"""
    try:
        cells = ctx.product("cells", page)
    except Exception:
        return {}
    if cells is None:
        return {}
    try:
        gray = ctx.raw_page(page)
    except Exception:
        return {}
    return occluded_cells(cell_densities(gray, cells), min_density=p.occluded_min_density,
                          min_cells=p.occluded_min_cells, min_cols=p.occluded_min_cols,
                          min_peak=p.occluded_min_peak, min_contrast=p.occluded_min_contrast)
