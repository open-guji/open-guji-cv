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

**混排栏**（大字夹双行小注，yxat 鳌头上栏、正文中栏）按字形认大字，不靠逐行特征（`segment_mixed`）：
大字居列中、宽约半列到七成列宽；小注字偏左或偏右、只占一线。墨连成的块（`glyph_units`，笔画间 ≤ 2px 的算一块）
单块居中够宽的是大字；左右挨着、各自够高、拼起来居中的两块（端＝立＋耑）也是大字；比列宽八成还宽的是框
（带框的标题，框里的字都按大字切）。大字占的行切大字，其余的行按双行小注（或单行小注）切。
哪些栏是混排由调用方按栏定（`big_share`）：全大字的栏里窄字（小、下、日）不居中也不够宽，照混排认会当成小注。
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from ...core.anchor import x_tr_to_tl
from .free_columns import min_ink_seam

ZONE_KINDS = ("big", "note", "solo")
CELL_KINDS = ("char", "jiazhu_a", "jiazhu_b", "jiazhu_solo")   # 与刻本链 cells 的 kind 同名


def seam_rows(col, W: int) -> tuple[np.ndarray, np.ndarray]:
    """列（`ColumnRec`）采样的缝 → 逐行左右缝 x（左上原点，相对列的 y0）。"""
    h = int(col.y1 - col.y0)
    ys = np.r_[np.arange(0, h, col.step), h - 1][:len(col.right)]
    rows = np.arange(h)
    right = np.interp(rows, ys, [x_tr_to_tl(x, W) for x in col.right])
    left = np.interp(rows, ys, [x_tr_to_tl(x, W) for x in col.left])
    return np.round(left).astype(int), np.round(right).astype(int)


def column_span(col, W: int) -> tuple[int, int]:
    """列图在页上横向裁的范围 [xa, xb)（左上原点）：左右缝外接再各让几 px。Step2-b、Step3 共用。"""
    left, right = seam_rows(col, W)
    return max(0, int(left.min()) - 4), min(W, int(right.max()) + 5)


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


@dataclass
class MixedParams:
    link: int = 3            # 笔画间这么近（px）的算一块
    mid: float = 0.12        # 居中：块中心离列中线 < mid × 列宽
    wmin: float = 0.36       # 大字宽下限（× 列宽）
    wmax: float = 0.7        # 大字宽上限（再宽就是两行小注并排）
    hmin: float = 0.25       # 单块大字高下限（× 列宽；一、二这类扁字够宽就行）
    frame: float = 0.8       # 比这还宽的块是框
    pair_gap: float = 0.1    # 左右两块拼大字：间隙上限（× 列宽）
    pair_h: float = 0.4      # 两块各自高过这么多（× 列宽）才拼：小注字矮
    pair_ov: float = 0.6     # 两块上下重叠占矮的那块的比例


def glyph_units(cimg: np.ndarray, link: int = 3, min_area: int = 20) -> list[tuple[int, int, int, int]]:
    """列图里墨连成的块 (x, y, w, h)，笔画间 ≤ link−1 px 的算一块。按 y 排。"""
    dil = cv2.dilate(cimg.astype(np.uint8), np.ones((link, link), np.uint8))
    _, _, st, _ = cv2.connectedComponentsWithStats(dil, connectivity=8)
    return sorted(((int(x), int(y), int(w), int(h)) for x, y, w, h, a in st[1:] if a >= min_area),
                  key=lambda u: u[1])


def big_spans(cimg: np.ndarray, prm: MixedParams = MixedParams()) -> list[tuple[int, int, int]]:
    """混排列里大字占的行段 [(y0, y1, 字高)]（相邻、重叠的并起来；字高取段里大字块的高）。"""
    h, wc = cimg.shape
    units = glyph_units(cimg, prm.link)

    def is_big(x0: int, x1: int) -> bool:
        return abs((x0 + x1) / 2 / wc - 0.5) < prm.mid and prm.wmin * wc <= x1 - x0 <= prm.wmax * wc

    found: list[tuple[int, int, int]] = []
    for x, y, w, hh in units:
        if w > prm.frame * wc or (is_big(x, x + w) and hh > prm.hmin * wc):
            found.append((y, y + hh, 0 if w > prm.frame * wc else hh))
    for i, (xi, yi, wi, hi) in enumerate(units):          # 左右两块拼成一个居中的大字
        for xj, yj, wj, hj in units[i + 1:]:
            if yj >= yi + hi:
                break
            (xa, ya, wa, ha), (xb, yb, wb, hb) = sorted([(xi, yi, wi, hi), (xj, yj, wj, hj)])
            gap = xb - (xa + wa)
            ov = min(ya + ha, yb + hb) - max(ya, yb)
            if (-2 <= gap <= prm.pair_gap * wc and min(ha, hb) > prm.pair_h * wc
                    and ov >= prm.pair_ov * min(ha, hb) and is_big(xa, max(xa + wa, xb + wb))):
                found.append((min(ya, yb), max(ya + ha, yb + hb), max(ha, hb)))
    spans: list[list[int]] = []
    for a, b, eh in sorted(found):
        if spans and a < spans[-1][1] - 2:
            spans[-1][1] = max(spans[-1][1], b)
            spans[-1][2] = max(spans[-1][2], eh)
        else:
            spans.append([a, b, eh])
    return [(a, b, eh) for a, b, eh in spans]


