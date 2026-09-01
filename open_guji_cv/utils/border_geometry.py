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
    （y 向下递增，起点是页面顶端 y=0 处的 x 值）。"""

    x_at_top: float
    slope: float

    def x_at(self, y: float) -> float:
        return self.x_at_top + self.slope * y

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
    v_outer_side: str | None = None  # "left" | "right"，由页码奇偶决定
    v_outer_offset: float | None = None  # 相对 verticals[0](right)或verticals[-1](left) 的偏移量


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
HR_DIST_MIN = 90          # 内边框离主上边框多远，实测 117~137
HR_DIST_MAX = 210
HR_CLUSTER_DY = 18        # 同一抬头块内相邻列的 inner_y 容差，实测差 2~8
HR_WALL_STRIP_W = 6
HR_WALL_SEARCH = 25       # 墙线在名义界行 x 附近的搜索半径
HR_WALL_MIN_FRAC = 0.5
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
OUTER_INK_MIN = 0.30      # 认一段"外框墨"的绝对门槛。**别为了提高覆盖率往下调**：
                          # 14 页 28 条边实测，0.30 以下放进来的每一档都会拖进
                          # >25px 的离群（0.26→最大 27.6px、0.12 弱档 6 例里 3 例
                          # 超 10px）。上下外框在这批书上大量磨没/裁掉，宁可报
                          # None 也不要报一个错的数。
OUTER_RUN_MIN = 4         # 墨条厚度：竖直外框实测 17~28px，上下 0~20px。
OUTER_RUN_MAX = 40        # 实测 30/40/60 三档结果完全一样，不是敏感参数。
OUTER_PRIOR_TOL = 10.0    # 偏离页级间距先验多少 px 算一个"半衰"
OUTER_PRIOR_WIN = 16.0    # 上下外框只在"页级内外间距"先验的 ±这么多 px 里找。
                          # 依据是用户给的判据、并已用金标验证：同一页四条边的
                          # 内外间距基本是个常数——竖直外框 38.4±4.0px（n=14）、
                          # 抬头框内外距 37.0px（n=11），两者对得上。放宽到 ±20
                          # 就会跑到远处的书口/纸边痕迹上去（vol01/32 top 报 -58、
                          # vol01/47 top 报 -62，都不是版框）。
OUTER_EDGE_RUN = 8        # 外延最多从墨段端点再往外走这么多 px


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
        thick = abs(float(offs[b] - offs[a]))
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


def detect_outer_borders(mask: np.ndarray, top: HLine, bottom: HLine,
                          verticals: list[VLine], width: int, height: int) -> dict:
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
            if r is not None and (best is None or r[1] > best[2]):
                best = (side, r[0], r[1])
        if best is not None:
            out["v_outer_side"], out["v_outer_offset"] = best[0], best[1]
    prior = None if out["v_outer_offset"] is None else abs(out["v_outer_offset"])
    if len(xs) > 10:
        for kind, line, sign in (("top", top, -1.0), ("bottom", bottom, 1.0)):
            base = np.array([line.y_at((width - 1) - x) for x in xs])
            lo, hi = OUTER_GAP_MIN, OUTER_GAP_MAX
            if prior is not None:      # 钉在页级间距先验上，见函数 docstring
                lo = max(lo, prior - OUTER_PRIOR_WIN)
                hi = min(hi, prior + OUTER_PRIOR_WIN)
            if hi - lo < 5:
                continue
            offs = np.arange(lo, hi + 1, 1.0) * sign
            prof = []
            for o in offs:
                yy = (base + o).astype(int)
                ok = (yy >= 0) & (yy < height)
                prof.append(binm[yy[ok], xs[ok]].mean() if ok.any() else 0.0)
            r = _outer_run(np.array(prof), offs, prefer_abs=prior)
            if r is not None:
                out[f"{kind}_outer_offset"] = r[0]
    return out


def detect_borders(gray: np.ndarray, expected_cols: int,
                    ink_threshold: int = 128) -> BorderDetectionResult:
    """整页边框+界行探测，输出新坐标系约定的结果。

    `expected_cols`：这一页应有的列数 N——竖直线应有 N+1 条（左右外边框各
    一 + N-1 条内部界行），跟 `peak_line_search.find_vertical_lines` 的
    `expected_count` 用法一致。
    """
    h, w = gray.shape[:2]
    mask = (gray < ink_threshold).astype(np.float64)

    vlines_old = find_vertical_lines(mask, expected_count=expected_cols + 1)
    top_old = find_horizontal_border(mask, "top")
    bottom_old = find_horizontal_border(mask, "bottom")

    verticals = [_vline_to_new(m, w, h) for m in vlines_old]
    # 新坐标系 x 向左递增：旧坐标里越靠右(x_old越大) -> 新坐标x_new越小，
    # 按 x_at_top 升序排列正好就是"从右到左"，对应列号从1开始递增。
    verticals.sort(key=lambda v: v.x_at_top)

    top = _hline_to_new(top_old, w, "top")
    bottom = _hline_to_new(bottom_old, w, "bottom")
    head_raise = detect_head_raise(mask, top, verticals, w)
    outer = detect_outer_borders(mask, top, bottom, verticals, w, h)
    return BorderDetectionResult(width=w, height=h, top=top, bottom=bottom,
                                  verticals=verticals, head_raise=head_raise,
                                  **outer)
