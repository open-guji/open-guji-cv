"""3d 字块图的其他特征（`cell_traits`，2026-11-28，CV3 第三步重构 W3）的纯算法：只看图量东西、按格出**原始分**。

Sheldon 11-27 定：切的动作留在第二步，「这格图有没有毛病」的判断都收到 3d。每格每个键一个原始分（不是概率），
收尾 `glyph_analyzer` 以后用人裁标注标定成 p 写进 `p_map`；第三步不判放行。步骤壳在 `steps/cell_traits.py`。

## 分的口径

每个键的分都在 0～1，**0.5 ≈ 现行判法的门槛**（各子判据按原处阈值线性映射：原阈值落在 0.5，
再往「更像有毛病」那边走一倍到 1）。一个键取它几个子判据的最大值，各子判据的值与原始量都写进
`evidence.<键>`，标定时可以按子判据分开拟合。分没有校准，不同键之间不能比大小。

| 键 | 意思 | 子判据（来源） |
|---|---|---|
| `cut` | 字被切断 | 同字对照墨高矮一截（guji-manager `review/seg_defect.same_char_clip`，只判列端）；Step3 选中切线穿墨 `seam_ink`（同 `CLIP_SEAM_INK`）；cell_shrink 旗 `boundary_ink`（弱，0.25）、`off_center`（0.35） |
| `border` | 混入边框 | 端区碎线 `end_debris`、隔开又伸出字身的端条 `end_band`（seg_defect `same_char_frame`，只判列端）；字块里满高细竖条 `rule_bar`、满宽扁横条 `frame_bars`（`extractor._defect_features` 连续值，cell_shrink 同名旗记 0.9） |
| `residue` | 混入上下字残留 | 上下带里与字身隔开的一块墨 `blob`（`extractor._defect_features` 的 edge_blob 同口径，字身取全部非边带连通块、去掉字自己的横画）；旗 `edge_blob`（0.7）、`tail_junk`（0.6）。左右空隙 `x_gap` 只记证据 |
| `stain` | 背景污染／印章遮挡 | 格四周扩半格的中等墨点密度（`steps/occlusion.cell_densities` 同口径）；与大印／小印外框的重叠（`occlusion.seal_overlap_cells` 同口径）；旗 `seal_region`（0.6） |
| `merged` | 两字并一格 | 墨高 ÷ 格高（夹注按本列夹注半格墨高中位）＋竖向投影中段低谷（seg_defect `_valley_split`／「超高无低谷」） |
| `blank` | 空格有墨／非字 | 字块墨量 ÷ 本页字块墨量中位（小＝像墨点、句读、残笔），乘 (1 − 3a 置信)（seed_admit `_blank_ink_pass` 的图像部分：有墨而库认不出）；旗 `suspect_empty`／`ink_blob`（0.6）、`sliver`（0.5） |

键可以加；加键不改格式。

## 和原处判法的差别（都写在这里，免得以后对不上）

- **同字参照只取本页**：seg_defect 取全册已放行的列中格；3d 一页一页跑，跨页取参照会让一页的产物依赖别的页、
  指纹管不住，所以只取本页 3a 判 same 的列中格（离本列首末各 2 格以外），同字（分整字／夹注）≥ `same_min_ref` 个才比。
  殿本一页 400 来格，常用字（之、也、不、曰）够数，生僻字多半没有参照，那时同字子判据记 None、不出分。
- **在最终字块（`char_patch`）上量形状**，与 seg_defect、extractor 一样；背景墨点、切线外压墨在**原图**上量（要看字块框外）。
- 不判放行，不改任何上游产物。

`edge_ink`（列端字块框靠版框那条边上下 5 行的墨占比，SJ 11-05 量法）只记进 `evidence.cut`，不进分：殿本列端字脚贴版框，
压墨高的多是带框不是切断，原处也只在史記当附加条件用。
"""
from __future__ import annotations

import statistics
from typing import Iterable

import numpy as np

KEYS = ("cut", "border", "residue", "stain", "merged", "blank")

INK_THR = 160           # 墨像素：灰度 < 它（seg_defect INK_THR）
BIN_THR = 128           # 二值墨（extractor BINARY_THRESHOLD_PATCH、occlusion）

