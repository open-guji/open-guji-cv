"""量横长短后端（M7 扩展第二阶段）：土士、未末这类「两横一长一短」的字组，看字块图上两横谁长。

下横/上横 > 1 ＝ 土、未；< 1 ＝ 士、末；离 1 不足 `margin`（缺省 0.1）或取不到两横则弃权。
只吃字块灰度图（`cell.patch`），不看上下文；与文意路各自出 pick，合并由调用方（`seed_admit` 接线时）按
「文意有字用文意、文意弃权才按量横、两路不一致打旗」做。缺图抛 `PatchUnavailable`，不静默弃权。
量法细节与评测见 `doc/design/M7-字形量横画法-土士未末.md`、`research/m7/bars/`。

本模块只是库代码：未登记进 `registry`、未接任何 Step，`code_hash` 不变。
"""
from __future__ import annotations

import numpy as np

from .protocol import GroupVerdict, JudgeInput, PatchUnavailable

#: 组 id → (下横长的字, 上横长的字)
PAIRS = {"ts": ("土", "士"), "wm": ("未", "末")}

_GAP = 8          # 横画内容许的白缝（刻印断口）
_BAR_FRAC = 0.3   # 一行里最长连续墨 > 此比例×字宽才算横画行


def _cv2():
    import cv2
    return cv2


def _main_cc(ink: np.ndarray) -> np.ndarray | None:
    """横向膨胀后取最大连通域（把被竖画或断口断开的横画连回来），返回裁到外框的墨掩码。"""
    cv2 = _cv2()
    k = cv2.dilate(ink.astype(np.uint8), np.ones((5, 25), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(k)
    if n < 2:
        return None
    m = (lab == 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))) & ink
    ys, xs = np.where(m)
    if len(ys) == 0:
        return None
    return m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _longest_run(row: np.ndarray, gap: int) -> int:
    xs = np.flatnonzero(row)
    if len(xs) == 0:
        return 0
    best, s, p = 0, xs[0], xs[0]
    for x in xs[1:]:
        if x - p - 1 > gap:
            best, s = max(best, p - s + 1), x
        p = x
    return max(best, p - s + 1)


def _bands(m: np.ndarray) -> list[tuple[int, int, int]]:
    L = np.array([_longest_run(r, _GAP) for r in m])
    on = L > _BAR_FRAC * m.shape[1]
    out, y = [], 0
    while y < len(on):
        if on[y]:
            y0 = y
            while y < len(on) and on[y]:
                y += 1
            out.append((y0, y - 1, int(L[y0:y].max())))
        else:
            y += 1
    return out


def bar_ratio(gray: np.ndarray) -> float | None:
    """下横/上横。取最长两条横带按 y 排序，长度＝带内墨的最左到最右。取不到两横 → None。"""
    cv2 = _cv2()
    g = np.asarray(gray)
    if g.ndim == 3:
        g = cv2.cvtColor(g, cv2.COLOR_BGR2GRAY)
    if g.dtype != np.uint8:
        g = g.astype(np.uint8)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    m = _main_cc(b > 0)
    if m is None:
        return None
    bands = _bands(m)
    if len(bands) < 2:
        return None
    top2 = sorted(sorted(bands, key=lambda z: -z[2])[:2], key=lambda z: z[0])
    ext = []
    for y0, y1, _ in top2:
        cols = np.flatnonzero(m[y0:y1 + 1].any(0))
        ext.append(int(cols.max() - cols.min() + 1))
    return ext[1] / ext[0]


class BarsImageBackend:
    name = "image"
    fingerprint = ""

    def __init__(self, margin: float = 0.1):
        self.margin = margin

    def judge(self, spec, cell: JudgeInput) -> GroupVerdict:
        if spec.id not in PAIRS:
            return GroupVerdict(None, why="abstain:no_pair", via="image")
        if cell.patch is None:
            raise PatchUnavailable(cell.id)
        r = bar_ratio(cell.patch())
        if r is None:
            return GroupVerdict(None, why="abstain:no_bars", via="image", extra={"ratio": None})
        if abs(r - 1) < self.margin:
            return GroupVerdict(None, conf=abs(r - 1), why="abstain:close", via="image", extra={"ratio": r})
        bottom_long, top_long = PAIRS[spec.id]
        return GroupVerdict(bottom_long if r > 1 else top_long, conf=abs(r - 1), why="agree", via="image",
                            extra={"ratio": r})
