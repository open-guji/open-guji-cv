"""Step 2（单列射影变换 + 去噪）—— 见 `.claude/doc/segmentation_v2_pipeline.md`。

给定 Step 1（`border_geometry.detect_borders`）里某一列的左右两条边线
（`VLine`，新坐标系：右上角原点、y 向下），把该列从原图裁出并做射影
变换矫正成竖直矩形，再做基础去噪（书斑/墨渍等孤立小连通体）。

`row_boundaries.py`/`peak_line_search.py` 探索阶段都各自写过一次性的
`cv2.getPerspectiveTransform` + `warpPerspective` 代码，没有沉淀成独立
函数——这个模块把它收拢成一处。
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .border_geometry import BorderDetectionResult, HLine, VLine


def warp_column(gray: np.ndarray, left: VLine, right: VLine,
                 top_y: float = 0.0, bottom_y: float | None = None) -> np.ndarray:
    """把 `left`/`right` 两条竖直边线之间的列矫正成竖直矩形灰度图。

    `left`/`right` 是新坐标系（右上角原点）下的 `VLine`；`top_y`/`bottom_y`
    也是新坐标系的 y（默认整页高度，通常应传 Step 1 输出的上下版框在该
    列位置的 y 值，而不是整页边缘——版框外的页边留白不属于这一列）。

    输出矩形的宽度取 `left`/`right` 在 `top_y`/`bottom_y` 两处间距的较大者
    （避免两端宽度不一致时把内容压扁）；高度取 `bottom_y - top_y`。输出图
    沿用标准图像坐标系（左上角原点）——矫正之后的列图不再是页面的一部分，
    没必要维持"右上角原点"这个页面级约定。
    """
    h, w = gray.shape[:2]
    if bottom_y is None:
        bottom_y = float(h - 1)
    if bottom_y <= top_y:
        raise ValueError(f"bottom_y({bottom_y}) must be > top_y({top_y})")

    def to_old_x(vline: VLine, y_new: float) -> float:
        return (w - 1) - vline.x_at(y_new)

    lx_top, rx_top = to_old_x(left, top_y), to_old_x(right, top_y)
    lx_bot, rx_bot = to_old_x(left, bottom_y), to_old_x(right, bottom_y)

    out_w = int(round(max(abs(rx_top - lx_top), abs(rx_bot - lx_bot))))
    out_h = int(round(bottom_y - top_y))
    if out_w <= 0 or out_h <= 0:
        raise ValueError(f"warped column size invalid: {out_w}x{out_h}")

    src = np.array([[lx_top, top_y], [rx_top, top_y],
                     [rx_bot, bottom_y], [lx_bot, bottom_y]], dtype=np.float32)
    dst = np.array([[0, 0], [out_w, 0], [out_w, out_h], [0, out_h]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(gray, m, (out_w, out_h),
                                flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def denoise_column(warped_gray: np.ndarray, ink_threshold: int = 128,
                    min_blob_area: int = 6) -> np.ndarray:
    """清掉矫正后列图里的孤立小连通体噪点（书斑/墨渍/扫描灰尘）。

    只处理二值化后面积 < `min_blob_area` 的连通体——笔画的连通体面积
    通常远大于这个量级，真正的噪点是几像素大小的孤立小点。噪点区域抹成
    背景色（白），其余像素原样保留（不是整体去噪滤波，只删孤立小块）。
    """
    mask = (warped_gray < ink_threshold).astype(np.uint8)
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = warped_gray.copy()
    for i in range(1, n_labels):
        if stats[i, cv2.CC_STAT_AREA] < min_blob_area:
            out[labels == i] = 255
    return out


# ── 逐列的矫正窗口 ───────────────────────────────────────────

RAISE_PAD = 8.0    # 抬头列在抬头框外延之上再多留这么多，别把外框自己切掉
BODY_PAD = 0.0     # 普通列在版框之外额外留的余量


@dataclass
class ColumnWindow:
    """一列该从哪儿矫正到哪儿——`warp_column` 的参数由这里算，不要再由调用方
    传页级标量。

    以前的做法是整页共用一个 `top_y = top.y_at(0)`（版框在**页面右端**处的
    y）。版框是斜的，越靠左的列这个锚点离该列真实版框越远——14 页 126 列
    实测均值 14.5px、最大 54.4px，而且**一律偏下**，等于列图顶端切进了正文，
    首字被削掉一截（`open-guji-dataset/char-segmentation/column-warp` 的
    known_limitations 记过这个现象）。抬头列更狠：列图裁在主版框上，而抬头
    字整段在版框以上，实测被切掉 140~187px，抬头字直接没了。
    """

    col: int                       # 列号，从右到左、从 1 开始
    left: VLine
    right: VLine
    top_y: float                   # 矫正窗口上界（新坐标 y）
    bottom_y: float                # 矫正窗口下界
    border_top_y: float            # **主**上版框在该列的 y（新坐标）
    border_bottom_y: float
    raised: bool                   # 这一列是不是抬头列
    head_raise_outer_y: float | None = None

    @property
    def border_top_in_column(self) -> float:
        """主上版框在**列图坐标**里的 y——Step 3 的 `border_top` 要这个值。
        普通列是 0；抬头列是正数（列图顶端在版框之上）。"""
        return self.border_top_y - self.top_y

    @property
    def border_bottom_in_column(self) -> float:
        return self.border_bottom_y - self.top_y


def _column_center_x(left: VLine, right: VLine, y: float) -> float:
    return (left.x_at(y) + right.x_at(y)) / 2.0


def _border_y_at_column(border: HLine, left: VLine, right: VLine) -> float:
    """版框线在这一列中心处的 y。列线本身也是斜的，所以 x 依赖 y、y 又依赖
    x——迭代两次就收敛到亚像素（两条线的斜率都是 1e-2 量级）。"""
    y = border.y_at(0.0)
    for _ in range(2):
        y = border.y_at(_column_center_x(left, right, y))
    return y


def page_column_windows(result: BorderDetectionResult,
                         raise_pad: float = RAISE_PAD,
                         body_pad: float = BODY_PAD) -> list[ColumnWindow]:
    """整页每一列的矫正窗口，上下界**逐列**算，抬头列自动上探到抬头框外延。

    `result` 直接用 `border_geometry.detect_borders()` 的输出——`head_raise`
    已经由 `detect_head_raise()` 填好，不需要调用方再给抬头先验。
    """
    hr = {b.col: b for b in result.head_raise}
    out: list[ColumnWindow] = []
    for i in range(len(result.verticals) - 1):
        col = i + 1
        right_v, left_v = result.verticals[i], result.verticals[i + 1]
        btop = _border_y_at_column(result.top, left_v, right_v)
        bbot = _border_y_at_column(result.bottom, left_v, right_v)
        box = hr.get(col)
        top_y = (box.outer_y - raise_pad) if box else (btop - body_pad)
        bottom_y = bbot + body_pad
        top_y = max(0.0, min(top_y, btop))
        bottom_y = min(float(result.height - 1), max(bottom_y, bbot))
        out.append(ColumnWindow(
            col=col, left=left_v, right=right_v,
            top_y=float(top_y), bottom_y=float(bottom_y),
            border_top_y=float(btop), border_bottom_y=float(bbot),
            raised=box is not None,
            head_raise_outer_y=None if box is None else float(box.outer_y)))
    return out


def warp_page_columns(gray: np.ndarray, result: BorderDetectionResult,
                       denoise: bool = False, **window_kwargs
                       ) -> list[tuple[ColumnWindow, np.ndarray]]:
    """整页逐列矫正，返回 `[(窗口, 列图), ...]`。Step 2 的正门。"""
    out = []
    for win in page_column_windows(result, **window_kwargs):
        img = warp_column(gray, win.left, win.right, win.top_y, win.bottom_y)
        if denoise:
            img = denoise_column(img)
        out.append((win, img))
    return out