def big_share(cimg: np.ndarray, prm: MixedParams = MixedParams()) -> tuple[int, int]:
    """(按字形认出的大字行数, 有墨行数)：调用方按栏加总，定这栏是全大字还是混排。"""
    return sum(b - a for a, b, _ in big_spans(cimg, prm)), int(cimg.any(1).sum())


def _lanes(sub: np.ndarray, solo_frac: float = 0.05) -> list[tuple[np.ndarray, str]]:
    """小注区 → 各线 (图, kind)：先右线后左线；一边几乎没墨就是单行小注。"""
    sx = split_note(sub)
    right, left = sub.copy(), sub.copy()
    for y in range(len(sx)):
        right[y, :sx[y]] = False
        left[y, sx[y]:] = False
    tot = sub.sum()
    if left.sum() < solo_frac * tot or right.sum() < solo_frac * tot:
        return [(sub, "jiazhu_solo")]
    return [(right, "jiazhu_a"), (left, "jiazhu_b")]


def segment_mixed(cimg: np.ndarray, prm: MixedParams = MixedParams(), min_ink_frac: float = 0.03) -> list[Cell]:
    """混排列图 → 读序的字框：大字段切大字，其余段按小注切。"""
    h, wc = cimg.shape
    spans = big_spans(cimg, prm)
    hs = [eh for _, _, eh in spans if eh]
    em_big = float(np.median(hs)) if hs else 0.55 * wc
    zs: list[tuple[str, int, int]] = []
    y = 0
    for a, b, _ in spans:
        if a > y:
            zs.append(("note", y, a))
        zs.append(("big", a, b))
        y = b
    if y < h:
        zs.append(("note", y, h))
    cells: list[Cell] = []
    for zi, (kind, a, b) in enumerate(zs):
        sub = cimg[a:b]
        if not sub.any():
            continue
        if kind == "big":
            lanes, em = [(sub, "char")], em_big
        else:
            lanes = _lanes(sub)
        for img, k in lanes:
            if kind != "big":
                em = float(np.clip(1.08 * (_ink_width(img) or 0.5 * wc), 0.3 * wc, 0.7 * wc))
            for y0, y1 in cut_line(img.sum(1), em):
                part = img[y0:y1]
                xs = np.flatnonzero(part.any(0))
                if len(xs) and part.sum() >= min_ink_frac * em * em:
                    cells.append(Cell(a + y0, a + y1, int(xs[0]), int(xs[-1]) + 1, k, zi, int(part.sum())))
    return cells


@dataclass
class OcrParams:
    min_score: float = 0.5   # 低于这个的识别行不用
    sure: float = 0.85       # 高于这个才按它读出的字数硬切；否则字数只当字高的先验
    big_w: float = 0.62      # 行框宽过列宽这么多、旁边又没有并排的行 → 大字行
    horiz: float = 1.2       # 读出两字以上、框高不到框宽这么多倍 → 一对小注被横着读成了一行
    snap: float = 0.15       # 区界在识别框边上下这么多（× 字高）内找最省墨的行
    gap: float = 0.5         # 两行之间空出这么多（× 字高）还有墨 → 识别漏了，这段交给规则


@dataclass
class _Zone:
    kind: str                                    # big | note | rule
    a: int
    b: int
    lines: list[tuple[float, float, str, bool]]  # 区里的识别行：(x0, x1, 文字, 字数可信)


