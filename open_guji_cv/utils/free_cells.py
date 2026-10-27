"""自由版式 Step3：一列 → 字框。列内先分区，再在每区里按字线切字。

列里可能交替出现三种区：

| 区 | 样子 | 怎么切 |
|---|---|---|
| big  大字 | 一个字占满列宽 | 一条字线，字高按本区墨宽估（字近方） |
| note 双行小注 | 左右两条小字线并排，中间有竖缝 | 先走最省墨竖缝分右/左两线，各自切；读序右线先 |
| solo 单行小注 | 只有一条小字线（注文收尾落单） | 一条字线，字高按本区墨宽估 |

分区用逐行两个特征＋Viterbi（换区有罚），不靠一堆阈值后处理：
- gap：以本行为中心、高 em_small 的窗里，列中段最空竖缝的墨量；
- ext：以本行为中心、高 2·em_small 的窗里，墨的横向跨度（占列宽）。

字线切字（`cut_line`）是一个小 DP：在行墨量上选切点，代价 = 切点墨量 + 字高偏离 em 的平方罚
＋每字一个小常数（防止碎切）。不假定每列字数。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .free_columns import min_ink_seam

ZONE_KINDS = ("big", "note", "solo")
CELL_KINDS = ("char", "jiazhu_a", "jiazhu_b", "jiazhu_solo")   # 与刻本链 cells 的 kind 同名


def straighten(ink: np.ndarray, left: np.ndarray, right: np.ndarray, pad: int = 2
               ) -> tuple[np.ndarray, np.ndarray]:
    """左右缝之间的像素逐行平移到左对齐 → (列图 h×wc, 每行左缝 x)。缝外清白。"""
    h, w = ink.shape
    L = np.clip(left - pad, 0, w - 1)
    R = np.clip(right + pad, 0, w - 1)
    wc = int(np.max(R - L)) + 1
    out = np.zeros((h, wc), bool)
    for y in range(h):
        seg = ink[y, L[y]:R[y] + 1]
        out[y, :len(seg)] = seg
    return out, L


def zone_costs(cimg: np.ndarray, em_small: float, span: tuple[float, float] = (0.25, 0.75),
               solo_hi: float = 0.66, big_lo: float = 0.76) -> np.ndarray:
    """逐行三种区的代价（h×3，列序同 ZONE_KINDS；越小越像）。无墨行全 0，交给前后文。"""
    h, wc = cimg.shape
    cs = np.vstack([np.zeros((1, wc)), np.cumsum(cimg, 0)])
    a0 = int(span[0] * wc)
    a1 = max(a0 + 1, int(span[1] * wc))
    w1, w2 = max(2, int(em_small / 2)), max(3, int(em_small))
    C = np.zeros((h, 3))
    has = cimg.any(1)
    for y in range(h):
        if not has[y]:
            continue
        ya, yb = max(0, y - w1), min(h, y + w1 + 1)
        col = cs[yb] - cs[ya]
        sm = np.convolve(col, np.ones(3) / 3, "same")
        x = a0 + int(np.argmin(sm[a0:a1]))
        tot = col.sum() + 1e-6
        gap = sm[x] / (yb - ya)
        both = min(col[:x].sum(), col[x + 1:].sum()) / tot
        ya, yb = max(0, y - w2), min(h, y + w2 + 1)
        col2 = cs[yb] - cs[ya]
        nz = np.where(col2 > 0.03 * (yb - ya))[0]
        ext = (nz[-1] - nz[0] + 1) / wc if len(nz) else 0.0
        C[y, 0] = min(3.0, max(0.0, (big_lo - ext) / 0.06)) + (1.0 if gap < 0.01 and both > 0.25 else 0.0)
        C[y, 1] = min(3.0, gap / 0.02) + (2.0 if both < 0.2 else 0.0)
        C[y, 2] = min(3.0, max(0.0, (ext - solo_hi) / 0.06))
    return C


def viterbi(C: np.ndarray, switch: float) -> np.ndarray:
    h, k = C.shape
    D = C[0].copy()
    P = np.zeros((h, k), int)
    for y in range(1, h):
        move = D.min() + switch
        P[y] = np.where(D <= move, np.arange(k), int(D.argmin()))
        D = np.minimum(D, move) + C[y]
    lab = np.zeros(h, int)
    lab[-1] = int(D.argmin())
    for y in range(h - 1, 0, -1):
        lab[y - 1] = P[y, lab[y]]
    return lab


def zones(cimg: np.ndarray, em_small: float, switch_frac: float = 0.8) -> list[tuple[str, int, int]]:
    """列图 → [(区类, y0, y1)]，段界收紧到墨。"""
    lab = viterbi(zone_costs(cimg, em_small), switch_frac * em_small)
    has = cimg.any(1)
    out = []
    s = 0
    for i in range(1, len(lab) + 1):
        if i == len(lab) or lab[i] != lab[s]:
            ys = np.where(has[s:i])[0]
            if len(ys):
                out.append((ZONE_KINDS[lab[s]], s + int(ys[0]), s + int(ys[-1]) + 1))
            s = i
    return out


def cut_line(prof: np.ndarray, em: float, lo: float = 0.55, hi: float = 1.45,
             lam: float = 1.5, item_cost: float = 0.15) -> list[tuple[int, int]]:
    """一条字线按行墨量切字 → [(y0, y1)]（收紧到墨）。"""
    ys = np.where(prof > 0)[0]
    if len(ys) == 0:
        return []
    a, b = int(ys[0]), int(ys[-1]) + 1
    p = prof[a:b].astype(np.float64)
    n = len(p)
    cost = p / (float(np.percentile(p[p > 0], 75)) + 1e-6)
    hmin, hmax = max(3, int(lo * em)), int(hi * em) + 1
    INF = 1e18
    D = np.full(n + 1, INF)
    P = np.zeros(n + 1, int)
    D[0] = 0.0
    for x in range(1, n + 1):
        j0 = max(0, x - hmax)
        j1 = x - 2 if x == n else x - hmin              # 末字允许偏短（列尾残字）
        best, arg = INF, -1
        for j in range(j0, max(j0, j1) + 1):
            if D[j] >= INF:
                continue
            c = D[j] + lam * ((x - j - em) / em) ** 2 + item_cost + (cost[x] if x < n else 0.0)
            if c < best:
                best, arg = c, j
        D[x], P[x] = best, arg
    if D[n] >= INF:
        return [(a, b)]
    cuts = [n]
    x = n
    while x > 0:
        x = int(P[x])
        cuts.append(x)
    cuts = cuts[::-1]
    out = []
    for i in range(len(cuts) - 1):
        y0, y1 = cuts[i] + a, cuts[i + 1] + a
        nz = np.where(prof[y0:y1] > 0)[0]
        if len(nz):
            out.append((y0 + int(nz[0]), y0 + int(nz[-1]) + 1))
    return out


def split_note(sub: np.ndarray) -> np.ndarray:
    """双行小注区 → 逐行右/左分界 x（列中段最空处起，走最省墨竖缝）。"""
    h, wc = sub.shape
    a0, a1 = int(0.25 * wc), max(int(0.25 * wc) + 1, int(0.75 * wc))
    sm = np.convolve(sub.sum(0).astype(float), np.ones(3) / 3, "same")
    x0 = a0 + int(np.argmin(sm[a0:a1]))
    return np.clip(min_ink_seam(sub, np.full(h, float(x0)), max(2, int(0.12 * wc))), 0, wc - 1)


@dataclass
class Cell:
    """列图坐标（straighten 之后）。"""
    y0: int
    y1: int
    x0: int
    x1: int
    kind: str
    zone: int          # 第几区（从 0 起）
    ink: int


def _ink_width(sub: np.ndarray) -> float | None:
    cs = np.cumsum(sub.sum(0))
    if cs[-1] <= 0:
        return None
    xa, xb = np.searchsorted(cs, 0.03 * cs[-1]), np.searchsorted(cs, 0.97 * cs[-1])
    return float(xb - xa + 1)


def segment_column(cimg: np.ndarray, *, small_em: float | None = None, big_ratio: float = 1.45,
                   min_ink_frac: float = 0.03) -> list[Cell]:
    """列图 → 读序的字框。

    `small_em`：本页小字的字身（页上双行小注字线墨宽的中位，由调用方先算一遍给出）。
    单行区的墨宽 > big_ratio × small_em 算大字，否则单行小注；不给就按列宽 0.36 估。
    墨量 < min_ink_frac × em² 的项（零星墨点凑成的）不出字框。"""
    h, wc = cimg.shape
    em_small = 0.5 * wc
    ref_small = small_em or 0.36 * wc
    cells: list[Cell] = []

    def emit(img: np.ndarray, y0: int, a: int, b: int, kind: str, zi: int, em: float) -> None:
        part = img[a:b]
        xs = np.where(part.any(0))[0]
        if len(xs) == 0:
            return
        ink = int(part.sum())
        if ink < min_ink_frac * em * em:
            return
        cells.append(Cell(y0 + a, y0 + b, int(xs[0]), int(xs[-1]) + 1, kind, zi, ink))

    for zi, (kind, y0, y1) in enumerate(zones(cimg, em_small)):
        sub = cimg[y0:y1]
        if kind == "note":
            sx = split_note(sub)
            right, left = sub.copy(), sub.copy()
            for y in range(len(sx)):
                right[y, :sx[y]] = False
                left[y, sx[y]:] = False
            for img, k in ((right, "jiazhu_a"), (left, "jiazhu_b")):
                em = _ink_width(img) or em_small
                em = float(np.clip(1.08 * em, 0.3 * wc, 0.7 * wc))
                for a, b in cut_line(img.sum(1), em):
                    emit(img, y0, a, b, k, zi, em)
        else:
            # 字身按本区墨宽估（字近方）：大字/单行小注判混了，字高也不至于离谱
            iw = _ink_width(sub)
            em = float(np.clip(1.08 * iw, 0.35 * wc, wc)) if iw else 0.92 * wc
            k = "char" if em > big_ratio * ref_small else "jiazhu_solo"
            for a, b in cut_line(sub.sum(1), em):
                emit(sub, y0, a, b, k, zi, em)
    return cells


def note_line_width(cimg: np.ndarray) -> list[float]:
    """本列各双行小注区里每条字线的墨宽（给调用方算页级小字字身用）。"""
    wc = cimg.shape[1]
    out = []
    for kind, y0, y1 in zones(cimg, 0.5 * wc):
        if kind != "note":
            continue
        sub = cimg[y0:y1]
        sx = split_note(sub)
        right, left = sub.copy(), sub.copy()
        for y in range(len(sx)):
            right[y, :sx[y]] = False
            left[y, sx[y]:] = False
        for img in (right, left):
            w = _ink_width(img)
            if w:
                out.append(w)
    return out
