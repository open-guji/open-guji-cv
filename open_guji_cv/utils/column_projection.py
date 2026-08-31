"""Step 2（单列射影变换 + 去噪）—— 见 `.claude/doc/segmentation_v2_pipeline.md`。

给定 Step 1（`border_geometry.detect_borders`）里某一列的左右两条边线
（`VLine`，新坐标系：右上角原点、y 向下），把该列从原图裁出并做射影
变换矫正成竖直矩形，再做基础去噪（书斑/墨渍等孤立小连通体）。

`row_boundaries.py`/`peak_line_search.py` 探索阶段都各自写过一次性的
`cv2.getPerspectiveTransform` + `warpPerspective` 代码，没有沉淀成独立
函数——这个模块把它收拢成一处。
"""

from __future__ import annotations

import cv2
import numpy as np

from .border_geometry import VLine


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