def _ocr_zones(prof: np.ndarray, wc: int, lines: list[tuple], prm: OcrParams) -> tuple[list[_Zone], float]:
    """识别行 → 列里自上而下的区（大字 / 小注 / 规则兜底）和大字字高。"""
    h = len(prof)
    L = [(x0, max(0, y0), x1, min(h, y1), t, s >= prm.sure) for x0, y0, x1, y1, t, s in lines
         if s >= prm.min_score and t and y1 > y0]

    def beside(i: int) -> bool:          # 有并排的行（上下大半重叠、分在列中线两边）
        x0, y0, x1, y1 = L[i][:4]
        return any(j != i and min(y1, v1) - max(y0, v0) > 0.5 * min(y1 - y0, v1 - v0)
                   and ((x0 + x1) / 2 - wc / 2) * ((u0 + u1) / 2 - wc / 2) < 0
                   for j, (u0, v0, u1, v1, *_) in enumerate(L))

    zs: list[_Zone] = []
    for i, (x0, a, x1, b, t, ok) in enumerate(L):
        if len(t) >= 2 and b - a < prm.horiz * (x1 - x0):      # 横读的一对小注：右字在前
            xm = (x0 + x1) / 2
            zs.append(_Zone("note", a, b, [(xm, x1, t[0], ok), (x0, xm, t[1], ok)]))
        else:
            big = x1 - x0 > prm.big_w * wc and not beside(i)
            zs.append(_Zone("big" if big else "note", a, b, [(x0, x1, t, ok)]))
    zs.sort(key=lambda z: z.a)
    merged: list[_Zone] = []
    for z in zs:                                      # 上下重叠的小注行并成一个小注区
        if merged and z.kind == merged[-1].kind == "note" and z.a < merged[-1].b - 0.1 * wc:
            merged[-1].b = max(merged[-1].b, z.b)
            merged[-1].lines += z.lines
        else:
            merged.append(z)
    hs = [(z.b - z.a) / len(z.lines[0][2]) for z in merged if z.kind == "big"]
    em = float(np.median(hs)) if hs else 0.55 * wc
    m = max(1, int(prm.snap * em))

    def low(lo: int, hi: int) -> int:                 # [lo, hi] 里最省墨的行
        lo, hi = max(0, lo), min(h, hi + 1)
        return lo + int(np.argmin(prof[lo:hi])) if hi > lo else min(max(lo, 0), h)

    out: list[_Zone] = []
    for z in merged:
        prev = out[-1].b if out else 0
        if z.a - prev > prm.gap * em and prof[prev:z.a].any():   # 前面空出一段还有墨：识别漏了
            e, s = (low(prev - m, prev + m) if out else 0), low(z.a - m, z.a + m)
            if out:
                out[-1].b = e
            out.append(_Zone("rule", e, s, []))
            z.a = s
        elif out:
            y = low(min(z.a, prev) - m, max(z.a, prev) + m)
            out[-1].b = z.a = y
        else:
            z.a = 0
        out.append(z)
    if not out:
        return [_Zone("rule", 0, h, [])], em
    tail = out[-1].b
    if h - tail > prm.gap * em and prof[tail:].any():
        out[-1].b = low(tail - m, tail + m)
        out.append(_Zone("rule", out[-1].b, h, []))
    else:
        out[-1].b = h
    return [z for z in out if z.b > z.a], em


def _cut_count(prof: np.ndarray, n: int, sure: bool) -> list[tuple[int, int]]:
    """按识别读出的字数切一条字线：字高先验 = 墨长 ÷ 字数；字数可信时收紧上下限，尽量切出 n 个。"""
    ys = np.flatnonzero(prof > 0)
    if not len(ys):
        return []
    em = (ys[-1] + 1 - ys[0]) / n
    if not sure:
        return cut_line(prof, em)
    best: list[tuple[int, int]] = []
    for lo, hi, lam in ((0.6, 1.4, 3.0), (0.45, 1.6, 1.5), (0.3, 2.0, 0.8)):
        r = cut_line(prof, em, lo, hi, lam=lam)
        if len(r) == n:
            return r
        if not best or abs(len(r) - n) < abs(len(best) - n):
            best = r
    return best


