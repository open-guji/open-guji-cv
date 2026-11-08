"""整页拟合双边版框的内框细线（2026-11-04，Sheldon 定：整页统一认内框，线上的像素统一抹掉）。

## 为什么要整页拟合

殿本（新图源）是双边版框：外面一道粗框，往里十几像素一道细内框。字就写在细内框以内，列首、列尾的字常常
贴着它，甚至笔画压在线上。细内框印得淡、磨成虚线。

以前逐列、逐格判断「这一行像不像线」：要满宽、要有白行把线和字隔开、要不连着字身。线跟字一粘连，这三条
都不成立，碰着字脚的那一截就留在字块里（所、祖、八、父的撇脚，中、謂的竖脚）。

整页看就简单多了。外粗框又粗又满，整页拟得非常稳；内细线跟外框平行，离外框一样远。一张页上几十段
虚线一起投票，哪一段被字遮住、哪一段磨断了都不要紧。定下线位和线厚以后，线带（连同线外）的像素一律抹白，
不再问它连不连着字。

## 怎么拟

1. 在版框提示 y 附近的横带里，把文字块宽切成 CHUNK 像素宽的小段，每段算行墨占比，取墨占比 ≥ RUN_COV 的
   连续行段；
2. **外粗框**：每段里最厚（≥ OUTER_MIN_THICK 行）的行段，取它朝页心那一边，RANSAC 拟二次曲线
   （纸张微弯，允许一点弯度）；
3. **内细线**：外框朝页心一侧 INNER_MAX_GAP 格高以内、厚 1–INNER_MAX_THICK 行的薄段，量它离外框多远；
   离外框的距离按 x 的一次式 RANSAC 拟（两道线基本平行，最多差一点斜率），线心＝外框曲线减这个距离；
4. 质量：外框内点占小段的比例、内线有支持的小段比例，太低就认为本页没有可信的内框，返回 None。

纯看图、量东西：坐标是传进来那张图的像素坐标（x 向右、y 向下），不认识任何一套书。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

CHUNK = 12               # 小段宽（px）：比虚线的段长短，比笔画宽
RUN_COV = 0.5            # 小段内一行有这么多墨算「这行在线上」
OUTER_MIN_THICK = 5      # 外粗框的行段至少这么厚（新图源外框 7–10 行、内线 3–4 行）
INNER_MAX_THICK = 7      # 内细线的行段至多这么厚
INNER_MAX_GAP = 0.4      # 内细线离外框最多这么多格高
OUTER_TOL = 2.0          # 外框 RANSAC 内点容差（px）
INNER_TOL = 1.5          # 内线距离 RANSAC 内点容差（px）
INNER_MAX_SLOPE = 0.01   # 内线距外框的距离随 x 的斜率上限（基本平行）
MIN_OUTER_INLIER = 0.35  # 外框内点至少占小段这么多
MIN_INNER_SUPPORT = 0.2  # 内线至少在这么多小段上看得见
GAP_MAX_INK = 0.15       # 内线与外框之间那条白缝：各小段墨占比的中位数不过这么多
GAP_MIN_ROWS = 2         # 白缝至少这么多行
BLANK_ABOVE = 0.6        # 线朝页心这么多格高里几乎没墨的小段（行间空白、空格下）算「空段」
BLANK_INK = 0.01         # ……墨占比不过这么多
MIN_BLANK_HITS = 0.35    # 空段里至少这么多段看得见内线（末行字的底横只在字下，空段里没有）
MIN_BLANK_N = 5          # 空段不到这么多就不验
RANSAC_ITERS = 300
# profile_fallback（_profile_inner）
PF_GAP_INK = 0.05        # 白缝：整宽行墨占比不过这么多
PF_PEAK_MIN = 0.06       # 内线峰：整宽行墨占比至少这么多（点线）
PF_DROP = 0.7            # 峰往页心 INNER_MAX_THICK 行内墨要掉到峰值的这么多以下
PF_D_RANGE = (0.08, 0.24)  # 线心离外框（格高）：殿本新图 10 册 1348 页小段法拟出的 p10–p90 为 10–15 行（格高约 83）
PF_MIN_PRESENCE = 0.25   # 线带里有墨的小段至少占这么多
PF_SEGS = 6              # 细化线位时把宽度切这么多段
PF_REFINE = 5            # 各段在粗线位 ±这么多行里找峰
PF_REFINE_TOL = 2.0      # 各段线心离一次式超过这么多行的不算
PF_RULE_COV = 0.7        # rule_mask：线位以上那段里墨占这么多以上的像素列当界行／竖画剔掉
PF_THICK_PER_CELL = 0.11  # profile_fit2：整宽法线厚上限 = max(INNER_MAX_THICK, 这么多 × 格高)；殿本新图粗内线 8–12 行（格高约 111）


@dataclass(frozen=True)
class InnerFrameLine:
    """内框细线：线心 y(x) ＝ np.polyval(center, x)，线厚 thick（px）。"""
    side: str                    # "bottom" | "top"
    center: tuple[float, ...]    # 二次多项式系数（高次在前）
    thick: float
    outer_inlier: float          # 外框拟合内点比例
    support: float               # 内线有支持的小段比例
    x_range: tuple[int, int]
    via: str = "chunks"          # "chunks" 小段投票 | "profile" 整宽行墨（profile_fallback）
    knots: tuple[tuple[float, float], ...] | None = None
    """逐段贴线后的线心折线 ((x, y), …)，有就按它插值、不再用 center（`localize_inner_line`）。"""

    def y(self, x) -> np.ndarray:
        if self.knots:
            kx = np.array([k[0] for k in self.knots], float)
            ky = np.array([k[1] for k in self.knots], float)
            return np.interp(np.asarray(x, float), kx, ky)
        return np.polyval(np.asarray(self.center, float), np.asarray(x, float))

    def text_edge(self, x) -> np.ndarray:
        """线朝页心（字那边）的边沿 y：下框线取上沿，上框线取下沿。"""
        h = self.thick / 2.0
        return self.y(x) - h if self.side == "bottom" else self.y(x) + h


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    i, n = 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def _ransac_poly(x: np.ndarray, y: np.ndarray, deg: int, tol: float, rng: np.random.Generator,
                 max_slope: float | None = None) -> np.ndarray | None:
    best = None
    k = deg + 1
    if len(x) < k:
        return None
    for _ in range(RANSAC_ITERS):
        idx = rng.choice(len(x), k, replace=False)
        if len(set(x[idx].tolist())) < k:
            continue
        c = np.polyfit(x[idx], y[idx], deg)
        if max_slope is not None and deg == 1 and abs(c[0]) > max_slope:
            continue
        inl = np.abs(y - np.polyval(c, x)) <= tol
        if best is None or inl.sum() > best.sum():
            best = inl
    return best


def fit_inner_frame_line(ink: np.ndarray, x0: int, x1: int, y_hint: float, cell_h: float,
                         side: str = "bottom", seed: int = 0, profile_fallback: bool = False,
                         max_thick: float = INNER_MAX_THICK, seed_fallback: bool = False,
                         profile_fit2: bool = False) -> InnerFrameLine | None:
    """在二值墨图 `ink`（True＝墨）上拟一道内框细线。

    x0/x1：文字块左右（只在这段里量）；y_hint：版框大致的 y（Step1/2 给的，内线或外框都行）；
    cell_h：格高（定搜索带与距离上限）；side：下框 "bottom" / 上框 "top"。拟不出可信的线返回 None。
    profile_fallback：外框拟出来了、小段投票拟不出内线时，改按外框拉直的整宽行墨找内线（`_profile_inner`）。
    profile_fit2：（只下框）整宽法也拟不出时再试一次：线厚上限放到 PF_THICK_PER_CELL 格高、剔掉界行再量（`_profile_inner` 的
    max_thick／rule_mask），加空段验线，只补原先拟不出的页。上框试过：列首的抬头框、粗上框里拟出的线不可靠（vol95 p170），不开。
    seed_fallback：两法都拟不出时，按「薄段＋白缝＋外框」三件套量出的中位距离从外框平移出一道种子线（via="seed"），
    只给 `localize_inner_line` 当起点——它贴不上（返回原线、没有 knots）就不能用。"""
    h, w = ink.shape
    x0, x1 = max(0, int(x0)), min(w, int(x1))
    if side == "bottom":
        lo, hi = int(y_hint - 0.5 * cell_h), int(y_hint + 0.4 * cell_h)
    else:
        lo, hi = int(y_hint - 0.4 * cell_h), int(y_hint + 0.5 * cell_h)
    lo, hi = max(0, lo), min(h, hi)
    if x1 - x0 < 4 * CHUNK or hi - lo < 8:
        return None
    band = ink[lo:hi]
    chunks: list[tuple[float, list[tuple[int, int]]]] = []
    ox, oy = [], []
    for x in range(x0, x1 - CHUNK + 1, CHUNK):
        rr = [(s + lo, t + lo) for s, t in _runs(band[:, x:x + CHUNK].mean(axis=1) >= RUN_COV)]
        cx = x + CHUNK / 2.0
        chunks.append((cx, rr))
        thick = [r for r in rr if r[1] - r[0] >= OUTER_MIN_THICK]
        if thick:
            r = max(thick, key=lambda r: r[1] - r[0])
            ox.append(cx)
            oy.append(r[0] if side == "bottom" else r[1])     # 外框朝页心那一边
    if len(ox) < 8:
        return None
    rng = np.random.default_rng(seed)
    ox_a, oy_a = np.asarray(ox, float), np.asarray(oy, float)
    inl = _ransac_poly(ox_a, oy_a, 2, OUTER_TOL, rng)
    if inl is None or inl.sum() < MIN_OUTER_INLIER * len(chunks):
        return None
    outer = np.polyfit(ox_a[inl], oy_a[inl], 2)
    line = _chunk_inner(ink, chunks, outer, float(inl.mean()), x0, x1, cell_h, side, rng, max_thick=max_thick)
    if line is None and profile_fallback:
        line = _profile_inner(ink, outer, float(inl.mean()), x0, x1, cell_h, side)
        if line is None and profile_fit2 and side == "bottom":
            line = _profile_inner(ink, outer, float(inl.mean()), x0, x1, cell_h, side,
                                  max_thick=max(float(INNER_MAX_THICK), PF_THICK_PER_CELL * float(cell_h)), rule_mask=True)
    if line is None and seed_fallback:
        line = _seed_inner(chunks, outer, float(inl.mean()), x0, x1, cell_h, side, max_thick)
    return line


def _seed_inner(chunks: list, outer: np.ndarray, outer_inlier: float, x0: int, x1: int, cell_h: float,
                side: str, max_thick: float) -> InnerFrameLine | None:
    """种子线：各小段里紧挨外框（朝页心、隔着 ≥ GAP_MIN_ROWS 行白缝）的那道薄段，量线心离外框的距离，取中位数。
    内线断续、空段验线过不了的页（全唐文 010 p74 下框）用；字底横后面跟的是内线不是外框，量不进来。"""
    sign = 1.0 if side == "bottom" else -1.0
    ds, ts = [], []
    for cx, rr in chunks:
        o = float(np.polyval(outer, cx))
        if side == "bottom":
            above = [(s, t) for s, t in rr if t <= o - GAP_MIN_ROWS and o - t <= INNER_MAX_GAP * cell_h]
            r = max(above, key=lambda v: v[1]) if above else None
        else:
            below = [(s, t) for s, t in rr if s >= o + GAP_MIN_ROWS and s - o <= INNER_MAX_GAP * cell_h]
            r = min(below, key=lambda v: v[0]) if below else None
        if r is not None and 1 <= r[1] - r[0] <= max_thick:
            ds.append(sign * (o - (r[0] + r[1]) / 2.0))
            ts.append(r[1] - r[0])
    if len(ds) < LOCAL_MIN_OBS * len(chunks):
        return None
    center = np.asarray(outer, float).copy()
    center[2] -= sign * float(np.median(ds))
    return InnerFrameLine(side=side, center=tuple(float(v) for v in center), thick=float(np.median(ts)),
                          outer_inlier=outer_inlier, support=len(ds) / len(chunks), x_range=(x0, x1), via="seed")


def _chunk_inner(ink: np.ndarray, chunks: list, outer: np.ndarray, outer_inlier: float, x0: int, x1: int,
                 cell_h: float, side: str, rng: np.random.Generator,
                 max_thick: float = INNER_MAX_THICK) -> InnerFrameLine | None:
    """小段投票拟内线（上面第 3、4 步）：各小段的薄行段量离外框的距离，RANSAC 拟一次式；加白缝、空段两道护栏。"""
    h = ink.shape[0]
    sign = 1.0 if side == "bottom" else -1.0         # 距离朝页心为正
    cx_l, d_l, t_l = [], [], []
    for cx, rr in chunks:
        o = float(np.polyval(outer, cx))
        for s, t in rr:
            d = (o - t) if side == "bottom" else (s - o)
            if 1 <= d <= INNER_MAX_GAP * cell_h and 1 <= t - s <= max_thick:
                cx_l.append(cx)
                d_l.append(sign * (o - (s + t) / 2.0))      # 线心离外框的距离（朝页心为正）
                t_l.append(t - s)
    if len(cx_l) < 6:
        return None
    cx_a, d_a, t_a = np.asarray(cx_l, float), np.asarray(d_l, float), np.asarray(t_l, float)
    inl2 = _ransac_poly(cx_a, d_a, 1, INNER_TOL, rng, max_slope=INNER_MAX_SLOPE)
    if inl2 is None:
        return None
    support = len({float(v) for v in cx_a[inl2]}) / len(chunks)
    if support < MIN_INNER_SUPPORT:
        return None
    k, b = np.polyfit(cx_a[inl2], d_a[inl2], 1)
    center = np.asarray(outer, float).copy()
    center[1] -= sign * k
    center[2] -= sign * b
    thick = float(np.median(t_a[inl2]))
    # 内线与外框之间要隔着一条白缝。末行字的底横常落在差不多同一高度、也离外框十几行，拟线拟到字脚上时，
    # 它和外框之间夹着真正的内线（贴着外框、跟外框粘成一条粗段时认不出来），缝就不白
    fr = []
    for cx, _rr in chunks:
        o = float(np.polyval(outer, cx))
        c = float(np.polyval(center, cx))
        a, z = (int(np.ceil(c + thick / 2.0)) + 1, int(np.floor(o)) - 1) if side == "bottom" else \
            (int(np.ceil(o)) + 1, int(np.floor(c - thick / 2.0)) - 1)
        if z - a + 1 < GAP_MIN_ROWS:
            return None
        xi = int(cx - CHUNK / 2.0)
        fr.append(float(ink[max(0, a):min(h, z + 1), xi:xi + CHUNK].mean()))
    if not fr or float(np.median(fr)) > GAP_MAX_INK:
        return None
    # 真内线是整页横贯的，字与字之间、空格底下也有；末行字的底横只在字下。看「上面没字」的小段里线在不在
    hit_x = {float(v) for v in cx_a[inl2]}
    n_blank = n_hit = 0
    for cx, _rr in chunks:
        c = float(np.polyval(center, cx))
        a, z = (int(c - thick / 2.0 - BLANK_ABOVE * cell_h), int(c - thick / 2.0) - 2) if side == "bottom" else \
            (int(c + thick / 2.0) + 3, int(c + thick / 2.0 + BLANK_ABOVE * cell_h))
        xi = int(cx - CHUNK / 2.0)
        sub = ink[max(0, a):min(h, z + 1), xi:xi + CHUNK]
        if sub.size and float(sub.mean()) <= BLANK_INK:
            n_blank += 1
            n_hit += cx in hit_x
    if n_blank >= MIN_BLANK_N and n_hit < MIN_BLANK_HITS * n_blank:
        return None
    return InnerFrameLine(side=side, center=tuple(float(v) for v in center),
                          thick=thick, outer_inlier=outer_inlier,
                          support=float(support), x_range=(x0, x1))


def _straight_rows(ink: np.ndarray, outer: np.ndarray, x0: int, x1: int, n: int, side: str) -> np.ndarray:
    """按外框曲线拉直：第 d 行＝外框朝页心 d 行处、x0..x1 各像素的墨，形状 (n, x1-x0)。"""
    xs = np.arange(x0, x1)
    oy = np.polyval(outer, xs)
    out = np.empty((n, len(xs)), dtype=bool)
    for d in range(n):
        ys = np.clip(np.round(oy - d if side == "bottom" else oy + d).astype(int), 0, ink.shape[0] - 1)
        out[d] = ink[ys, xs]
    return out


def _peak_at(pr: np.ndarray, pk: int, lo_idx: int = 0, base: float = 0.0) -> tuple[int, int]:
    """峰 pk 的半高宽连续段 [a, b]；`base`：底子（半高量在底子与峰之间）。"""
    pv = pr[pk]
    half = base + (pv - base) / 2
    a = b = pk
    while a - 1 >= lo_idx and pr[a - 1] >= half:
        a -= 1
    while b + 1 < len(pr) and pr[b + 1] >= half:
        b += 1
    return a, b


def _profile_inner(ink: np.ndarray, outer: np.ndarray, outer_inlier: float, x0: int, x1: int,
                   cell_h: float, side: str, max_thick: float = INNER_MAX_THICK,
                   rule_mask: bool = False) -> InnerFrameLine | None:
    """整宽行墨找内线（2026-11-05，A22-2 列端评测集）：殿本新图约两成页的内线磨成点线，小段里一行墨占比
    到不了 RUN_COV，或空段里看不见，小段投票拟不出来；但外框拟得稳，把版面按外框拉直、整宽求每行墨占比，
    点线也在离外框固定距离（殿本 10–15 行）上叠出一个峰。

    1. 整宽行墨：离外框 PF_D_RANGE 格高内的局部峰里，外框与峰之间隔着白缝（≤ PF_GAP_INK）、峰够高
       （≥ PF_PEAK_MIN）、往页心 INNER_MAX_THICK 行内有个谷（墨掉到 PF_DROP 以下）的，取最高的那个当粗线位；
    2. 内线跟外框差一点斜率，整宽叠起来峰会变胖：把宽度切 PF_SEGS 段，各段在粗线位 ±PF_REFINE 行里找峰，
       半高宽超过 INNER_MAX_THICK 的段（线跟字脚连成片）不用，其余至少 3 段，线心按 x 拟一次式（与小段法同样
       允许 INNER_MAX_SLOPE），线厚取各段半高宽的中位数；
    3. 线带里有墨的小段至少 PF_MIN_PRESENCE（几个字脚对齐成不了这么宽）。

    `max_thick`：线厚上限（缺省 INNER_MAX_THICK）。`rule_mask`（cell_shrink.inner_frame_fit2）：线位以上那段里
    几乎整段是墨的像素列（界行、字的竖画）先剔掉再量行墨，各段的半高宽按「峰与线往页心那侧的谷」之间量——
    点线的峰只有 0.1–0.2，界行和字脚垫起来的底子就有 0.1，按 0 量半高宽量不出来（殿本 vol95 p19、p45）。"""
    n = int(INNER_MAX_GAP * cell_h)
    if n < 6:
        return None
    rows = _straight_rows(ink, outer, x0, x1, n, side)
    lo, hi = max(2, int(np.ceil(PF_D_RANGE[0] * cell_h))), min(n - 2, int(PF_D_RANGE[1] * cell_h))
    xs_all = np.arange(x0, x1)
    if rule_mask and n - hi > 4:
        keep_c = rows[hi + 1:].mean(axis=0) < PF_RULE_COV
        if keep_c.sum() >= 0.5 * len(keep_c):
            rows, xs_all = rows[:, keep_c], xs_all[keep_c]
    pr = rows.mean(axis=1)
    best = None
    for d in range(lo, hi + 1):
        pv = float(pr[d])
        if pv < PF_PEAK_MIN or pv < pr[d - 1] or pv < pr[d + 1]:
            continue
        a, _b = _peak_at(pr, d, 1)
        if a < 3 or float(pr[2:a].min()) > PF_GAP_INK:
            continue
        after = pr[d + 1:d + 1 + int(max_thick)]       # 线往里 max_thick 行内要有个谷（字脚可能紧跟着线）
        if after.size == 0 or float(after.min()) > PF_DROP * pv:
            continue
        if best is None or pv > best[1]:
            best = (d, pv)
    if best is None:
        return None
    c0 = best[0]
    w = rows.shape[1] // PF_SEGS
    xs_l, c_l, t_l = [], [], []
    for k in range(PF_SEGS):
        ps = rows[:, k * w:(k + 1) * w].mean(axis=1)
        a0, z0 = max(1, c0 - PF_REFINE), min(n - 1, c0 + PF_REFINE + 1)
        pk = a0 + int(np.argmax(ps[a0:z0]))
        if ps[pk] < PF_PEAK_MIN:
            continue
        base = float(ps[pk + 1:pk + 2 + int(max_thick)].min()) if rule_mask and pk + 1 < n else 0.0
        a, b = _peak_at(ps, pk, 1, base=min(base, 0.5 * float(ps[pk])))
        if b - a + 1 > max_thick:             # 这段线跟字脚连成一片，量不准，不用
            continue
        xs_l.append(float(xs_all[k * w:(k + 1) * w].mean()))
        c_l.append((a + b) / 2.0)
        t_l.append(b - a + 1)
    if len(xs_l) < 3:
        return None
    xa, ca = np.asarray(xs_l, float), np.asarray(c_l, float)
    keep = np.ones(len(xa), bool)
    for _ in range(2):
        kk, bb = np.polyfit(xa[keep], ca[keep], 1)
        res = np.abs(ca - (kk * xa + bb))
        keep = res <= PF_REFINE_TOL
        if keep.sum() < 3:
            return None
    kk, bb = np.polyfit(xa[keep], ca[keep], 1)
    if abs(kk) > INNER_MAX_SLOPE:
        return None
    thick = float(np.median(np.asarray(t_l, float)[keep]))
    if thick > max_thick:
        return None
    cm = kk * (x0 + x1) / 2.0 + bb
    if not (PF_D_RANGE[0] * cell_h <= cm <= PF_D_RANGE[1] * cell_h):
        return None
    sign = 1.0 if side == "bottom" else -1.0
    center = np.asarray(outer, float).copy()
    center[1] -= sign * kk
    center[2] -= sign * bb
    # 线带里有墨的小段比例（按拟好的线心逐列取线带）
    xs = np.arange(x0, x1)
    cy = np.polyval(center, xs)
    half = thick / 2.0 + 1.0
    hit = []
    for i in range(0, len(xs) - CHUNK + 1, CHUNK):
        ys0 = np.clip(np.round(cy[i:i + CHUNK] - half).astype(int), 0, ink.shape[0] - 1)
        ys1 = np.clip(np.round(cy[i:i + CHUNK] + half).astype(int) + 1, 0, ink.shape[0])
        hit.append(any(ink[ys0[j]:ys1[j], xs[i + j]].any() for j in range(CHUNK)))
    pres = float(np.mean(hit)) if hit else 0.0
    if pres < PF_MIN_PRESENCE:
        return None
    if rule_mask:
        # 放宽后容易把一排字脚当线（vol95 p46：字脚的碎墨排成一行，真内线淡到拟不出）：同小段法的空段验线——
        # 线朝页心 BLANK_ABOVE 格高里没字的小段（空格底下）也要看得见线
        n_blank = n_hit = 0
        for j, i in enumerate(range(0, len(xs) - CHUNK + 1, CHUNK)):
            c = float(cy[i + CHUNK // 2])
            a, z = (int(c - half - BLANK_ABOVE * cell_h), int(c - half) - 2) if side == "bottom" else \
                (int(c + half) + 3, int(c + half + BLANK_ABOVE * cell_h))
            sub = ink[max(0, a):min(ink.shape[0], z + 1), xs[i]:xs[i] + CHUNK]
            if sub.size and float(sub.mean()) <= BLANK_INK:
                n_blank += 1
                n_hit += bool(hit[j])
        if n_blank >= MIN_BLANK_N and n_hit < MIN_BLANK_HITS * n_blank:
            return None
    return InnerFrameLine(side=side, center=tuple(float(v) for v in center), thick=thick,
                          outer_inlier=outer_inlier, support=pres, x_range=(x0, x1), via="profile")


INNER_THICK_PER_CELL = 0.065
"""内线厚上限随格高放大（`inner_thick_limit`）：INNER_MAX_THICK 是按殿本新图（格高约 83）定的，全唐文格高约 205、
内线厚 5–12 行，固定 7 行时一半小段的内线被当成「太厚」不认，空段验线不过、整页拟不出（012 p58 上框、010 p166 下框）。"""


def inner_thick_limit(cell_h: float) -> float:
    """内线厚上限：max(INNER_MAX_THICK, INNER_THICK_PER_CELL × 格高)。"""
    return max(float(INNER_MAX_THICK), INNER_THICK_PER_CELL * float(cell_h))


LOCAL_REACH = 0.5        # 逐段贴线：离整页拟合线心这么多格高以内找本段的内线
LOCAL_WIN = 3            # 逐段贴线：残差取左右各这么多小段的中位数
LOCAL_TOL = 3.0          # ……离中位数超过这么多行的观测丢掉
LOCAL_GAP_TOL = 4.0      # ……缝宽离附近中位数超过这么多行的候选不认
LOCAL_GAP_WIN = 15       # ……附近＝左右这么多小段
LOCAL_GAP_DRIFT = 8.0    # ……附近中位数离全页中位数超过这么多行就不信、用全页的
LOCAL_MIN_OBS = 0.3      # 观测到的小段不到这么多就不贴、原样返回


def localize_inner_line(ink: np.ndarray, line: InnerFrameLine, cell_h: float,
                        max_thick: float = INNER_MAX_THICK) -> InnerFrameLine:
    """整页拟合的内线逐小段贴到本段真线上（cell_shrink `inner_frame_local`，2026-11-05 全唐文 S4）。

    整页拟合是「外框二次曲线 − 一次式距离」。外框在页边拐弯（全唐文 006 p121 右端外框上翘 40 行）、内线本身
    波浪起伏时，二次曲线跟不上，线心在页的一端落到外框上沿，内线整段漏抹，列尾字块挂着线（006:121:1:22「上」）。

    每个小段在拟合线心 ±LOCAL_REACH 格高里找：厚 1–max_thick 行的薄段，朝框外隔着白缝紧跟一道 ≥ OUTER_MIN_THICK
    行、且厚过 max_thick 的粗段（外框）。内线离外框的距离在页内很稳、只慢慢变（006 p121 左中右都是 31–32 行），所以先取
    各段候选里离拟合线最近那个的缝宽，按附近 ±LOCAL_GAP_WIN 段取中位数，只认缝宽与它差 LOCAL_GAP_TOL 行以内的——字的底横离外框远得多，认不成。观测线心减拟合线心得残差，
    左右 LOCAL_WIN 段取中位数、离群的丢掉，再按 x 线性插值成折线（两端取最近观测）。观测太少原样返回。"""
    h, w = ink.shape
    x0, x1 = line.x_range
    reach = LOCAL_REACH * cell_h
    gap_max = INNER_MAX_GAP * cell_h
    cands: list[tuple[float, float, list[tuple[float, float]]]] = []    # (cx, pred, [(线心, 缝宽)…])
    for x in range(x0, x1 - CHUNK + 1, CHUNK):
        cx = x + CHUNK / 2.0
        pred = float(line.y(cx))
        if line.side == "bottom":
            lo, hi = int(pred - reach), int(pred + reach + gap_max + 4 * OUTER_MIN_THICK)
        else:
            lo, hi = int(pred - reach - gap_max - 4 * OUTER_MIN_THICK), int(pred + reach)
        lo, hi = max(0, lo), min(h, hi)
        got: list[tuple[float, float]] = []
        if hi - lo >= 8:
            rr = [(s + lo, t + lo) for s, t in _runs(ink[lo:hi, x:x + CHUNK].mean(axis=1) >= RUN_COV)]
            for i, (s, t) in enumerate(rr):
                if not 1 <= t - s <= max_thick:
                    continue
                c = (s + t) / 2.0
                if abs(c - pred) > reach:
                    continue
                if line.side == "bottom":
                    nb = rr[i + 1] if i + 1 < len(rr) else None
                else:
                    nb = rr[i - 1] if i > 0 else None
                # 外框比内线厚得多；内线本身厚过 OUTER_MIN_THICK 时，「字横＋白缝＋内线」会冒充「内线＋白缝＋外框」（006:75:1:1 觀）
                if nb is None or nb[1] - nb[0] < max(OUTER_MIN_THICK, max_thick + 1):
                    continue
                g = (nb[0] - t) if line.side == "bottom" else (s - nb[1])
                if GAP_MIN_ROWS <= g <= gap_max:
                    got.append((c, float(g)))
        cands.append((cx, pred, got))
    n = len(cands)
    near = [min(got, key=lambda v: abs(v[0] - pred))[1] for _cx, pred, got in cands if got]
    if not n or len(near) < LOCAL_MIN_OBS * n:
        return line
    near_x = np.array([cx for cx, _pred, got in cands if got], float)
    near_g = np.array(near, float)
    gap_all = float(np.median(near_g))
    obs_x, obs_r = [], []
    for cx, pred, got in cands:
        # 缝宽在页内会慢慢变（006 p75 左 39 行、右 34 行）：取附近 ±LOCAL_GAP_WIN 段的中位数
        # 内线整段断掉的地方附近只剩字底横当候选，局部中位数会被带偏（010 p166 x≈1700–1950 内线缺、字底横离外框 70 行），
        # 局部值离全页中位数超过 LOCAL_GAP_DRIFT 行就用全页的
        m = np.abs(near_x - cx) <= LOCAL_GAP_WIN * CHUNK
        gap0 = float(np.median(near_g[m])) if m.any() else gap_all
        if abs(gap0 - gap_all) > LOCAL_GAP_DRIFT:
            gap0 = gap_all
        ok = [c for c, g in got if abs(g - gap0) <= LOCAL_GAP_TOL]
        if ok:
            obs_x.append(cx)
            obs_r.append(min(ok, key=lambda c: abs(c - pred)) - pred)
    if len(obs_x) < LOCAL_MIN_OBS * n:
        return line
    ox, orr = np.asarray(obs_x), np.asarray(obs_r)
    keep = np.zeros(len(ox), bool)
    med = np.zeros(len(ox))
    for i in range(len(ox)):
        a, b = max(0, i - LOCAL_WIN), min(len(ox), i + LOCAL_WIN + 1)
        med[i] = float(np.median(orr[a:b]))
        keep[i] = abs(orr[i] - med[i]) <= LOCAL_TOL
    if keep.sum() < LOCAL_MIN_OBS * n:
        return line
    kx = ox[keep]
    xs = np.arange(x0, x1 + CHUNK, CHUNK, dtype=float)
    ys = line.y(xs) + np.interp(xs, kx, med[keep])
    return InnerFrameLine(side=line.side, center=line.center, thick=line.thick, outer_inlier=line.outer_inlier,
                          support=line.support, x_range=line.x_range, via=line.via + "+local",
                          knots=tuple((float(a), float(b)) for a, b in zip(xs, ys)))
