"""自由版式 Step1：版框、分栏线 → 页上的文字块（左上原点像素）。

给「没有固定格网、多半没有界行、一页可能好几块版面」的坊刻本用（第一本：
《幼學須知鰲頭雜字》yxat，四周粗单边框、鳌头上下两栏、帖式表格）。殿本那套
21 格、界行定列的先验在这里一条都不用。设计见 `doc/design/自由版式切分-游学鳌头.md`。

只做三件事，都可被人标的版面提示（`layout_hints`）整页或逐块覆盖：

1. `ink_mask`：除以大窗中值背景再取阈——纸色深浅不均、透墨的扫描也稳；
2. `find_rules`：找长横线、长竖线。按条带投票，不靠形态学开运算——版框线粗细
   不匀、有断口，开运算一断就整条丢；条带法只要求「多数条带里这一行几乎全黑」；
3. `find_frame`：外框四边取内沿（找不到的边退回文字墨外包）；
4. `find_banxin`：按书脊拆开的半叶，书脊一侧有一条窄的版心（书名、卷次、页码、鱼尾），
   不是正文。在书脊一侧框内 20–150px 找版心线（很浅，用 `thin_vlines` 找）；
5. `split_region`：版心以内的版面按**首尾贯穿**的线递归切块（block_detect 1.3）：先找贯穿全区的
   横线切上下（鳌头的上下栏、帖式的分层），切不动再看竖线一侧有没有只在那一侧贯穿的横线
   （混排页：下栏右两列一路到底、左边再分层），有就左右切开再递归。线浅、断，量法见 `scan_hlines`；
   每块里探到的竖线一并记下，Step2 当硬列界用。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


def ink_mask(gray: np.ndarray, bg_win: int = 51, ratio: float = 0.72) -> np.ndarray:
    """墨 = 比局部背景（`bg_win` 见方中值）暗过 `ratio` 的像素。"""
    bg = cv2.medianBlur(gray, bg_win).astype(np.float32) + 1.0
    return (gray.astype(np.float32) / bg) < ratio


def drop_specks(ink: np.ndarray, min_area: int = 15) -> np.ndarray:
    """去掉面积 < min_area 的连通墨点（纸屑、霉点）。切列、切字用；找线不用（断线的碎段也是线）。"""
    n, lab, st, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    keep = st[:, cv2.CC_STAT_AREA] >= min_area
    keep[0] = False
    return keep[lab]


@dataclass
class Rule:
    """一条长直线。横线 y = a + slope·x；竖线 x = a + slope·y。lo/hi 是沿线方向的覆盖范围。"""
    orient: str            # "h" | "v"
    a: float
    slope: float
    lo: int
    hi: int
    n_strips: int          # 有几个条带投了票（线有多完整）

    def at(self, t: float) -> float:
        return self.a + self.slope * t

    @property
    def span(self) -> int:
        return self.hi - self.lo


def _longest_run(m: np.ndarray) -> np.ndarray:
    """每行最长的连续 True 段长度。"""
    h = m.shape[0]
    d = np.diff(np.pad(m, ((0, 0), (1, 1))).astype(np.int8), axis=1)
    r0, c0 = np.nonzero(d == 1)
    _, c1 = np.nonzero(d == -1)            # 行优先序，起止一一配对
    out = np.zeros(h, int)
    np.maximum.at(out, r0, c1 - c0)
    return out


def _rules_along_x(ink: np.ndarray, orient: str, n_strips: int, fill: float, run: float,
                   tol: int, min_votes: int) -> list[Rule]:
    """沿 x 方向的线（竖线把图转置后调同一函数）。

    每个条带里，「该行墨占 ≥ fill、且最长连续墨段 ≥ run × 条带宽」的连续行段算一个候选点（取段中心）；
    y 相近（≤ tol）的候选点、每条带至多一票，票数 ≥ min_votes 的成一条线，最小二乘定斜率。
    条带宽约 1/10 页宽，比一个大字宽得多；要的是**连续**墨段，所以一排对齐的字
    （「二兩」「三錢」横画同高）中间有列缝，凑不成线。
    """
    H, W = ink.shape
    # 沿法向膨胀 2px 容线在条带内的轻微倾斜；沿线方向闭 7px 补断口
    m = cv2.dilate(ink.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_RECT, (1, 5)))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 1))) > 0
    edges = np.linspace(0, W, n_strips + 1).astype(int)
    pts: list[tuple[float, float, int]] = []          # (条带中心 x, 候选 y, 条带号)
    for i in range(n_strips):
        a, b = edges[i], edges[i + 1]
        sub = m[:, a:b]
        full = (sub.mean(1) >= fill) & (_longest_run(sub) >= run * (b - a))
        d = np.diff(np.r_[0, full.astype(np.int8), 0])
        for y0, y1 in zip(np.where(d == 1)[0], np.where(d == -1)[0]):
            pts.append(((a + b) / 2.0, (y0 + y1 - 1) / 2.0, i))
    pts.sort(key=lambda p: p[1])
    used = [False] * len(pts)
    out: list[Rule] = []
    for i, (_, y, _) in enumerate(pts):
        if used[i]:
            continue
        near = [j for j in range(len(pts)) if not used[j] and abs(pts[j][1] - y) <= tol]
        best: dict[int, int] = {}                     # 条带号 → 离种子最近的那个候选
        for j in near:
            s = pts[j][2]
            if s not in best or abs(pts[j][1] - y) < abs(pts[best[s]][1] - y):
                best[s] = j
        if len(best) < min_votes:
            continue
        for j in near:
            used[j] = True
        xs = np.array([pts[j][0] for j in best.values()])
        ys = np.array([pts[j][1] for j in best.values()])
        slope, a0 = np.polyfit(xs, ys, 1) if len(xs) >= 2 else (0.0, float(ys[0]))
        strips = sorted(best)
        w = W / n_strips
        out.append(Rule(orient, float(a0), float(slope), int(strips[0] * w),
                        int((strips[-1] + 1) * w), len(best)))
    return out


def find_rules(ink: np.ndarray, n_strips: int = 8, fill: float = 0.8, run: float = 0.65,
               tol: int = 20, min_votes: int = 3) -> tuple[list[Rule], list[Rule]]:
    """→ (横线, 竖线)。"""
    hs = _rules_along_x(ink, "h", n_strips, fill, run, tol, min_votes)
    vs = _rules_along_x(ink.T, "v", n_strips, fill, run, tol, min_votes)
    return hs, vs


@dataclass
class Frame:
    """版框内沿（左上原点像素）。`found` 记四边哪几条是真探到的，没探到的退回文字墨外包。"""
    top: float
    bottom: float
    left: float
    right: float
    found: dict[str, bool] = field(default_factory=dict)


def join_segments(rules: list[Rule], *, tol: float = 15) -> list[Rule]:
    """同一条线断成的几段（版片弯、框线中间换了斜率、粗线两段各拟了个斜率，各段条带票数都不够）连成一条：
    两段在接口处（有重叠就取重叠段中点）位置差 ≤ tol px，就连起来、票数相加，位置取两端点连线。
    双线框的两条线相距 20px 以上，不连。"""
    out: list[Rule] = []
    for r in sorted(rules, key=lambda r: r.lo):
        for i, q in enumerate(out):
            if q.orient != r.orient:
                continue
            j = (max(q.lo, r.lo) + min(q.hi, r.hi)) / 2
            if abs(q.at(j) - r.at(j)) <= tol:
                end = r if r.hi >= q.hi else q
                slope = (end.at(end.hi) - q.at(q.lo)) / max(1, end.hi - q.lo)
                out[i] = Rule(q.orient, q.at(q.lo) - slope * q.lo, slope, q.lo, end.hi,
                              q.n_strips + r.n_strips)
                break
        else:
            out.append(r)
    return out


def find_frame(ink: np.ndarray, hs: list[Rule], vs: list[Rule], *, edge_y: float = 0.025,
               edge_x: float = 0.012, min_votes: int = 4, merge: int = 45) -> Frame:
    """四边各取最外一条够完整（≥ min_votes 条带）的线，再取它 merge px 内最靠里的一条
    （粗框线的两沿、双线框的内线）当内沿。贴图边 edge_y／edge_x 以内的线是扫描纸边，不算
    （左右边距窄：书脊一侧的框线可以离图边只有 2% 页宽）。"""
    H, W = ink.shape
    hs, vs = join_segments(hs), join_segments(vs)
    hh = sorted((r for r in hs if r.n_strips >= min_votes and edge_y * H < r.at(W / 2) < (1 - edge_y) * H),
                key=lambda r: r.at(W / 2))
    vv = sorted((r for r in vs if r.n_strips >= min_votes and edge_x * W < r.at(H / 2) < (1 - edge_x) * W),
                key=lambda r: r.at(H / 2))

    def inner(lines: list[Rule], pos: float, from_low: bool) -> float | None:
        if not lines:
            return None
        seq = lines if from_low else lines[::-1]
        c0 = seq[0].at(pos)
        grp = [r.at(pos) for r in seq if abs(r.at(pos) - c0) <= merge]
        return max(grp) if from_low else min(grp)

    top = inner([r for r in hh if r.at(W / 2) < 0.3 * H], W / 2, True)
    bottom = inner([r for r in hh if r.at(W / 2) > 0.7 * H], W / 2, False)
    left = inner([r for r in vv if r.at(H / 2) < 0.3 * W], H / 2, True)
    right = inner([r for r in vv if r.at(H / 2) > 0.7 * W], H / 2, False)
    found = {"top": top is not None, "bottom": bottom is not None,
             "left": left is not None, "right": right is not None}
    if not all(found.values()):
        # 兜底：文字墨的外包（剔掉贴边 2% 的纸边阴影）
        mx, my = int(0.02 * W), int(0.02 * H)
        core = ink[my:H - my, mx:W - mx]
        rows = np.where(core[:, int(.1 * W):int(.9 * W)].mean(1) > 0.01)[0] + my
        cols = np.where(core[int(.1 * H):int(.9 * H)].mean(0) > 0.01)[0] + mx
        if top is None:
            top = float(rows.min()) if len(rows) else 0.0
        if bottom is None:
            bottom = float(rows.max()) if len(rows) else float(H - 1)
        if left is None:
            left = float(cols.min()) if len(cols) else 0.0
        if right is None:
            right = float(cols.max()) if len(cols) else float(W - 1)
    return Frame(float(top), float(bottom), float(left), float(right), found)


def snap_frame_edges(ink: np.ndarray, frame: Frame, *, thr: float = 0.3, reach: int = 45,
                     inward: int = 20) -> Frame:
    """框线位置（线中心，或双线框里认成内线的位置）→ 框线墨带的内沿。

    每边在框线附近量墨的投影（只量边长中间 80%）：所在处已在墨带里（≥ thr）就往里走到墨带尽头
    （最多 inward px，别把贴框的一列字吃进去）；不在墨带里就往外找最近的墨带（最多 reach px），
    取它的内沿。块从这里起算，左右上下不再另留空白（Sheldon 10-27：「边框就是起点」）。"""
    H, W = ink.shape
    t, b, l, r = (int(round(v)) for v in (frame.top, frame.bottom, frame.left, frame.right))
    ys, xs = slice(t + (b - t) // 10, b - (b - t) // 10), slice(l + (r - l) // 10, r - (r - l) // 10)
    colp = ink[ys].mean(0)
    rowp = ink[:, xs].mean(1)

    def edge(prof: np.ndarray, at: int, out: int) -> float:
        n = len(prof)
        if not 0 <= at < n:
            return float(at)
        if prof[at] >= thr:
            k = at
            while 0 <= k - out < n and prof[k - out] >= thr and abs(k - out - at) <= inward:
                k -= out
            return float(k - out)
        for d in range(1, reach + 1):
            k = at + out * d
            if not 0 <= k < n:
                break
            if prof[k] >= thr:
                return float(k - out)
        return float(at)

    found = frame.found or {}
    return Frame(top=edge(rowp, t, -1) if found.get("top") else frame.top,
                 bottom=edge(rowp, b, 1) if found.get("bottom") else frame.bottom,
                 left=edge(colp, l, -1) if found.get("left") else frame.left,
                 right=edge(colp, r, 1) if found.get("right") else frame.right, found=frame.found)


@dataclass
class Block:
    """一块文字区（左上原点像素，半开 [x0,x1)×[y0,y1)）。"""
    x0: int
    y0: int
    x1: int
    y1: int
    vrules: list[float] = field(default_factory=list)   # 块内竖线在块中线高度处的 x
    source: str = "auto"                                 # auto | hint


def block_vrules(vs: list[Rule], x0: int, y0: int, x1: int, y1: int, *,
                 min_votes: int = 2, side: int = 30) -> list[float]:
    """块内的竖线（界行、表格竖线）：穿过块中线高度、离块左右边 > side 的。"""
    ym = (y0 + y1) / 2
    return sorted(r.at(ym) for r in vs
                  if r.n_strips >= min_votes and r.lo <= ym <= r.hi and x0 + side < r.at(ym) < x1 - side)


def thin_vlines(gray: np.ndarray, bg_win: int = 51, width: int = 9, length: int = 41,
                bridge: int = 0) -> np.ndarray:
    """细竖线的强度图（0–1）：比背景暗多少，只留「比 width 窄、比 length 长」的竖向墨。

    浅界行、版心线常常淡到过不了墨阈（`ink_mask`），这里不取阈：横向开运算减掉粗笔画，
    再竖向开运算只留连续的竖线段。按列取均值就是「这一 x 上有没有竖线」。
    `bridge` > 0：虚线界栏（yxat 35 页起，一段段的短划）——竖段只要长过 length，再竖向闭运算把
    bridge 以内的断口接上。"""
    bg = cv2.medianBlur(gray, bg_win).astype(np.float32) + 1.0
    d = np.clip(1.0 - gray.astype(np.float32) / bg, 0.0, 1.0)
    th = d - cv2.morphologyEx(d, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (width, 1)))
    out = cv2.morphologyEx(th, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, length)))
    if bridge:
        out = cv2.morphologyEx(out, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, bridge)))
    return out


SPINE_MODES = ("auto", "left", "right", "odd_left", "odd_right", "none")


def spine_sides(mode: str, page: int) -> list[str]:
    """书脊（版心）可能在哪一侧。odd_left：奇数页在左、偶数页在右。auto：两侧都看。"""
    if mode == "none":
        return []
    if mode in ("left", "right"):
        return [mode]
    if mode == "odd_left":
        return ["left" if page % 2 else "right"]
    if mode == "odd_right":
        return ["right" if page % 2 else "left"]
    return ["left", "right"]


def find_banxin(prof: np.ndarray, left: float, right: float, sides: list[str], *,
                lo: int = 20, hi: int = 150, min_line: float = 0.04) -> tuple[str | None, float | None]:
    """→ (版心在哪一侧, 版心线 x)。`prof` 是框内各 x 的细竖线强度（`thin_vlines` 按列均值）。

    在给的几侧里，各取框边往里 [lo, hi) px 内最强的一条线；够 min_line 的里取最强那侧。
    线探不到时见 `find_banxin_gap`。
    只有一侧可选时，线没探到也返回该侧（x 为 None），让 Step2 知道那边的墨可能是版心。"""
    W = len(prof)
    best: tuple[float, str, float] | None = None
    for side in sides:
        a, b = ((int(left) + lo, int(left) + hi) if side == "left" else (int(right) - hi, int(right) - lo))
        a, b = max(0, a), min(W, b)
        if b <= a:
            continue
        i = a + int(np.argmax(prof[a:b]))
        if prof[i] >= min_line and (best is None or prof[i] > best[0]):
            best = (float(prof[i]), side, float(i))
    if best is not None:
        return best[1], best[2]
    return (sides[0], None) if len(sides) == 1 else (None, None)


def find_banxin_gap(ink_prof: np.ndarray, left: float, right: float, side: str, *,
                    lo: int = 20, hi: int = 100, max_frac: float = 0.35) -> float | None:
    """版心线太浅探不到时的退路：书脊一侧 [lo, hi) px 内最空的竖缝（墨量 ≤ max_frac × 框内
    各 x 墨量中位；纸纹、透墨让空白处也有 2–3% 的「墨」，所以门槛是相对的）当版心与正文的
    分界；缝外（靠框边那边）没墨就不算（没有版心内容，不用裁）。hi 要小于一个列距（实测版心
    宽 45–80px、列距 ≥ 100），不然没有版心的页会把第一条列缝当版心、裁掉一整列。

    `ink_prof` 是框内各 x 的墨占比（已平滑）。"""
    W = len(ink_prof)
    a, b = ((int(left) + lo, int(left) + hi) if side == "left" else (int(right) - hi, int(right) - lo))
    a, b = max(0, a), min(W, b)
    if b <= a:
        return None
    med = float(np.median(ink_prof[int(left):int(right)])) + 1e-6
    i = a + int(np.argmin(ink_prof[a:b]))
    if ink_prof[i] > max_frac * med:
        return None
    outer = ink_prof[int(left):i] if side == "left" else ink_prof[i + 1:int(right)]
    return float(i) if len(outer) and float(outer.max()) > max_frac * med else None


def thin_hlines(gray: np.ndarray, bg_win: int = 51, width: int = 9, length: int = 21) -> np.ndarray:
    """细横线的强度图：`thin_vlines` 转置过来。"""
    return thin_vlines(gray.T, bg_win, width, length).T


def rule_hlines(gray: np.ndarray, bg_win: int = 51, *, thr: float = 0.03, bridge: int = 25,
                length: int = 70) -> np.ndarray:
    """横界栏图（0/1，有界栏的正文、格子用）：细横线（`thin_hlines`）过阈后横向闭运算接上虚线断口（bridge），
    再横向开运算只留长过 length 的段——字里的横画短，留不下来。"""
    m = (thin_hlines(gray, bg_win) > thr).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, bridge), np.uint8))
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((1, length), np.uint8))


def rule_vlines(gray: np.ndarray, bg_win: int = 51, **kw) -> np.ndarray:
    """竖界栏图（0/1）：`rule_hlines` 转置来做。"""
    return rule_hlines(gray.T, bg_win, **kw).T


def line_maps(gray: np.ndarray, ink: np.ndarray, bg_win: int = 51, long: int = 301) -> tuple[np.ndarray, np.ndarray]:
    """→ (横线强度图, 竖线强度图)，0–1。细线用 `thin_hlines`／`thin_vlines`（浅、过不了墨阈的也在）；
    粗线（比 9px 厚，细线检测会当笔画减掉）另取墨里长度 ≥ long 的横向／竖向连续段补上；long 要比
    最宽的字长得多——齐平的大字横画（合成页、格网整齐的刻本）隔着列缝也能连成一排。"""
    k_h = cv2.getStructuringElement(cv2.MORPH_RECT, (long, 1))
    thick_h = cv2.morphologyEx(ink.astype(np.uint8), cv2.MORPH_OPEN, k_h).astype(np.float32)
    thick_v = cv2.morphologyEx(ink.astype(np.uint8), cv2.MORPH_OPEN, k_h.T).astype(np.float32)
    return (np.maximum(thin_hlines(gray, bg_win), thick_h), np.maximum(thin_vlines(gray, bg_win), thick_v))


@dataclass
class LineCand:
    """区里探到的一条细线（横线：pos 是区中线处的 y；竖线：pos 是区中线处的 x）。"""
    pos: float
    slope: float
    cov: float        # 线像素盖住区宽（竖线：区高）的比例
    reach: float      # 首尾贯穿度：容 gap 断口后最长一段 ÷ 区宽


def _shear(m: np.ndarray, s: float) -> np.ndarray:
    h, w = m.shape
    return cv2.warpAffine(m, np.float32([[1, 0, 0], [-s, 1, s * w / 2]]), (w, h), flags=cv2.INTER_NEAREST)


def _longest_chain(v: np.ndarray, gap: int) -> int:
    """v 里 True 的点，相邻间距 ≤ gap 的连成一段，返回最长一段的跨度。"""
    xs = np.flatnonzero(v)
    if len(xs) == 0:
        return 0
    cuts = np.flatnonzero(np.diff(xs) > gap)
    starts = np.r_[xs[0], xs[cuts + 1]]
    ends = np.r_[xs[cuts], xs[-1]]
    return int((ends - starts + 1).max())


def scan_hlines(lines: np.ndarray, x0: int, y0: int, x1: int, y1: int, *, thr: float = 0.03,
                thr_lo: float = 0.03, band: int = 9, slopes: float = 0.02, min_cov: float = 0.4,
                gap: int = 150, sep: int = 25, margin: int = 30) -> list[LineCand]:
    """区 [x0,x1)×[y0,y1) 里的细横线（`lines` 是 `thin_hlines` 的强度图）→ 自上而下。

    鳌头本的栏线又浅又细、微斜，木版磨损处断成虚线，字还常贴着线。所以分两层量：
    `cov`（线像素按 ±slopes 几个斜率剪切、竖向膨胀 band 后，盖住区宽的比例，取峰）定「这是条线」；
    `reach`（用更低的阈 thr_lo 取线像素，断口 ≤ gap 的连成一段，最长一段占区宽多少）定「线首尾
    贯穿这一区」。半截线（混排页只盖住一部分列的线）cov 可以很高，reach 到不了 0.95。"""
    m = (lines[y0:y1, x0:x1] > thr).astype(np.uint8)
    lo = (lines[y0:y1, x0:x1] > thr_lo).astype(np.uint8)
    h, w = m.shape
    if h < 2 * margin + 3 or w < 10:
        return []
    k = np.ones((band, 1), np.uint8)
    m, lo = cv2.dilate(m, k), cv2.dilate(lo, k)
    cov = np.zeros(h, np.float32)
    best = np.zeros(h, np.float32)
    for s in np.linspace(-slopes, slopes, 9):
        c = _shear(m, s).mean(1)
        up = c > cov
        cov[up], best[up] = c[up], s
    out: list[LineCand] = []
    for y in range(margin, h - margin):
        if cov[y] < min_cov or cov[y] < cov[max(0, y - sep):y + sep + 1].max():
            continue
        if out and y + y0 - out[-1].pos <= sep:            # 同一个平顶已经取过
            continue
        z = y
        while z + 1 < h and cov[z + 1] >= cov[y]:          # 平顶（粗线、竖向膨胀）：取中
            z += 1
        yc = (y + z) // 2
        reach = _longest_chain(_shear(lo, float(best[yc]))[yc] > 0, gap) / w
        out.append(LineCand(float(yc + y0), float(best[yc]), float(cov[y]), reach))
    return out


def scan_vlines(lines: np.ndarray, x0: int, y0: int, x1: int, y1: int, **kw) -> list[LineCand]:
    """细竖线（`lines` 是 `thin_vlines` 的强度图）→ 自左而右；量法同 `scan_hlines`，转置来做。"""
    return scan_hlines(lines.T, y0, x0, y1, x1, **kw)


@dataclass
class SplitParams:
    reach: float = 0.95      # 分栏线要首尾贯穿当前区的比例（Sheldon 10-27：60% 不够，混排页的半截线会误切）
    min_cov: float = 0.4     # 线像素至少盖住区宽的比例（低于它不当线）
    gap: int = 150           # 量贯穿时容许的断口（磨损、贴字）
    merge: int = 45          # 两条切线挨这么近算同一条（粗线两沿、双线）
    pad: int = 12            # 块边离线中心（大过半个线粗）
    min_h: int = 40          # 切出来比这还窄的块不要
    auto_v: bool = False     # 没人标时也试左右切（混排页）；缺省关，混排页由人标版面树
    max_depth: int = 3       # auto_v 时的递归深度
    min_side: float = 0.1    # 左右切时，较窄一边至少占区宽的比例
    snap: float = 0.25       # 人标切位的吸附范围：相邻两份里较小那份的这个比例
    snap_cov: float = 0.3    # 吸附时线的门槛（比自动认线低：人已经说了这里有分界）


def _cuts(pos: list[float], merge: int) -> list[list[float]]:
    out: list[list[float]] = []
    for v in sorted(pos):
        if out and v - out[-1][1] <= merge:
            out[-1][1] = v
        else:
            out.append([v, v])
    return out


def cut_pieces(lo: int, hi: int, pos: list[float], prm: SplitParams) -> list[tuple[int, int]]:
    """[lo, hi) 在 pos 处切开（每条切线两边各让 pad）→ 各段。"""
    edges = [lo] + [v for c in _cuts(pos, prm.merge) for v in c] + [hi]
    out = []
    for i in range(0, len(edges), 2):
        a = int(edges[i] + (prm.pad if i else 0))
        b = int(edges[i + 1] - (prm.pad if i + 1 < len(edges) - 1 else 0))
        if b - a >= prm.min_h:
            out.append((a, b))
    return out


def split_region(hl: np.ndarray, vl: np.ndarray, x0: int, y0: int, x1: int, y1: int, *,
                 prm: SplitParams = SplitParams(), depth: int = 0) -> list[Block]:
    """没人标时：一区按**首尾贯穿**的横线切开 → 块（自上而下）。`hl`、`vl` 是横、竖线强度图（`line_maps`）。

    贯穿 = reach ≥ prm.reach（缺省 0.95）。宁漏勿错：漏了的分栏由人标补（`splits`、`tree`），
    错切一刀则整页读序都乱。`prm.auto_v` 开时再试左右切：区里没有贯穿横线、但某条贯穿上下的竖线
    一侧有「在那一侧贯穿」的横线（混排页），就在竖线处切开，两边再递归（读序自右而左）。"""
    pos = [c.pos for c in scan_hlines(hl, x0, y0, x1, y1, min_cov=prm.min_cov, gap=prm.gap)
           if c.reach >= prm.reach]
    if pos:
        out: list[Block] = []
        for a, b in cut_pieces(y0, y1, pos, prm):
            out += split_region(hl, vl, x0, a, x1, b, prm=prm, depth=depth + 1) \
                if prm.auto_v and depth < prm.max_depth else [Block(x0, a, x1, b)]
        return out or [Block(x0, y0, x1, y1)]
    if prm.auto_v and depth < prm.max_depth:
        w = x1 - x0
        for c in scan_vlines(vl, x0, y0, x1, y1, min_cov=prm.min_cov, gap=prm.gap):
            x = int(c.pos)
            if c.reach < prm.reach or min(x - x0, x1 - x) < prm.min_side * w:
                continue
            for a, b in ((x + prm.pad, x1), (x0, x - prm.pad)):
                if any(s.reach >= prm.reach for s in scan_hlines(hl, a, y0, b, y1, min_cov=prm.min_cov, gap=prm.gap)):
                    return (split_region(hl, vl, x + prm.pad, y0, x1, y1, prm=prm, depth=depth + 1)
                            + split_region(hl, vl, x0, y0, x - prm.pad, y1, prm=prm, depth=depth + 1))
    return [Block(x0, y0, x1, y1)]


def snap_cut(orient: str, approx: float, window: float, hl: np.ndarray, vl: np.ndarray, ink: np.ndarray,
             x0: int, y0: int, x1: int, y1: int, prm: SplitParams = SplitParams()) -> float:
    """人标的大约切位 → 准位。`orient` "h" 切上下（approx 是 y）、"v" 切左右（approx 是 x）。

    window 内有线（cov ≥ prm.snap_cov，贯不贯穿都算——人已经说了这里有分界）就取盖得最满的那条
    （浅的分栏线断断续续、量出的贯穿反而不如图格里的半截横线，但盖住的总宽度还是它最多）；
    没有线就取 window 内最空的一行（列）：两栏之间的空白。"""
    lo, hi = approx - window, approx + window
    if orient == "h":
        cand = [c for c in scan_hlines(hl, x0, y0, x1, y1, min_cov=prm.snap_cov, gap=prm.gap) if lo <= c.pos <= hi]
    else:
        cand = [c for c in scan_vlines(vl, x0, y0, x1, y1, min_cov=prm.snap_cov, gap=prm.gap) if lo <= c.pos <= hi]
    if cand:
        return max(cand, key=lambda c: c.cov).pos
    if orient == "h":
        a, b = int(max(y0, lo)), int(min(y1, hi))
        prof = ink[a:b, x0:x1].mean(1) if b > a else None
    else:
        a, b = int(max(x0, lo)), int(min(x1, hi))
        prof = ink[y0:y1, a:b].mean(0) if b > a else None
    if prof is None or len(prof) == 0:
        return approx
    prof = cv2.GaussianBlur(prof.astype(np.float32).reshape(-1, 1), (1, 9), 2).ravel()
    low = prof <= prof.min() + 1e-3                 # 最空的几行常连成一片（两栏间整段空白）：取最长那片的中点
    best, i = (0, 0), 0
    while i < len(low):
        if low[i]:
            j = i
            while j < len(low) and low[j]:
                j += 1
            best = max(best, (j - i, -(i + j) // 2))
            i = j
        else:
            i += 1
    return float(a - best[1])


def _ratios(spec, n_parts: int) -> list[float]:
    """切法 → 各份占比。int n：均分 n 份；列表：按比例（如 [1, 2]、右 2 列左 14 列写 [2, 14]）。"""
    r = [1.0] * int(spec) if isinstance(spec, int) else [float(v) for v in spec]
    if n_parts and len(r) < n_parts:
        r += [r[-1]] * (n_parts - len(r))
    return r


def tree_label(path: tuple[int, ...]) -> str:
    """版面树叶子的块号：第一层切出的份是 1、2、3，第二层在后面加 a、b、c，第三层再加数字（1a、1b、2、3b2）。"""
    return "".join(str(i + 1) if d % 2 == 0 else chr(ord("a") + i) for d, i in enumerate(path))


def tree_blocks(node: dict, hl: np.ndarray, vl: np.ndarray, ink: np.ndarray, x0: int, y0: int, x1: int, y1: int,
                prm: SplitParams = SplitParams(), path: tuple[int, ...] = ()) -> list[tuple[Block, dict]]:
    """人标的版面树 → [(叶子块, 叶子的提示)]，按读序（上下切自上而下，左右切自右而左）。

    节点写法（`layout_hints` 的 `tree`）：`{h: 切法, parts: [...]}` 切上下，`{v: 切法, parts: [...]}`
    切左右；切法是份数或比例（左右切的比例、parts 都按读序**自右而左**写）；不切的是叶子，可带
    `cols`、`pitch`、`kind`、`fmt`（写在切开的节点上就是各份都这样）。人只给大约比例，切位由 `snap_cut` 吸到线或空白上。
    叶子的提示里加 `_label`：按切的层次编的块号（`tree_label`）。"""
    if "h" not in node and "v" not in node:
        return [(Block(x0, y0, x1, y1, source="hint"), {**node, "_label": tree_label(path) or "1"})]
    orient = "h" if "h" in node else "v"
    r = _ratios(node[orient], len(node.get("parts") or []))
    inherit = {k: node[k] for k in ("cols", "pitch", "kind", "ruled", "fmt") if k in node}   # 切开的节点上写的叶子参数传给各份
    parts = [{**inherit, **c} for c in (node.get("parts") or [])]
    parts += [dict(inherit)] * (len(r) - len(parts))
    tot = sum(r)
    if orient == "h":
        lo, span = y0, y1 - y0
        approx = [lo + span * sum(r[:i + 1]) / tot for i in range(len(r) - 1)]
    else:                                   # 自右而左：第一份贴右边
        lo, span = x1, -(x1 - x0)
        approx = [lo + span * sum(r[:i + 1]) / tot for i in range(len(r) - 1)]
    win = [prm.snap * abs(span) * min(r[i], r[i + 1]) / tot for i in range(len(r) - 1)]
    cuts = [snap_cut(orient, a, w, hl, vl, ink, x0, y0, x1, y1, prm) for a, w in zip(approx, win)]
    out: list[tuple[Block, dict]] = []
    if orient == "h":
        for k, ((a, b), child) in enumerate(zip(cut_pieces(y0, y1, cuts, prm), parts)):
            out += tree_blocks(child, hl, vl, ink, x0, a, x1, b, prm, (*path, k))
    else:
        segs = cut_pieces(x0, x1, cuts, prm)[::-1]            # 自右而左
        for k, ((a, b), child) in enumerate(zip(segs, parts)):
            out += tree_blocks(child, hl, vl, ink, a, y0, b, y1, prm, (*path, k))
    return out
