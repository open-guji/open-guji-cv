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

from functools import lru_cache
from pathlib import Path

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
    # 每格数「落在扩半格框里的中等墨点」。原来先在整页上建积分图（两次 cumsum，约 0.3 s/页）再取框和；
    # 框和恰是 Y0 ≤ y < Y1、X0 ≤ x < X1 的点数，点只有几千、格一两百，直接数，整数逐个相同（2026-10-20）。
    xi = np.clip(pts[:, 0].astype(int), 0, W - 1) if len(pts) else np.zeros(0, int)
    yi = np.clip(pts[:, 1].astype(int), 0, H - 1) if len(pts) else np.zeros(0, int)
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
            k = int(np.count_nonzero((yi >= Y0) & (yi < Y1) & (xi >= X0) & (xi < X1)))
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


def text_ink_fraction(gray: np.ndarray, cells) -> dict[tuple[int, int, str], float]:
    """每格（**不扩框**，就是格本身）里「大块墨」占格面积的比例，{(col, slot, sub): 0~1}。

    大块墨＝连通块面积 > `OCC_AREA_MAX` 的墨（字的笔画主体；印泥斑点、斑驳底纸的碎点都是中等以下的小块，
    不算）。vol04 p130 实测：真字格 0.13~0.35，只有斑点的空格 ≤0.14，多数 ≤0.10（见
    `doc/research/遮挡判据误伤清楚字-vol04-p130-诊断.md`）。用于 `occluded_rescue_ink` 把「判成遮挡、
    其实是清楚的字」的格救回来。"""
    import cv2
    b = (gray < 128).astype(np.uint8)
    _n, lab, st, _cen = cv2.connectedComponentsWithStats(b, connectivity=8)
    big = st[:, cv2.CC_STAT_AREA] > OCC_AREA_MAX
    big[0] = False
    bigmask = big[lab]
    H, W = b.shape
    out: dict[tuple[int, int, str], float] = {}
    for c in cells.columns:
        for x in c.cells:
            if not x.quad_page:
                continue
            q = np.asarray(x.quad_page, dtype=float)
            x0, y0 = q.min(0)
            x1, y1 = q.max(0)
            X0, X1, Y0, Y1 = int(max(0, x0)), int(min(W, x1)), int(max(0, y0)), int(min(H, y1))
            if X1 <= X0 or Y1 <= Y0:
                continue
            out[(c.col, x.slot, x.sub or "")] = float(bigmask[Y0:Y1, X0:X1].mean())
    return out


def cell_ink_fraction(gray: np.ndarray, cells) -> dict[tuple[int, int, str], float]:
    """每格（不扩框）全部墨（灰度 < 128）占格面积的比例；`gray` 的坐标系须与 `quad_page` 一致。"""
    b = gray < 128
    H, W = b.shape
    out: dict[tuple[int, int, str], float] = {}
    for c in cells.columns:
        for x in c.cells:
            if not x.quad_page:
                continue
            q = np.asarray(x.quad_page, dtype=float)
            x0, y0 = q.min(0)
            x1, y1 = q.max(0)
            X0, X1, Y0, Y1 = int(max(0, x0)), int(min(W, x1)), int(max(0, y0)), int(min(H, y1))
            if X1 <= X0 or Y1 <= Y0:
                continue
            out[(c.col, x.slot, x.sub or "")] = float(b[Y0:Y1, X0:X1].mean())
    return out


