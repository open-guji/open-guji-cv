"""Step 1（边框探测）的新坐标系接口——见 `.claude/doc/segmentation_v2_pipeline.md`。

新坐标系跟 `peak_line_search.py` 内部使用的标准图像坐标（左上角原点，x
向右、y 向下）不一样：**原点在页面右上角，x 向左递增，y 向下递增不变**，
列号从右到左、从 1 开始——对齐古籍从右到左的阅读顺序（旧管线是"计数从
右到左，坐标原点却在左上角"这种拧巴状态，这次改掉）。

底层探测算法完全不用改——`peak_line_search.py` 的半高宽匹配度 + 位置
角度联合搜索照常在标准图像坐标里跑，这个模块只在探测完成后做一次坐标
系转换，把结果包装成新约定的输出格式。

抬头列的内外上边框由 `detect_head_raise()` 探测，已接入 `detect_borders()`
（14 页金标：13/13 可观测抬头框全中、8 页普通页零误报，inner 0.6px /
outer 0.4px）。坐标口径跟金标一致：**`inner_y` 取线心、`outer_y` 取外延**
（外框常是一条 15~23px 的粗条，取峰值位置会落在条中间、比外延低 2~4px）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .peak_line_search import (
    LineMatch,
    find_horizontal_border,
    find_vertical_lines,
    find_vertical_lines_grid,
    grid_thresholds,
    half_height_score_at,
    local_maxima,
)


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


def _hline_to_new(m: LineMatch, w: int, kind: str) -> HLine:
    """旧: y = m.position + m.slope*(x_old - w/2)，x_old 是左上角原点、向右的横坐标。
    新: x_new = (w-1) - x_old  =>  x_old = (w-1) - x_new。"""
    x_old_at_new_origin = (w - 1) - 0.0  # 新坐标 x_new=0 对应的旧坐标 x_old
    y_at_right = m.position + m.slope * (x_old_at_new_origin - w / 2.0)
    return HLine(y_at_right=float(y_at_right), slope=float(-m.slope), kind=kind)


def _vline_to_new(m: LineMatch, w: int, h: int) -> VLine:
    """旧: x_old = m.position + m.slope*(y - h/2)。
    新: x_new = (w-1) - x_old，y 不变。"""
    x_old_at_top = m.position + m.slope * (0.0 - h / 2.0)
    x_at_top = (w - 1) - x_old_at_top
    return VLine(x_at_top=float(x_at_top), slope=float(-m.slope))


# --- 抬头框探测的形态常数（全部来自 14 页金标实测，见 segmentation_v2_pipeline.md） ---
HR_BAND_ABOVE = 230       # 往主上边框上方扫多深：实测外边框最远 197px
HR_BAND_MARGIN = 25       # 下沿离主边框留出，避开主边框自己的内外双线
HR_THIN_WD_MAX = 10       # 内边框的形态：细锐线，实测半高宽 4~8
HR_THIN_INK_MIN = 0.35    # 内边框的墨占比，实测 0.38~0.97
HR_FAT_WD_MIN = 15        # 外边框的另一种形态：粗满墨条，实测半高宽 17~23
HR_FAT_WD_MAX = 32
HR_FAT_INK_MIN = 0.75
HR_PAIR_MIN = 20          # 内外边框峰间距，实测 23~38
HR_PAIR_MAX = 55
HR_DIST_MIN = 75          # 内边框离主上边框多远。vol01 实测 117~137，**vol02 有 80.3**
                          # （p101 c6「聖祖仁皇帝」），90 把它挡在门外。放到 75 在
                          # 两份金标上都无代价，见 HR_WALL_MIN_FRAC 的记录。
HR_DIST_MAX = 210
HR_CLUSTER_DY = 18        # 同一抬头块内相邻列的 inner_y 容差，实测差 2~8
HR_WALL_STRIP_W = 6
HR_WALL_SEARCH = 25       # 墙线在名义界行 x 附近的搜索半径
HR_WALL_MIN_FRAC = 0.40
# **0.5 → 0.40，与 HR_DIST_MIN 90 → 75 是同一次改动**（2026-09-12）。
#
# 起因：vol02/vol03 整册 head_raise 探到 0 个，下游代价是 Step2 把列图裁在
# 版框线上、抬头字整个落在图外，Step3 丢首字（vol02 p11 c4/c5 丢「御」、
# p101 c6 丢「聖」，且 Step9 文本层读着通顺、不报阙文，**丢字看不见**）。
#
# 查下来**不是算法坏了，是两个常数卡在边界上**——原算法（水平投影找内/外
# 边框 + 墙线校验）本身是对的，vol01 18 列金标复核 15/18 命中、零误报、
# inner_y 中位误差 0.55px：
#   - vol02/11 c4/c5：内边框**找到了**（dist=143.5、ink=1.00），块被墙线判据
#     拒掉，墙覆盖率 **0.48 vs 门槛 0.50**，差两个百分点；
#   - vol02/101 c6：内边框 dist=**80.3**，差 HR_DIST_MIN 不到 10px。
# 两处都是"就差一点"，不是判据选错了量。
#
# 改动代价实测（两份金标都跑了）：
#   | 判据 | vol01 列级金标 18 列 | 页级金标 70 页（8 页有抬头）| vol02 全书 |
#   |---|---|---|---|
#   | 90 / 0.50（旧）| 命中 15 漏 3 误报 0 | 命中 **6/8** 误报 0 | 1 列 |
#   | 75 / 0.40（新）| 命中 15 漏 3 误报 0 | 命中 **8/8** 误报 0 | 6 列 / 3 页 |
# vol01 逐位不变，页级召回 6/8 → 8/8，两份金标零误报。vol01/32 那 3 条仍漏
# （`estimated=true`，外边框根本没印上），那是另一回事，不在本次范围。
#
# ⚠️ 别再往下放：0.35 时 vol01 金标才多命中 1 条，而墙线判据是挡"普通页把
# 装饰墨迹当台阶"的唯一防线（`detect_head_raise` 文档串记过：不看墙线时
# 9/14/142 三页的"上諭"全是假阳性）。0.40 是"两份金标都零误报"的下沿。
HR_DEFAULT_PAIR_GAP = 38  # 外边框整条没印上时，按实测中位间距推


def _wall_frac(mask: np.ndarray, y_top: float, y_bottom: float, x0: float) -> float:
    """竖直连接墙线的覆盖率：抬头框比主版框高出来的那一截，两侧要有竖墙
    落到主边框上。在 x0 附近 ±HR_WALL_SEARCH 内扫取最好的一条——界行的 x
    来自 find_vertical_lines，vol01/47 那页顶端就系统性偏 13~39px，固定
    窄条会整条错过真正的墙。"""
    h, w = mask.shape
    y_top, y_bottom = int(y_top), int(y_bottom)
    if y_bottom - y_top < 5:
        return 0.0
    best = 0.0
    for dx in range(-HR_WALL_SEARCH, HR_WALL_SEARCH + 1, 3):
        xs = int(max(0, min(w - HR_WALL_STRIP_W, x0 + dx)))
        strip = mask[y_top:y_bottom, xs:xs + HR_WALL_STRIP_W]
        if strip.size:
            best = max(best, float(strip.any(axis=1).mean()))
    return best


def _outer_edge(curve: np.ndarray, lo: int, y_peak: float) -> float:
    """粗条/线的**外延**：从峰往外(y 小的一侧)走到墨占比跌破峰值一半的地方，
    线性插值取亚像素。金标 `outer_y` 就是按这个口径标的——外边框常常是一条
    15~23px 的粗条，取"峰值位置"会落在条中间、比外延低 2~4px。"""
    i = int(round(y_peak)) - lo
    if not (0 <= i < len(curve)):
        return float(y_peak)
    half = curve[i] * 0.5
    while i > 0 and curve[i - 1] >= half:
        i -= 1
    if i == 0:
        return float(lo)
    p0, p1 = float(curve[i - 1]), float(curve[i])
    if p1 == p0:
        return float(lo + i)
    return float(lo + i) - (p1 - half) / (p1 - p0)


def _dedup_peaks(peaks: list[tuple[float, float, float]],
                 min_dy: float = 12.0) -> list[tuple[float, float, float]]:
    """同一条线上会冒出好几个极大值点(尤其粗条)，按 y 间距去重，保留最上的。"""
    out: list[tuple[float, float, float]] = []
    for p in sorted(peaks):
        if not out or p[0] - out[-1][0] > min_dy:
            out.append(p)
    return out


def detect_head_raise(mask: np.ndarray, top: HLine, verticals: list[VLine],
                       width: int) -> list[HeadRaiseBorder]:
    """探测抬头框（某几列的版框整体向上抬起一截）。

    判据不是"边框上方有字凸出"——那条路走过，9/14/142 三页的"上諭"紧贴
    一条完全笔直的边框，全是假阳性。真判据是**边框线本身有台阶**：该列
    在主上边框上方有一条自己的横边框，且台阶两端有竖直墙线落回主边框。

    算法（形态常数全部来自 14 页金标实测）：
    1. 每列在主上边框上方开一个深窗口，按行算墨占比曲线；
    2. 找局部极大值，分两类——细锐线(内边框形态)和粗满墨条(外边框形态)；
    3. 取最上面的细锐线作 inner。outer 优先认它上方 20~55px 的粗条；没有
       粗条时才认"最上两条细线其实是内外框"(vol01/49、51 那种 outer 也
       印成细线的)；两者都没有就按中位间距推，`estimated=True`。
       **不能反过来要求"必须成对"**——vol01/51 三列的 outer 在扫描里墨
       占比只有 0.00~0.18，整条根本没印上；硬要求成对会把它们全杀掉。
    4. inner 离主边框的距离要落在 90~210px（普通页在窗口里唯一能找到的
       细锐线是外边框自己，距离只有 26~45px，被这一条挡掉）；
    5. 相邻列 inner_y 差 ≤18px 的聚成一个**抬头块**，墙线只查块的最外
       两侧——连续抬头列共用一个抬头框，块内部的界行在抬头区继续延伸，
       不是墙（vol01/33 c7 在块中间，实测墙覆盖率只有 0.00~0.04）。
    """
    h, w = mask.shape
    binm = (mask > 0).astype(np.uint8)
    per_col: list[dict | None] = []
    for i in range(len(verticals) - 1):
        right_v, left_v = verticals[i], verticals[i + 1]
        x_old = lambda v, y: (width - 1) - v.x_at(y)  # noqa: E731
        btop = float(np.mean([top.y_at(v.x_at(0.0)) for v in (right_v, left_v)]))
        lo = max(0, int(btop - HR_BAND_ABOVE))
        hi = max(lo + 20, int(btop - HR_BAND_MARGIN))
        ym = (lo + hi) / 2.0
        xl = int(max(0, min(x_old(right_v, ym), x_old(left_v, ym))))
        xr = int(min(w, max(x_old(right_v, ym), x_old(left_v, ym))))
        if xr - xl < 20 or hi <= lo:
            per_col.append(None)
            continue
        curve = binm[lo:hi, xl:xr].sum(axis=1).astype(np.float64) / (xr - xl)
        thin: list[tuple[float, float, float]] = []
        fat: list[tuple[float, float, float]] = []
        for ci in local_maxima(curve, radius=3):
            wd, _ = half_height_score_at(curve, ci)
            ink = float(curve[ci])
            y = float(lo + ci)
            if wd <= HR_THIN_WD_MAX and ink >= HR_THIN_INK_MIN:
                thin.append((y, ink, wd))
            elif HR_FAT_WD_MIN <= wd <= HR_FAT_WD_MAX and ink >= HR_FAT_INK_MIN:
                fat.append((y, ink, wd))
        thin, fat = _dedup_peaks(thin), _dedup_peaks(fat)
        if not thin:
            per_col.append(None)
            continue
        inner, outer, estimated = thin[0], None, True
        above_fat = [f for f in fat if HR_PAIR_MIN <= thin[0][0] - f[0] <= HR_PAIR_MAX]
        if above_fat:
            outer, estimated = above_fat[0], False  # 粗条会被拆成上下两个峰，取外沿
        elif len(thin) >= 2 and HR_PAIR_MIN <= thin[1][0] - thin[0][0] <= HR_PAIR_MAX:
            outer, inner, estimated = thin[0], thin[1], False
        if not (HR_DIST_MIN <= btop - inner[0] <= HR_DIST_MAX):
            per_col.append(None)
            continue
        per_col.append(dict(
            col=i + 1, inner_y=inner[0],
            outer_y=(_outer_edge(curve, lo, outer[0]) if outer
                     else inner[0] - HR_DEFAULT_PAIR_GAP),
            estimated=estimated, btop=btop, xl=xl, xr=xr))

    blocks: list[list[dict]] = []
    cur: list[dict] = []
    for c in per_col + [None]:
        if c is not None and (not cur or abs(c["inner_y"] - cur[-1]["inner_y"]) <= HR_CLUSTER_DY):
            cur.append(c)
        else:
            if cur:
                blocks.append(cur)
            cur = [c] if c is not None else []

    out: list[HeadRaiseBorder] = []
    for blk in blocks:
        wall = max(
            _wall_frac(binm, blk[0]["inner_y"], blk[0]["btop"], blk[0]["xr"] - HR_WALL_STRIP_W),
            _wall_frac(binm, blk[-1]["inner_y"], blk[-1]["btop"], blk[-1]["xl"]),
        )
        if wall < HR_WALL_MIN_FRAC:
            continue
        out.extend(HeadRaiseBorder(col=c["col"], inner_y=c["inner_y"],
                                   outer_y=c["outer_y"], estimated=c["estimated"])
                   for c in blk)
    return out


# --- 外边框探测（形态常数来自 14 页金标实测） ---
OUTER_GAP_MIN, OUTER_GAP_MAX = 12, 78   # 外框离内框多远，金标实测 24~47
OUTER_INK_MIN = 0.25      # 认一段"外框墨"的绝对门槛。
                          # **2026-09-19 从 0.30 降到 0.25**，依据是两册全书实扫
                          # （不是原来那 14 页金标，那批太小且早于厚度 off-by-one 修复）：
                          #     vol02  0.30→0.25: top 探到 135→142、bottom 106→112，
                          #            **误报 0→0**，报出的 offset std 8.0→8.1 / 5.8→5.9
                          #     vol01  0.30→0.25: top 161→163、bottom 140→140，误报 0→0
                          # 也就是说多认出来的十几页没有拖进离群——原注释担心的
                          # ">25px 离群"在修掉厚度 off-by-one 之后不再出现。
                          # **0.22 是下界，别再往下**：vol02 开始有 3 个误报、
                          # vol01 有 4 个（top 1 / bottom 3），收益只剩 1~3 页。
                          # 上下外框在这批书上仍大量磨没/裁掉，宁可报 None 也不要报错的数。
#: 竖直外框单独的墨门槛（2026-09-20）。它是上下外框搜索窗口的**先验**，认错一次
#: 整页两条边都跟着错：vol02 p10 一段 0.27 的噪点被当成竖直外框（offset 74，正常
#: 36~48），窗口被推到空白处，上下都报 None。真竖直外框峰值 0.48~1.00（docstring
#: 实测），0.40 留了余量。两册实扫：vol02 top 142→143 / bottom 112→113、vol01
#: 163→165 / 140→143，**误报 0→0**。
OUTER_V_INK_MIN = 0.40
#: 單邊框判定（2026-09-20）：从内框线（偏移 0）起连续 >= SINGLE_BAR_INK 墨占比的行数
#: >= SINGLE_BAR_MIN，就是「一条粗条、没有独立外框」的版式。vol02 全册分布：雙邊框页的
#: 内框只有 0~5 行，單邊框页 8/8/12/14 行（p82/p162/p160/p55），中间是空的，门槛定 8
#: 不含糊。這種页 `*_outer_offset` 报 None 是**对的**（没有第二条），但闸1 以前把它跟
#: 「漏探」混在一个 flag 里（文案写着「未区分」）——现在用 `*_frame_kind="single"` 分开。
SINGLE_BAR_INK = 0.50
SINGLE_BAR_MIN = 8
#: 粗条可以从内框线外 0~这么多行处开始（`push_bottom_to_bar` 把线放在条上沿 −BPUSH_MARGIN，
#: 条从 +4 起；不容忍这几行白，推过线的页会被判成 none、再被 OUTER_GAP_MIN=12 挡住报「没探到」）。
SINGLE_BAR_LEAD = 8
OUTER_RUN_MIN = 4         # 墨条厚度：竖直外框实测 17~28px，上下 0~20px。
OUTER_RUN_MAX = 40        # 实测 30/40/60 三档结果完全一样，不是敏感参数。
OUTER_PRIOR_TOL = 10.0    # 偏离页级间距先验多少 px 算一个"半衰"
OUTER_PRIOR_SHIFT = {"top": -4.0, "bottom": -7.0}
                          # 版框**不是四边等距的**：先验是从竖直外框量的，套到上下
                          # 要先减掉这个差，否则窗口中心整体偏外。
                          #
                          # 取值是 `scripts/measure_frame_geometry.py` 在 90 页上量
                          # 的同页配对差中位数（竖直外延 − 上/下外延）：
                          #     top    +4.2 ± 6.5px  中位 +3.6  (n=23)
                          #     bottom +6.3 ± 3.9px  中位 +6.8  (n=12)
                          # **别再用小样本拟合这两个数**：头一版拿 5 页拟出
                          # top=-10.8/bottom=-5.9，扩到 90 页后 top 那个差了 2.5 倍
                          # （真值 -4.2），bottom 才对得上。14 页金标那套评测在
                          # -3~-10.8 之间**分辨不出来**（都是 1.2~1.3px），所以它
                          # 挑不出对的值，只能靠直接量。
                          # top 这个差本身散得厉害（±6.5），别当精确常数用。
OUTER_PRIOR_WIN = 16.0    # 上下外框只在"页级内外间距"先验的 ±这么多 px 里找。
                          # 依据是用户给的判据、并已用金标验证：同一页四条边的
                          # 内外间距基本是个常数——竖直外框 38.4±4.0px（n=14）、
                          # 抬头框内外距 37.0px（n=11），两者对得上。放宽到 ±20
                          # 就会跑到远处的书口/纸边痕迹上去（vol01/32 top 报 -58、
                          # vol01/47 top 报 -62，都不是版框）。
OUTER_EDGE_RUN = 8        # 外延最多从墨段端点再往外走这么多 px
OUTER_PAPER_LO, OUTER_PAPER_HI = 10, 40
OUTER_PAPER_MAX = 0.11    # **外框条外面必须是纸**：外延再往外 10~40px 的行墨中位数
                          # 超过这个就认定找错了，返回 None。
                          #
                          # 依据是 108 条人裁（`border-detection/outer-edge`）。健康页
                          # 外条之外的行墨是**恰好 0.000 一路到 +110px**；而两条被用户
                          # 点名「线直接穿过文字」的（vol02/153 bottom、vol02/75 bottom）
                          # 是 0.178 / 0.126——因为那两页 `bottom` 内框线本身就没落在
                          # 下版框上，外框探测于是在正文里挑了最黑的一段，线下面还是正文。
                          # 这是"彻底不同"而不是"差一点"。
                          #
                          # ⚠️ **门槛压不到更低，因为抬头页是真例外**：抬头框就在上框
                          # 外面，vol01/52/49/58/134 的 top 条外之墨有 0.028~0.094，
                          # 而它们都是人裁 `ok`。0.11 这个值把三条坏的（0.126~0.178）
                          # 拦下、四条抬头页全放行，`ok` 一条没误伤。


def _outer_run(prof: np.ndarray, offs: np.ndarray,
                prefer_abs: float | None = None) -> tuple[float, float] | None:
    """在"由内向外"单调排列的剖面里找外框墨条，返回 (外延offset, 峰值墨)。

    **`offs` 必须单调**（不能按绝对值排序）——负方向排成递减的话
    `offs[b]-offs[a]` 会算出负厚度，整段被 RUN_MIN 挡掉；原型就是这么让
    top 和 right 侧全军覆没的。

    `prefer_abs`：这一页"内外间距应该是多少"的先验（用户给的判据——四条边
    的内外间距全页基本一致，实测上 36.3±6.2 / 下 38.2±5.1 / 侧 38.4±4.0）。
    给了就对偏离它的候选段打折。上下外框在这批书上磨损严重，光看墨量会
    挑到更远处的别的痕迹；竖直外框那一侧墨很稳（峰值 0.48~1.00），拿它当
    先验能把上下那几个离群页拉回来。
    """
    idx = np.where(prof >= OUTER_INK_MIN)[0]
    if len(idx) == 0:
        return None
    runs, a, b = [], idx[0], idx[0]
    for q in idx[1:]:
        if q == b + 1:
            b = q
        else:
            runs.append((a, b)); a = b = q
    runs.append((a, b))
    best = None
    for a, b in runs:
        # 厚度按**行数**算，不是端点之差：offs 步长 1px，占了 a..b 共 b-a+1 行的墨条
        # 厚 b-a+1 px。原来写 offs[b]-offs[a] 少算 1px，4px 的条算成 3 被 RUN_MIN 挡掉
        # ——vol02 上下外框实测只有 3~5px 厚（竖直外框 19~24px，RUN_MIN=4 是按它标的），
        # 正好卡在这个 off-by-one 上，整册 top 漏报 11 页、bottom 更多。
        thick = abs(float(offs[b] - offs[a])) + 1.0
        if not (OUTER_RUN_MIN <= thick <= OUTER_RUN_MAX):
            continue
        score = float(prof[a:b + 1].mean()) * (thick + 1.0)
        if prefer_abs is not None:
            mid = abs(float(offs[a] + offs[b]) / 2.0)
            score /= 1.0 + (abs(mid - prefer_abs) / OUTER_PRIOR_TOL) ** 2
        if best is None or score > best[0]:
            pk = float(prof[a:b + 1].max())
            half = pk * 0.5
            # 外延要有刹车：半高门槛在低对比区会一路滑到搜索边界（vol01/32 top
            # 的段明明在 -45~-50，却一路滑出去报了 -78=GAP_MAX）。最多再走
            # OUTER_EDGE_RUN px。
            i, limit = b, min(len(prof) - 1, b + OUTER_EDGE_RUN)
            while i < limit and prof[i + 1] >= half:
                i += 1
            if i >= len(prof) - 1 or prof[i + 1] >= half:
                edge = float(offs[i])
            else:
                p0, p1 = float(prof[i]), float(prof[i + 1])
                edge = (float(offs[i]) if p0 == p1 else
                        float(offs[i]) + (p0 - half) / (p0 - p1) * float(offs[i + 1] - offs[i]))
            best = (score, edge, pk)
    return None if best is None else (best[1], best[2])


def _paper_beyond(binm: np.ndarray, base: np.ndarray, xs: np.ndarray,
                   edge: float, sign: float, height: int) -> float:
    """外延再往外 `OUTER_PAPER_LO..HI` px 的行墨中位数——版框之外应该是纸。"""
    far = abs(edge)
    vals = []
    for o in range(int(far) + OUTER_PAPER_LO, int(far) + OUTER_PAPER_HI + 1):
        yy = np.rint(base + o * sign).astype(int)
        ok = (yy >= 0) & (yy < height)
        if ok.mean() < 0.5:          # 大半跑出页面了，别拿残缺的行下判断
            continue
        vals.append(float(binm[yy[ok], xs[ok]].mean()))
    return float(np.median(vals)) if vals else 0.0


def detect_outer_borders(mask: np.ndarray, top: HLine, bottom: HLine,
                          verticals: list[VLine], width: int, height: int,
                          outer_shift: dict | None = None) -> dict:
    """上下版框的外框偏移 + 纸边侧竖直外框偏移。

    坐标口径是**外延**（朝外那一侧的半高边缘），跟 `detect_head_raise()` 的
    `outer_y` 统一。外框是一条粗墨条，"位置"取决于量条的哪一侧，不定死口径
    就没法比——抬头框那边踩过这个坑。

    **上下外框走"页级间距先验"**：先测竖直外框（墨最稳，峰值 0.48~1.00、
    14/14 页侧别正确），拿 `abs(v_outer_offset)` 当这一页的内外间距，再只在
    它的 ±`OUTER_PRIOR_WIN` 里找上下外框。这是用户给的判据（内外间距全页
    基本一致），已用 14 页金标验证成立：竖直 38.4±4.0px、抬头框内外距
    37.0px（n=11）。

    ⚠️ **上下外框有一半根本不该报数**。14 页 28 条边里只有 14 条在先验窗口
    内有 >=0.30 的版框墨；其余要么磨没了（vol01/141 bottom 窗内峰值墨 0.048、
    vol01/142 top 0.129），要么被扫描裁掉了。这些一律返回 None——试过用
    弱档（ink>=0.12）把它们补上，6 例里 3 例误差超 10px，是负结果。
    报数的那 14 条离金标均值 3.0px / 中位 2.1px。

    ⚠️ **上下外框的人工金标口径本身也不统一**（14 页实测：top 外延6/中心3/
    内沿1，bottom 外延8/内沿3/中心1），所以剩下那点差**部分是标注口径的
    散布，不全是探测误差**，别照着它继续调参。竖直外框那一侧口径是干净的
    （外延 12/14，金标离真墨外延平均 4.1px）。
    """
    binm = (mask > 0).astype(np.uint8)
    out: dict = dict(top_outer_offset=None, bottom_outer_offset=None,
                     top_frame_kind=None, bottom_frame_kind=None,
                     top_bar_extent=None, bottom_bar_extent=None,
                     v_outer_side=None, v_outer_offset=None)
    vx = sorted((width - 1) - v.x_at(height / 2.0) for v in verticals)
    xs = np.arange(int(vx[0] + 30), int(vx[-1] - 30), 2)
    ys = np.arange(int(height * 0.12), int(height * 0.88), 3)
    # 先测竖直外框——那一侧的墨最稳（峰值 0.48~1.00），拿它当上下的间距先验
    if len(ys) > 10 and len(verticals) >= 2:
        best = None
        for side, vi, sign in (("right", 0, -1.0), ("left", len(verticals) - 1, 1.0)):
            base = np.array([(width - 1) - verticals[vi].x_at(y) for y in ys])
            offs = np.arange(OUTER_GAP_MIN, OUTER_GAP_MAX + 1, 1.0) * sign
            prof = []
            for o in offs:
                xx = (base - o).astype(int)     # 新坐标 x 向左递增 => 旧坐标取反
                ok = (xx >= 0) & (xx < width)
                prof.append(binm[ys[ok], xx[ok]].mean() if ok.any() else 0.0)
            r = _outer_run(np.array(prof), offs)
            if r is not None and r[1] < OUTER_V_INK_MIN:
                r = None            # 竖直外框是先验，弱峰宁可不要（见 OUTER_V_INK_MIN）
            if r is not None and (best is None or r[1] > best[2]):
                best = (side, r[0], r[1])
        if best is not None:
            out["v_outer_side"], out["v_outer_offset"] = best[0], best[1]
    prior = None if out["v_outer_offset"] is None else abs(out["v_outer_offset"])
    if len(xs) > 10:
        for kind, line, sign in (("top", top, -1.0), ("bottom", bottom, 1.0)):
            base = np.array([line.y_at((width - 1) - x) for x in xs])
            # 先判單邊框：从内框线起往外连续的粗墨。是粗条就不找第二条了。
            run0, start0 = 0, None
            for o in range(0, OUTER_GAP_MAX + 1):
                yy = (base + o * sign).astype(int)
                ok = (yy >= 0) & (yy < height)
                v = binm[yy[ok], xs[ok]].mean() if ok.any() else 0.0
                if v >= SINGLE_BAR_INK:
                    if start0 is None:
                        start0 = o
                    run0 += 1
                elif start0 is not None:
                    break
                elif o >= SINGLE_BAR_LEAD:
                    break
            if start0 is not None and run0 >= SINGLE_BAR_MIN:
                out[f"{kind}_frame_kind"] = "single"
                out[f"{kind}_bar_extent"] = float(start0 + run0)
                continue
            out[f"{kind}_frame_kind"] = "none"
            lo, hi = OUTER_GAP_MIN, OUTER_GAP_MAX
            if prior is not None:      # 钉在页级间距先验上，见函数 docstring
                # 四边不等距，先按边校正。`outer_shift` 是**书级**标定值
                # （`BookSpec.outer_shift`），不给才退回缺省——这个差按书变，
                # vol01 -4.2/-6.3 对 vol02 -12.0/-19.8，抄错就整册漏报。
                shift = (outer_shift or {}).get(kind, OUTER_PRIOR_SHIFT[kind])
                c = prior + shift
                lo = max(lo, c - OUTER_PRIOR_WIN)
                hi = min(hi, c + OUTER_PRIOR_WIN)
            if hi - lo < 5:
                continue
            offs = np.arange(lo, hi + 1, 1.0) * sign
            prof = []
            for o in offs:
                yy = (base + o).astype(int)
                ok = (yy >= 0) & (yy < height)
                prof.append(binm[yy[ok], xs[ok]].mean() if ok.any() else 0.0)
            r = _outer_run(np.array(prof), offs, prefer_abs=prior)
            if r is None:
                continue
            if _paper_beyond(binm, base, xs, r[0], sign, height) > OUTER_PAPER_MAX:
                continue          # 条外面还是墨 => 这根本不是最外层，见常量注释
            out[f"{kind}_outer_offset"] = r[0]
            out[f"{kind}_frame_kind"] = "double"
    return out


# ---------------------------------------------------------------- 界行折线拟合

BEND_SEARCH = 40          # 弯度投影窗口半宽（px）。要盖得住弯幅（实测最大 ~30），
                          # 又别宽到吃进邻列的字（列距 ~185）
BEND_INK_W_MAX = 9        # 一行在窗口里的墨宽超过这个就当被笔画占了，不算——
                          # 界行本身 3~6px 宽，不剔量的是字不是线
BEND_Y_STEP = 2
BEND_MIN_ROWS = 150       # 有效行少于这个不给结论（按直线处理）
BEND_W80_MED = 7.0        # 页级 w80 中位 >= 这个 => 整页三段。
                          # 门槛定在"折线开始有收益"的那一档，不是拍脑袋：200 页
                          # 实测（加局部一致性闸后）直线主峰在 4~6（137 页），
                          # 7~9 档 37 页强制跑折线，**18/18 页全部降到 4~5、每页
                          # 9~10 条线都动了**——说明这一档已经是真的轻微弯，不是
                          # 噪声。定 7 会切 ~31% 的页，代价只是 Step2 多做两次
                          # 射影；每条线另有"折线得分不比直线高就退回"的保险。
BEND_W80_MAX = 24.0       # 或任一条线 w80 >= 这个（单条线跑飞的那一型：vol01/11
                          # 页级中位只有 9.5 但单条到 64，只看中位会漏）
KNOT_SEARCH = 40          # 每个折点在直线估计的 ±这么多 px 里找。
                          # 24 不够：vol01/119 L3 段3 真墨离直线中位 23px（到 33）、
                          # L4 段1 中位 18.5px（到 55），折点够不着。扫 24/40/60：
                          # 40 把这两段从 w80 19/22 修到 15/13，60 再无收益（已收敛），
                          # 对照页 vol01/151、11、24、vol02/95 一个数都没变。
                          # 邻列界行相距 ~183px，40 不会跳到隔壁。
KNOT_PASSES = 3           # 坐标下降轮数（实测 2 轮已收敛，第 3 轮保险）
KNOT_GUARD_HITS: list = []   # 诊断：护栏每退回一条线记 (线序号, 该对列宽变化率)，跑批时可清空
PAIR_WIDTH_TOL = 0.25     # 护栏：相邻两条折线之间的间距（列宽）沿高度的变化率上限。
                          # 同一页的线是一起弯的，所以**弯页上列宽也不随高度变**——人裁认可的
                          # 折线金标（vol01/11、119、151，83/90 段）上相邻对的变化率全部 ≤ 8%，
                          # 两册 146 张折线页 1302 对里中位 2.3%、95 分位 12.7%。列宽沿高度
                          # 突变只有一种解释：某条线的折点跑进字里了。2026-09-08 vol02/119
                          # 实锤：c5|c6 共用那条界行下半段印得淡，c6 的 其/在/君/故 竖笔粗且
                          # 连续，「墨落在线上的行数」这个目标下竖笔得分反而高，折点被吸进
                          # c6 46px，c6 宽 175→107（变化率 62%），侧墨 0.165 过不了 L2。
                          # ⚠️ 别拿「折线列宽 vs 直线列宽」当判据（第一版就是）：真弯页上直线
                          # 本身就偏 30px，量到的是弯度不是错误，把金标页 119/151 的 4 条好线
                          # 拉偏了 17~29px。


BEND_COHERE_WIN = 9       # 局部一致性：跟相邻这么多个有效行的 x 中位比
BEND_COHERE_TOL = 3.0     # 偏离超过这么多 px 的行剔掉——碎片是跳的，线是连的


def _rule_rows(binm: np.ndarray, xfn, y0: int, y1: int, w: int
               ) -> tuple[np.ndarray, np.ndarray]:
    """挑出"这一行的墨确实像界行"的行。两道闸：

    1. 窗口里有墨且墨宽 <= BEND_INK_W_MAX（界行 3~6px 宽；宽了是撞上字）。
    2. **局部一致性**：这一行墨的 x 跟相邻 BEND_COHERE_WIN 个有效行的中位差
       不超过 BEND_COHERE_TOL。真线（哪怕弯）在 y 方向是连续的，笔画碎片是
       跳的。没这道闸 vol02/3 会被判成"最弯的页之一"（w80 36），其实界行是
       直的，只是断掉的行里混进了一小截笔画——第 1 道闸拦不住 <=9px 的碎片。

    返回 (有效行 ys, 全部采样 ys)。`xfn(y)` 是当前线的 x，要能吃 ndarray。

    **实现是整批 gather**（2026-09-03 向量化，结果逐位相同）：原来逐行切片
    每页 10 条线 × 2 次 × 600 行的 Python 循环占 `fit_vlines_polyline` 的 38%
    （直线页 86%）。现在 `_row_windows` 一次取出 (n, 81) 的窗口矩阵，墨宽/质心
    用矩阵算；局部一致性闸中段用 sliding_window_view 去掉中心列取中位，两端
    不足 9 个邻居的 4 行仍按原来的截断窗口逐行算，跟旧实现一样。"""
    ys = np.arange(int(y0), int(y1), BEND_Y_STEP)
    rows, lo, win = _row_windows(binm, xfn, ys, w)
    k = win.sum(axis=1)
    good = (k > 0) & (k <= BEND_INK_W_MAX)
    cand_y = rows[good]
    if len(cand_y) < BEND_COHERE_WIN:
        return cand_y.astype(int), ys
    j = np.arange(2 * BEND_SEARCH + 1, dtype=np.float64)
    cx = lo[good] + (win[good] * j).sum(axis=1) / k[good]      # 墨的 x 质心
    half = BEND_COHERE_WIN // 2
    n = len(cx)
    keep = np.zeros(n, dtype=bool)
    for i in list(range(min(half, n))) + list(range(max(half, n - half), n)):
        a, b = max(0, i - half), min(n, i + half + 1)
        nb = np.concatenate([cx[a:i], cx[i + 1:b]])
        keep[i] = len(nb) == 0 or abs(cx[i] - np.median(nb)) <= BEND_COHERE_TOL
    if n > 2 * half:
        sw = np.lib.stride_tricks.sliding_window_view(cx, BEND_COHERE_WIN)   # (n-8, 9)
        nb = np.delete(sw, half, axis=1)                                     # 去掉自己
        mid = np.abs(cx[half:n - half] - np.median(nb, axis=1)) <= BEND_COHERE_TOL
        keep[half:n - half] = mid
    return cand_y[keep].astype(int), ys


def _row_windows(binm: np.ndarray, xfn, ys: np.ndarray, w: int
                 ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """每一行以这条线为中心取 ±BEND_SEARCH 的窗口（新坐标方向，右到左翻回来），
    一次 gather 成 (n, 81)。窗口出界的行整行丢掉（跟旧实现的 `continue` 一样）。
    返回 (保留的行 y, 各行窗口起点 lo（新坐标）, 窗口矩阵)。"""
    c = np.rint(xfn(ys.astype(np.float64))).astype(int)
    lo = c - BEND_SEARCH
    ok = (lo >= 0) & (c + BEND_SEARCH + 1 <= w)
    ys, lo = ys[ok], lo[ok]
    # 新坐标 x = lo + j  <=>  旧列 (w-1) - (lo + j)
    cols = (w - 1) - (lo[:, None] + np.arange(2 * BEND_SEARCH + 1)[None, :])
    win = binm[ys[:, None], cols]
    return ys, lo, win


def gutter_projection(binm: np.ndarray, xfn, y0: int, y1: int, w: int
                      ) -> tuple[float, int, int, int] | None:
    """把一条界行整条投到 x 轴（用户给的直度判据）：线越直，墨全落在同一个 x
    上，峰越高越窄。返回 (peak, w50, w80, n_rows)，n 不够返回 None。

    peak = 投影峰值 ÷ 采样行数（1.0 = 完美）；w50 = 半高宽；w80 = 装下 80% 墨的
    最窄 x 跨度。**判弯用 w80**——线弯成两段时 w50 会出现双峰、被误判成窄。
    """
    rows, _ = _rule_rows(binm, xfn, y0, y1, w)
    if len(rows) < BEND_MIN_ROWS:
        return None
    _, _, win = _row_windows(binm, xfn, rows, w)
    proj = win.sum(axis=0, dtype=np.float64)      # 0/1 计数，整数和，跟逐行累加逐位相同
    p = proj / len(rows)
    pk = float(p.max())
    if pk <= 0:
        return None
    w50 = int((p >= pk / 2.0).sum())
    total, need = p.sum(), p.sum() * 0.80
    best, run, a = len(p), 0.0, 0
    for b in range(len(p)):
        run += p[b]
        while run - p[a] >= need:
            run -= p[a]
            a += 1
        if run >= need:
            best = min(best, b - a + 1)
    return pk, w50, int(best), int(len(rows))


_ALIGN_KERNEL = ((0, 3), (-1, 2), (1, 2), (-2, 1), (2, 1))


def _aligned(binm: np.ndarray, rows: np.ndarray, xs: np.ndarray, w: int) -> int:
    """rows 里的墨落在 xs（新坐标）附近的加权计数——三角核 {0:3, ±1:2, ±2:1}。
    就是"投影峰在 0 处的高度"，但**峰是尖的**：界行 3~6px 宽，用 ±1 硬窗口
    会在线上出现一段平台、折点定不到线心（合成页实测偏 2.9px）；三角核让
    线心处唯一最高。"""
    xo = (w - 1) - np.rint(xs).astype(int)          # 转回旧坐标列号
    total = 0
    for d, wt in _ALIGN_KERNEL:
        xx = xo + d
        ok = (xx >= 0) & (xx < w)
        total += wt * int((binm[rows[ok], xx[ok]] > 0).sum())
    return total


def _aligned_batch(binm: np.ndarray, rows: np.ndarray, xs: np.ndarray, w: int) -> np.ndarray:
    """`_aligned` 的批量版：xs 是 (n_rows, n_cand)，一次算 n_cand 个候选线的得分。
    折点搜索里每个折点要试 81 档偏移，原来是 81 × 5 次小 gather（每页 1.4 万次
    `_aligned` 调用占弯页 `fit_vlines_polyline` 的 49%），现在 5 次 (n_rows, 81)
    的 gather。逐元素算式跟 `_aligned` 相同（同样的 rint / 出界置零），
    结果逐位相同。"""
    xo = (w - 1) - np.rint(xs).astype(int)
    total = np.zeros(xs.shape[1], dtype=np.int64)
    ridx = rows[:, None]
    for d, wt in _ALIGN_KERNEL:
        xx = xo + d
        ok = (xx >= 0) & (xx < w)
        hit = (binm[ridx, np.clip(xx, 0, w - 1)] > 0) & ok
        total += wt * hit.sum(axis=0)
    return total


def _from_knots(kx: list[float], ky: list[float]) -> VLine:
    """四个折点 x + 四个折点 y -> (x, k1, k2, k3)，精确等价。"""
    k1 = (kx[1] - kx[0]) / (ky[1] - ky[0])
    k2 = (kx[2] - kx[1]) / (ky[2] - ky[1])
    k3 = (kx[3] - kx[2]) / (ky[3] - ky[2])
    return VLine(x_at_top=float(kx[0] - k1 * ky[0]), slope=float(k1),
                 k2=float(k2), k3=float(k3), y1=float(ky[1]), y2=float(ky[2]))


# ---------------------------------------------------------------- 下版框：推到框条上

#: `push_bottom_to_bar`（2026-09-20）。Step1 的下版框线在这批书上有两种落点：
#: 贴在框条上方的白缝里（+4~+11px，vol02 67 页）或粗条之下（55 页，`_descend_to_ink_bottom`
#: 的下沿路线）——都不切字。错的是第三种：内框磨没了，线塌到**最后一行字的底边**，
#: 真框条在 12~40px 之下（p35/p106/p79/p32/p70…，vol02 25 页、vol01 22 页）。
#: 这一步只修第三种：线下第一条「够格的横条」（≥BPUSH_MIN_ROWS 行、桥接 ≤6px 断口后
#: 最长横段 ≥BPUSH_MIN_RUN_FRAC×版框宽——字的底边横段最长只有 3~7%，p105 那种 9% 的
#: 鬼影也够不着）离线 ≥BPUSH_MIN_SHIFT px 才动，动到条上沿 −BPUSH_MARGIN，**只往下**
#: （用户 2026-09-13 定的单侧口径：宁可多留白，不可切字）。取**第一条**不取最后一条：
#: 雙邊框页内框细线在 +4~+11、外框在 +25，取最后一条会把线推过内框。
BPUSH_UP = 6
BPUSH_DOWN = 70
BPUSH_BRIDGE = 6
BPUSH_STRUCT_COV = 0.08
BPUSH_MIN_ROWS = 3
BPUSH_MIN_RUN_FRAC = 0.12
BPUSH_MARGIN = 4
BPUSH_MIN_SHIFT = 8
BPUSH_MAX_SHIFT = 45


def _bridge_row(row: np.ndarray, maxgap: int) -> np.ndarray:
    """把一行里 ≤maxgap 的断口填上（横向闭运算），返回 bool 行。"""
    r = row.astype(bool).copy()
    if not r.any():
        return r
    d = np.diff(np.concatenate(([0], r.astype(np.int8), [0])))
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)   # 墨段 [start, end)
    for e, s in zip(ends[:-1], starts[1:]):
        if s - e <= maxgap:
            r[e:s] = True
    return r


def _longest_true_run(r: np.ndarray) -> int:
    if not r.any():
        return 0
    d = np.diff(np.concatenate(([0], r.astype(np.int8), [0])))
    return int((np.flatnonzero(d == -1) - np.flatnonzero(d == 1)).max())


def push_bottom_to_bar(binm: np.ndarray, bottom: HLine, verticals: list[VLine],
                       width: int, height: int) -> tuple[HLine, float]:
    """下版框线之下若有真框条、线又离它 ≥BPUSH_MIN_SHIFT，把线推到条上沿之上。
    返回 (新线, 推了多少 px)。见 BPUSH_* 常量注释。"""
    from dataclasses import replace as _replace
    if len(verticals) < 2:
        return bottom, 0.0
    vx = sorted((width - 1) - v.x_at(height * 0.9) for v in verticals)
    x0, x1 = int(vx[0] + 15), int(vx[-1] - 15)
    if x1 - x0 < 100:
        return bottom, 0.0
    xs = np.arange(x0, x1)
    base = np.array([bottom.y_at((width - 1) - x) for x in xs])
    fw = len(xs)
    rows = []
    for o in range(0, BPUSH_DOWN + 1):
        yy = (base + o).astype(int)
        ok = (yy >= 0) & (yy < height)
        r = np.zeros(fw, bool)
        r[ok] = binm[yy[ok], xs[ok]] > 0
        rows.append(_bridge_row(r, BPUSH_BRIDGE))
    cov = np.array([r.mean() for r in rows])
    struct = cov >= BPUSH_STRUCT_COV
    # 从线往下第一组「够格的条」
    i = 0
    while i < len(struct):
        if not struct[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(struct) and (struct[j + 1] or (j + 2 < len(struct) and struct[j + 2])):
            j += 1
        n_rows = j - i + 1
        run = max(_longest_true_run(rows[k]) for k in range(i, j + 1))
        if n_rows >= BPUSH_MIN_ROWS and run >= BPUSH_MIN_RUN_FRAC * fw:
            target = i - BPUSH_MARGIN
            if target < BPUSH_MIN_SHIFT:
                return bottom, 0.0
            shift = float(min(target, BPUSH_MAX_SHIFT))
            return _replace(bottom, y_at_right=bottom.y_at_right + shift), shift
        i = j + 1
    return bottom, 0.0


# ---------------------------------------------------------------- 界行：按证据重定位

#: `snap_verticals_to_evidence`（2026-09-20）。折线拟合只认「墨落在线上 ±1px」，界行
#: 淡到看不见的横带里它会去贴字的竖笔；vol02 后半册（p149~185）一半以上横带没有可见
#: 界行，p160 v3~v5 在页底偏出 25~45px、v3 直接穿进文字列；p177/p178 只有顶端 10% 印了
#: 界行，下面整段外推，偏到 80px。**能看见界行的地方线从不偏**（两册普查：有界行的
#: 横带里偏移全部 ≤2px），所以这一步只在没有界行证据的横带用**文字缝中心**当证据，
#: 与有界行横带的界行位置一起重新拟合三段折线；证据不足或改动 <SNAP_MIN_CHANGE 的线
#: 原样保留，外框线（首尾两条）不动。
SNAP_K = 8                  # 横带数
SNAP_RULE_SEARCH = 30       # 界行在线位 ±这么多 px 里找
SNAP_RULE_MIN_FRAC = 0.5    # 沿线 3px 宽、桥接 ≤SNAP_RULE_GAP 行后最长竖段 ≥ 带高的这个比例才算界行
SNAP_RULE_GAP = 3           # （字的竖笔最长只到一个字高 ≈ 带高 0.37，够不着 0.5）
SNAP_GAP_INK = 0.02         # 文字缝：列投影 ≤ 此值的连续段
SNAP_GAP_MIN_W = 30         # 缝至少这么宽（有界行的缝只有 15~20，不会被当成无界行缝）
SNAP_GAP_MAX_FRAC = 0.55    # 缝至多 0.55×列距（跨过空白列的不算）
SNAP_FLANK = 100            # 缝两侧这么多 px 内都要有字墨（≥SNAP_FLANK_INK）
SNAP_FLANK_INK = 0.10
SNAP_TEXT_DENSE = 0.20      # 线位 ±12px 的列投影均值 ≥ 此值 ⇒ 线**压在字上**（这条线有病）。
                            # vol02 全书无界行横带的这个量：0.02~0.16 是一大坨（淡界行、离字边 10~15px
                            # 的线），0.20 以上才是真压在字上的尾巴（p177 实测 0.24~0.48）。0.12 时
                            # 175/188 页被判有病。擦进字边 ≤5px 的不算——那是 Step2 侧削的量级。
                            # 淡界行是一条 3~5px 的细线，±12 均值到不了 0.15；字是 100px 宽的墨块。
                            # 「线不在零墨缝里」不能当有病——淡到长竖段判据都看不见的界行照样把
                            # 零墨缝切断，按那条判 vol02 178/188 页全「有病」，线被拉到界行旁边的
                            # 缝里去（fix3 实测，p160 v7 反而偏出 39px）。
SNAP_GAP_CLEAR = 8          # 线在零墨缝里、离缝两端都 ≥ 这么多 px ⇒ 这一带线位没问题。
                            # **判定按整条线**：所有横带都在界行上或缝里 ⇒ 这条线健康，一动不动
                            # （缝中心不是界行位置——两侧文字列不对称时差 ±18px，p160 v4 实测，
                            # 健康的线不该被拉去凑缝中心）；只要有一带压到字/贴着字边、或离可见
                            # 界行 ≥SNAP_MIN_DEVIATION ⇒ 这条线有病，整条按「界行位 + 缝中心」重铺
                            # （缝中心 = 离两侧文字最远，正是 Step2/3 要的）。半锚半拉会在折点处
                            # 拧出假弯（合成页实测顶端被带偏 7px），所以不做混合。
SNAP_MIN_TARGETS = 4
SNAP_MIN_DEVIATION = 8.0    # 至少一个横带的证据离现役线 ≥ 这么多才值得重拟合
SNAP_RESID = 15.0           # 第一轮拟合后残差超过这个的证据点剔掉再拟一次
SNAP_REG = 0.01             # 折点往现役线拉的弱正则（没证据的段保持原状；0.05 会把 p177 底端折点拉回 9px）
SNAP_MIN_CHANGE = 4.0       # 拟合结果与现役线最大差 < 这个就不换（防抖）
SNAP_PITCH_LO, SNAP_PITCH_HI = 0.6, 1.4   # 换线后与邻线间距须在列距的这个范围内


def _rule_offset(binm: np.ndarray, v: VLine, width: int, y0: int, y1: int) -> float | None:
    ys = np.arange(y0, y1, 2)
    base = (width - 1) - v.x_at(ys.astype(float))
    best = None
    for d in range(-SNAP_RULE_SEARCH, SNAP_RULE_SEARCH + 1):
        xs = np.round(base + d).astype(int)
        ok = (xs >= 1) & (xs < width - 1)
        if ok.sum() < 10:
            continue
        col = np.maximum.reduce([binm[ys[ok], xs[ok] - 1], binm[ys[ok], xs[ok]], binm[ys[ok], xs[ok] + 1]]) > 0
        # 桥接 ≤SNAP_RULE_GAP 个采样点（每点 2 行）
        b = c = g = 0
        for t in col:
            if t:
                c += 1; g = 0
            else:
                g += 1
                if g > SNAP_RULE_GAP:
                    c = 0
            b = max(b, c)
        s = b / max(1, len(col))
        if s >= SNAP_RULE_MIN_FRAC and (best is None or s > best[1] or (s == best[1] and abs(d) < abs(best[0]))):
            best = (d, s)
    return None if best is None else float(best[0])


def _gap_target(colp: np.ndarray, xl: int, pitch: float, width: int,
                xp: float | None = None) -> tuple[float, bool] | None:
    """无界行横带的缝证据。返回 (选中缝的中心, 线是否已稳稳在缝里)；没有合格缝 ⇒ None。
    「在缝里」= 线在缝内且离两端都 ≥SNAP_GAP_CLEAR。

    `xp`：这一带线**应该**在哪的先验（调用方给邻线中点——列等距）。线压在字上时它左右
    两条缝几乎等距，按「离线最近」选缝是抛硬币，选错就差一整列；按邻线中点选不会错。"""
    half = int(pitch * 0.6)
    lo, hi = max(0, xl - half), min(width, xl + half + 1)
    seg = colp[lo:hi] <= SNAP_GAP_INK
    runs, a = [], None
    for i, z in enumerate(list(seg) + [False]):
        if z and a is None:
            a = i
        if not z and a is not None:
            runs.append((a, i - 1)); a = None
    runs = [r for r in runs if SNAP_GAP_MIN_W <= r[1] - r[0] + 1 <= SNAP_GAP_MAX_FRAC * pitch]
    if not runs:
        return None
    rel = xl - lo
    ref = rel if xp is None else xp - lo
    ra, rb = min(runs, key=lambda r: abs((r[0] + r[1]) / 2.0 - ref))
    left = colp[max(0, lo + ra - SNAP_FLANK):lo + ra].max() if lo + ra > 0 else 0.0
    right = colp[lo + rb + 1:min(width, lo + rb + 1 + SNAP_FLANK)].max() if lo + rb + 1 < width else 0.0
    if left < SNAP_FLANK_INK or right < SNAP_FLANK_INK:
        return None
    inside = ra + SNAP_GAP_CLEAR <= rel <= rb - SNAP_GAP_CLEAR
    return lo + (ra + rb) / 2.0, inside


def _fit_knots(ys: np.ndarray, xs: np.ndarray, ws: np.ndarray, ky: list[float],
               kx0: list[float]) -> list[float]:
    """带权最小二乘拟合连续三段折线的 4 个折点 x（帽函数基），弱正则拉向 kx0。"""
    A = np.zeros((len(ys), 4))
    for n, y in enumerate(ys):
        i = 0 if y <= ky[1] else (1 if y <= ky[2] else 2)
        t = (y - ky[i]) / (ky[i + 1] - ky[i])
        A[n, i] = 1 - t; A[n, i + 1] = t
    sw = np.sqrt(ws)
    Aw = A * sw[:, None]; bw = xs * sw
    reg = np.sqrt(SNAP_REG)
    Aw = np.vstack([Aw, reg * np.eye(4)]); bw = np.concatenate([bw, reg * np.array(kx0)])
    sol, *_ = np.linalg.lstsq(Aw, bw, rcond=None)
    return [float(x) for x in sol]


def snap_verticals_to_evidence(binm: np.ndarray, top: HLine, bottom: HLine,
                               verticals: list[VLine], width: int, height: int
                               ) -> tuple[list[VLine], int]:
    """内部界行逐条按横带证据（界行 / 文字缝中心）重拟合三段折线。返回 (新线表, 换了几条)。
    见 SNAP_* 常量注释。输入输出都是新坐标系的 VLine；证据在原图坐标里量。"""
    n = len(verticals)
    if n < 4:
        return verticals, 0
    vx_raw = sorted((width - 1) - v.x_at(height / 2.0) for v in verticals)
    pitch = float(np.median(np.diff(vx_raw)))
    if pitch < 40:
        return verticals, 0
    xc_mid = verticals[n // 2].x_at(height / 2.0)
    yt_g, yb_g = int(top.y_at(xc_mid)), int(bottom.y_at(xc_mid))
    if yb_g - yt_g < 400:
        return verticals, 0
    bands = []
    for k in range(SNAP_K):
        y0 = yt_g + int((yb_g - yt_g) * k / SNAP_K); y1 = yt_g + int((yb_g - yt_g) * (k + 1) / SNAP_K)
        bands.append((y0, y1, (y0 + y1) // 2, binm[y0:y1, :].mean(axis=0)))
    out = list(verticals)
    cands: dict[int, VLine] = {}
    for vi in range(1, n - 1):
        v = verticals[vi]
        ys, xs, ws = [], [], []
        sick = False
        for (y0, y1, yc, colp) in bands:
            xl_new = float(v.x_at(float(yc)))
            xl_raw = int(round((width - 1) - xl_new))
            d = _rule_offset(binm, v, width, y0, y1)
            if d is not None:
                ys.append(yc); xs.append(xl_new - d); ws.append(1.0)     # 原图 +d ⇒ 新坐标 −d
                if abs(d) >= SNAP_MIN_DEVIATION:
                    sick = True
                continue
            if colp[max(0, xl_raw - 12):xl_raw + 13].mean() >= SNAP_TEXT_DENSE:
                sick = True                       # 压在字上（见 SNAP_TEXT_DENSE）
            xp_raw = (width - 1) - (verticals[vi - 1].x_at(float(yc)) + verticals[vi + 1].x_at(float(yc))) / 2.0
            gt = _gap_target(colp, xl_raw, pitch, width, xp_raw)
            if gt is not None:
                g, _inside = gt
                # 缝证据一律用缝中心（见 SNAP_GAP_CLEAR 注释）；健康的线下面直接跳过，不会用到
                ys.append(yc); xs.append((width - 1) - g); ws.append(1.0)
        if not sick or len(ys) < SNAP_MIN_TARGETS:
            continue
        xc = v.x_at(height / 2.0)
        yt, yb = float(top.y_at(xc)), float(bottom.y_at(xc))
        ky = [yt, yt + (yb - yt) / 3.0, yt + 2.0 * (yb - yt) / 3.0, yb]
        kx0 = [float(v.x_at(y)) for y in ky]
        ys_a, xs_a, ws_a = np.array(ys, float), np.array(xs, float), np.array(ws, float)
        kx = _fit_knots(ys_a, xs_a, ws_a, ky, kx0)
        cand = _from_knots(kx, ky)
        resid = np.abs(np.array([cand.x_at(float(y)) for y in ys_a]) - xs_a)
        keep = resid <= SNAP_RESID
        if keep.sum() >= SNAP_MIN_TARGETS and keep.sum() < len(ys_a):
            kx = _fit_knots(ys_a[keep], xs_a[keep], ws_a[keep], ky, kx0)
            cand = _from_knots(kx, ky)
        elif keep.sum() < SNAP_MIN_TARGETS:
            continue
        change = max(abs(cand.x_at(float(yc)) - v.x_at(float(yc))) for (_, _, yc, _) in bands)
        if change < SNAP_MIN_CHANGE:
            continue
        cands[vi] = cand
    # 邻线间距护栏：按邻线的候选量（邻线没候选就按旧线）。整页一起偏的页（p177）
    # 旧邻线本身是错的，按旧邻线量会把正确的纠正当成「间距 1.45×列距」拒掉。
    changed = 0
    for vi, cand in cands.items():
        ok = True
        xc = verticals[vi].x_at(height / 2.0)
        yt, yb = float(top.y_at(xc)), float(bottom.y_at(xc))
        for y in (yt, yt + (yb - yt) / 3.0, yt + 2.0 * (yb - yt) / 3.0, yb):
            for ni in (vi - 1, vi + 1):
                nb = cands.get(ni, verticals[ni])
                gap = abs(cand.x_at(y) - nb.x_at(y))
                if not (SNAP_PITCH_LO * pitch <= gap <= SNAP_PITCH_HI * pitch):
                    ok = False
        if ok:
            out[vi] = cand
            changed += 1
    return out, changed


def fit_vlines_polyline(mask: np.ndarray, top: HLine, bottom: HLine,
                        verticals: list[VLine], w: int, h: int, fit: bool = True
                        ) -> tuple[list[VLine], int, float | None, float | None]:
    """按弯度决定整页用直线还是三段折线，弯就逐线拟合折线。
    返回 (verticals, segments, w80_med, w80_max)。

    `fit=False`：只量 w80（给闸1 的 L2 旗标用），**不拟合**，整页保持直线。
    给界行淡而断的书用（`BookSpec.vline_polyline: false`）：那种书上 w80 量的是
    "线有多断"不是"线有多弯"——北行日錄刻本平直扫描页 w80 中位 41、远超
    BEND_W80_MED=7，整页被判成弯页；折点得分在淡线上是噪声，某条线找到一个
    假最优、失败的邻居再照抄它的位移，全页 20 条线齐刷刷平移 33~39px 落到空白
    纸上（p40/p41 实测），闸2 因此只剩 1/19 列过闸。

    **先量再改**：先在直线拟合下算每条线的 w80，页级中位 >= BEND_W80_MED 或任
    一条 >= BEND_W80_MAX 才进入三段；否则原样返回、segments=1。**整页统一**——
    用户要求"要变整个页面都变"，Step2 分带逻辑也只看页级标志。

    三段的拟合不按 k1→k2→k3 顺序贪心搜（前一段的误差会往下传），而是直接搜
    四个折点的 x（x0/xa/xb/x3，在这条线跟上版框、1/3、2/3、下版框交点处），
    连续性天然满足；目标 = 相邻段"墨落在线上 ±1px"的行数（= 投影峰在 0 处的
    高度，就是用户说的"投影最能出现高峰"）。坐标下降 KNOT_PASSES 轮。最后换算
    成 (x, k1, k2, k3)，精确等价。某条线折线得分不高于直线时退回直线斜率
    （k2=k3=k1），格式仍是三段，整页保持一致。
    """
    binm = (mask > 0).astype(np.uint8)
    metrics = []
    for v in verticals:
        xc = v.x_at(h / 2.0)
        y0 = int(top.y_at(xc)) + 30
        y1 = int(bottom.y_at(xc)) - 30
        m = gutter_projection(binm, v.x_at, y0, y1, w) if y1 - y0 > 400 else None
        metrics.append(m)
    w80s = [m[2] for m in metrics if m]
    if not w80s:
        return verticals, 1, None, None
    w80_med, w80_max = float(np.median(w80s)), float(max(w80s))
    if not fit:
        return verticals, 1, w80_med, w80_max
    if w80_med < BEND_W80_MED and w80_max < BEND_W80_MAX:
        return verticals, 1, w80_med, w80_max

    out, shifts, failed = [], [], []
    for vi, v in enumerate(verticals):
        xc = v.x_at(h / 2.0)
        yt, yb = float(top.y_at(xc)), float(bottom.y_at(xc))
        if yb - yt < 400:
            out.append(VLine(v.x_at_top, v.slope, v.slope, v.slope,
                             yt + (yb - yt) / 3, yt + 2 * (yb - yt) / 3))
            continue
        ky = [yt, yt + (yb - yt) / 3.0, yt + 2.0 * (yb - yt) / 3.0, yb]
        kx = [v.x_at(y) for y in ky]                      # 直线初值
        rows_all, _ = _rule_rows(binm, v.x_at, int(yt), int(yb), w)
        if len(rows_all) < BEND_MIN_ROWS:
            out.append(VLine(v.x_at_top, v.slope, v.slope, v.slope, ky[1], ky[2]))
            failed.append(vi)
            continue

        # 三段的行集合和归一化位置 t 在整个坐标下降里不变，先算好
        segs = []
        for i in range(3):
            r = rows_all[(rows_all >= ky[i]) & (rows_all < ky[i + 1])]
            segs.append((r, (r - ky[i]) / (ky[i + 1] - ky[i]) if len(r) else None))

        def seg_score(i, xa, xb):
            r, t = segs[i]
            if len(r) == 0:
                return 0
            return _aligned(binm, r, xa + t * (xb - xa), w)

        offs = np.arange(-KNOT_SEARCH, KNOT_SEARCH + 1, dtype=np.float64)
        base_score = sum(seg_score(i, kx[i], kx[i + 1]) for i in range(3))
        for _ in range(KNOT_PASSES):
            moved = False
            for j in range(4):
                xs_all = kx[j] + offs                          # 81 个候选折点 x
                sc = np.zeros(len(offs), dtype=np.int64)
                if j > 0:                                      # 左段：xa 固定，xb 变
                    r, t = segs[j - 1]
                    if len(r):
                        xa = kx[j - 1]
                        sc += _aligned_batch(binm, r, xa + t[:, None] * (xs_all[None, :] - xa), w)
                if j < 3:                                      # 右段：xa 变，xb 固定
                    r, t = segs[j]
                    if len(r):
                        xb = kx[j + 1]
                        sc += _aligned_batch(binm, r, xs_all[None, :] + t[:, None] * (xb - xs_all[None, :]), w)
                # 跟旧的逐档循环同一条挑选规则：分数严格更高才换；平分取 |d| 更小的
                best, best_x = None, kx[j]
                for di, d in enumerate(range(-KNOT_SEARCH, KNOT_SEARCH + 1)):
                    x = kx[j] + d
                    s_ = int(sc[di])
                    if best is None or s_ > best or (s_ == best and abs(d) < abs(best_x - kx[j])):
                        best, best_x = s_, x
                if best_x != kx[j]:
                    kx[j] = best_x
                    moved = True
            if not moved:
                break
        new_score = sum(seg_score(i, kx[i], kx[i + 1]) for i in range(3))
        if new_score <= base_score:
            out.append(VLine(v.x_at_top, v.slope, v.slope, v.slope, ky[1], ky[2]))
            continue
        shifts.append([kx[j] - v.x_at(ky[j]) for j in range(4)])
        out.append(_from_knots(kx, ky))

    # 拟合失败的线（有效行不够）借同页已拟合线的折点位移——**同一页的线是一起
    # 弯的**（纸张/雕版形变是整页的），这个先验比"退回直线"强得多。
    # 治的是最外侧那两条框线：窗口里同时压着内框细线和外框粗条，合起来墨宽
    # 中位 17~21px，被 BEND_INK_W_MAX 全剔掉，有效行只剩 83/1185（vol01/11 L1）
    # 和 46/1197（vol01/119 L1）。
    if shifts and failed:
        med = np.median(np.array(shifts), axis=0)
        for i in failed:
            v = verticals[i]
            xc = v.x_at(h / 2.0)
            yt, yb = float(top.y_at(xc)), float(bottom.y_at(xc))
            ky = [yt, yt + (yb - yt) / 3.0, yt + 2.0 * (yb - yt) / 3.0, yb]
            out[i] = _from_knots([v.x_at(ky[j]) + med[j] for j in range(4)], ky)

    # ── 护栏：折点被邻列字的竖笔勾走（见 PAIR_WIDTH_TOL 注释）────────────
    # 折线得分只看「墨落在线上的行数」，分不清淡界行和粗竖笔；「得分不比直线高就退回」
    # 在这种情况下不触发（勾到字上得分更高）。几何兜底：相邻两条折线的间距沿高度
    # 变化超过 PAIR_WIDTH_TOL 就是断裂对。断裂对里退谁——看另一侧：一条线若两侧的对
    # 都断（或它是外框线、另一侧无对），退它；否则退另一侧也断的那条；两条都只此一侧
    # 断时退折点位移更大的那条。退回的形状用**相邻线的局部位移插值**（同页的线一起弯，
    # 邻线怎么弯它就怎么弯），不用页级中位——中位会被少数跑飞的线带偏。最多扫两轮。
    n_out = len(out)
    if n_out >= 2:
        def _ys(i):
            xc = verticals[i].x_at(h / 2.0)
            yt, yb = float(top.y_at(xc)), float(bottom.y_at(xc))
            return [yt + 30.0, yt + (yb - yt) / 3.0, yt + (yb - yt) / 2.0, yt + 2.0 * (yb - yt) / 3.0, yb - 30.0]
        def _pair_var(i):
            ws = [abs(out[i + 1].x_at(y) - out[i].x_at(y)) for y in _ys(i)]
            lo = min(ws)
            return (max(ws) / lo - 1.0) if lo > 1e-6 else float('inf')
        def _shift(i, y):
            return out[i].x_at(y) - verticals[i].x_at(y)
        def _revert(k):
            v = verticals[k]
            xc = v.x_at(h / 2.0)
            yt, yb = float(top.y_at(xc)), float(bottom.y_at(xc))
            ky = [yt, yt + (yb - yt) / 3.0, yt + 2.0 * (yb - yt) / 3.0, yb]
            nb = [j for j in (k - 1, k + 1) if 0 <= j < n_out]
            kx = [v.x_at(y) + (sum(_shift(j, y) for j in nb) / len(nb) if nb else 0.0) for y in ky]
            out[k] = _from_knots(kx, ky)
        for _pass in range(2):
            bad = [i for i in range(n_out - 1) if _pair_var(i) > PAIR_WIDTH_TOL]
            if not bad:
                break
            done: set[int] = set()
            for i in bad:
                a, b = i, i + 1
                if a in done or b in done:
                    continue
                a_other = (a == 0) or (_pair_var(a - 1) > PAIR_WIDTH_TOL)
                b_other = (b == n_out - 1) or (_pair_var(b) > PAIR_WIDTH_TOL)
                if a_other and not b_other:
                    k = a
                elif b_other and not a_other:
                    k = b
                else:
                    da = max(abs(_shift(a, y)) for y in _ys(a))
                    db = max(abs(_shift(b, y)) for y in _ys(a))
                    k = a if da >= db else b
                KNOT_GUARD_HITS.append((k, round(float(_pair_var(i)), 3)))
                _revert(k)
                done.add(k)
    return out, 3, w80_med, w80_max


def measure_book_outer_shift(results, masks, ink: float = OUTER_INK_MIN) -> dict:
    """量一册的 `outer_shift`：上/下外框中心相对「竖直外框内外间距」的差。

    版框四边不等距，`detect_outer_borders` 的搜索窗口是拿竖直外框的间距当先验、
    再按边校正过去的。**这个校正量按书变**：vol01 量出 top -4.2 / bottom -6.3，
    vol02 实测 **top -12.0 / bottom -19.8**（n=136/110，std 7.9/6.5）。差 8~13px
    看着不多，但这批书的上下外框只有 3~5px 厚（竖直外框 19~24px），窗口偏一点
    就把它挤到边上、凑不满 `OUTER_RUN_MIN`，整册漏报几十页。

    `results`/`masks`：整册的 `BorderDetectionResult` 与对应二值 mask（同序）。
    返回 `{"top": float, "bottom": float}`，量不到的边不进字典。
    ⚠️ 只在标定时跑一次写进 yaml，别放进逐页流水线——那等于每页重跑全书。
    """
    acc: dict[str, list[float]] = {"top": [], "bottom": []}
    for res, binm in zip(results, masks):
        if res is None or binm is None or res.v_outer_offset is None:
            continue
        h, w = binm.shape[:2]
        vx = sorted((w - 1) - v.x_at(h / 2.0) for v in res.verticals)
        if len(vx) < 2:
            continue
        xs = np.arange(int(vx[0] + 30), int(vx[-1] - 30), 2)
        if len(xs) < 10:
            continue
        prior = abs(res.v_outer_offset)
        for kind, line, sign in (("top", res.top, -1.0), ("bottom", res.bottom, 1.0)):
            base = np.array([line.y_at((w - 1) - x) for x in xs])
            lo, hi = 10, 70
            prof = []
            for o in range(lo, hi + 1):
                yy = (base + o * sign).astype(int)
                ok = (yy >= 0) & (yy < h)
                prof.append(float(binm[yy[ok], xs[ok]].mean()) if ok.any() else 0.0)
            prof = np.array(prof)
            idx = np.where(prof >= ink)[0]
            if idx.size == 0:
                continue
            runs, a, b = [], idx[0], idx[0]
            for q in idx[1:]:
                if q == b + 1:
                    b = q
                else:
                    runs.append((a, b)); a = b = q
            runs.append((a, b))
            best = max(runs, key=lambda t: prof[t[0]:t[1] + 1].mean() * (t[1] - t[0] + 1))
            acc[kind].append(lo + (best[0] + best[1]) / 2.0 - prior)
    return {k: float(np.median(v)) for k, v in acc.items() if v}


def measure_book_bottom_gap(grays, ink_threshold: int = 128) -> float | None:
    """整册「页高 − 下版框 y」的中位数，给下版框跨页先验救援当基准。

    **不需要金标**：三册实测，整册算法输出的中位数与金标真基准只差 0~1px
    （vol02 完全相等 327.0，vol03 差 1.0）；截尾均值反而更差，众数分箱在
    vol02 上差 5.5px，都不如直接取中位数。三册的值也高度一致（325/327/326），
    但仍按册现算而不写死常数——换一种版式的书就未必是这个数。

    异常页高的扫描要先排掉（封面类整页近全黑的图会给出荒谬的"版框"，
    实测 vol01/1 等页高 1359 vs 正常 ~3100）。这里按页高中位数 ±15% 过滤；
    这类页在生产里本来也已被闸1判为 skip。
    """
    hs = [g.shape[0] for g in grays]
    if not hs:
        return None
    med_h = float(np.median(hs))
    vals = []
    for g in grays:
        h, w = g.shape[:2]
        if abs(h - med_h) > 0.15 * med_h:
            continue
        mask = (g < ink_threshold).astype(np.float64)
        m = find_horizontal_border(mask, "bottom")
        vals.append(h - (m.position + m.slope * ((w - 1) / 2.0 - w / 2.0)))
    return float(np.median(vals)) if vals else None


def detect_borders(gray: np.ndarray, expected_cols: int,
                    ink_threshold: int = 128,
                    book_bottom_gap: float | None = None,
                    top_band_frac: float | None = None,
                    bottom_band_frac: float | None = None,
                    column_grid: bool = False,
                    col_pitch: float | None = None,
                    frame_height: float | None = None,
                    vline_polyline: bool = True,
                    outer_shift: dict | None = None) -> BorderDetectionResult:
    """整页边框+界行探测，输出新坐标系约定的结果。

    `expected_cols`：这一页应有的列数 N——竖直线应有 N+1 条（左右外边框各
    一 + N-1 条内部界行），跟 `peak_line_search.find_vertical_lines` 的
    `expected_count` 用法一致。

    `column_grid` / `col_pitch`：竖线走**网格模式**（`find_vertical_lines_grid`）——
    版框定死、列距均匀、逐槽验线、缺槽插值，结果里 `vline_filled` 标出插值的槽。
    给**界行没印全**的书用（北行日錄刻本 12.3% 的槽位没线，自由模式只能拿字身
    假峰凑数）。不开就是加这套之前的行为，逐位不变。`col_pitch` 是列距先验
    （`BookSpec.col_pitch`），给了用来过滤版框对。

    ⚠️ **网格模式不是自由模式的超集**，不要拿它当默认。没有 `col_pitch` 约束时
    选版框对可能挑到被拉伸（甚至半列距）的一对，反而比自由模式差——四庫總目
    vol02/176 实测：无先验时选中列距 93.22（真值 ~185），10 条线全挤到页面右半边、
    齐刷刷穿字；给上 `col_pitch=184` 就选对了。vol02/3 是同一病的轻症。
    两本书 394 页实测：381 页两模式逐位相同，差异集中在版框一端只有粗外条的页。
    见 overview 仓 `图片初步数字化/进度/北行日录古本/03-竖线探测模块化.md` §A。

    `col_pitch` / `frame_height`：网格模式那几个阈值原本是在北行日錄刻本
    （列距 119、框高 1482）上标的**绝对像素**，这两个先验给了就按
    `peak_line_search.grid_thresholds()` 换算到本书尺度。不给则退回那组绝对值
    ——**换一本分辨率差一倍的书不报错、只静默退化**（整页插值或整页验不上）。

    `vline_polyline=False`：界行不做三段折线拟合，只量 w80。理由见
    `fit_vlines_polyline` 的 `fit` 参数。

    `book_bottom_gap`：整册「页高 − 下版框 y」的中位数，用于下版框的跨页先验
    救援（见 `peak_line_search._rescue_bottom`）。不传就不救，行为与改动前
    逐位相同——单页函数拿不到整册统计，只能由调用方按册算好传进来，
    `measure_book_bottom_gap()` 就是干这个的。

    `top_band_frac` / `bottom_band_frac`：上/下版框的**搜索带占页高的比例**，
    不传就用 `find_horizontal_border` 的默认 0.15。

    ⚠️ **天头比页高的 15% 还宽时必须调大 `top_band_frac`**，否则真版框根本
    不在搜索窗口里，探测器只能在天头空白/书名装饰里挑一个峰——而且它**不报错**，
    只是给出一个偏上几百 px 的 `top`，下游列窗整体上移、列图切歪，最后表现为
    闸2 大批列 `side_floor` 超标（看着像"界行没剥干净"，其实是窗口就没对）。
    北行日錄刻本（筒子页，天头 ≈585px / 页高 2343px = 25%）实测：0.15 时
    54/54 页全部落空、误差中位 440px；0.26 起误差中位 12px 且到 0.40 稳定不变
    （不是卡在临界值上）。见 `BookSpec.top_band_frac`。
    """
    h, w = gray.shape[:2]
    mask = (gray < ink_threshold).astype(np.float64)

    if column_grid:
        # 阈值按本书的列距/框高换算；两个先验都不给时 grid_thresholds 原样返回
        # 北行日錄那组标定值，与加这套之前逐位相同。
        vlines_old, filled_old = find_vertical_lines_grid(
            mask, n_lines=expected_cols + 1, col_pitch=col_pitch,
            **grid_thresholds(col_pitch, frame_height))
    else:
        vlines_old = find_vertical_lines(mask, expected_count=expected_cols + 1)
        filled_old = [False] * len(vlines_old)
    # 上下边框曾经各 1.4s、并成 2 线程有收益；分块 BLAS 之后各只剩 0.17s，
    # 线程开销反而更大——跟窗口级线程池一起撤了，理由见 peak_line_search.py 顶部。
    top_kw = {} if top_band_frac is None else {"band_frac": float(top_band_frac)}
    bot_kw = {} if bottom_band_frac is None else {"band_frac": float(bottom_band_frac)}
    top_old = find_horizontal_border(mask, "top", **top_kw)
    bottom_old = find_horizontal_border(mask, "bottom", verticals=vlines_old,
                                        book_gap=book_bottom_gap, **bot_kw)

    # 新坐标系 x 向左递增：旧坐标里越靠右(x_old越大) -> 新坐标x_new越小，
    # 按 x_at_top 升序排列正好就是"从右到左"，对应列号从1开始递增。
    # filled 标记跟着线一起排。
    pairs = sorted(zip((_vline_to_new(m, w, h) for m in vlines_old), filled_old),
                   key=lambda t: t[0].x_at_top)
    verticals = [v for v, _ in pairs]
    vline_filled = [bool(f) for _, f in pairs]

    top = _hline_to_new(top_old, w, "top")
    bottom = _hline_to_new(bottom_old, w, "bottom")
    binm_new = (mask > 0).astype(np.uint8)
    # 下版框塌到最后一行字底边、真框条在下面十几到几十 px 的页：推到条上（见 BPUSH_*）。
    # 要在折线拟合之前——折点 y 取自线跟上下版框的交点。
    bottom, bottom_pushed = push_bottom_to_bar(binm_new, bottom, verticals, w, h)
    # 弯页整页换三段折线（先量 w80 再决定，直线页原样通过）——要在 top/bottom
    # 之后，折点 y 取自这条线跟上下版框的交点
    verticals_straight = list(verticals)
    verticals, vseg, w80_med, w80_max = fit_vlines_polyline(mask, top, bottom,
                                                            verticals, w, h,
                                                            fit=vline_polyline)
    # 界行淡到看不见的横带按文字缝重定位（见 SNAP_*）。换了线的页统一成三段格式。
    verticals, vlines_snapped = snap_verticals_to_evidence(binm_new, top, bottom, verticals, w, h)
    if vlines_snapped and vseg == 1:
        conv = []
        for v in verticals:
            if v.segments == 3:
                conv.append(v); continue
            xc = v.x_at(h / 2.0)
            yt_, yb_ = float(top.y_at(xc)), float(bottom.y_at(xc))
            conv.append(VLine(v.x_at_top, v.slope, v.slope, v.slope,
                              yt_ + (yb_ - yt_) / 3.0, yt_ + 2.0 * (yb_ - yt_) / 3.0))
        verticals, vseg = conv, 3
    head_raise = detect_head_raise(mask, top, verticals, w)
    outer = detect_outer_borders(mask, top, bottom, verticals, w, h,
                                 outer_shift=outer_shift)
    return BorderDetectionResult(width=w, height=h, top=top, bottom=bottom,
                                  verticals=verticals, head_raise=head_raise,
                                  vline_segments=vseg, bend_w80_med=w80_med,
                                  bend_w80_max=w80_max,
                                  verticals_straight=verticals_straight,
                                  vline_filled=vline_filled,
                                  bottom_pushed=float(bottom_pushed),
                                  vlines_snapped=int(vlines_snapped),
                                  **outer)