# ── 同字对照（seg_defect）────────────────────────────────────────────
SAME_FLAT = 0.30        # 参照墨高 < 它×格高的扁字（「一」）不判
SAME_H = 0.80           # 墨高比低于它算缺一截 → cut 0.5
SAME_H_WIDE = 0.85
SAME_ASPECT = 1.30      # 墨高比在 SAME_H～SAME_H_WIDE 之间、宽比/高比 ≥ 它也算缺一截
FRAME_MIN_H = 0.90      # 带框子判据要墨高不比同字矮这么多（更矮的归 cut）
SAME_FRAME_W = 1.10     # 端条：墨宽比同字 ≥ 它
END_BAND = 3
FRAME_GAP = 0.30
FRAME_OVER = 0.05
FRAME_DEBRIS = 0.15     # 端区碎线占宽 ≥ 它 → border 0.5
FRAME_DEBRIS_H = 0.08
CLIP_SEAM_INK = 30      # 切线穿墨 ≥ 它 → cut 0.5
EDGE_ROWS = 2

# ── 并格（seg_defect）────────────────────────────────────────────────
MERGED_H = 1.6          # 有低谷时墨高 ≥ 它×基准 → merged 0.5
MERGED_TALL_H = 1.8     # 无低谷（整字格）墨高 ≥ 它×基准 → merged 0.5
MERGED_VALLEY = 0.10
MERGED_GAP = 0.08
MERGED_PART = 0.30
MERGED_INK = 0.20

# ── 背景墨点（steps/occlusion，同口径；那边是 L3，这里抄常数不 import）──────
OCC_AREA_MIN = 3
OCC_AREA_MAX = 150
OCC_GROW = 0.5          # 格框四周各扩半格
OCC_DENSITY = 4.0       # 每万像素中等墨点数 ≥ 它 → stain 0.5（occlusion min_density）
OCC_SEAL_OVERLAP = 0.5  # 大印重叠 ≥ 它 → stain 0.5
OCC_CRISP_OVERLAP = 0.3

# ── extractor 缺陷量的门槛（clustering/extractor.py 同名常数）─────────────
RULE_BAR_INK = 0.02
EDGE_BLOB_INK = 0.03
WIDE_GAP_T = 0.12

#: cell_shrink 旗 → (键, 分)。确定层（extractor 文档：实测零误报）记 0.9，疑似层按原处误报情况记低分
FLAG_SCORES: dict[str, tuple[str, float]] = {
    "rule_bar": ("border", 0.9),
    "frame_bars": ("border", 0.9),
    "edge_blob": ("residue", 0.7),
    "tail_junk": ("residue", 0.6),
    "boundary_ink": ("cut", 0.25),       # 殿本 vol12：364 条多在列尾、字脚贴版框就打旗，几乎全误报（A22 11-04）
    "off_center": ("cut", 0.35),         # 疑似横向截断（extractor 疑似层）
    "seal_region": ("stain", 0.6),
    "suspect_empty": ("blank", 0.6),
    "ink_blob": ("blank", 0.6),
    "sliver": ("blank", 0.5),
}


def lin(x: float | None, at0: float, at1: float) -> float:
    """x 线性映射到 [0, 1]：x＝at0 给 0、x＝at1 给 1（at1 可小于 at0），两头截断。x 为 None 给 0。"""
    if x is None or at1 == at0:
        return 0.0
    return float(min(1.0, max(0.0, (x - at0) / (at1 - at0))))


def r4(x: float | None) -> float | None:
    return None if x is None else round(float(x), 4)


# ── 字块形状量 ───────────────────────────────────────────────────────

def ink_h(patch: np.ndarray | None) -> int | None:
    """墨高：墨像素（< INK_THR）≥ 2 个的行，首末行之间的高（seg_defect `_ink_h`）。"""
    if patch is None or patch.size == 0:
        return None
    rows = np.nonzero((patch < INK_THR).sum(axis=1) >= 2)[0]
    return None if rows.size == 0 else int(rows[-1] - rows[0] + 1)


