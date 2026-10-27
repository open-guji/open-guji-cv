"""自由版式 Step1：版框、分栏线 → 页上的文字块（左上原点像素）。

给「没有固定格网、多半没有界行、一页可能好几块版面」的坊刻本用（第一本：
《幼學須知鰲頭雜字》yxat，四周粗单边框、鳌头上下两栏、帖式表格）。殿本那套
21 格、界行定列的先验在这里一条都不用。设计见 `doc/design/自由版式切分-游学鳌头.md`。

只做三件事，都可被人标的版面提示（`layout_hints`）整页或逐块覆盖：

1. `ink_mask`：除以大窗中值背景再取阈——纸色深浅不均、透墨的扫描也稳；
2. `find_rules`：找长横线、长竖线。按条带投票，不靠形态学开运算——版框线粗细
   不匀、有断口，开运算一断就整条丢；条带法只要求「多数条带里这一行几乎全黑」；
3. `page_blocks`：外框四边取内沿（找不到的边退回文字墨外包），框内跨宽 ≥ 60% 的
   横线把框切成上下几块（鳌头的上下栏、帖式的分层）；每块里探到的竖线一并记下，
   Step2 当硬列界用。
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


def find_frame(ink: np.ndarray, hs: list[Rule], vs: list[Rule], *, edge_y: float = 0.025,
               edge_x: float = 0.012, min_votes: int = 4, merge: int = 45) -> Frame:
    """四边各取最外一条够完整（≥ min_votes 条带）的线，再取它 merge px 内最靠里的一条
    （粗框线的两沿、双线框的内线）当内沿。贴图边 edge_y／edge_x 以内的线是扫描纸边，不算
    （左右边距窄：书脊一侧的框线可以离图边只有 2% 页宽）。"""
    H, W = ink.shape
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


@dataclass
class Block:
    """一块文字区（左上原点像素，半开 [x0,x1)×[y0,y1)）。"""
    x0: int
    y0: int
    x1: int
    y1: int
    vrules: list[float] = field(default_factory=list)   # 块内竖线在块中线高度处的 x
    source: str = "auto"                                 # auto | hint


def page_blocks(ink: np.ndarray, frame: Frame, hs: list[Rule], vs: list[Rule], *,
                div_span: float = 0.6, div_margin: float = 0.05, merge: int = 45,
                pad: int = 6, min_h: int = 40) -> list[Block]:
    """框内按分栏横线切块，自上而下。"""
    fw, fh = frame.right - frame.left, frame.bottom - frame.top
    xm = (frame.left + frame.right) / 2
    divs = sorted(r.at(xm) for r in hs
                  if r.span >= div_span * fw
                  and frame.top + div_margin * fh < r.at(xm) < frame.bottom - div_margin * fh)
    cuts: list[list[float]] = []                      # 同一条粗线的两沿并成 [上沿, 下沿]
    for y in divs:
        if cuts and y - cuts[-1][1] <= merge:
            cuts[-1][1] = y
        else:
            cuts.append([y, y])
    edges = [frame.top] + [v for c in cuts for v in c] + [frame.bottom]
    out: list[Block] = []
    for i in range(0, len(edges), 2):
        y0, y1 = int(edges[i] + pad), int(edges[i + 1] - pad)
        if y1 - y0 < min_h:
            continue
        out.append(Block(int(frame.left + pad), y0, int(frame.right - pad), y1,
                         vrules=block_vrules(vs, int(frame.left + pad), y0, int(frame.right - pad), y1)))
    return out


def block_vrules(vs: list[Rule], x0: int, y0: int, x1: int, y1: int, *,
                 min_votes: int = 2, side: int = 30) -> list[float]:
    """块内的竖线（界行、表格竖线）：穿过块中线高度、离块左右边 > side 的。"""
    ym = (y0 + y1) / 2
    return sorted(r.at(ym) for r in vs
                  if r.n_strips >= min_votes and r.lo <= ym <= r.hi and x0 + side < r.at(ym) < x1 - side)