def seal_overlap_cells(cells, seals, kind: str, overlap: float) -> dict[tuple[int, int, str], tuple[float, object]]:
    """格（`quad_page`，规范空间）与 `kind` 类印（`seals` 产物的 `Seal`）的外框重叠 ÷ 格面积 ≥ `overlap` 的格
    → {(col, slot, sub): (重叠比, 那方印)}；一格压着几方印取重叠最大的。"""
    out: dict[tuple[int, int, str], tuple[float, object]] = {}
    boxes = [s for s in seals if s.kind == kind]
    if not boxes:
        return out
    for c in cells.columns:
        for x in c.cells:
            if not x.quad_page:
                continue
            q = np.asarray(x.quad_page, dtype=float)
            gx0, gy0 = q.min(0)
            gx1, gy1 = q.max(0)
            area = (gx1 - gx0) * (gy1 - gy0)
            if area <= 0:
                continue
            for s in boxes:
                bx0, by0, bx1, by1 = s.bbox
                ov = max(0.0, min(gx1, bx1) - max(gx0, bx0)) * max(0.0, min(gy1, by1) - max(gy0, by0)) / area
                key = (c.col, x.slot, x.sub or "")
                if ov >= overlap and ov > out.get(key, (0.0, None))[0]:
                    out[key] = (ov, s)
    return out


#: 遮挡格：格与大印外框重叠 ≥ 这个比例（印章系统化，2026-10-22）
OCC_SEAL_OVERLAP = 0.5
#: 小印压字：格与小印外框重叠 ≥ 这个比例（印章系统化第 4 期）。比大印低：小印的边框正好横穿印边那一列的字
#: （vol09 p68 c7、p265 c7，重叠 0.35–0.44，字上压着一道印边）；印边外一列只蹭到 ≤ 0.18。
OCC_CRISP_OVERLAP = 0.3
#: 印框内的格，自己的背景噪点密度（`cell_densities`，每万像素中等墨点数）低于此值、且全部墨占格面积 < `OCC_SEAL_MAX_INK`
#: 的，不算遮挡：框边缘擦到、背景干净的字（20–99 册 7 册抽样 516 遮挡格里约 14% 是这种；sheldon 10-28 定
#: 「印章范围内＋背景有大量噪点」才算）。`seed_admit.occluded_seal_min_noise` 可调，0＝关。
OCC_SEAL_MIN_NOISE = 4.0
OCC_SEAL_MAX_INK = 0.5


def _drop_clean_cells(ctx, page: int, cells, occ: dict, p) -> dict:
    """大印框内但格内背景干净（噪点密度低、不是整块黑）的格不算遮挡。读不到原图就原样返回。"""
    thr = float(getattr(p, "occluded_seal_min_noise", OCC_SEAL_MIN_NOISE) or 0.0)
    if not occ or thr <= 0:
        return occ
    try:
        gray = ctx.raw_page(page)[:, ::-1]   # 原图左上原点、格框右上原点（规范空间）：翻成同一坐标系
    except Exception:
        return occ
    dens = cell_densities(gray, cells)
    ink = cell_ink_fraction(gray, cells)
    return {k: v for k, v in occ.items()
            if not (dens.get(k, thr) < thr and ink.get(k, 1.0) < OCC_SEAL_MAX_INK)}


