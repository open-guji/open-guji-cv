"""Step 2（单列射影变换 + 去噪）—— 见 `.claude/doc/segmentation_v2_pipeline.md`。

给定 Step 1（`border_geometry.detect_borders`）里某一列的左右两条边线
（`VLine`，新坐标系：右上角原点、y 向下），把该列从原图裁出并做射影
变换矫正成竖直矩形，再做基础去噪（书斑/墨渍等孤立小连通体）。

`row_boundaries.py`/`peak_line_search.py` 探索阶段都各自写过一次性的
`cv2.getPerspectiveTransform` + `warpPerspective` 代码，没有沉淀成独立
函数——这个模块把它收拢成一处。

Step2 的职责后来又扩了一项：**清掉矫正图两侧的残余界行**。界行是 Step1
给的左右边线本身的墨迹，`warp_column` 把边线映射到 x=0/x=out_w，界行有
宽度（约 5~10px），于是半条线必然留在矫正图里——实测 14 页 126 列
**没有一列是干净的**（两侧 6px 内墨占比中位 0.65~0.75）。这些残留会污染
Step3 的行投影和 Step4 的连通体归属，得在这一步就清掉。

`column_profile` / `column_text_band` / `strip_column_rules` 三个函数就是
干这个的，也是 `char-segmentation/column-warp` 金标的量法定义所在。
"""

from __future__ import annotations

import cv2
import numpy as np

from .border_geometry import HLine, VLine


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


def column_bounds(top: HLine, bottom: HLine,
                   head_raise_inner_y: float | None = None) -> tuple[float, float]:
    """给 `warp_column` 算 `top_y`/`bottom_y` 的**标准调用约定**。

    版框是斜的（实测上版框斜率最大 0.032），`HLine` 只是一条线，"这一列的
    上下界在哪"取决于沿这条线的哪个 x 取值——接口里没写死，这个函数把约定
    固化下来：**一律取页面右端锚点 `x=0`**（即 `HLine.y_at_right`），不随列
    位置变化。

    代价是已知的、如实记着：越靠左的列，这个锚点离该列真实版框越远——14 页
    126 列实测，`y_at(0)` 与"该列中心处的版框 y"相差 top 均值 14.6px / 最大
    60.5px、bottom 均值 8.7px / 最大 26.5px（最差都在 vol01/47、33 这类上版框
    斜率大的页面的最左几列）。也就是说最左列的矫正图上端可能比真实版框低
    60px，会切进首字。这是选定约定时明知的取舍，不是 bug；要改口径就改这
    一个函数，`warp_column` 不动。

    抬头列传 `head_raise_inner_y`（`BorderDetectionResult.head_raise` 里该列
    的 `inner_y`；同一列有多级台阶时传**最小的那个**，即最高的一级），上界
    直接用它——抬头字顶到主版框以上，用主版框会把抬头字齐腰切掉。抬头框本身
    是局部量、不贯穿全页，没有"沿哪个 x 取值"的问题。
    """
    top_y = float(top.y_at(0.0)) if head_raise_inner_y is None else float(head_raise_inner_y)
    return top_y, float(bottom.y_at(0.0))


def column_profile(warped_gray: np.ndarray, ink_threshold: int = 128) -> np.ndarray:
    """矫正图**沿竖直方向的投影**：长度 = 图宽，每个 x 上的墨占比（0~1）。

    这是 `char-segmentation/column-warp` 金标的核心量——矫正对了的话，这条
    曲线两端应该是空白（界行已清除），中间是字身墨；矫正歪了的话，界行
    残留会从"又窄又高的尖峰"摊成"又宽又矮的鼓包"（一条直线歪了 δ px 就在
    投影上抹开 δ px），所以曲线的形状本身也是残余倾斜的读数。
    """
    return (warped_gray < ink_threshold).astype(np.float64).mean(axis=0)


def column_text_band(warped_gray: np.ndarray, ink_threshold: int = 128,
                      rule_coverage: float = 0.35, skirt_coverage: float = 0.12,
                      max_rule_frac: float = 0.15) -> tuple[int, int]:
    """找矫正图里**文字带的左右边界** `(x_left, x_right)`（半开区间，右端不含）。

    边界外侧就是残余界行。判据：界行是一条贯穿整列的竖直墨线，在
    `column_profile` 上表现为紧贴边缘、墨占比很高的一小段；字身墨再密也
    到不了那个占比（字与字之间有空隙）。所以从两端各自往里扫——

    1. 先吃掉墨占比 >= `rule_coverage` 的那一段（界行本体）；
    2. 再吃掉紧跟着的、墨占比仍 >= `skirt_coverage` 的一段（界行边缘的
       灰过渡带 + 矫正重采样抹开的裙边）；
    3. 整个过程限制在 `max_rule_frac * 宽度` 以内——扫过头就是把字吃了，
       宁可留一点残墨也不切字（Step4 的字框收缩还有一道防线，切掉的字
       没人补得回来）。

    某一侧压根没有界行（比如版心侧被装订切掉了）时，第 1 步一开始就不满足，
    返回的边界就是 0 / 宽度本身，不会误吃。
    """
    prof = column_profile(warped_gray, ink_threshold)
    n = len(prof)
    limit = max(1, int(round(max_rule_frac * n)))

    def scan(order: list[int]) -> int:
        eaten = 0
        while eaten < limit and prof[order[eaten]] >= rule_coverage:
            eaten += 1                     # 第1步：界行本体
        if eaten == 0:
            return 0                       # 这一侧压根没有界行，别动
        while eaten < limit and prof[order[eaten]] >= skirt_coverage:
            eaten += 1                     # 第2步：界行边缘的灰过渡带/重采样裙边
        return eaten

    left = scan(list(range(n)))
    right = n - scan(list(range(n - 1, -1, -1)))
    if left >= right:                       # 整条都被判成界行——判据失效，原样返回
        return 0, n
    return left, right


def strip_column_rules(warped_gray: np.ndarray, ink_threshold: int = 128,
                        rule_coverage: float = 0.35, skirt_coverage: float = 0.12,
                        max_rule_frac: float = 0.15) -> np.ndarray:
    """把矫正图两侧的残余界行抹成背景白，返回**同尺寸**的新图。

    抹白而不是裁掉——矫正图的局部坐标系是 Step3(`row-boundaries` 金标)、
    Step4 共用的锚，裁一刀所有挂在上面的坐标就全漂了。要裁的调用方自己
    按 `column_text_band` 的返回值裁。
    """
    left, right = column_text_band(warped_gray, ink_threshold, rule_coverage,
                                    skirt_coverage, max_rule_frac)
    out = warped_gray.copy()
    out[:, :left] = 255
    out[:, right:] = 255
    return out
