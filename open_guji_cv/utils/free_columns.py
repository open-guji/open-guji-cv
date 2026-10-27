"""自由版式 Step2：块内找列（无界行），产每列的左右缝（逐行 x，块内坐标）。

做法（一块一块做，块由 `free_blocks` 或人标给出）：

1. **剪切校斜**：在 ±3% 斜率里找让竖投影最「尖」（相邻差平方和最大）的剪切量——
   刻本整版略斜，列是斜的；拉直后投影的列间谷才清楚。
2. **列距**：投影自相关的峰里，取「不弱于最强峰 0.6 倍」的最小那个。最强峰常落在
   两倍列距上（大字列与小注列交替），取最小的够强峰避开倍频。
3. **列数**：人标给了就用；没给就在「块宽 ÷ 列距」±1 里挑平均切线墨量最小的。
4. **定直线**：DP 在投影上选 n+1 条切线，代价 = 切线处墨量 + 列宽偏离列距的平方罚。
   不要求等宽——标题列、表格列宽窄不一，罚得轻。
5. **变缝**：每条内部切线放回剪切前的斜线，在 ±0.18 列宽带里走最省墨竖缝
   （逐行最多挪 1px），绕开探进邻列的笔画。最外两条就用直线。

块里有竖线（界行、表格线）时先按竖线把块切成几段，各段分别做，竖线本身就是列界。

**有列距先验时走等宽网格（`grid_columns`，2026-10-27 起正文页的主路）**：坊刻本虽然界行
很浅、多半探不全，但一版里列宽非常一致（yxat 幼學段半叶 12 列、列距 110–120 px，杂字段
约 143）。列距由人按页段标（`layout_hints` 的 `pitch`），算法只做：

1. 代价 = 竖投影墨量（先抠掉细长竖线，界行本身不算墨）− 细竖线强度（浅界行是好切线）；
2. DP 选 n+1 条切线：列宽偏离列距的平方罚（宽松到 ±20%，容纸面弯曲带来的列宽渐变），
   两端浮动、但切线外剩下的墨按「漏了几列」计罚——于是网格自己落在正文上，不吞版心；
3. n 在「块宽 ÷ 列距」±1 里挑总代价最小的；人给了列数就只用它；
4. 内部切线在 ±8% 列距带里走最省墨竖缝。

不给列距时退回上面的自估（自相关列距常落到两倍，见设计文档）。
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


def shear(img: np.ndarray, s: float) -> np.ndarray:
    """x' = x − s·(y − h/2)：把斜率 s（dx/dy）的竖列拉直。"""
    h, w = img.shape
    M = np.float32([[1, -s, s * h / 2], [0, 1, 0]])
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)


def best_shear(ink: np.ndarray, rng: float = 0.03, step: float = 0.0025) -> float:
    u = ink.astype(np.uint8)
    best_s, best_sc = 0.0, -1.0
    for s in np.arange(-rng, rng + 1e-9, step):
        f = shear(u, float(s)).sum(0).astype(np.float64)
        sc = float(np.sum(np.diff(f) ** 2))
        if sc > best_sc:
            best_s, best_sc = float(s), sc
    return best_s


def smooth(f: np.ndarray, sigma: float) -> np.ndarray:
    k = int(3 * sigma) * 2 + 1
    return cv2.GaussianBlur(f.reshape(1, -1).astype(np.float32), (k, 1), sigma).ravel()


def estimate_pitch(profile: np.ndarray, lo: int, hi: int, rel: float = 0.6) -> int | None:
    g = profile - profile.mean()
    ac = np.correlate(g, g, "full")[len(g) - 1:]
    ac = ac / (ac[0] + 1e-9)
    hi = min(hi, len(ac) - 2)
    if hi <= lo:
        return None
    peaks = [x for x in range(lo, hi) if ac[x] > ac[x - 1] and ac[x] >= ac[x + 1] and ac[x] > 0.05]
    if not peaks:
        return None
    top = max(ac[x] for x in peaks)
    return int(min(x for x in peaks if ac[x] >= rel * top))