def page_occluded(ctx, page: int, p) -> dict[tuple[int, int, str], float]:
    """本页的遮挡格 {(col, slot, sub): 分数}——**判据的唯一入口**。

    `seed_admit` 的 `occluded_gate` 与 `feedback.consumers.glyphdb_admit` 的入库闸都走这里
    （2026-09-30，H-seal：人裁「确认」事件的 `no_glyph_lib` 可能是 false，闸不能只信事件）。

    2026-10-22 起（印章系统化第 2 期）：遮挡格＝与印章定位 `seals` 产物里**大印**外框重叠 ≥
    `OCC_SEAL_OVERLAP` 的格，分数取那方印的峰值密度。大印区整块不识别（用户 10-22：「大的印章就是
    完全不用识别」）。殿本十页大印页对比旧的格级密度判据：旧 1,226 格、新 1,290 格，新增的非空格
    62 个（vol08 p2 印淡、旧判据只认出半方 57 格；vol04 p130 5 格），旧有新无 24 格（印框外的边角）。
    旧判据量墨点时把规范空间（右上原点）的格框直接套在原图（左上原点）上，量的是左右镜像处，
    印在页中间才没出事。没有 `seals` 产物的旧产物才退回旧的密度判据（模块头，`p` 带
    `occluded_min_*` 五个字段，`SeedAdmitParams`）。读不到 Step3 字格就当没有遮挡（返回空表）。

    第 4 期（用户 10-22 定）：**小印压着的真字**也算遮挡——与小印外框重叠 ≥ `OCC_CRISP_OVERLAP` 的格，
    除去盖章空栏候选（`page_seal_blank`：格里的墨全在印笔画上，是印不是字），分数取小印的分数。
    印的笔画压在字上，字块带着印进字形库会污染刻例，识别也不可信（vol09 p68／p162／p265 卷末）。"""
    try:
        cells = ctx.product("cells", page)
    except Exception:
        return {}
    if cells is None:
        return {}
    has_seals = getattr(ctx, "has_product", None)
    if has_seals is not None and has_seals("seals", page):
        seals = ctx.product("seals", page).seals
        hit = seal_overlap_cells(cells, seals, "stain", OCC_SEAL_OVERLAP)
        occ = {k: float(s.score) for k, (_ov, s) in hit.items()}
        occ = _drop_clean_cells(ctx, page, cells, occ, p)
        # 小印压着的字（用户 10-22 定：同大印，默认整理本字、不进字形库）；只有印没有字的格是盖章空栏，归 page_seal_blank
        small = seal_overlap_cells(cells, seals, "crisp", OCC_CRISP_OVERLAP)
        if small:
            blank = page_seal_blank(ctx, page, p)
            occ.update({k: float(s.score) for k, (_ov, s) in small.items() if k not in blank and k not in occ})
    else:
        try:
            gray = ctx.raw_page(page)
        except Exception:
            return {}
        occ = occluded_cells(cell_densities(gray, cells), min_density=p.occluded_min_density,
                             min_cells=p.occluded_min_cells, min_cols=p.occluded_min_cols,
                             min_peak=p.occluded_min_peak, min_contrast=p.occluded_min_contrast)
    # 清楚的字救回：块里夹着的、格内大块墨 ≥ `occluded_rescue_ink` 的格不算遮挡（0＝关，缺省，行为不变）。
    # getattr：别的调用方（`feedback.consumers`、`cell_shrink` 的缺省参数）传的参数对象可能没有这个字段。
    rescue = float(getattr(p, "occluded_rescue_ink", 0.0) or 0.0)
    if occ and rescue > 0:
        try:
            gray = ctx.raw_page(page)
        except Exception:
            return occ
        frac = text_ink_fraction(gray, cells)
        occ = {k: v for k, v in occ.items() if frac.get(k, 0.0) < rescue}
    return occ


# ── 盖章空栏判空（`seal_blank_page`，2026-10-09，道 B 规格 overview#493）─────────
#
# 固定印「乾隆御覽之寶」（约 660×680 px，印在卷末页，位置约 (830,330)）：NCC 模板匹配找印框，
# 再看框内格：格与印框重叠 ≥ `overlap` 的才是候选。候选还要过 seed_admit 里的格级保险
# （无坐标字 ∧ 未被强通道放行），缺一不可——印压真字的页（vol02 p188、vol03 p110、vol10 p175）
# 命中了模板，但框内是字，不能整列判空。判空本身在 seed_admit（`_seal_blank_flip`）做。

SEAL_TPL_DIR = Path(__file__).resolve().parents[2] / "config" / "seal_templates"
#: 模板左上角的搜索先验：x∈[830−150, 830+150]、y∈[330−150, 330+150]（按已有 4 册页图标定）
SEAL_WIN_XY = (830, 330)
SEAL_WIN_HALF = 150


