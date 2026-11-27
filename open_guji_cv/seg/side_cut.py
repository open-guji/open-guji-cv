"""2b 左右切掉位置（2026-11-25 用户定）：整列竖直墨量投影，先认框线（界行），再在框线内侧附近找墨最少处切。

2b `column_band` 的 `side_cut`（缺省开）用它定文字带；出口闸 `cut_gate` 的 L2c 自检也用它当探针。
以旧算法 `column_text_band` 当金标比过 4 套书 1460 列（CV2 2026-11-25，见 `doc/2-切字/五小步.md` 2b 节）。
"""
from __future__ import annotations

import numpy as np

#: 框线判据：贴边墨占比到这么高才算有框线
RULE_INK = 0.3
#: 框线最多占列宽这么多（再往里就当是字了）
RULE_CAP = 0.15
#: 只在框线内侧这么宽（列宽比例）的小范围里找切点（用户 11-25「更激进：只在里边框很近的小范围里找」）
REACH = 0.15
#: 「够低」：墨占比不超过窗口最小值加这么多
LOW_TOL = 0.01


def side_rule_inner_edge(profile: np.ndarray, side: str, rule_ink: float = RULE_INK, cap: float = RULE_CAP) -> int:
    """列图一侧框线的结束位置（从该侧边缘数起的像素数）；这一侧没有框线（边缘墨占比 < `rule_ink`）返回 0。

    从边缘起，墨占比 ≥ `rule_ink` 的算框线身；之后一路下降的算框线的毛边，降到第一个谷为止（不越过 `cap`×列宽）。
    """
    q = profile if side == "L" else profile[::-1]
    if len(q) == 0 or q[0] < rule_ink:
        return 0
    i, lim = 0, min(len(q) - 1, int(cap * len(q)))
    while i < lim and (q[i] >= rule_ink or q[i + 1] < q[i] - 1e-9):
        i += 1
    return i


def side_cut_points(raw: np.ndarray, top: float, bottom: float, ink_threshold: int = 128,
                    row_margin: int = 60, inset: int = 2, reach: float = REACH) -> tuple[int, int] | None:
    """左右切掉位置 `(x_left, x_right)`（列图坐标，半开区间：保留 [x_left, x_right)）。

    整列竖直墨量投影，**只取上下边框之间的行、且离上下边框各留 `row_margin` 行不算**（横框墨、字压框的墨
    会把投影带偏，用户 2026-11-25 看图指出）。各侧在框线之后 `reach`×列宽 的窗口里，取**第一个**够低
    （≤ 窗口最小 + `LOW_TOL`）的位置，再往里缩 `inset` 像素（不越出这段够低的带）。行范围不足 200 行返回 None。
    """
    h, w = raw.shape[:2]
    y0 = int(max(0, top)) + row_margin
    y1 = int(min(h, bottom)) - row_margin
    if y1 - y0 < 200:
        return None
    p = (raw[y0:y1] < ink_threshold).mean(axis=0)
    out = []
    for side in ("L", "R"):
        q = p if side == "L" else p[::-1]
        lo = side_rule_inner_edge(p, side) + 1
        seg = q[lo:lo + max(1, int(w * reach))]
        if len(seg) == 0:
            return None
        m = float(seg.min())
        i0 = int(np.argmax(seg <= m + LOW_TOL))
        i1 = i0
        while i1 + 1 < len(seg) and seg[i1 + 1] <= m + LOW_TOL:     # 这段够低的带
            i1 += 1
        x = lo + min(i0 + inset, i1)
        out.append(x if side == "L" else w - 1 - x)
    xl, xr = out[0], out[1] + 1
    return (xl, xr) if xr > xl else None