def dp_cuts(profile: np.ndarray, n: int, pitch: float, reg: float = 1.0,
            end_slack: float = 0.45) -> tuple[list[int], float]:
    """在 [0, L) 上选 n+1 条切线，返回 (切线 x 升序, 总代价)。首末切线可在两端 end_slack 列距内浮动。"""
    L = len(profile)
    cost = profile / (float(np.percentile(profile, 90)) + 1e-6)
    lo_w, hi_w = max(1, int(0.45 * pitch)), max(2, int(1.8 * pitch))
    e = max(1, int(end_slack * pitch))
    INF = 1e18
    D = np.full((n + 1, L), INF)
    P = np.zeros((n + 1, L), int)
    D[0, :e + 1] = cost[:e + 1]
    for k in range(1, n + 1):
        for x in range(L):
            a, b = max(0, x - hi_w), x - lo_w
            if b < a:
                continue
            gaps = x - np.arange(a, b + 1)
            tot = D[k - 1, a:b + 1] + reg * ((gaps - pitch) / pitch) ** 2
            j = int(np.argmin(tot))
            D[k, x] = tot[j] + cost[x]
            P[k, x] = a + j
    tail = np.arange(max(0, L - 1 - e), L)
    x = int(tail[np.argmin(D[n, tail])])
    total = float(D[n, x])
    cuts = [x]
    for k in range(n, 0, -1):
        x = int(P[k, x])
        cuts.append(x)
    return cuts[::-1], total


def min_ink_seam(ink: np.ndarray, x_line: np.ndarray, band: int, move: int = 1) -> np.ndarray:
    """竖向最省墨缝：第 y 行的 x 在 x_line[y] ± band 内，相邻行最多挪 move px。返回逐行 x。"""
    h, w = ink.shape
    c = ink.astype(np.float32)
    off = np.arange(-band, band + 1)
    nb = len(off)
    base = np.round(x_line).astype(int)

    def row_cost(y: int) -> np.ndarray:
        xs = np.clip(base[y] + off, 0, w - 1)
        return c[y, xs] + 0.002 * np.abs(off)          # 同等墨量时偏向直线

    D = row_cost(0)
    P = np.zeros((h, nb), np.int16)
    idx = np.arange(nb)
    for y in range(1, h):
        best = np.full(nb, np.inf, np.float32)
        arg = np.zeros(nb, np.int16)
        for d in range(-move, move + 1):
            sh = np.roll(D, d)
            if d > 0:
                sh[:d] = np.inf
            elif d < 0:
                sh[d:] = np.inf
            m = sh < best
            best[m] = sh[m]
            arg[m] = (idx - d)[m]
        D = best + row_cost(y)
        P[y] = arg
    i = int(np.argmin(D))
    path = [i]
    for y in range(h - 1, 0, -1):
        i = int(P[y, i])
        path.append(i)
    return base + off[np.array(path[::-1])]


@dataclass
class ColumnSeams:
    """一列（块内坐标）：逐行左右缝 x。"""
    left: np.ndarray
    right: np.ndarray


@dataclass
class BlockColumns:
    columns: list[ColumnSeams]          # 右→左（读序）
    shear: float
    pitch: float | None
    n_source: str                       # hint | auto | rule（竖线分段后各段自估）
    alt_n: list[int]                    # 自估时同样说得过去的其他列数（给人审看）


def _segment_columns(ink: np.ndarray, n: int | None, pitch_range: tuple[int, int],
                     seam_band: float) -> tuple[list[ColumnSeams], float, float | None, list[int]]:
    """一段（无竖线）→ 左→右的列。"""
    h, w = ink.shape
    s = best_shear(ink)
    prof = smooth(shear(ink.astype(np.uint8), s).sum(0).astype(np.float32), 3)
    pitch = estimate_pitch(smooth(prof, 6), *pitch_range)
    alt: list[int] = []
    if n is None:
        guess = max(1, round(w / pitch)) if pitch else 1
        scored = []
        for m in range(max(1, guess - 1), guess + 2):
            cuts, c = dp_cuts(prof, m, w / m)
            scored.append((c / (m + 1), m, cuts))
        scored.sort()
        _, n, cuts = scored[0]
        alt = [m for c, m, _ in scored[1:] if c <= 1.15 * scored[0][0]]
    else:
        cuts, _ = dp_cuts(prof, n, w / n)
    ys = np.arange(h)
    lines = [cx + s * (ys - h / 2) for cx in cuts]       # 剪切前坐标
    band = max(4, int(seam_band * w / n))
    seams = [np.clip(np.round(lines[0]).astype(int), 0, w - 1)]
    seams += [np.clip(min_ink_seam(ink, ln, band), 0, w - 1) for ln in lines[1:-1]]
    seams.append(np.clip(np.round(lines[-1]).astype(int), 0, w - 1))
    cols = [ColumnSeams(seams[i], seams[i + 1]) for i in range(len(seams) - 1)]
    return cols, s, (float(pitch) if pitch else None), alt