def ink_w(patch: np.ndarray | None) -> int:
    """墨宽：有墨像素的列数（seg_defect `_ink_w`）。"""
    if patch is None or patch.size == 0:
        return 0
    return int(((patch < INK_THR).sum(axis=0) > 0).sum())


def valley_split(patch: np.ndarray | None, cell_h: float) -> tuple[int, int] | None:
    """竖向投影中段的低谷 (y0, y1)：上下两团各高 ≥ MERGED_PART 格高、墨量小比大 ≥ MERGED_INK（seg_defect `_valley_split`）。"""
    if patch is None or patch.size == 0 or not cell_h:
        return None
    ink = (patch < BIN_THR).sum(axis=1).astype(float)
    if ink.max() <= 0:
        return None
    nz = np.nonzero(ink)[0]
    top, bot = int(nz[0]), int(nz[-1])
    low = ink < MERGED_VALLEY * ink.max()
    best = None
    y = top
    while y <= bot:
        if low[y]:
            y0 = y
            while y <= bot and low[y]:
                y += 1
            if y0 > top and y <= bot and (y - y0) >= MERGED_GAP * cell_h \
                    and (y0 - top) >= MERGED_PART * cell_h and (bot - y + 1) >= MERGED_PART * cell_h:
                up, down = ink[top:y0].sum(), ink[y:bot + 1].sum()
                if min(up, down) >= MERGED_INK * max(up, down):
                    best = (y0, y)
        y += 1
    return best