def segment_ocr(cimg: np.ndarray, lines: list[tuple], prm: OcrParams = OcrParams(),
                min_ink_frac: float = 0.01) -> list[Cell]:
    """有识别行的列 → 读序的字框。识别行定区（大字行、并排的小注行）和每行字数，切点照旧按墨；
    识别漏掉的段落交给 `segment_mixed`。`lines` 是列图坐标 (x0, y0, x1, y1, 文字, 置信度)。"""
    h, wc = cimg.shape
    zs, em = _ocr_zones(cimg.sum(1), wc, lines, prm)
    cells: list[Cell] = []
    for zi, z in enumerate(zs):
        sub = cimg[z.a:z.b]
        if not sub.any():
            continue
        if z.kind == "rule":
            cells += [Cell(c.y0 + z.a, c.y1 + z.a, c.x0, c.x1, c.kind, zi, c.ink) for c in segment_mixed(sub)]
            continue
        if z.kind == "big":
            t, ok = z.lines[0][2], z.lines[0][3]
            lanes = [(sub, "char", (len(t), ok))]
        else:
            got = _lanes(sub)
            right = [ln for ln in z.lines if (ln[0] + ln[1]) / 2 > wc / 2]
            left = [ln for ln in z.lines if (ln[0] + ln[1]) / 2 <= wc / 2]
            if len(got) == 1:
                one = z.lines if len(z.lines) == 1 else []
                lanes = [(got[0][0], got[0][1], (len(one[0][2]), one[0][3]) if one else None)]
            else:
                lanes = [(img, k, (len(g[0][2]), g[0][3]) if len(g) == 1 else None)
                         for (img, k), g in zip(got, (right, left))]
        for img, k, cnt in lanes:
            prof = img.sum(1)
            if cnt:
                segs = _cut_count(prof, *cnt)
            elif k == "char":
                segs = cut_line(prof, em)
            else:
                segs = cut_line(prof, float(np.clip(1.08 * (_ink_width(img) or 0.5 * wc), 0.3 * wc, 0.7 * wc)))
            for y0, y1 in segs:
                part = img[y0:y1]
                xs = np.flatnonzero(part.any(0))
                if len(xs) and part.sum() >= min_ink_frac * em * em:
                    cells.append(Cell(z.a + y0, z.a + y1, int(xs[0]), int(xs[-1]) + 1, k, zi, int(part.sum())))
    return cells


def line_char_heights(lines: list[tuple], prm: OcrParams = OcrParams()) -> list[float]:
    """可信识别行的平均字高（行高 ÷ 字数），给同一块的列当字高先验。"""
    return [(ln[3] - ln[1]) / len(ln[4]) for ln in lines if ln[5] >= prm.sure and ln[4] and ln[3] > ln[1]]


def segment_plain(cimg: np.ndarray, lines: list[tuple] | None = None, prm: OcrParams = OcrParams(),
                  col_w: float | None = None, em_hint: float | None = None, char_ratio: float = 0.9,
                  min_ink_frac: float = 0.03, min_w: float = 0.25) -> list[Cell]:
    """每列一行字的块（人标 `fmt: plain`：正文或标题，字宽约等于列宽）→ 读序的字框。

    不分大字、小注，整列一条字线按墨切。字高先验 = 列宽 `col_w`（左右缝间距的中位数；列图本身比它宽，
    缝会弯、两边还各让了几 px）× `char_ratio`，块里别的列识别出的字高 `em_hint` 优先（标题字常比列宽小）；有识别行时：都可信且盖住了
    这列的墨，就按读出的总字数切，否则拿可信行的平均字高当先验。`lines` 同 `segment_ocr`。"""
    h, wc = cimg.shape
    prof = cimg.sum(1)
    ys = np.flatnonzero(prof > 0)
    if not len(ys):
        return []
    wc = col_w or wc
    em = em_hint or char_ratio * wc
    good = [ln for ln in lines or [] if ln[5] >= prm.min_score and ln[4] and ln[3] > ln[1]]
    sure = [ln for ln in good if ln[5] >= prm.sure]
    span = ys[-1] + 1 - ys[0]
    covered = sum(min(ln[3], ys[-1] + 1) - max(ln[1], ys[0]) for ln in good)
    if good and len(sure) == len(good) and covered >= 0.8 * span:
        segs = _cut_count(prof, sum(len(ln[4]) for ln in good), True)
    else:
        if sure:
            em = float(np.median(line_char_heights(sure, prm)))
        segs = cut_line(prof, float(np.clip(em, 0.5 * wc, 1.4 * wc)))
    cells: list[Cell] = []
    for y0, y1 in segs:
        part = cimg[y0:y1]
        xs = np.flatnonzero(part.any(0))
        # 太少的墨、太窄的条（邻列的字伸过列界的边角）不算字
        if len(xs) and part.sum() >= min_ink_frac * em * em and xs[-1] + 1 - xs[0] >= min_w * em:
            cells.append(Cell(y0, y1, int(xs[0]), int(xs[-1]) + 1, "char", 0, int(part.sum())))
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
