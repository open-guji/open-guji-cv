"""列图坐标 → 原图坐标的逆映射（Step2 射影的反算），Step3/Step4 回写锚点用。

直线页一个单应矩阵；三段折线页按带各一个矩阵，带界与 `warp_column` 共用
`_strip_bounds`，dst 侧的带高按各带 `out_h` 累加——必须与 `warp_column` 逐位一致，
否则回写的锚点会整体错位。
"""

from __future__ import annotations

import numpy as np

from ..core.anchor import x_tl_to_tr
from ..utils.border_geometry import VLine
from ..utils.column_projection import _strip_bounds, column_warp_matrix

Point = tuple[float, float]


class ColumnMapper:
    """一列的 (列图 x, y) → 原图规范空间 (x_tr, y)。"""

    def __init__(self, page_width: int, left: VLine, right: VLine,
                 top_y: float, bottom_y: float):
        self.page_width = int(page_width)
        if left.segments == 1 and right.segments == 1:
            m, out_w, out_h = column_warp_matrix(page_width, left, right, top_y, bottom_y)
            self.bands = [(0.0, float(out_h), np.linalg.inv(m))]
            self.out_w, self.out_h = out_w, out_h
            return
        strips = _strip_bounds(left, right, top_y, bottom_y)
        mats = [column_warp_matrix(page_width, left, right, a, b) for a, b in strips]
        out_w = max(m[1] for m in mats)
        y = 0.0
        bands = []
        for (a, b), (_, _, out_h) in zip(strips, mats):
            m, _, _ = column_warp_matrix(page_width, left, right, a, b, out_w=out_w)
            bands.append((y, y + out_h, np.linalg.inv(m)))
            y += out_h
        self.bands, self.out_w, self.out_h = bands, out_w, int(y)

    def _inv_for(self, y: float) -> np.ndarray:
        for lo, hi, inv in self.bands:
            if y < hi:
                return inv
        return self.bands[-1][2]

    def to_page_tl(self, x: float, y: float) -> Point:
        inv = self._inv_for(y)
        v = inv @ np.array([x, y, 1.0])
        return float(v[0] / v[2]), float(v[1] / v[2])

    def to_page_tr(self, x: float, y: float) -> Point:
        X, Y = self.to_page_tl(x, y)
        return x_tl_to_tr(X, self.page_width), Y

    def quad_tr(self, x0: float, y0: float, x1: float, y1: float) -> list[Point]:
        """列图矩形四角 → 规范空间四边形（右上、左上、左下、右下的顺序不作保证，按输入角序）。"""
        return [self.to_page_tr(x0, y0), self.to_page_tr(x1, y0),
                self.to_page_tr(x1, y1), self.to_page_tr(x0, y1)]

    def bbox_tr(self, x0: float, y0: float, x1: float, y1: float) -> tuple[float, float, float, float]:
        q = self.quad_tr(x0, y0, x1, y1)
        xs, ys = [p[0] for p in q], [p[1] for p in q]
        return (min(xs), min(ys), max(xs), max(ys))