def end_band(patch: np.ndarray | None, bottom: bool) -> tuple[float, float] | None:
    """靠版框那头的端条 (gap, overhang)（seg_defect `end_band`）：gap 小＝端条和字身隔开；overhang＝端条墨列伸出字身左右的占比。"""
    if patch is None or patch.size == 0:
        return None
    m = patch < INK_THR
    if bottom:
        m = m[::-1]
    rows = np.nonzero(m.sum(axis=1) >= 2)[0]
    if rows.size == 0:
        return None
    r0, ih = int(rows[0]), int(rows[-1] - rows[0] + 1)
    band = m[r0:r0 + END_BAND]
    nxt = m[r0 + END_BAND:r0 + END_BAND + 8].sum(axis=1)
    gap = float(nxt.min() / max(1, band.sum(axis=1).max())) if nxt.size else 1.0
    bcols = band.any(axis=0)
    body = m[r0 + END_BAND + max(2, int(0.05 * ih)):r0 + ih // 2].any(axis=0)
    xs = np.nonzero(body)[0]
    if xs.size == 0 or not bcols.any():
        return gap, 0.0
    out = bcols.copy()
    out[xs[0]:xs[-1] + 1] = False
    return gap, float(out.sum() / bcols.sum())


def end_debris(patch: np.ndarray | None, bottom: bool) -> tuple[float, int]:
    """靠版框那头端区里与字身分开的细碎截 (占宽, 个数)（seg_defect `end_debris`）。"""
    if patch is None or patch.size == 0:
        return 0.0, 0
    import cv2
    m = (patch < INK_THR).astype(np.uint8)
    if bottom:
        m = np.ascontiguousarray(m[::-1])
    rows = np.nonzero(m.sum(axis=1) >= 2)[0]
    if rows.size == 0:
        return 0.0, 0
    r0, ih = int(rows[0]), int(rows[-1] - rows[0] + 1)
    e = max(6, int(0.15 * ih))
    n, _, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n <= 2:
        return 0.0, 0
    big = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    cols = np.zeros(m.shape[1], bool)
    k = 0
    for i in range(1, n):
        x, y, w, h = (int(v) for v in st[i, :4])
        if i != big and y + h <= r0 + e + 1 and h <= max(3, FRAME_DEBRIS_H * ih):
            cols[x:x + w] = True
            k += 1
    return float(cols.sum() / m.shape[1]), k


def end_spread(patch: np.ndarray | None, bottom: bool) -> float | None:
    """端区墨列跨度 ÷ 字身墨列跨度（seg_defect `end_spread` 第一项；与尺度无关）。量不出 None。"""
    if patch is None or patch.size == 0:
        return None
    m = patch < INK_THR
    if bottom:
        m = m[::-1]
    rows = np.nonzero(m.sum(axis=1) >= 2)[0]
    if rows.size == 0:
        return None
    r0, ih = int(rows[0]), int(rows[-1] - rows[0] + 1)
    e = max(6, int(0.15 * ih))
    zone = np.nonzero(m[r0:r0 + e].any(axis=0))[0]
    body = np.nonzero(m[r0 + END_BAND + max(2, int(0.05 * ih)):r0 + ih // 2].any(axis=0))[0]
    if zone.size == 0 or body.size < 2:
        return None
    return float((zone[-1] - zone[0] + 1) / (body[-1] - body[0] + 1))


#: 上下带里与字身隔开的一块墨，要排除的「字自己的横画」：扁（宽 ≥ STROKE_FLAT×高）且中心落在字身左右范围内。
#: 「二」「元」「云」「示」的顶横整体落在边缘带里、和字身隔开，在裁紧的字块上 extractor 的 edge_blob 会算它
#: （殿本 vol02 原图裁块 edge_blob ≥ 0.06 的 300 多格多是这种）
STROKE_FLAT = 3.0
BODY_MIN = 0.3          # 字身（非边带连通块）墨量至少占全块这么多才判
DEFECT_BAND = 0.18      # extractor DEFECT_BAND
EDGE_BLOB_GAP = 0.10    # extractor EDGE_BLOB_GAP


def residue_blob(patch: np.ndarray | None) -> float:
    """上下边缘带里**整体**落在带内、与字身纵向隔开 > EDGE_BLOB_GAP×高的连通块，墨量占全块的最大比例
    （extractor `_defect_features` 的 edge_blob 同口径），只是：字身＝不整体落在带内的全部连通块（extractor 只取最大一块，
    「元」「兆」这种字身分成几块的就量歪）；扁而落在字身左右范围内的算字自己的横画，不算。"""
    if patch is None or patch.size == 0:
        return 0.0
    import cv2
    b = (patch < BIN_THR).astype(np.uint8)
    total = int(b.sum())
    if total == 0:
        return 0.0
    h, _w = b.shape
    band = max(2, int(h * DEFECT_BAND))
    n, _, st, _ = cv2.connectedComponentsWithStats(b, 8)
    if n <= 2:
        return 0.0
    edge = [k for k in range(1, n) if st[k, 1] + st[k, 3] <= band or st[k, 1] >= h - band]
    body = [k for k in range(1, n) if k not in edge]
    if sum(int(st[k, 4]) for k in body) < BODY_MIN * total:
        return 0.0                                     # 墨多在上下带里（「二」「一」这种扁字）：分不出字身，不判
    bx0 = min(int(st[k, 0]) for k in body)
    bx1 = max(int(st[k, 0] + st[k, 2]) for k in body)
    by0 = min(int(st[k, 1]) for k in body)
    by1 = max(int(st[k, 1] + st[k, 3]) for k in body)
    def flat_in_body(k) -> bool:
        cx, _cy, cw, ch = (int(v) for v in st[k, :4])
        return cw >= STROKE_FLAT * ch and bx0 <= cx + cw / 2 <= bx1

    strokes = [k for k in edge if flat_in_body(k)]

    def same_row(k) -> bool:
        """和某条横画同一行（纵向重叠过半）：横画磨断成几截，断下来的那截不扁也算横画。"""
        y0, y1 = int(st[k, 1]), int(st[k, 1] + st[k, 3])
        return any(min(y1, int(st[j, 1] + st[j, 3])) - max(y0, int(st[j, 1])) >= 0.5 * (y1 - y0) for j in strokes)

    best = 0.0
    for k in edge:
        cx, cy, cw, ch, area = (int(v) for v in st[k])
        top = cy + ch <= band
        gap = (by0 - (cy + ch)) if top else (cy - by1)
        if gap <= EDGE_BLOB_GAP * h or k in strokes or same_row(k):
            continue                                   # 贴着字身，或是字自己的横画
        best = max(best, area / total)
    return float(best)


def patch_shape(patch: np.ndarray | None) -> dict:
    """一块字块的形状量：墨高、墨宽、墨像素数，及 extractor 的缺陷连续量（rule_bar／edge_blob／frame_bars／x_gap）。"""
    if patch is None or patch.size == 0:
        return {"h": None, "w": 0, "ink": 0, "rule_bar": 0.0, "edge_blob": 0.0, "blob": 0.0, "frame_bars": 0, "x_gap": 0.0}
    from .extractor import _defect_features
    f = _defect_features(patch)
    return {"h": ink_h(patch), "w": ink_w(patch), "ink": int((patch < BIN_THR).sum()),
            "rule_bar": float(f["rule_bar"]), "edge_blob": float(f["edge_blob"]), "blob": residue_blob(patch),
            "frame_bars": int(f["frame_bars"]), "x_gap": float(f["x_gap"])}


# ── 原图上量的（格框以外）─────────────────────────────────────────────

def medium_dots(gray: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """整页中等墨点（面积 OCC_AREA_MIN～OCC_AREA_MAX 的连通块）的质心 (xs, ys)，左上原点（occlusion `cell_densities` 同口径）。"""
    import cv2
    b = (gray < BIN_THR).astype(np.uint8)
    _n, _lab, st, cen = cv2.connectedComponentsWithStats(b, connectivity=8)
    a = st[:, cv2.CC_STAT_AREA]
    keep = (a >= OCC_AREA_MIN) & (a <= OCC_AREA_MAX)
    keep[0] = False
    pts = cen[keep]
    return pts[:, 0].astype(int), pts[:, 1].astype(int)


def dot_density(dots: tuple[np.ndarray, np.ndarray], bbox_page, shape: tuple[int, int]) -> float | None:
    """格框（`bbox_page`，右上原点）四周各扩半格，框里中等墨点个数 ÷ 面积 × 1e4。"""
    from ..core.anchor import to_cv
    H, W = shape
    x0, y0, x1, y1 = to_cv(bbox_page, W)
    w, h = x1 - x0, y1 - y0
    X0, X1 = int(max(0, x0 - OCC_GROW * w)), int(min(W, x1 + OCC_GROW * w))
    Y0, Y1 = int(max(0, y0 - OCC_GROW * h)), int(min(H, y1 + OCC_GROW * h))
    if X1 <= X0 or Y1 <= Y0:
        return None
    xs, ys = dots
    k = int(np.count_nonzero((ys >= Y0) & (ys < Y1) & (xs >= X0) & (xs < X1)))
    return float(k) / ((X1 - X0) * (Y1 - Y0)) * 1e4


def edge_ink(gray: np.ndarray, bbox_page, bottom: bool) -> float:
    """字块框靠版框那条边（列首上沿、列尾下沿）上下 [边-2, 边+3) 共 5 行、框宽以内的墨占比（seg_defect `edge_line_ink`
    的量法，改在原图上量）。"""
    from ..core.anchor import crop_patch
    x0, y0, x1, y1 = (float(v) for v in bbox_page)
    edge = (y1 - 1) if bottom else y0
    band = crop_patch(gray, (x0, edge - EDGE_ROWS, x1, edge + EDGE_ROWS + 1))
    return 0.0 if band is None or band.size == 0 else float((band < INK_THR).mean())


def seal_overlap(bbox_page, seals: Iterable) -> dict[str, float]:
    """格框与各类印外框的最大重叠 ÷ 格面积 {stain: …, crisp: …}（两者同在右上原点的规范空间；occlusion `seal_overlap_cells` 同口径）。"""
    gx0, gy0, gx1, gy1 = (float(v) for v in bbox_page)
    area = (gx1 - gx0) * (gy1 - gy0)
    out = {"stain": 0.0, "crisp": 0.0}
    if area <= 0:
        return out
    for s in seals:
        bx0, by0, bx1, by1 = s.bbox
        ov = max(0.0, min(gx1, bx1) - max(gx0, bx0)) * max(0.0, min(gy1, by1) - max(gy0, by0)) / area
        if s.kind in out and ov > out[s.kind]:
            out[s.kind] = ov
    return out


# ── 同字参照 ─────────────────────────────────────────────────────────

def same_char_refs(items: Iterable[tuple[str, bool, int | None, int, int]], min_ref: int) -> dict:
    """(字, 是否夹注, 墨高, 字块宽, 墨宽) 的列表 → {(字, 是否夹注): (墨高中位, 宽中位, 个数, 墨宽中位)}，不够 `min_ref` 个的不给。"""
    acc: dict[tuple[str, bool], list[tuple[int, int, int]]] = {}
    for ch, sub, h, w, iw in items:
        if ch and h:
            acc.setdefault((ch, sub), []).append((h, w, iw))
    return {k: (statistics.median(x[0] for x in v), statistics.median(x[1] for x in v), len(v),
                statistics.median(x[2] for x in v))
            for k, v in acc.items() if len(v) >= max(1, min_ref)}


def slot_period(recs) -> float:
    """没有 Step3 格高时的退路：本列整字格中心间距 ÷ 格号差的中位（char_index 的 `bbox_col`、`slot`）。量不出给 0。"""
    pts = sorted(((r.slot, (r.bbox_col[1] + r.bbox_col[3]) / 2) for r in recs if not r.sub and r.slot > 0))
    d = [(b[1] - a[1]) / (b[0] - a[0]) for a, b in zip(pts, pts[1:]) if b[0] > a[0]]
    return float(statistics.median(d)) if d else 0.0


# ── 打分 ─────────────────────────────────────────────────────────────

def score_cell(patch: np.ndarray | None, shape: dict, *, flags: Iterable[str] = (), end: str | None = None,
               height: float = 0.0, sub: bool = False, period: float = 0.0, merge_base: float = 0.0,
               ref: tuple | None = None, seam_ink: int | None = None, stain_page: bool = False,
               edge: float | None = None, density: float | None = None, seal_ov: dict | None = None,
               page_ink_med: float = 0.0, conf3a: float | None = None) -> tuple[dict[str, float], dict]:
    """一格 → ({键: 原始分}, evidence)。

    `shape`：`patch_shape(patch)`；`end`：列首 "top"／列尾 "bottom"／列中 None；`height`：char_index 的字框高；
    `period`：本列格高；`merge_base`：并格判的基准高（整字＝格高，夹注＝本列夹注半格墨高中位）；
    `ref`：同字参照（`same_char_refs` 的一项，没有为 None）；`seam_ink`：Step3 选中切线穿墨（本格上下两条取大）；
    `stain_page`：本页有大印（切线穿墨不判：印泥满纸噪点）；`edge`：`edge_ink`；`density`：`dot_density`；
    `seal_ov`：`seal_overlap`；`page_ink_med`：本页字块墨像素数中位；`conf3a`：3a 置信（same＝1，其余取首位相似度，没跑 None）。"""
    flags = list(flags or ())
    sub_scores: dict[str, dict[str, float]] = {k: {} for k in KEYS}
    ev: dict[str, dict] = {k: {} for k in KEYS}
    for f in flags:
        if f in FLAG_SCORES:
            k, s = FLAG_SCORES[f]
            sub_scores[k][f"flag:{f}"] = s
    h, w_ink = shape.get("h"), shape.get("w") or 0
    pw = int(patch.shape[1]) if patch is not None and patch.size else 0
    bottom = end == "bottom"

    # 同字对照的比值（列端才进分；列中只记证据：列中本来就有压扁的字，seg_defect 殿本 vol12 量过 18 格几乎全是好字）
    rh = rw = rwi = None
    if ref is not None and h and period and ref[0] >= SAME_FLAT * period and ref[0] > 0:
        rh = h / ref[0]
        rw = (pw / ref[1]) if ref[1] else None
        rwi = (w_ink / ref[3]) if len(ref) > 3 and ref[3] else None
    same_ev = {"rh": r4(rh), "rw": r4(rw), "rw_ink": r4(rwi), "n_ref": (ref[2] if ref is not None else 0)}

    # cut
    if end and rh is not None:
        s = lin(rh, 1.0, 1.0 - 2 * (1.0 - SAME_H))           # 0.80 → 0.5
        if rh < SAME_H_WIDE and rw is not None and rw / rh >= SAME_ASPECT:
            s = max(s, 0.5)
        sub_scores["cut"]["same_h"] = s
    if seam_ink is not None:
        if stain_page or "seal_region" in flags:
            ev["cut"]["seam_skipped"] = "seal"
        else:
            sub_scores["cut"]["seam"] = lin(seam_ink, 0, 2 * CLIP_SEAM_INK)
    ev["cut"].update({"end": end, **same_ev, "seam_ink": seam_ink, "edge_ink": r4(edge)})

    # border：列端的端区框线样（seg_defect 带框一侧）；字块里的满高竖条、满宽横条（extractor）
    sub_scores["border"]["rule_bar"] = lin(shape.get("rule_bar"), 0, 2 * RULE_BAR_INK)
    if int(shape.get("frame_bars") or 0) >= 2:
        sub_scores["border"]["frame_bars"] = 0.9
    if end and patch is not None and patch.size and (rh is None or rh >= FRAME_MIN_H):
        ds, k = end_debris(patch, bottom)
        sub_scores["border"]["end_debris"] = lin(ds, 0, 2 * FRAME_DEBRIS)
        eb = end_band(patch, bottom)
        sp = end_spread(patch, bottom)
        if eb is not None and eb[0] <= FRAME_GAP and (rw is None or rw >= SAME_FRAME_W):
            sub_scores["border"]["end_band"] = lin(eb[1], 0, 2 * FRAME_OVER)
        ev["border"].update({"debris": r4(ds), "debris_n": k, "band_gap": r4(eb[0]) if eb else None,
                             "band_over": r4(eb[1]) if eb else None, "spread": r4(sp)})
    ev["border"].update({"end": end, "rule_bar": r4(shape.get("rule_bar")), "frame_bars": int(shape.get("frame_bars") or 0),
                         "rw": r4(rw), "rw_ink": r4(rwi)})

    # residue
    sub_scores["residue"]["blob"] = lin(shape.get("blob"), 0, 2 * EDGE_BLOB_INK)
    # x_gap（左右两团墨的最大空隙，extractor 疑似跨列）只记证据不进分：左右结构字（引、行、川）本来就大，vol02 量过
    ev["residue"].update({"blob": r4(shape.get("blob")), "edge_blob": r4(shape.get("edge_blob")),
                          "x_gap": r4(shape.get("x_gap"))})

    # stain
    if density is not None:
        sub_scores["stain"]["density"] = lin(density, 0, 2 * OCC_DENSITY)
    if seal_ov:
        sub_scores["stain"]["seal"] = lin(seal_ov.get("stain", 0.0), 0, 2 * OCC_SEAL_OVERLAP)
        sub_scores["stain"]["crisp"] = lin(seal_ov.get("crisp", 0.0), 0, 2 * OCC_CRISP_OVERLAP)
    ev["stain"].update({"density": r4(density),
                        "seal_ov": r4((seal_ov or {}).get("stain")), "crisp_ov": r4((seal_ov or {}).get("crisp"))})

    # merged
    hr = (height / merge_base) if merge_base and height else None
    v = valley_split(patch, merge_base) if hr is not None and hr >= 1.0 else None
    if hr is not None:
        if v is not None:
            sub_scores["merged"]["valley"] = lin(hr, 1.0, 1.0 + 2 * (MERGED_H - 1.0))
        elif not sub:
            sub_scores["merged"]["tall"] = lin(hr, 1.0, 1.0 + 2 * (MERGED_TALL_H - 1.0))
    ev["merged"].update({"h_ratio": r4(hr), "valley": list(v) if v else None, "base": r4(merge_base)})

    # blank：墨少（相对本页字块）且 3a 不认得
    small = None
    ink = int(shape.get("ink") or 0)
    if page_ink_med > 0:
        small = lin(ink / page_ink_med, 0.5, 0.0)            # 墨量 ≤ 中位 1/4 → 0.5
        sub_scores["blank"]["small_ink"] = small * (1.0 - (conf3a or 0.0))
    ev["blank"].update({"ink_rel": r4(ink / page_ink_med) if page_ink_med > 0 else None, "conf3a": r4(conf3a)})

    scores: dict[str, float] = {}
    for k in KEYS:
        subs = {n: round(s, 4) for n, s in sub_scores[k].items()}
        scores[k] = max(subs.values(), default=0.0)
        ev[k]["sub"] = subs
    ev["flags"] = flags
    return scores, ev