def block_columns(ink: np.ndarray, n: int | None = None, vrules: list[float] | None = None, *,
                  pitch_range: tuple[int, int] = (80, 300), seam_band: float = 0.18,
                  rule_pad: int = 6) -> BlockColumns:
    """块（ink 已裁到块）→ 列。`vrules` 是块内竖线 x（块内坐标）。"""
    h, w = ink.shape
    if not vrules:
        cols, s, pitch, alt = _segment_columns(ink, n, pitch_range, seam_band)
        return BlockColumns(cols[::-1], s, pitch, "hint" if n else "auto", alt)
    bounds = [0] + [int(x) for x in sorted(vrules)] + [w]
    cols: list[ColumnSeams] = []
    shears, pitches = [], []
    for a, b in zip(bounds[:-1], bounds[1:]):
        a2, b2 = (a + rule_pad if a > 0 else a), (b - rule_pad if b < w else b)
        if b2 - a2 < 0.6 * pitch_range[0]:          # 竖线与块边之间的窄条（双线框的夹缝）
            continue
        sub = ink[:, a2:b2]
        if not sub.any():
            continue
        # 段宽不足一个半列距的当一列，不再自估
        m = 1 if (b2 - a2) < 1.5 * pitch_range[0] else None
        seg, s, p, _ = _segment_columns(sub, m, pitch_range, seam_band)
        shears.append(s)
        if p:
            pitches.append(p)
        cols += [ColumnSeams(c.left + a2, c.right + a2) for c in seg]
    return BlockColumns(cols[::-1], float(np.median(shears)) if shears else 0.0,
                        float(np.median(pitches)) if pitches else None, "rule", [])


def split_vlines(ink: np.ndarray, length: int = 61) -> tuple[np.ndarray, np.ndarray]:
    """→ (去掉细长竖线的墨, 细长竖线)。界行、版心线是列界，不该算进列的墨量。"""
    u = ink.astype(np.uint8)
    vl = cv2.morphologyEx(u, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, length))) > 0
    vl = cv2.dilate(vl.astype(np.uint8), np.ones((1, 5), np.uint8)) > 0
    return ink & ~vl, vl


def dp_grid(cost: np.ndarray, mass: np.ndarray, n: int, pitch: float, *, reg: float = 4.0,
            cover: float = 1.0, width: tuple[float, float] = (0.8, 1.2),
            fixed_ends: bool = False) -> tuple[float, list[int]]:
    """n 列、列宽贴近 pitch 的 n+1 条切线（升序）。

    `cost` 已去中位（空白处为负）；`mass` 是墨量前缀和（长 L+1）。两端浮动时，第一条线左边、
    最后一条线右边剩下的墨按「相当于几列」× cover 计罚；`fixed_ends` 时两端就是块边（0 与 L−1）。
    返回 (总代价, 切线)。"""
    L = len(cost)
    colm = mass[-1] / max(n, 1) + 1e-6
    lo, hi = max(1, int(width[0] * pitch)), int(width[1] * pitch) + 1
    INF = 1e18
    if fixed_ends:
        D = np.full(L, INF)
        D[0] = 0.0
    else:
        D = cost + cover * mass[:L] / colm
    P = np.zeros((n + 1, L), int)
    for k in range(1, n + 1):
        N = np.full(L, INF)
        for x in range(lo, L):
            a, b = max(0, x - hi), x - lo
            g = x - np.arange(a, b + 1)
            t = D[a:b + 1] + reg * ((g - pitch) / pitch) ** 2
            j = int(np.argmin(t))
            N[x] = t[j] + (0.0 if fixed_ends and k == n else cost[x])
            P[k, x] = a + j
        D = N
    if fixed_ends:
        x = L - 1
        best = float(D[x])
    else:
        tot = D + cover * (mass[-1] - mass[:L]) / colm
        x = int(np.argmin(tot))
        best = float(tot[x])
    cuts = [x]
    for k in range(n, 0, -1):
        x = int(P[k, x])
        cuts.append(x)
    return best, cuts[::-1]


