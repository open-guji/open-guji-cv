"""单列射影矫正与列窗口（2026-10-30 切分模块化第 3 步，从 `utils/column_projection` 原样拆出）。

`column_warp_matrix`／`warp_column`：给一列左右两条边线（`VLine`，右上原点），把该列裁出并射影矫正成竖直矩形。
`page_column_windows`／`column_bounds`：按整页边框结果给出每列的上下界与窗口（抬头列、普通列留不同余量）。
殿本 Step2 与北行日錄的 column_crop 都用。
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .frame_types import BorderDetectionResult, HLine, VLine


def column_warp_matrix(page_width: int, left: VLine, right: VLine,
                        top_y: float, bottom_y: float, out_w: int | None = None
                        ) -> tuple[np.ndarray, int, int]:
    """算这一列的射影矩阵和输出尺寸，返回 `(M, out_w, out_h)`。

    `warp_column` 用它，金标那边也用它——**把人标的列图坐标反算回原图坐标**
    需要 `M` 的逆。金标一旦有了原图坐标的锚，上游改边线/窗口之后就能把标注
    重新投影到新列图上，而不是整批作废重标（见
    `scripts/migrate_column_warp_gold.py`）。

    ⚠️ 这个矩阵只对**直线**边线成立。三段折线的页（`vline_segments == 3`）
    `warp_column` 会按折点分带、每带一个矩阵——要反算列图坐标得先按 y 落在
    哪一带找对应的矩阵（带界见 `_strip_bounds`）。`out_w` 可外给，分带时三带
    要共用一个宽度。
    """
    if bottom_y <= top_y:
        raise ValueError(f"bottom_y({bottom_y}) must be > top_y({top_y})")

    def to_old_x(vline: VLine, y_new: float) -> float:
        return (page_width - 1) - vline.x_at(y_new)

    lx_top, rx_top = to_old_x(left, top_y), to_old_x(right, top_y)
    lx_bot, rx_bot = to_old_x(left, bottom_y), to_old_x(right, bottom_y)

    if out_w is None:
        out_w = int(round(max(abs(rx_top - lx_top), abs(rx_bot - lx_bot))))
    out_h = int(round(bottom_y - top_y))
    if out_w <= 0 or out_h <= 0:
        raise ValueError(f"warped column size invalid: {out_w}x{out_h}")

    src = np.array([[lx_top, top_y], [rx_top, top_y],
                     [rx_bot, bottom_y], [lx_bot, bottom_y]], dtype=np.float32)
    dst = np.array([[0, 0], [out_w, 0], [out_w, out_h], [0, out_h]], dtype=np.float32)
    return cv2.getPerspectiveTransform(src, dst), out_w, out_h


def warp_column(gray: np.ndarray, left: VLine, right: VLine,
                 top_y: float = 0.0, bottom_y: float | None = None) -> np.ndarray:
    """把 `left`/`right` 两条竖直边线之间的列矫正成竖直矩形灰度图。

    `left`/`right` 是新坐标系（右上角原点）下的 `VLine`；`top_y`/`bottom_y`
    也是新坐标系的 y（默认整页高度，通常应由 `column_bounds()` /
    `page_column_windows()` 给出，而不是整页边缘——版框外的页边留白不属于
    这一列）。

    输出矩形的宽度取 `left`/`right` 在 `top_y`/`bottom_y` 两处间距的较大者；
    高度取 `bottom_y - top_y`。输出图沿用标准图像坐标系（左上角原点）——
    矫正之后的列图不再是页面的一部分，没必要维持"右上角原点"这个页面级约定。

    **`out_w` 取较大者会不会把内容压扁？不会**（负结果，已查）：梯形→矩形的
    射影映射把**每一条源图水平线都归一到 `out_w`**，实测梯形量最大的那一列
    逐行缩放 1.0010（顶）→ 1.1269（底），每行映射后都精确落在 0..out_w。
    所以 max/min/mean 只决定输出的整体分辨率、不改变顶底之间的相对形变，
    取 max 保证没有任何一行被下采样。
    """
    h, w = gray.shape[:2]
    if bottom_y is None:
        bottom_y = float(h - 1)
    if left.segments == 1 and right.segments == 1:
        m, out_w, out_h = column_warp_matrix(w, left, right, top_y, bottom_y)
        return cv2.warpPerspective(gray, m, (out_w, out_h),
                                    flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    # 三段折线：一个单应变换表示不了折线，按折点把列切成横带各自射影、竖向拼接。
    # 相邻带共享同一组源角点，拼缝天然对齐；out_w 三带取同一个（最大者），否则
    # 拼不起来。左右两条线的折点 y 差几 px（版框有斜率），取均值当带界——那几
    # px 里把线当直线，误差亚像素。
    strips = _strip_bounds(left, right, top_y, bottom_y)
    mats = [column_warp_matrix(w, left, right, a, b) for a, b in strips]
    out_w = max(m[1] for m in mats)
    parts = []
    for (a, b), (_, _, out_h) in zip(strips, mats):
        m, _, _ = column_warp_matrix(w, left, right, a, b, out_w=out_w)
        parts.append(cv2.warpPerspective(gray, m, (out_w, out_h), flags=cv2.INTER_LINEAR,
                                         borderMode=cv2.BORDER_REPLICATE))
    return np.vstack(parts)


def _strip_bounds(left: VLine, right: VLine, top_y: float, bottom_y: float
                  ) -> list[tuple[float, float]]:
    """按两条边线的折点把 [top_y, bottom_y] 切成横带。"""
    ks = sorted(set((a + b) / 2.0 for a, b in zip(left.knots() or right.knots(),
                                                 right.knots() or left.knots())))
    cuts = [top_y] + [k for k in ks if top_y + 2 < k < bottom_y - 2] + [bottom_y]
    return [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)]


def _column_center_x(left: VLine, right: VLine, y: float) -> float:
    return (left.x_at(y) + right.x_at(y)) / 2.0


def _border_y(border: HLine, left: VLine | None, right: VLine | None) -> float:
    """版框线在这一列中心处的 y；没给列线就退回页面右端锚点 x=0。"""
    if left is None or right is None:
        return float(border.y_at(0.0))
    y = border.y_at(0.0)
    for _ in range(2):
        y = border.y_at(_column_center_x(left, right, y))
    return float(y)


def column_bounds(top: HLine, bottom: HLine,
                   head_raise_inner_y: float | None = None,
                   left: VLine | None = None,
                   right: VLine | None = None) -> tuple[float, float]:
    """给 `warp_column` 算 `top_y`/`bottom_y` 的**标准调用约定**。

    版框是斜的（实测上版框斜率最大 0.032），`HLine` 只是一条线，"这一列的
    上下界在哪"取决于沿这条线的哪个 x 取值——接口里没写死，这个函数把约定
    固化下来：**一律取页面右端锚点 `x=0`**（即 `HLine.y_at_right`），不随列
    位置变化。

    **传了 `left`/`right` 就不再用页面右端锚点**，改成沿版框线取"该列中心处"
    的值——这是上面那个取舍的正解，按原计划只改了这一个函数、`warp_column`
    不动。列线本身也是斜的，所以"列中心 x"依赖 y、y 又依赖 x，迭代两次就
    收敛到亚像素。

    不传 `left`/`right` 时退回原约定（一律取 `x=0`），代价是已知的、如实
    记着：越靠左的列这个锚点离该列真实版框越远——14 页 126 列实测，`y_at(0)`
    与"该列中心处的版框 y"相差 top 均值 14.5px / 最大 54.4px（28 列超 20px），
    而且**方向全部同号**（锚点一律落在真实版框**下方**）。后果两个：列图
    根本不含上版框线，Step 3 想拿版框锚行拿不到；抬头列更是整段被切。

    抬头列传 `head_raise_inner_y`（`BorderDetectionResult.head_raise` 里该列
    的 `inner_y`；同一列有多级台阶时传**最小的那个**，即最高的一级），上界
    直接用它——抬头字顶到主版框以上，用主版框会把抬头字齐腰切掉。抬头框本身
    是局部量、不贯穿全页，没有"沿哪个 x 取值"的问题。
    """
    if head_raise_inner_y is not None:
        return float(head_raise_inner_y), _border_y(bottom, left, right)
    return _border_y(top, left, right), _border_y(bottom, left, right)


# ── 逐列的矫正窗口 ───────────────────────────────────────────

BODY_PAD = 0.0     # 普通列在版框之外额外留的余量（上界；下界见 BOTTOM_PAD）

BOTTOM_PAD = 40.0
# 抬头列上界在抬头框**内边框线心**之上再开的余量（2026-09-08 用户实审 vol01/32
# c5「太祖」：窗口顶边 = inner_y = 307 正压在「太」的顶横上，列图第 3 行就有墨，
# 抬头字顶被切）。线心本来就带半条线宽，字又常顶着线写；开 20px 让字完整进来，
# 多进来的框线由 Step 3 的 top_slack 与 Step 4 的框线闸处理。20px 时「太」的竖笔尖仍顶边，取 30。
HEAD_PAD = 30.0
# **下界要多开一截**（2026-09-03 加）。`detect_borders` 的下版框线系统性偏上，
# 窗口就切在末字中部：dev_set 155 列实测，下界到真实版框线之间还剩字墨
# **中位 21px、最大 69px，83% 的列被切掉 >5px**（目视复核 vol01/60c4、
# vol02/181c5、vol01/137c6、vol01/24c1，红线切断「托」「更」「著」「淵」下半）。
# 偏差呈双峰：45% 的列 ≤0（定位准），38% >15px，长尾整页出现
# （01/60、02/3、02/181、01/137 多列同时偏），是下版框定位问题不是随机噪声。
#
# ⚠️ **别用连通体高度差量这个偏差**——笔画被切断后就不再与列图内的部分相连，
# 那样只能量到 2px，低估整整一个量级。要量「下界到版框线上沿之间还有多少字墨」。
#
# 多开进来的版框线不用担心：`clean_column` 的 `column_border_trim` 本来就负责
# 抹掉上下版框，它在文字带宽度内按水平投影归零判边，版框线进到列图里正是它
# 设计要处理的输入。40px 覆盖实测最大切幅 69px 里的绝大多数，又不至于把下一
# 页/页边噪声卷进来。见 doc/step3_error_survey.md 戊类、
# 反馈批次 2026-09-03-step1-bottom-clip。


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
    head_raise_inner_y: float | None = None

    @property
    def border_top_in_column(self) -> float:
        """主上版框在**列图坐标**里的 y——Step 3 的 `border_top` 要这个值。
        普通列是 0；抬头列是正数（列图顶端在版框之上）。"""
        return self.border_top_y - self.top_y

    @property
    def border_bottom_in_column(self) -> float:
        return self.border_bottom_y - self.top_y


def page_column_windows(result: BorderDetectionResult,
                         body_pad: float = BODY_PAD,
                         bottom_pad: float = BOTTOM_PAD,
                         head_pad: float = HEAD_PAD) -> list[ColumnWindow]:
    """整页每一列的矫正窗口——上下界**逐列**算（委派给 `column_bounds`），
    抬头列自动用抬头框的内边框当上界。

    `result` 直接用 `border_geometry.detect_borders()` 的输出：`head_raise`
    已经由 `detect_head_raise()` 填好，调用方不需要再给抬头先验。同一列若有
    多级台阶，取 `inner_y` **最小**的那个（最高的一级）。

    `bottom_pad` 与 `body_pad` **分开**：下版框探测系统性偏上，下界要多开一截
    才不会切掉末字下半，多进来的版框线由 `clean_column` 抹掉。理由与实测见
    `BOTTOM_PAD`。
    """
    hr: dict[int, float] = {}
    for b in result.head_raise:
        hr[b.col] = min(hr.get(b.col, b.inner_y), b.inner_y)
    out: list[ColumnWindow] = []
    for i in range(len(result.verticals) - 1):
        col = i + 1
        right_v, left_v = result.verticals[i], result.verticals[i + 1]
        btop, bbot = column_bounds(result.top, result.bottom,
                                    left=left_v, right=right_v)
        raised_top = hr.get(col)
        top_y, bottom_y = column_bounds(
            result.top, result.bottom, head_raise_inner_y=raised_top,
            left=left_v, right=right_v)
        top_y -= body_pad
        if raised_top is not None:
            top_y -= head_pad                  # 见 HEAD_PAD
        bottom_y += bottom_pad
        top_y = max(0.0, min(top_y, btop))
        bottom_y = min(float(result.height - 1), max(bottom_y, bbot))
        out.append(ColumnWindow(
            col=col, left=left_v, right=right_v,
            top_y=float(top_y), bottom_y=float(bottom_y),
            border_top_y=float(btop), border_bottom_y=float(bbot),
            raised=raised_top is not None,
            head_raise_inner_y=None if raised_top is None else float(raised_top)))
    return out
