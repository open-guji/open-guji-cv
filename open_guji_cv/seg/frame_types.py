"""边框探测结果的数据类型（2026-10-30 从 `utils/border_geometry` 拆出，切分模块化第 3 步）。

坐标是新坐标系：**原点在页面右上角，x 向左递增，y 向下**，列号从右到左、从 1 开始。
产物（`products/kinds/borders`）、殿本 Step1、北行日錄的行探测都用这几个类型，所以放在共用原语库。
探测算法本身不在这里。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class HLine:
    """水平线（上/下版框）：新坐标系里 y = y_at_right + slope * x
    （x 向左递增，起点是页面右端 x=0 处的 y 值）。"""

    y_at_right: float
    slope: float
    kind: str  # "top" | "bottom"

    def y_at(self, x: float) -> float:
        return self.y_at_right + self.slope * x

    @classmethod
    def from_endpoints(cls, x1: float, y1: float, x2: float, y2: float,
                       w: int, kind: str) -> "HLine":
        """标注工具按"标准像素坐标(左上角原点)里这条线上任意两点"采集
        (方便拖拽——手柄不必落在图像左右边缘上，只要是这条线上两个不同的
        点即可)，这里转成新坐标系。不用先在旧LineMatch(中心锚点)绕一圈，
        直接从两点算斜率再外推到新坐标系的锚点(页面右端 x_new=0，也就是
        旧坐标 x_old=w-1 处)。"""
        slope_old = (y2 - y1) / (x2 - x1)  # 旧坐标：y_old(x)=y1+slope_old*(x-x1)
        y_at_right = y1 + slope_old * ((w - 1) - x1)
        return cls(y_at_right=float(y_at_right), slope=float(-slope_old), kind=kind)


@dataclass
class VLine:
    """竖直线（外边框/界行）：新坐标系里 x = x_at_top + slope * y
    （y 向下递增，起点是页面顶端 y=0 处的 x 值）。

    **弯的界行用三段折线表示**（用户 2026-09-02 定的方案）：以上下内版框为界，
    把版框内高度三等分，每条线加两个折点，记成 `(x, k1, k2, k3)`——`x_at_top`
    就是 x，`slope` 就是 k1，再加 `k2`/`k3` 是第二、三段的斜率，`y1`/`y2` 是两个
    折点的 y。`k2 is None` 就是原来的直线，所有只调 `x_at()` 的下游代码不用改。
    折点以上/以下按 k1/k3 外推。**整页要么全直线要么全三段**，看
    `BorderDetectionResult.vline_segments`。

    为什么存 y1/y2 而不是让下游自己按 top/bottom 算：折点 y 取决于这条线自己
    在上下版框上的交点（版框有斜率，每条线的折点 y 差几 px），存下来 `x_at()`
    才是自洽的。"""

    x_at_top: float
    slope: float
    k2: float | None = None
    k3: float | None = None
    y1: float | None = None
    y2: float | None = None

    @property
    def segments(self) -> int:
        return 1 if self.k2 is None else 3

    def x_at(self, y):
        """y 可以是标量或 ndarray。数组分支用 np.where 逐元素走**同一套算式**
        （每个元素的加减乘顺序跟标量分支一样，结果逐位相同），`_rule_rows` /
        `gutter_projection` 的向量化版靠这个。"""
        if self.k2 is None or self.y1 is None or self.y2 is None or self.k3 is None:
            return self.x_at_top + self.slope * y
        xa = self.x_at_top + self.slope * self.y1
        xb = xa + self.k2 * (self.y2 - self.y1)
        if isinstance(y, np.ndarray):
            return np.where(y <= self.y1, self.x_at_top + self.slope * y,
                            np.where(y <= self.y2, xa + self.k2 * (y - self.y1),
                                     xb + self.k3 * (y - self.y2)))
        if y <= self.y1:
            return self.x_at_top + self.slope * y
        if y <= self.y2:
            return xa + self.k2 * (y - self.y1)
        return xb + self.k3 * (y - self.y2)

    def knots(self) -> list[float]:
        """折点的 y（直线返回空表）。Step2 按这些 y 把列切成横带分别射影。"""
        return [] if self.k2 is None else [float(self.y1), float(self.y2)]

    @classmethod
    def from_endpoints(cls, x1: float, y1: float, x2: float, y2: float, w: int) -> "VLine":
        """同上，标注工具按"这条线上任意两点(标准像素坐标)"采集，不要求
        手柄落在图像上下边缘。"""
        slope_old = (x2 - x1) / (y2 - y1)  # 旧坐标：x_old(y)=x1+slope_old*(y-y1)
        x_old_at_top = x1 + slope_old * (0.0 - y1)
        return cls(x_at_top=float((w - 1) - x_old_at_top), slope=float(-slope_old))


@dataclass
class HeadRaiseBorder:
    """某一抬头列自己的内外上边框——局部量（只对这一列有意义），不是
    像 HLine 那样贯穿整页的一条线。"""

    col: int  # 列号，从右到左、从 1 开始
    inner_y: float
    outer_y: float
    # "这条记录不是全观测"。`detect_head_raise()` 里=外边框没在扫描中找到、
    # outer_y 是按实测中位间距从 inner_y 推的(vol01/51 型：外框墨占比只有
    # 0.00~0.18，整条没印上)；人工金标里同义，且拆得更细——那边另有
    # inner_observed/outer_observed 两个字段分别记两个坐标是不是量出来的，
    # estimated = not(inner_observed and outer_observed)。
    # estimated=True 时 outer_y 不能跟观测到线的记录同等确信度使用。
    estimated: bool = False


@dataclass
class BorderDetectionResult:
    width: int
    height: int
    top: HLine
    bottom: HLine
    verticals: list[VLine]  # 从右到左排列：verticals[0]是第1列外边框(最右)，verticals[-1]是最左外边框
    head_raise: list[HeadRaiseBorder] = field(default_factory=list)
    # 外边框：上下版框各有内外两层；左右外边框只在"纸边"那一侧存在——
    # 筒子页对折装订，偶数页纸边在左、奇数页在右，版心/装订那一侧没有
    # 独立外边框(被切/装订吃掉，不是没探测到)。跟对应内边框斜率锁定，
    # 只用一个"沿垂直方向的偏移量"描述，不需要独立的位置+角度两个自由度。
    # 由 `detect_outer_borders()` 填（口径=**外延**，跟 head_raise.outer_y 统一）。
    # 探测不到就留 None——这批书的上下外框磨损严重，14 页里 5 例峰值墨只有
    # 0.08~0.30，宁可报 None 也不硬凑。
    top_outer_offset: float | None = None
    bottom_outer_offset: float | None = None
    # 上/下版框的版式："double"（内框 + 独立外框）/ "single"（單邊框：一条 >= SINGLE_BAR_MIN
    # 行的粗条，没有第二条）/ "none"（既不是粗条、也没探到外框——磨没、裁掉或漏探）。
    # 由 `detect_outer_borders()` 填；single 时 `*_bar_extent` 是粗条从内框线往外的行数。
    top_frame_kind: str | None = None
    bottom_frame_kind: str | None = None
    top_bar_extent: float | None = None
    bottom_bar_extent: float | None = None
    # 这条外框是不是按书级先验兜底估出来的（见 OUTER_INK_FALLBACK）。估的值位置可信度
    # 低于观测值，下游要区别对待。
    top_outer_estimated: bool = False
    bottom_outer_estimated: bool = False
    # `push_bottom_to_bar` 把下版框往下推了多少 px（0 = 没动）；`snap_verticals_to_evidence`
    # 换了几条界行。都是诊断量，闸1 转成 flag 给人看。
    bottom_pushed: float = 0.0
    vlines_snapped: int = 0
    v_outer_side: str | None = None  # "left" | "right"，由页码奇偶决定
    v_outer_offset: float | None = None  # 相对 verticals[0](right)或verticals[-1](left) 的偏移量
    # 界行是直线(1)还是三段折线(3)——**整页统一**。由 `fit_vlines_polyline()`
    # 按弯度指标决定：`bend_w80_med`/`bend_w80_max` 是直线拟合下的 w80（装下
    # 80% 墨的最窄 x 跨度，px；界行本身 3~6px 宽，直线页 5~7）。Step2 看到 3
    # 就要按折点分带射影（`column_projection.warp_column` 已处理）。
    vline_segments: int = 1
    bend_w80_med: float | None = None
    bend_w80_max: float | None = None
    # 折线拟合**之前**的直线（跟 verticals 一一对应）。量"改前改后"要用它——
    # 三段页的 verticals[i].x_at_top/slope 是第一段外推到 y=0 的值，拿它当
    # "原直线"是错的（量法踩过：改前数字全被第一段的斜率带偏）。直线页两者相同。
    verticals_straight: list[VLine] = field(default_factory=list)
    # 网格模式（`detect_borders(column_grid=True)`）下与 verticals 一一对应：True =
    # 该槽位没探到细线、位置是相邻已验线之间的几何插值。自由模式全 False。
    vline_filled: list[bool] = field(default_factory=list)