def grid_columns(ink: np.ndarray, lines: np.ndarray, *, pitch: float | None, n: int | None,
                 spine: str | None = None, spine_margin: int = 150, line_bonus: float = 3.0,
                 line_full: float = 0.05, reg: float = 4.0, cover: float = 1.0,
                 seam_band: float = 0.08, width: tuple[float, float] = (0.8, 1.2),
                 fixed_ends: bool = False, gap_sigma: float = 0.0) -> BlockColumns:
    """块（ink、lines 已裁到块）→ 等宽网格的列。`lines` 是 `free_blocks.thin_vlines` 的细竖线强度。

    `spine`：块的这一侧可能还带着没裁掉的版心（版心线没探到），那一侧 spine_margin 内的墨
    不要求被网格盖住。pitch、n 至少给一个；只给 n 时 pitch 取「块宽 ÷ n」。
    `width` 是列宽相对 pitch 的上下限：正文列很齐（0.8–1.2）；界栏不规律的列宽不齐、标题列窄，放到 0.5–1.2。
    `fixed_ends`：两端就是块边（版框内沿、版心线；本书左右不留白），只找内部切线，列宽 ≈ 块宽 ÷ n。
    `gap_sigma`（× pitch）：切线代价先按这么宽抹平——列间空白抹平后最低点在空白正中；
    双行小注两行之间的窄缝、字里的空隙抹平后就不低了，切线不会落进去。"""
    h, w = ink.shape
    body, _ = split_vlines(ink)
    s = best_shear(body)
    prof = smooth(shear(body.astype(np.uint8), s).sum(0).astype(np.float32), 2) / max(h, 1)
    lp = shear(np.clip(lines * 255, 0, 255).astype(np.uint8), s).mean(0) / 255.0
    raw = prof / (float(np.percentile(prof, 90)) + 1e-6) - line_bonus * np.clip(lp / line_full, 0, 1)
    if gap_sigma > 0:
        raw = smooth(raw, max(1.0, gap_sigma * (pitch or w / float(n or 1))))
    cost = raw - float(np.median(raw))
    pm = prof.copy()
    if spine == "left":
        pm[:spine_margin] = 0
    elif spine == "right":
        pm[-spine_margin:] = 0
    mass = np.r_[0.0, np.cumsum(pm)]
    if pitch is None:
        pitch = w / float(n)
    cands = [n] if n else list(range(max(1, int(w / pitch) - 1), int(w / pitch) + 2))
    best: tuple[float, int, list[int]] | None = None
    for m in cands:
        pm_ = w / float(m) if fixed_ends else pitch   # 两端定死：列距按列数回算（块宽 ÷ 列数）
        if m * width[0] * pm_ > w:
            continue
        tot, cuts = dp_grid(cost, mass, m, pm_, reg=reg, cover=cover, width=width, fixed_ends=fixed_ends)
        if fixed_ends:                              # 两端不计价：比内部切线的平均代价，不偏向多切
            tot /= max(1, m - 1)
        if best is None or tot < best[0]:
            best = (tot, m, cuts)
    if best is None:                                # 块比一列还窄
        best = (0.0, 1, [0, w - 1])
    _, m, cuts = best
    if fixed_ends:
        pitch = w / float(m)
    ys = np.arange(h)
    lines_x = [cx + s * (ys - h / 2) for cx in cuts]
    band = max(3, int(seam_band * pitch))
    seams = [np.clip(np.round(lines_x[0]).astype(int), 0, w - 1)]
    seams += [np.clip(min_ink_seam(body, ln, band), 0, w - 1) for ln in lines_x[1:-1]]
    seams.append(np.clip(np.round(lines_x[-1]).astype(int), 0, w - 1))
    if fixed_ends:                                  # 块边是竖的，不随剪切斜
        seams[0], seams[-1] = np.zeros(h, int), np.full(h, w - 1)
    cols = [ColumnSeams(seams[i], seams[i + 1]) for i in range(len(seams) - 1)]
    return BlockColumns(cols[::-1], s, float(pitch), "hint" if n else "grid", [c for c in cands if c != m])


def rule_breaks(hlines: np.ndarray, x0: int, x1: int, y0: int, y1: int, *, frac: float = 0.5,
                merge: int = 30, edge: int = 25) -> list[int]:
    """有界栏的一列 [x0,x1)×[y0,y1) 里的横界栏 → 断开处 y（页面坐标，自上而下）。

    `hlines` 是 `free_blocks.rule_hlines` 的横界栏图（0/1）。某行界栏像素盖住列宽 ≥ frac 就算一道，
    挨着的几行并成一条取中；贴着列上下端 edge 以内的不要（那是块边的栏线）。"""
    if x1 - x0 < 4 or y1 - y0 <= 2 * edge:
        return []
    cov = hlines[y0:y1, x0:x1].mean(1)
    groups: list[list[int]] = []
    for y in np.flatnonzero(cov >= frac):
        if groups and y - groups[-1][-1] <= merge:
            groups[-1].append(int(y))
        else:
            groups.append([int(y)])
    mids = [int(round(np.mean(g))) for g in groups]
    return [y0 + m for m in mids if edge <= m <= y1 - y0 - edge]