@lru_cache(maxsize=1)
def load_seal_templates() -> tuple[np.ndarray, ...]:
    """`config/seal_templates/*.png` 的灰度模板；目录缺失或读不出就是空元组（判不出印）。"""
    import cv2

    from ..utils.image_io import imread
    if not SEAL_TPL_DIR.is_dir():
        return ()
    out = []
    for f in sorted(SEAL_TPL_DIR.glob("*.png")):
        im = imread(str(f), cv2.IMREAD_GRAYSCALE)
        if im is not None:
            out.append(im)
    return tuple(out)


SEAL_COVER_DILATE = 5   # 印章笔画覆盖区：命中模板二值化（<128）膨胀的像素数（道 A 量法，overview#493）


def find_seal_box(gray: np.ndarray, *, templates, thr: float):
    """窗口先验内 NCC 最高的模板位置：(印框 (x, y, w, h)、分数、模板)；没有模板、窗口超出页图、分数 < `thr` 返回 None。"""
    import cv2
    if not templates or gray is None:
        return None
    H, W = gray.shape[:2]
    best, box, best_tpl = -1.0, None, None
    x0, y0 = SEAL_WIN_XY[0] - SEAL_WIN_HALF, SEAL_WIN_XY[1] - SEAL_WIN_HALF
    for tpl in templates:
        th, tw = tpl.shape[:2]
        # 模板左上角在 [x0, x0+2·half] × [y0, y0+2·half] 内 → ROI 要能容下整块模板
        rx0, ry0 = max(0, x0), max(0, y0)
        rx1 = min(W, x0 + 2 * SEAL_WIN_HALF + tw)
        ry1 = min(H, y0 + 2 * SEAL_WIN_HALF + th)
        if rx1 - rx0 < tw or ry1 - ry0 < th:
            continue
        res = cv2.matchTemplate(gray[ry0:ry1, rx0:rx1], tpl, cv2.TM_CCOEFF_NORMED)
        _mn, mx, _mnl, (px, py) = cv2.minMaxLoc(res)
        if mx > best:
            best, box, best_tpl = float(mx), (rx0 + px, ry0 + py, tw, th), tpl
    if box is None or best < thr:
        return None
    return box, best, best_tpl


def seal_blank_cells(gray: np.ndarray, cells, *, templates, thr: float,
                     overlap: float, ink_out: float | None = None
                     ) -> dict[tuple[int, int, str], dict]:
    """找印框，返回框内候选格 {(col, slot, sub): {"seal_score", "overlap", "ink_out"}}。

    印框 = 窗口先验内 NCC 最高（≥ `thr`）的那个模板位置。格与印框重叠面积 ÷ 格面积 ≥ `overlap`
    才入选。找不到印框、没有模板、窗口超出页图都返回空表。只给候选，不判空。

    `ink_out`（第四条保险，道 A 量法）：格内「模板外墨」＝格框内 <128 且落在覆盖区外的像素 ÷ 格面积；
    ≥ `ink_out` 的格退出候选（仍走原路径，即待审）。覆盖区 ＝ 命中的那个模板在命中位置的二值化（<128）
    膨胀 `SEAL_COVER_DILATE` 像素，与 NCC 命中同一坐标系、不另起对位。`ink_out=None` 不做这道过滤。"""
    hit = find_seal_box(gray, templates=templates, thr=thr)
    if hit is None:
        return {}
    import cv2
    box, best, best_tpl = hit
    H, W = gray.shape[:2]
    bx, by, bw, bh = box
    # 覆盖区：命中模板在命中位置的笔画（<128）膨胀；只在页图尺寸内
    cov = np.zeros((H, W), np.uint8)
    stroke = (best_tpl < 128).astype(np.uint8)
    kern = np.ones((2 * SEAL_COVER_DILATE + 1, 2 * SEAL_COVER_DILATE + 1), np.uint8)
    dil = cv2.dilate(stroke, kern)
    ch, cw = min(bh, H - by), min(bw, W - bx)
    cov[by:by + ch, bx:bx + cw] = dil[:ch, :cw]
    out: dict[tuple[int, int, str], dict] = {}
    for c in cells.columns:
        for x in c.cells:
            if not x.quad_page:
                continue
            q = np.asarray(x.quad_page, dtype=float)
            gx0, gy0 = q.min(0)
            gx1, gy1 = q.max(0)
            area = (gx1 - gx0) * (gy1 - gy0)
            if area <= 0:
                continue
            ix = max(0.0, min(gx1, bx + bw) - max(gx0, bx))
            iy = max(0.0, min(gy1, by + bh) - max(gy0, by))
            ov = ix * iy / area
            if ov < overlap:
                continue
            xi0, yi0 = max(0, int(np.floor(gx0))), max(0, int(np.floor(gy0)))
            xi1, yi1 = min(W, int(np.ceil(gx1))), min(H, int(np.ceil(gy1)))
            g_win = gray[yi0:yi1, xi0:xi1] < 128
            ink = float(np.count_nonzero(g_win & (cov[yi0:yi1, xi0:xi1] == 0))) / area
            if ink_out is not None and ink >= ink_out:
                continue
            out[(c.col, x.slot, x.sub or "")] = {"seal_score": round(best, 4),
                                                 "overlap": round(ov, 3),
                                                 "ink_out": round(ink, 4)}
    return out


