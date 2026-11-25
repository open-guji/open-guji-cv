"""左右切掉位置（2026-11-25）：整列竖直墨量投影，取框内缘之后墨量最小处。只给出口闸 `cut_gate` 的自检用，不进切分。"""
from __future__ import annotations

import numpy as np


# ── 左右切掉位置（2026-11-25，用户定：竖直墨量投影、取框内缘之后墨量最小处、稍往里缩） ──────────

def side_rule_inner_edge(profile: np.ndarray, side: str, rule_ink: float = 0.3, gap_ink: float = 0.05) -> int:
    """列图一侧版框线的内缘位置（从该侧边缘数起的像素数）；这一侧没有框线（边缘墨占比 < `rule_ink`）返回 0。"""
    q = profile if side == "L" else profile[::-1]
    if len(q) == 0 or q[0] < rule_ink:
        return 0
    i = 0
    while i < len(q) - 1 and q[i] >= gap_ink:
        i += 1
    return i


def side_cut_points(raw: np.ndarray, top: float, bottom: float, ink_threshold: int = 128,
                    row_margin: int = 60, inset: int = 2, reach: float = 0.25) -> tuple[int, int] | None:
    """左右各一个切掉位置 `(x_left, x_right)`（列图坐标，保留 [x_left, x_right]）。

    整列竖直墨量投影，**只取上下边框之间的行、且离上下边框各留 `row_margin` 行不算**（横框墨、字压框的墨
    会把投影带偏，用户 2026-11-25 看图指出）；各侧在框线内缘之后 `reach`×列宽 的窗口里取墨量最小处，
    并列时取最靠框线那一端、再往里缩 `inset` 像素（不越出最小墨带）。行范围不足 200 行返回 None。
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
        a = side_rule_inner_edge(p, side)
        lo, hi = a + 1, a + 1 + int(w * reach)
        seg = q[lo:hi]
        if len(seg) == 0:
            return None
        m = float(seg.min())
        i0 = next(i for i, v in enumerate(seg) if v <= m + 1e-3)
        i1 = i0
        while i1 + 1 < len(seg) and seg[i1 + 1] <= m + 1e-3:     # 第一段连续的最少墨带
            i1 += 1
        x = lo + min(i0 + inset, i1)
        out.append(x if side == "L" else w - 1 - x)
    return out[0], out[1]