def page_seal_blank(ctx, page: int, p) -> dict[tuple[int, int, str], dict]:
    """本页盖章空栏候选格（读不到 Step3 字格或原图就当没有）。`p` 带 `seal_blank_thr`／`seal_blank_overlap`／`seal_blank_ink_out`。

    2026-10-22 起（印章系统化第 2 期）：印框取印章定位 `seals` 产物里的**小印**（`seal_blank_thr` 不再用），
    格与印框重叠 ≥ `seal_blank_overlap` 入选；「印外墨」的覆盖区取 `seal_detect.stroke_mask`。格框从规范空间
    换回原图坐标再量（旧路径直接拿右上原点的格框比左上原点的印框）。没有 `seals` 产物的旧产物才走旧路径。"""
    try:
        cells = ctx.product("cells", page)
        gray = ctx.raw_page(page)
    except Exception:
        return {}
    if cells is None:
        return {}
    has_seals = getattr(ctx, "has_product", None)
    if has_seals is None or not has_seals("seals", page):
        return seal_blank_cells(gray, cells, templates=load_seal_templates(),
                                thr=p.seal_blank_thr, overlap=p.seal_blank_overlap,
                                ink_out=p.seal_blank_ink_out)
    from .seal_detect import stroke_mask
    H, W = gray.shape[:2]
    out: dict[tuple[int, int, str], dict] = {}
    masks: dict[int, np.ndarray | None] = {}
    for key, (ov, s) in seal_overlap_cells(cells, ctx.product("seals", page).seals, "crisp",
                                           p.seal_blank_overlap).items():
        if id(s) not in masks:
            masks[id(s)] = stroke_mask(s, H, W)
        cov = masks[id(s)]
        col, slot, sub = key
        x = next(x for c in cells.columns if c.col == col for x in c.cells if x.slot == slot and (x.sub or "") == sub)
        q = np.asarray(x.quad_page, dtype=float)
        gx0, gy0 = q.min(0)
        gx1, gy1 = q.max(0)
        area = (gx1 - gx0) * (gy1 - gy0)
        y0, y1 = max(0, int(np.floor(gy0))), min(H, int(np.ceil(gy1)))
        x0, x1 = max(0, int(np.floor(W - 1 - gx1))), min(W, int(np.ceil(W - 1 - gx0)))
        ink = gray[y0:y1, x0:x1] < 128
        if cov is not None:
            ink = ink & (cov[y0:y1, x0:x1] == 0)
        frac = float(np.count_nonzero(ink)) / area
        if p.seal_blank_ink_out is not None and frac >= p.seal_blank_ink_out:
            continue
        out[key] = {"seal_score": round(float(s.score), 4), "overlap": round(ov, 3), "ink_out": round(frac, 4)}
    return out
