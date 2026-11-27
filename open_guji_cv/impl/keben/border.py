"""Step 1（边框探测）的新坐标系接口——见 `doc/segmentation_v2_pipeline.md`。

原 `utils/border_geometry`，2026-10-30 切分模块化第 3 步拆开：数据类型进 `seg/frame_types`，界行折线拟合进
`seg/polyline`，这里留殿本版式的部分——抬头框、双边外框与下框条、按横带证据把界行回直、整册标定、整页调度
`detect_borders`。Step1 目前各套书共用这一份调度。

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

import numpy as np

from ...seg.frame_types import BorderDetectionResult, HeadRaiseBorder, HLine, VLine
from ...seg.lines import (
    LineMatch,
    find_horizontal_border, TOP_WEAK_RATIO,
    find_vertical_lines,
    half_height_score_at,
    local_maxima,
)
from ...seg.grid import find_vertical_lines_grid, grid_thresholds
from ...seg.polyline import _bridge_row, _fit_knots, _from_knots, _hit_frac, _longest_true_run, fit_vlines_polyline


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
#: 抬头块向邻列延伸（`detect_head_raise(extend=True)`，2026-10-21）：邻列在块的内边框高度 ±HR_CLUSTER_DY 里
#: 有一条细锐线、墨占比 ≥ 此值（够不上 HR_THIN_INK_MIN，内边框印得淡、或被抬头字压着），就算同一个抬头框，
#: 并进块里，再一起过墙线判据。殿本 vol04 p9 c8 0.18、vol09 p109 c5/c6 0.21/0.15；块外的普通列在这一高度是空白。
HR_EXTEND_INK_MIN = 0.12
#: 延伸还要这一列真有抬头字：框线下 HR_EXTEND_SKIP 行起到窗口下沿，墨占比 > 0.1 的行占到 HR_EXTEND_TEXT_ROWS 以上。
#: 七册全部页：真抬头列 0.77~0.99；抬头框旁边的普通列（线只是邻框的延长）0.00~0.08
HR_EXTEND_SKIP = 8
HR_EXTEND_TEXT_ROWS = 0.5
#: 字凸出判据（`detect_head_raise(text_rule=True)`，2026-10-21）：有的抬头框只印了粗外框、没有内细线（殿本 vol04 p84
#: 那种连顶线都没有），横线判据找不到。改看主上边框上方 [btop−130, btop−45] 这一段：列中间一半（先去掉整段
#: 都有墨的竖条，即墙线）按行算墨占比，像字的行（HR_TEXT_ROW_LO~HR_TEXT_ROW_HI）占到 HR_TEXT_ROWS 以上，
#: 而且至少一侧（界行往外 HR_TEXT_WALL_OUT 内）有墙线覆盖 HR_TEXT_WALL 以上，就算抬头。
#: 殿本 vol04／06／07／09 全部页：抬头框没认出的 5 列（vol04 p65 c8、p84 c5，vol06 p58 c6，vol07 p46 c7、p77 c2）
#: 全中，另中 vol04 p11 c5（图上确实抬头，格位表记成不抬），别无误报。
#: 墙线这一道挡的是「上諭」那种字紧贴笔直版框、没有台阶的页（见 `detect_head_raise` 文档串）。
HR_TEXT_BAND = (130, 45)
HR_TEXT_ROW_LO, HR_TEXT_ROW_HI = 0.1, 0.6
HR_TEXT_ROWS = 0.4
HR_TEXT_WALL = 0.5
HR_TEXT_WALL_OUT = 70
HR_TEXT_PAD = 8
#: 抬头框探测的**像素尺度**（2026-10-26，GUJI-748）。上面这些 HR_* 长度常数全是在殿本旧图（列距约 185px）上量的
#: 绝对像素；换图源 siku-qiefen-v2 之后图缩到约 0.70 倍（缩放 0.66–0.79），常数没跟着缩，抬头框整片认不出：
#: vol07 新 p43 粗外框半高宽 11~12（卡在细线上限 10 与粗条下限 15 的缝里），内边框／抬头字离主上边框 56~79px
#: （够不上 HR_DIST_MIN 75），五列抬头一列没认。`scale` 由调用方按册给（`border_detect.head_raise_scale`，
#: 册 yaml 里与 bottom_gap、period_prior 乘同一个缩放比）；1.0 时取的就是上面这组原值，产物逐位不变。
#: 墨占比、覆盖率这类比例量不随尺度变，不缩；局部极大值半径、墙线条宽、扫描步长是采样粒度，也不缩。
HR_SCALE_LENGTHS = ("HR_BAND_ABOVE", "HR_BAND_MARGIN", "HR_THIN_WD_MAX", "HR_FAT_WD_MIN", "HR_FAT_WD_MAX",
                    "HR_PAIR_MIN", "HR_PAIR_MAX", "HR_DIST_MIN", "HR_DIST_MAX", "HR_CLUSTER_DY",
                    "HR_WALL_SEARCH", "HR_DEFAULT_PAIR_GAP", "HR_EXTEND_SKIP", "HR_TEXT_WALL_OUT", "HR_TEXT_PAD")


class _HRGeom:
    """按尺度换算过的 HR_* 长度常数。`scale == 1.0` 时每个值都是模块常数原样（int），不做任何运算。"""

    def __init__(self, scale: float = 1.0):
        self.scale = float(scale)
        g = globals()
        for name in HR_SCALE_LENGTHS:
            v = g[name]
            setattr(self, name[3:], v if self.scale == 1.0 else int(round(v * self.scale)))
        self.TEXT_BAND = HR_TEXT_BAND if self.scale == 1.0 else \
            tuple(int(round(v * self.scale)) for v in HR_TEXT_BAND)
        self.DEDUP_DY = 12.0 if self.scale == 1.0 else 12.0 * self.scale


def _raised_text_top(binm: np.ndarray, btop: float, xl: int, xr: int,
                     geom: _HRGeom | None = None) -> float | None:
    """字凸出判据（见 HR_TEXT_BAND）：这一列算抬头就返回抬头字的上沿 − HR_TEXT_PAD，否则 None。"""
    g = geom or _HRGeom()
    h, w = binm.shape
    y0, y1 = int(btop - g.TEXT_BAND[0]), int(btop - g.TEXT_BAND[1])
    m = (xr - xl) // 4
    if y0 < 0 or xr - xl < 20:
        return None
    band = binm[y0:y1, xl + m:xr - m]
    keep = band.mean(axis=0) < HR_TEXT_ROW_HI          # 去掉墙线那种整段有墨的竖条
    if not keep.any():
        return None

    def charlike(a: np.ndarray) -> np.ndarray:
        r = a[:, keep].mean(axis=1)
        return (r > HR_TEXT_ROW_LO) & (r < HR_TEXT_ROW_HI)
    if charlike(band).mean() < HR_TEXT_ROWS:
        return None
    wall = 0.0
    for x0, sgn in ((xl, -1), (xr, 1)):
        for dx in range(-10, g.TEXT_WALL_OUT + 1, 3):
            xs = int(max(0, min(w - HR_WALL_STRIP_W, x0 + sgn * dx)))
            wall = max(wall, float(binm[y0:y1, xs:xs + HR_WALL_STRIP_W].any(axis=1).mean()))
    if wall < HR_TEXT_WALL:
        return None
    lo = max(0, int(btop - g.BAND_ABOVE))
    rows = np.flatnonzero(charlike(binm[lo:y1, xl + m:xr - m]))
    return float(lo + rows[0] - g.TEXT_PAD) if len(rows) else None


def _extend_head_raise(per_col: list, curves: list, geom: _HRGeom | None = None) -> None:
    """已认下的抬头列向两侧邻列延伸（见 `detect_head_raise` 第 6 步），原地改 `per_col`。"""
    g = geom or _HRGeom()
    changed = True
    while changed:
        changed = False
        for i, c in enumerate(per_col):
            if c is not None or curves[i] is None:
                continue
            refs = [per_col[j]["inner_y"] for j in (i - 1, i + 1) if 0 <= j < len(per_col) and per_col[j]]
            if not refs:
                continue
            curve, lo, btop, xl, xr = curves[i]
            best = None
            for ci in local_maxima(curve, radius=3):
                y, ink = float(lo + ci), float(curve[ci])
                wd, _ = half_height_score_at(curve, ci)
                if wd <= g.THIN_WD_MAX and ink >= HR_EXTEND_INK_MIN \
                        and min(abs(y - r) for r in refs) <= g.CLUSTER_DY \
                        and g.DIST_MIN <= btop - y <= g.DIST_MAX and (best is None or ink > best[1]):
                    best = (y, ink)
            below = curve[int(best[0] - lo) + g.EXTEND_SKIP:] if best is not None else curve[:0]
            if len(below) and float((below > 0.1).mean()) >= HR_EXTEND_TEXT_ROWS:
                per_col[i] = dict(col=i + 1, inner_y=best[0], outer_y=best[0] - g.DEFAULT_PAIR_GAP,
                                  estimated=True, btop=btop, xl=xl, xr=xr)
                changed = True


def _wall_frac(mask: np.ndarray, y_top: float, y_bottom: float, x0: float,
               search: int = HR_WALL_SEARCH) -> float:
    """竖直连接墙线的覆盖率：抬头框比主版框高出来的那一截，两侧要有竖墙
    落到主边框上。在 x0 附近 ±HR_WALL_SEARCH 内扫取最好的一条——界行的 x
    来自 find_vertical_lines，vol01/47 那页顶端就系统性偏 13~39px，固定
    窄条会整条错过真正的墙。"""
    h, w = mask.shape
    y_top, y_bottom = int(y_top), int(y_bottom)
    if y_bottom - y_top < 5:
        return 0.0
    best = 0.0
    for dx in range(-search, search + 1, 3):
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
                       width: int, extend: bool = True, text_rule: bool = True,
                       scale: float = 1.0, fit: bool = False) -> list[HeadRaiseBorder]:
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
    6. 聚块之前，已认下的列向两侧邻列延伸（`extend`，2026-10-21）——邻列在同一高度有淡一些的细锐线
       （`HR_EXTEND_INK_MIN`）、线下有抬头字的墨（`HR_EXTEND_TEXT_ROWS`）就并进来，可以一列接一列延伸；
       延伸出来的块照样过第 5 步的墙线判据。
       管内边框印得淡、或被抬头字压着的列（殿本 vol04 p9 c8、vol09 p109 c5/c6：抬头字整个落在列图外）。
    7. 前面都没认下的列，再看字凸出（`text_rule`，2026-10-21，见 `HR_TEXT_BAND`）：主上边框上方有像字的墨、
       旁边有墙线。管只印了粗外框、没有内细线（或连顶线都没有）的抬头框。不是第一句说的那条老路：
       这里去掉了墙线竖条、只数像字的行，而且要有墙。inner_y 取抬头字上沿往上 HR_TEXT_PAD，`estimated=True`。

    `scale`：本页图相对殿本旧图（上面那些像素常数的标定尺度）的缩放比，见 `HR_SCALE_LENGTHS`。缺省 1.0 = 原值。
    `fit`（`border_detect.head_raise_fit`，2026-11-25，缺省关）：认下抬头列之后再校内框高度，见 `_fit_head_raise`。
    """
    g = _HRGeom(scale)
    h, w = mask.shape
    binm = (mask > 0).astype(np.uint8)
    per_col: list[dict | None] = []
    curves: list[tuple | None] = []
    for i in range(len(verticals) - 1):
        right_v, left_v = verticals[i], verticals[i + 1]
        x_old = lambda v, y: (width - 1) - v.x_at(y)  # noqa: E731
        btop = float(np.mean([top.y_at(v.x_at(0.0)) for v in (right_v, left_v)]))
        lo = max(0, int(btop - g.BAND_ABOVE))
        hi = max(lo + 20, int(btop - g.BAND_MARGIN))
        ym = (lo + hi) / 2.0
        xl = int(max(0, min(x_old(right_v, ym), x_old(left_v, ym))))
        xr = int(min(w, max(x_old(right_v, ym), x_old(left_v, ym))))
        if xr - xl < 20 or hi <= lo:
            per_col.append(None)
            curves.append(None)
            continue
        curve = binm[lo:hi, xl:xr].sum(axis=1).astype(np.float64) / (xr - xl)
        curves.append((curve, lo, btop, xl, xr))
        thin: list[tuple[float, float, float]] = []
        fat: list[tuple[float, float, float]] = []
        for ci in local_maxima(curve, radius=3):
            wd, _ = half_height_score_at(curve, ci)
            ink = float(curve[ci])
            y = float(lo + ci)
            if wd <= g.THIN_WD_MAX and ink >= HR_THIN_INK_MIN:
                thin.append((y, ink, wd))
            elif g.FAT_WD_MIN <= wd <= g.FAT_WD_MAX and ink >= HR_FAT_INK_MIN:
                fat.append((y, ink, wd))
        thin, fat = _dedup_peaks(thin, g.DEDUP_DY), _dedup_peaks(fat, g.DEDUP_DY)
        if not thin:
            per_col.append(None)
            continue
        inner, outer, estimated = thin[0], None, True
        above_fat = [f for f in fat if g.PAIR_MIN <= thin[0][0] - f[0] <= g.PAIR_MAX]
        if above_fat:
            outer, estimated = above_fat[0], False  # 粗条会被拆成上下两个峰，取外沿
        elif len(thin) >= 2 and g.PAIR_MIN <= thin[1][0] - thin[0][0] <= g.PAIR_MAX:
            outer, inner, estimated = thin[0], thin[1], False
        if not (g.DIST_MIN <= btop - inner[0] <= g.DIST_MAX):
            per_col.append(None)
            continue
        per_col.append(dict(
            col=i + 1, inner_y=inner[0],
            outer_y=(_outer_edge(curve, lo, outer[0]) if outer
                     else inner[0] - g.DEFAULT_PAIR_GAP),
            estimated=estimated, btop=btop, xl=xl, xr=xr))

    if extend:
        _extend_head_raise(per_col, curves, g)
    blocks: list[list[dict]] = []
    cur: list[dict] = []
    for c in per_col + [None]:
        if c is not None and (not cur or abs(c["inner_y"] - cur[-1]["inner_y"]) <= g.CLUSTER_DY):
            cur.append(c)
        else:
            if cur:
                blocks.append(cur)
            cur = [c] if c is not None else []

    out: list[HeadRaiseBorder] = []
    for blk in blocks:
        wall = max(
            _wall_frac(binm, blk[0]["inner_y"], blk[0]["btop"], blk[0]["xr"] - HR_WALL_STRIP_W, g.WALL_SEARCH),
            _wall_frac(binm, blk[-1]["inner_y"], blk[-1]["btop"], blk[-1]["xl"], g.WALL_SEARCH),
        )
        if wall < HR_WALL_MIN_FRAC:
            continue
        out.extend(HeadRaiseBorder(col=c["col"], inner_y=c["inner_y"],
                                   outer_y=c["outer_y"], estimated=c["estimated"])
                   for c in blk)
    if text_rule:
        got = {b.col for b in out}
        for i, cv in enumerate(curves):
            if cv is None or i + 1 in got:
                continue
            y = _raised_text_top(binm, cv[2], cv[3], cv[4], g)
            if y is not None:
                out.append(HeadRaiseBorder(col=i + 1, inner_y=y, outer_y=y - g.DEFAULT_PAIR_GAP, estimated=True))
        out.sort(key=lambda b: b.col)
    if fit and out:
        text_cols = set() if not text_rule else {b.col for b in out} - got
        out = _fit_head_raise(out, curves, text_cols, g)
    return out


#: 内框对齐（`_fit_head_raise`）：本列内框比相邻抬头列低出这么多以上，才去邻列高度找细线。
HR_FIT_TOL = 8
#: 邻列高度 ±这么多行里找细线。
HR_FIT_SNAP = 5
#: 细线认不出时，外框跟邻列差不超过这么多就算同一个抬头框（双抬挨单抬外框差一格，约 100px）。
HR_FIT_OUTER_DY = 6
#: 本页内外间距只认离先验这么近的观测（殿本实测 36–46）。
HR_FIT_GAP_WIN = 10
#: 只有粗外框的列：粗框条认墨占比 ≥ 此值的最上一个峰。
HR_FIT_BAR_INK = 0.6


def _top_bar_edge(curve: np.ndarray, lo: int) -> float | None:
    """本列窗口里最上一道粗框条（墨 ≥ HR_FIT_BAR_INK 的最上一个峰）的外延，没有返回 None。"""
    peaks = [ci for ci in local_maxima(curve, radius=3) if curve[ci] >= HR_FIT_BAR_INK]
    return _outer_edge(curve, lo, float(lo + min(peaks))) if peaks else None


#: `_fit_head_raise` 迭代上限（每列几轮）：只在值真变了才再来一轮，这个上限只兜底来回跳的情形。
HR_FIT_MAX_ROUNDS = 4


def _fit_head_raise(out: list[HeadRaiseBorder], curves: list, text_cols: set[int],
                    g: _HRGeom) -> list[HeadRaiseBorder]:
    """抬头列认下以后校内框高度（`detect_head_raise(fit=True)`，2026-11-25，A21 版面基准）。

    1. **同一抬头框内框齐平**：相邻两列都抬头、本列内框比邻列低出 HR_FIT_TOL 以上，且本列在邻列内框高度
       ±HR_FIT_SNAP 有一条细线（墨 ≥ HR_EXTEND_INK_MIN，同 `_extend_head_raise` 的口径），本列内框就改到这条线——
       原来认的是抬头字的顶笔（殿本 vol01 p30 c4/c6 认在「實」「天」字头上，低 12–24px；vol04 p6 c5 低 45px）。
       双抬挨着单抬时，单抬列在双抬内框高度是框外白纸，没有细线，不动。
       细线淡到认不出、但本列最上一道粗框条跟邻列同高（框条＋间距落在邻列内框 ±2×HR_FIT_OUTER_DY）时，内框按本页间距从框条推
       （estimated）。本页间距取观测到、离先验不远的内外距中位。
    2. **只有粗外框的列**（`text_rule` 认下的）：内框原取抬头字上沿往上一点，常落在粗外框上（vol04 p6 c1/c3 高 45px）。
       改成本列最上一道粗框条的外延 + 本页实测内外间距（观测到的列的中位，没有就 HR_DEFAULT_PAIR_GAP）。
    """
    by_col = {b.col: b for b in out}
    # 本页内外间距：观测到的列里落在先验 HR_DEFAULT_PAIR_GAP ± HR_FIT_GAP_WIN 内的取中位（内框认到字头上、或外框认到
    # 字笔上的列间距会偏离先验，vol01 p46 c5 63、vol04 p6 c5 24），一个都没有就用先验
    win = HR_FIT_GAP_WIN * g.scale
    gaps = [b.inner_y - b.outer_y for b in out if not b.estimated and b.col not in text_cols
            and abs(b.inner_y - b.outer_y - g.DEFAULT_PAIR_GAP) <= win]
    gap = float(np.median(gaps)) if gaps else float(g.DEFAULT_PAIR_GAP)
    for c in sorted(text_cols):
        cv = curves[c - 1] if 0 < c <= len(curves) else None
        if cv is None:
            continue
        curve, lo = cv[0], cv[1]
        oy = _top_bar_edge(curve, lo)
        if oy is None:
            continue
        by_col[c] = HeadRaiseBorder(col=c, inner_y=float(oy + gap), outer_y=float(oy), estimated=True)
    changed = True
    rounds = 0
    while changed and rounds < HR_FIT_MAX_ROUNDS * max(1, len(by_col)):
        changed = False
        rounds += 1
        for c in sorted(by_col):
            b = by_col[c]
            cv = curves[c - 1] if 0 < c <= len(curves) else None
            if cv is None:
                continue
            curve, lo = cv[0], cv[1]
            refs = [by_col[j] for j in (c - 1, c + 1) if j in by_col
                    and by_col[j].inner_y < b.inner_y - HR_FIT_TOL]
            for r in sorted(refs, key=lambda r: r.inner_y):
                best = None
                for ci in local_maxima(curve, radius=2):
                    y = float(lo + ci)
                    if abs(y - r.inner_y) > HR_FIT_SNAP or curve[ci] < HR_EXTEND_INK_MIN:
                        continue
                    wd, _ = half_height_score_at(curve, ci)
                    if wd <= g.THIN_WD_MAX and (best is None or curve[ci] > best[1]):
                        best = (y, float(curve[ci]))
                if best is not None:
                    nb = HeadRaiseBorder(col=c, inner_y=best[0],
                                         outer_y=best[0] - (r.inner_y - r.outer_y),
                                         estimated=b.estimated or r.estimated)
                    if nb != b:        # 原地不动的更新不算变（脈經 01 p67：两邻列互吸、同值反复写，死循环）
                        by_col[c] = nb
                        changed = True
                    break
                oy = _top_bar_edge(curve, lo)
                if oy is not None and abs(oy + gap - r.inner_y) <= 2 * HR_FIT_OUTER_DY:
                    # 细线淡到认不出，但本列最上一道粗框条跟邻列在同一高度（同一个抬头框）：内框按本页内外间距从框条推
                    nb = HeadRaiseBorder(col=c, inner_y=float(oy + gap), outer_y=float(oy), estimated=True)
                    if nb != b:
                        by_col[c] = nb
                        changed = True
                    break
    return [by_col[c] for c in sorted(by_col)]


#: 缺口列（`notch_top`，2026-11-20，A22）：一页上抬头列占多数时，`find_horizontal_border` 把抬头框的内框线当成主上版框，
#: 没抬头的列反成了版框上的「缺口」——主上框以下先是一段白纸、再是本列真版框（粗框条＋内细线），整页抬头认不出、
#: 缺口列首格切进白纸（殿本 vol24 p27、vol28 p9：抬头格只有 20 多 px 高、缺口里切出假字格、抬头列末字没格）。
#: 判据只看列中间一半：主上框不横穿本列（主上框上 HR_PAIR_MAX＋NOTCH_TOP_PAD 行到下 NOTCH_TOP_PAD 行里没有 ≥ NOTCH_INNER_INK 的墨行：
#: 普通页的空列有框条，哪怕内细线印成虚线）；
#: 去掉整段有墨的竖条（抬头框的墙）后，主上框下 [HR_BAND_MARGIN, 第一道粗墨) 几乎全白（墨 >0.1 的行 ≤ NOTCH_BLANK_ROWS），
#: 第一道墨（≥ NOTCH_LINE_INK）离主上框落在 [HR_DIST_MIN − HR_PAIR_MAX, HR_DIST_MAX]；本列真上框取这道框条往下
#: HR_PAIR_MAX＋NOTCH_INNER_PAD 内最后一段 ≥ NOTCH_INNER_INK 的墨（框条内沿的细线，同「框条内沿约定」）。
NOTCH_LINE_INK = 0.5
NOTCH_INNER_INK = 0.3
NOTCH_INNER_PAD = 15
NOTCH_BLANK_ROWS = 0.05
NOTCH_TOP_PAD = 8


def _notch_inner_y(binm: np.ndarray, btop: float, xl: int, xr: int, g: _HRGeom) -> float | None:
    """缺口列（见 NOTCH_*）：返回本列真上版框（框条内沿细线）的 y，不是缺口列返回 None。"""
    h = binm.shape[0]
    m = (xr - xl) // 4
    lo = int(btop + g.BAND_MARGIN)
    hi = min(h, int(btop + g.DIST_MAX + g.PAIR_MAX + NOTCH_INNER_PAD))
    if xr - xl < 20 or hi - lo < 20:
        return None
    y0 = max(0, int(btop - g.PAIR_MAX - NOTCH_TOP_PAD))
    if float(binm[y0:int(btop + NOTCH_TOP_PAD) + 1, xl + m:xr - m].mean(axis=1).max(initial=0.0)) >= NOTCH_INNER_INK:
        return None                                   # 主上框（框条＋内细线）横穿本列：本列在版框里，不是缺口
    curve = binm[lo:hi, xl + m:xr - m].mean(axis=1)
    strong = np.flatnonzero(curve >= NOTCH_LINE_INK)
    if not len(strong):
        return None
    ys = int(strong[0])
    if not (g.DIST_MIN - g.PAIR_MAX <= lo + ys - btop <= g.DIST_MAX) or ys < 20:
        return None
    band = binm[lo:lo + ys - 3, xl + m:xr - m]
    keep = band.mean(axis=0) < HR_TEXT_ROW_HI       # 去掉抬头框的墙（整段有墨的竖条），同 `_raised_text_top`
    if not keep.any() or float((band[:, keep].mean(axis=1) > 0.1).mean()) > NOTCH_BLANK_ROWS:
        return None
    seg = curve[ys:ys + g.PAIR_MAX + NOTCH_INNER_PAD] >= NOTCH_INNER_INK
    rows = np.flatnonzero(seg)
    last = int(rows[-1])
    first = last
    while first > 0 and seg[first - 1]:
        first -= 1
    return float(lo + ys + (first + last) / 2.0)


def notch_top(mask: np.ndarray, top: HLine, verticals: list[VLine], width: int,
              extend: bool = True, scale: float = 1.0,
              fit: bool = False) -> tuple[HLine, list[HeadRaiseBorder]] | None:
    """主上版框认在抬头框上的页（见 NOTCH_*）：把主上框挪到缺口列的真上框，重探抬头框；挪了以后**缺口以外的列全都认成抬头**
    才接受，返回 (新主上框, 抬头框)，否则 None。只在本页一个抬头框都没认出时由 `detect_borders(head_raise_notch=True)` 调。"""
    g = _HRGeom(scale)
    binm = (mask > 0).astype(np.uint8)
    n = len(verticals) - 1
    if n < 2:
        return None
    x_old = lambda v, y: (width - 1) - v.x_at(y)  # noqa: E731
    found: dict[int, tuple[float, float]] = {}
    for i in range(n):
        right_v, left_v = verticals[i], verticals[i + 1]
        btop = float(np.mean([top.y_at(v.x_at(0.0)) for v in (right_v, left_v)]))
        ym = btop + g.DIST_MAX / 2.0
        xl = int(max(0, min(x_old(right_v, ym), x_old(left_v, ym))))
        xr = int(min(binm.shape[1], max(x_old(right_v, ym), x_old(left_v, ym))))
        y = _notch_inner_y(binm, btop, xl, xr, g)
        if y is not None:
            found[i + 1] = (y, btop)
    if not found or len(found) == n:
        return None
    dys = [y - b for y, b in found.values()]
    if max(dys) - min(dys) > 2 * g.CLUSTER_DY:
        return None
    new_top = HLine(y_at_right=top.y_at_right + float(np.median(dys)), slope=top.slope, kind=top.kind)
    hr = detect_head_raise(mask, new_top, verticals, width, extend=extend, scale=scale,
                           **({"fit": True} if fit else {}))
    if {b.col for b in hr} != set(range(1, n + 1)) - set(found):
        return None
    return new_top, hr


# --- 外边框探测（形态常数来自 14 页金标实测） ---
OUTER_GAP_MIN, OUTER_GAP_MAX = 12, 78   # 外框离内框多远，金标实测 24~47
#: 外框搜索窗上限按列距缩放（2026-11-26）：`OUTER_GAP_MAX` 是殿本（列距约 185px）标的，
#: 全唐文大图（页宽 4296、列距约 350px）内外框距约 80px，压在窗上限上，量到与否看线的细小斜率差（046 p93）。
#: 只在 `outer_scale`（border_detect 参数，缺省关）开时生效。列距 ≤ `OUTER_REF_PITCH` 的页窗口不变（殿本、脈經、史記逐字节同）；更大的页按 scale=列距/OUTER_REF_PITCH
#: 把外框探测里的像素量一并放大（窗上限、墨条厚度上限 OUTER_RUN_MAX、外延刹车、先验窗与容差、条外纸带）——
#: 全唐文外框粗条厚约 56px，只放窗不放厚度上限会被 OUTER_RUN_MAX=40 整段挡掉（qtw005:18、qtw190:138）。
OUTER_REF_PITCH = 220.0
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
SINGLE_BAR_GAP = 3
#: 判了 single 之后再往外看：粗条外 `SINGLE_BAR_GAP` 行起、到 `OUTER_GAP_MAX` 为止，
#: 若还有 ≥ `OUTER_INK_MIN` 的墨，说明这条「粗条」是内框、外面那条才是外框——
#: **是 double，不是 single**。vol02 判 single 的 30 页里 4 页属此（p12/16/110/185，
#: 粗条 14~23 行，外框在它外面 10~30px），不查就当成「本来就没有外框」漏报。
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
                prefer_abs: float | None = None, scale: float = 1.0) -> tuple[float, float] | None:
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
        if not (OUTER_RUN_MIN <= thick <= OUTER_RUN_MAX * scale):
            continue
        score = float(prof[a:b + 1].mean()) * (thick + 1.0)
        if prefer_abs is not None:
            mid = abs(float(offs[a] + offs[b]) / 2.0)
            score /= 1.0 + (abs(mid - prefer_abs) / (OUTER_PRIOR_TOL * scale)) ** 2
        if best is None or score > best[0]:
            pk = float(prof[a:b + 1].max())
            half = pk * 0.5
            # 外延要有刹车：半高门槛在低对比区会一路滑到搜索边界（vol01/32 top
            # 的段明明在 -45~-50，却一路滑出去报了 -78=GAP_MAX）。最多再走
            # OUTER_EDGE_RUN px。
            i, limit = b, min(len(prof) - 1, b + int(round(OUTER_EDGE_RUN * scale)))
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
                   edge: float, sign: float, height: int, scale: float = 1.0) -> float:
    """外延再往外 `OUTER_PAPER_LO..HI` px 的行墨中位数——版框之外应该是纸。"""
    far = abs(edge)
    vals = []
    lo_, hi_ = (OUTER_PAPER_LO, OUTER_PAPER_HI) if scale == 1.0 else (
        int(round(OUTER_PAPER_LO * scale)), int(round(OUTER_PAPER_HI * scale)))
    for o in range(int(far) + lo_, int(far) + hi_ + 1):
        yy = np.rint(base + o * sign).astype(int)
        ok = (yy >= 0) & (yy < height)
        if ok.mean() < 0.5:          # 大半跑出页面了，别拿残缺的行下判断
            continue
        vals.append(float(binm[yy[ok], xs[ok]].mean()))
    return float(np.median(vals)) if vals else 0.0


#: `skip_top` 区间两侧再让出这么多 px（抬头框的墙）。
OUTER_SKIP_PAD = 40


def detect_outer_borders(mask: np.ndarray, top: HLine, bottom: HLine,
                          verticals: list[VLine], width: int, height: int,
                          outer_shift: dict | None = None,
                          book_gap: dict | None = None,
                          frame_layers: dict | None = None,
                          outer_side: str | None = None,
                          skip_top: list[tuple[float, float]] | None = None,
                          outer_scale: bool = False) -> dict:
    """上下版框的外框偏移 + 纸边侧竖直外框偏移。

    `skip_top`（旧坐标 x 区间，`head_raise_fit` 传抬头列）：量上外框时不看这些 x——抬头列那一段主上框上方是抬头框里的字，
    没有外框条。抬头列占多数的页（殿本 vol04 p6，9 列抬 6 列）原来整条量不出外框。剩下不到 10 个采样点就照旧全宽量。

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

    **按套书规则（2026-11-23，册配置 `frame_layers` / `side_frame`）**：框型是书的版式、不是逐页猜的。
    - `frame_layers[边]==1`：这一边只有一条线（脈經上下），一律记 `single`，只量粗条宽度（`*_bar_extent`），
      不找外框、不兜底；
    - `frame_layers[边]==2`：外框一定存在，只量位置（量不到按册基准估，标 `*_outer_estimated`）；
    - `outer_side`（由 `side_frame` 按页码奇偶定，"left"/"right"）：纸边侧有外框、靠版心一侧没有；
      只在这一侧量竖直外框，不再两侧比强弱；量不到按 `book_gap["side"]`（缺则上下基准的均值）估。
    """
    binm = (mask > 0).astype(np.uint8)
    out: dict = dict(top_outer_offset=None, bottom_outer_offset=None,
                     top_frame_kind=None, bottom_frame_kind=None,
                     top_bar_extent=None, bottom_bar_extent=None,
                     top_outer_estimated=False, bottom_outer_estimated=False,
                     v_outer_side=None, v_outer_offset=None, v_outer_estimated=False)
    vx = sorted((width - 1) - v.x_at(height / 2.0) for v in verticals)
    gap_max, scale = OUTER_GAP_MAX, 1.0
    if outer_scale and len(vx) >= 3:
        pitch = float(np.median(np.diff(vx)))
        if pitch > OUTER_REF_PITCH:
            scale = pitch / OUTER_REF_PITCH
            gap_max = int(round(OUTER_GAP_MAX * scale))
    xs = np.arange(int(vx[0] + 30), int(vx[-1] - 30), 2)
    # 界行探到图外（史記09 年表页）时 xs 会越过图宽、取墨 IndexError：去掉越界的列。只去 ≥ 图宽的，没越界的页逐字节不变
    xs = xs[xs < width]
    ys = np.arange(int(height * 0.12), int(height * 0.88), 3)
    # 先测竖直外框——那一侧的墨最稳（峰值 0.48~1.00），拿它当上下的间距先验
    if len(ys) > 10 and len(verticals) >= 2:
        best = None
        for side, vi, sign in (("right", 0, -1.0), ("left", len(verticals) - 1, 1.0)):
            if outer_side in ("left", "right") and side != outer_side:
                continue        # 按套书规则：靠版心一侧没有外框，不量
            if (frame_layers or {}).get(side) == 1:
                continue        # 册声明这一侧单线（四周單邊）：最外线就是版框，没有外框
            base = np.array([(width - 1) - verticals[vi].x_at(y) for y in ys])
            offs = np.arange(OUTER_GAP_MIN, gap_max + 1, 1.0) * sign
            prof = []
            for o in offs:
                xx = (base - o).astype(int)     # 新坐标 x 向左递增 => 旧坐标取反
                ok = (xx >= 0) & (xx < width)
                prof.append(binm[ys[ok], xx[ok]].mean() if ok.any() else 0.0)
            r = _outer_run(np.array(prof), offs, scale=scale)
            if r is not None and r[1] < OUTER_V_INK_MIN:
                r = None            # 竖直外框是先验，弱峰宁可不要（见 OUTER_V_INK_MIN）
            if r is not None and (best is None or r[1] > best[2]):
                best = (side, r[0], r[1])
        if best is not None:
            out["v_outer_side"], out["v_outer_offset"] = best[0], best[1]
    if outer_side in ("left", "right") and out["v_outer_side"] is None and len(verticals) >= 2:
        # 规则说这一侧有外框，但这页看不清（磨没/裁掉/糊了）：按册基准估位置，标 estimated
        g = (book_gap or {}).get("side")
        if g is None and book_gap and book_gap.get("top") is not None and book_gap.get("bottom") is not None:
            g = (book_gap["top"] + book_gap["bottom"]) / 2.0
        if g is not None:
            vi = 0 if outer_side == "right" else len(verticals) - 1
            edge = (width - 1) - verticals[vi].x_at(height / 2.0)   # 旧坐标（左上原点）里内框线的 x
            sgn = -1.0 if outer_side == "right" else 1.0
            off = min(float(g) + OUTER_ESTIMATE_SLACK, float(gap_max))
            room = edge if sgn < 0 else (width - 1 - edge)
            off = min(off, max(0.0, room - 1.0))
            if off > 0:
                out["v_outer_side"], out["v_outer_offset"] = outer_side, off * sgn
                out["v_outer_estimated"] = True
    prior = None if out["v_outer_offset"] is None else abs(out["v_outer_offset"])
    xs_all = xs
    xs_top = xs
    if skip_top:
        keep = np.ones(len(xs), dtype=bool)
        for a, b in skip_top:
            keep &= ~((xs >= min(a, b) - OUTER_SKIP_PAD) & (xs <= max(a, b) + OUTER_SKIP_PAD))
        if keep.sum() > 10:
            xs_top = xs[keep]
    if len(xs) > 10:
        for kind, line, sign in (("top", top, -1.0), ("bottom", bottom, 1.0)):
            xs = xs_top if kind == "top" else xs_all
            base = np.array([line.y_at((width - 1) - x) for x in xs])
            # 书级声明了这条边有 2 层，就不许判 single——版式是全书一致的，
            # 这一页看着像一根粗条，是内外框之间被污糊连成了片（见 BookSpec.frame_layers）。
            declared = (frame_layers or {}).get(kind)
            if declared == 1:
                # 版式就是单线：不找外框，只量这条粗条（从内框线起往外连续的粗墨）的宽度
                ext = 0
                for o in range(0, gap_max + 1):
                    yy = (base + o * sign).astype(int)
                    ok = (yy >= 0) & (yy < height)
                    v = binm[yy[ok], xs[ok]].mean() if ok.any() else 0.0
                    if v >= SINGLE_BAR_INK:
                        ext = o + 1
                    elif o >= SINGLE_BAR_LEAD:
                        break
                out[f"{kind}_frame_kind"] = "single"
                out[f"{kind}_bar_extent"] = float(ext) if ext else None
                continue
            # 先判單邊框：从内框线起往外连续的粗墨。是粗条就不找第二条了。
            run0, start0 = 0, None
            for o in range(0, gap_max + 1):
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
                # 粗条之外还有墨 → 那才是外框，这条粗条只是内框（见 SINGLE_BAR_GAP）
                second = 0.0
                for o in range(start0 + run0 + SINGLE_BAR_GAP, gap_max + 1):
                    yy = (base + o * sign).astype(int)
                    ok = (yy >= 0) & (yy < height)
                    v = binm[yy[ok], xs[ok]].mean() if ok.any() else 0.0
                    second = max(second, float(v))
                if second < OUTER_INK_MIN and declared != 2:
                    out[f"{kind}_frame_kind"] = "single"
                    out[f"{kind}_bar_extent"] = float(start0 + run0)
                    continue
            out[f"{kind}_frame_kind"] = "none"
            lo, hi = OUTER_GAP_MIN, gap_max
            if prior is not None:      # 钉在页级间距先验上，见函数 docstring
                # 四边不等距，先按边校正。`outer_shift` 是**书级**标定值
                # （`BookSpec.outer_shift`），不给才退回缺省——这个差按书变，
                # vol01 -4.2/-6.3 对 vol02 -12.0/-19.8，抄错就整册漏报。
                shift = (outer_shift or {}).get(kind, OUTER_PRIOR_SHIFT[kind] * scale)
                c = prior + shift
                lo = max(lo, c - OUTER_PRIOR_WIN * scale)
                hi = min(hi, c + OUTER_PRIOR_WIN * scale)
            if hi - lo < 5:
                continue
            offs = np.arange(lo, hi + 1, 1.0) * sign
            prof = []
            for o in offs:
                yy = (base + o).astype(int)
                ok = (yy >= 0) & (yy < height)
                prof.append(binm[yy[ok], xs[ok]].mean() if ok.any() else 0.0)
            r = _outer_run(np.array(prof), offs, prefer_abs=prior, scale=scale)
            if r is None:
                continue
            if _paper_beyond(binm, base, xs, r[0], sign, height, scale) > OUTER_PAPER_MAX:
                continue          # 条外面还是墨 => 这根本不是最外层，见常量注释
            out[f"{kind}_outer_offset"] = r[0]
            out[f"{kind}_frame_kind"] = "double"
    # 书级先验兜底：该有外框却没探到的边，在册基准邻域找弱一档的墨（见 OUTER_INK_FALLBACK）
    if book_gap:
        for kind, line, sign in (("top", top, -1.0), ("bottom", bottom, 1.0)):
            xs = xs_top if kind == "top" else xs_all
            declared = (frame_layers or {}).get(kind)
            if declared == 1 or out[f"{kind}_outer_offset"] is not None:
                continue
            # 没声明层数时保持老行为：判了 single 就不再兜底。
            # 声明 2 层的边不会走到这里判 single（上面拦了），继续兜底。
            if declared != 2 and out[f"{kind}_frame_kind"] == "single":
                continue
            g = book_gap.get(kind)
            if g is None:
                continue
            base = np.array([line.y_at((width - 1) - x) for x in xs])
            lo = float(OUTER_GAP_MIN)          # 下界不收，见 OUTER_PRIOR_FALLBACK_WIN
            hi = min(gap_max, g + OUTER_PRIOR_FALLBACK_WIN * scale)
            best = None
            for o in np.arange(lo, hi + 1, 1.0):
                yy = (base + o * sign).astype(int)
                ok = (yy >= 0) & (yy < height)
                v = float(binm[yy[ok], xs[ok]].mean()) if ok.any() else 0.0
                if v >= OUTER_INK_FALLBACK and (best is None or v > best[1]):
                    best = (float(o), v)
            if best is not None and _paper_beyond(
                    binm, base, xs, best[0] * sign, sign, height, scale) > OUTER_PAPER_MAX:
                best = None        # 条外面还是墨 => 不是最外层，当没找着
            if best is None:
                if declared != 2:
                    continue
                # 声明了 2 层却一点墨都没看见：外框仍然**存在**，只是这一页
                # 印不清/糊了/磨没了。按册基准硬落位——位置未必准，但往外让过
                # （OUTER_ESTIMATE_SLACK）保证不会切到字。
                off = g + OUTER_ESTIMATE_SLACK
            else:
                off = best[0]      # 见到墨了就是实测位置，不外让
            off = min(float(off), float(gap_max))
            # 让出纸面就退回纸边内侧，别把框画到图像外头
            room = (float(base.min()) if sign < 0
                    else float(height - 1 - base.max()))
            off = min(off, max(0.0, room - 1.0))
            if off <= 0:
                continue
            out[f"{kind}_outer_offset"] = off * sign
            out[f"{kind}_frame_kind"] = "double"
            out[f"{kind}_outer_estimated"] = True
    return out


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


def push_bottom_to_bar(binm: np.ndarray, bottom: HLine, verticals: list[VLine],
                       width: int, height: int) -> tuple[HLine, float]:
    """下版框线之下若有真框条、线又离它 ≥BPUSH_MIN_SHIFT，把线推到条上沿之上。
    返回 (新线, 推了多少 px)。见 BPUSH_* 常量注释。"""
    from dataclasses import replace as _replace
    if len(verticals) < 2:
        return bottom, 0.0
    vx = sorted((width - 1) - v.x_at(height * 0.9) for v in verticals)
    x0, x1 = int(vx[0] + 15), int(vx[-1] - 15)
    # 右界线外推出图（换源新图，vol23 p10、vol37 p74）时截到图内；原先在这里越界报错，截了不影响没越界的页
    x1 = min(x1, binm.shape[1])
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


# ---------------------------------------------------------------- 内框线：线落在外板框上时拉回内板框

#: `pull_inner_line`（2026-11-23，册配置声明 `frame_layers: 2`、参数 `inner_pull` 开时用）。双线版框的书，
#: 内板框线磨淡或印不出时，探出的线会落在**外板框的粗条**上或紧贴它的内沿（殿本下框偏 8–33px、全唐文下框 31px、
#: 史記上框 19px，layout-gold 已知问题 1/4）。金标口径是内板框线位置。
#: 判据：线所在处（±INNER_ON_BAR 内）有一条粗条（≥INNER_THICK_MIN 行的连续墨带，行覆盖 ≥INNER_BAR_COV）——内框线只有
#: 2~6px，粗条必是外框。是外框就往文字一侧找：粗条内沿之内 INNER_SEARCH_GAP~(册 outer_gap + INNER_SEARCH_EXTRA) px 里
#: 的细条（≤INNER_THIN_MAX 行、覆盖 ≥INNER_THIN_COV）取最靠文字的那条当内框线；找不到按「外沿 − 册 outer_gap」估
#: （不给 outer_gap 就不动）。线不在粗条上（含内框线清楚、粗条在 +18~+30 外面的页）原样不动。
INNER_ON_BAR = 8
INNER_BAR_COV = 0.5
INNER_THICK_MIN = 10
INNER_THIN_COV = 0.30
INNER_THIN_MAX = 9
INNER_SEARCH_GAP = 6
INNER_SEARCH_EXTRA = 25
INNER_GAP_TOL = (0.5, 1.7)  # 细条离粗条外沿的距离须在册 outer_gap 的这个比例内才信（内外框间距全书基本一致）
INNER_OUT = 70           # 线外（朝外）看多远，找粗条外沿


def pull_inner_line(binm: np.ndarray, line: HLine, kind: str, verticals: list[VLine],
                    width: int, height: int, gap: float | None) -> tuple[HLine, float]:
    """线落在外板框粗条上（或紧贴内沿）时，拉回内板框线。返回 (新线, 朝文字一侧拉了多少 px，没动＝0)。"""
    from dataclasses import replace as _replace
    if len(verticals) < 2:
        return line, 0.0
    vx = sorted((width - 1) - v.x_at(height * 0.5) for v in verticals)
    x0, x1 = int(vx[0] + 15), min(int(vx[-1] - 15), binm.shape[1])
    if x1 - x0 < 100:
        return line, 0.0
    xs = np.arange(x0, x1)
    base = np.array([line.y_at((width - 1) - x) for x in xs])
    out_sign = 1.0 if kind == "bottom" else -1.0       # 朝外（版框外沿）的 y 方向
    lo_o, hi_o = -(INNER_SEARCH_EXTRA + int(gap or 30) + INNER_SEARCH_GAP + 20), INNER_OUT
    offs = np.arange(lo_o, hi_o + 1)                   # 外向为正
    cov = np.zeros(len(offs))
    for i, o in enumerate(offs):
        yy = (base + o * out_sign).astype(int)
        ok = (yy >= 0) & (yy < height)
        if ok.any():
            cov[i] = float((binm[yy[ok], xs[ok]] > 0).mean())
    bar = cov >= INNER_BAR_COV
    # 离线（偏移 0）最近的粗条：连续（容 1 行缝）的 ≥INNER_BAR_COV 带
    z = -lo_o
    cand = None
    i = 0
    while i < len(bar):
        if not bar[i]:
            i += 1
            continue
        j = i
        while j + 2 < len(bar) and (bar[j + 1] or bar[j + 2]):
            j += 1 if bar[j + 1] else 2
        if j - i + 1 >= INNER_THICK_MIN and offs[i] - INNER_ON_BAR <= 0 <= offs[j] + INNER_ON_BAR:
            cand = (i, j)
            break
        i = j + 1
    if cand is None:
        return line, 0.0
    i0, j0 = cand
    inner_edge, outer_edge = int(offs[i0]), int(offs[j0])      # 外向为正：粗条内沿、外沿
    inside = inner_edge < 0 <= outer_edge                      # 线压在粗条里（否则只是紧贴它的内沿）
    # 粗条内沿之内找细条（朝文字 = 偏移更小）
    best = None
    k = i0 - INNER_SEARCH_GAP
    lim = i0 - INNER_SEARCH_GAP - (int(gap or 30) + INNER_SEARCH_EXTRA)
    while k > max(lim, 0):
        if cov[k] >= INNER_THIN_COV:
            e = k
            while e - 1 > 0 and cov[e - 1] >= INNER_THIN_COV:
                e -= 1
            if k - e + 1 <= INNER_THIN_MAX:
                best = (e + k) / 2.0              # 细条中心的下标
            k = e - 1
            continue
        k -= 1
    if best is not None and gap:
        d = outer_edge - float(offs[0] + best)             # 细条离粗条外沿多远，该约等于册内外框间距
        if not (INNER_GAP_TOL[0] * gap <= d <= INNER_GAP_TOL[1] * gap):
            best = None
    if best is not None:
        new_off = float(offs[0] + best)
    elif gap and inside:
        new_off = float(outer_edge - gap)
        new_off = min(new_off, float(inner_edge - 4))
    else:
        return line, 0.0
    shift = new_off * out_sign                  # 线在 y 上要挪的量（朝外为正的偏移 → y）
    if abs(new_off) < 4:
        return line, 0.0
    return _replace(line, y_at_right=line.y_at_right + shift), float(-new_off)


# ---------------------------------------------------------------- 界行：按证据重定位

#: `snap_verticals_to_evidence`（2026-09-20）。折线拟合只认「墨落在线上 ±1px」，界行
#: 淡到看不见的横带里它会去贴字的竖笔；vol02 后半册（p149~185）一半以上横带没有可见
#: 界行，p160 v3~v5 在页底偏出 25~45px、v3 直接穿进文字列；p177/p178 只有顶端 10% 印了
#: 界行，下面整段外推，偏到 80px。**能看见界行的地方线从不偏**（两册普查：有界行的
#: 横带里偏移全部 ≤2px），所以这一步只在没有界行证据的横带用**文字缝中心**当证据，
#: 与有界行横带的界行位置一起重新拟合三段折线；证据不足或改动 <SNAP_MIN_CHANGE 的线
#: 原样保留。
#: 外框线（首尾两条）同样按「折点只许在有界行支撑的横带偏离直线」管，但只认两种证据：线就压在
#: 可见框线上（偏 <SNAP_MIN_DEVIATION）→ 原位；否则 → 直线位（直线已由 `_snap_to_inner_rule`
#: 挑过细内框）。不用文字缝（外侧没有文字列），也不往远处的框线挪（外框外侧 17~40px 是粗外条，
#: 挪过去列就宽进一条黑边）。vol08 p2（卷首大印页）左外框下半段印得淡、折线被第 9 列字的竖笔
#: 吸进 42px，七个字只罩住右半——护栏退的是邻线，外框线自己没人管。
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
SNAP_MIN_CHANGE = 4.0       # 拟合结果与现役线最大差 < 这个就不换（防抖）
SNAP_PITCH_LO, SNAP_PITCH_HI = 0.6, 1.4   # 换线后与邻线间距须在列距的这个范围内


def _rule_offset(binm: np.ndarray, v: VLine, width: int, y0: int, y1: int) -> float | None:
    ys = np.arange(y0, min(y1, binm.shape[0]), 2)   # 新图版框贴图底：下框拟合线可越出图底一两行
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


def snap_verticals_to_evidence(binm: np.ndarray, top: HLine, bottom: HLine,
                               verticals: list[VLine], width: int, height: int,
                               straight: list[VLine] | None = None
                               ) -> tuple[list[VLine], int]:
    """界行逐条按横带证据重拟合三段折线。返回 (新线表, 换了几条)。见 SNAP_* 常量注释。
    输入输出都是新坐标系的 VLine；证据在原图坐标里量。

    每个横带的证据，按优先级：
      1. 可见界行（长竖段）→ 界行位置；
      2. 线压在字上 → 文字缝中心（按邻线中点选缝）；
      3. 否则 → **直线拟合的位置**（`straight`，折线拟合之前那条）。折线拟合在界行淡到
         看不见的横带里会把折点贴到字的竖笔上（vol02 p160 页底 c4~c7 偏 21~37px，而直线
         外推离文字列中心算出的界行 ≤5px）——折点只许在有界行支撑的横带偏离直线。
         没给 `straight` 就退回当前线位。
    首尾两条外框线只用 1（且只认线就压着的框线）和 3，见 SNAP_* 注释。"""
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
    for vi in range(n):
        v = verticals[vi]
        outer = vi in (0, n - 1)
        ys, xs, ws = [], [], []
        sick = False
        for (y0, y1, yc, colp) in bands:
            xl_new = float(v.x_at(float(yc)))
            xl_raw = int(round((width - 1) - xl_new))
            d = _rule_offset(binm, v, width, y0, y1)
            if outer and d is not None and abs(d) >= SNAP_MIN_DEVIATION:
                d = None                          # 外框线不往远处的框线挪（见 SNAP_* 注释）
            if d is not None:
                ys.append(yc); xs.append(xl_new - d); ws.append(1.0)     # 原图 +d ⇒ 新坐标 −d
                if abs(d) >= SNAP_MIN_DEVIATION:
                    sick = True
                continue
            on_text = colp[max(0, xl_raw - 12):xl_raw + 13].mean() >= SNAP_TEXT_DENSE
            if on_text and not outer:
                sick = True                       # 压在字上（见 SNAP_TEXT_DENSE）
                xp_raw = (width - 1) - (verticals[vi - 1].x_at(float(yc)) + verticals[vi + 1].x_at(float(yc))) / 2.0
                gt = _gap_target(colp, xl_raw, pitch, width, xp_raw)
                if gt is not None:
                    ys.append(yc); xs.append((width - 1) - gt[0]); ws.append(1.0)
                    continue
            # 无界行、没压字：折线不许在这里偏离直线（见 docstring 第 3 条）
            sx = float(straight[vi].x_at(float(yc))) if straight and vi < len(straight) else xl_new
            if abs(sx - xl_new) >= SNAP_MIN_DEVIATION:
                sick = True
            ys.append(yc); xs.append(sx); ws.append(1.0)
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
        # 重定位后的线压在界行上的行不许比直线少（`seg/polyline._hit_frac`）：真界行是直的、看得见的页上，
        # 某一带被判成「压字」挪去字缝，整条线跟着弯 20–70px 斜穿字（A20 11-03 报 vol84 p101/112、
        # vol21 p68、vol40 p173；11 册沙箱 956 条重定位线里 54 条如此，看图全是斜穿）
        base = straight[vi] if straight and vi < len(straight) else v
        if _hit_frac(binm, cand.x_at, int(yt), int(yb), width) < _hit_frac(binm, base.x_at, int(yt), int(yb), width):
            continue
        cands[vi] = cand
    # 邻线间距护栏：按邻线的候选量（邻线没候选就按旧线）。整页一起偏的页（p177）
    # 旧邻线本身是错的，按旧邻线量会把正确的纠正当成「间距 1.45×列距」拒掉。
    # 分两轮：先定内部界行（只看内部候选，外框线按旧线），再按定下来的邻线判外框线——
    # 外框线的候选不许反过来放行内部界行的候选（vol04 p178 实测：外框回直线后 v1 的坏候选
    # 跟着过了护栏，页底偏 64px）。
    inner = {vi: c for vi, c in cands.items() if 0 < vi < n - 1}
    changed = 0
    for group, nb_of in ((inner, lambda ni: inner.get(ni, verticals[ni])),
                         ({vi: c for vi, c in cands.items() if vi not in inner}, lambda ni: out[ni])):
        for vi, cand in group.items():
            ok = True
            # 在横带中心量（有证据的地方）。折点 y 在版框顶/底，最后一带之外是外推，
            # 边框相邻列的合理纠正会在那里被读成 1.4×列距。
            for y in (float(yc) for (_, _, yc, _) in bands):
                for ni in (vi - 1, vi + 1):
                    if not 0 <= ni < n:
                        continue
                    gap = abs(cand.x_at(y) - nb_of(ni).x_at(y))
                    if not (SNAP_PITCH_LO * pitch <= gap <= SNAP_PITCH_HI * pitch):
                        ok = False
            if ok:
                out[vi] = cand
                changed += 1
    return out, changed


#: 书级外框间距先验（`BookSpec.outer_gap`，2026-09-20）。整册「外框外延 − 内框线」
#: 极稳：vol02 上 38.6±8.3 / 下 27.2±5.3，vol01 上 36.7±6.7 / 下 27.4±4.7（std 都在
#: 一条框的厚度量级）。所以某一页因为磨损/扫描糊了探不到时，**不该报 None**——
#: 按整册基准兜底给一个，比没有强（用户 2026-09-20 定）。
#:
#: 兜底只在先验邻域 ±`OUTER_PRIOR_FALLBACK_WIN` 内找**弱一档**的墨（≥`OUTER_INK_FALLBACK`）：
#: 全书实测漏探页在册中位附近仍有 0.30~0.93 的峰，只是够不着 `OUTER_INK_MIN=0.25`
#: 的连续段判据（磨断了）。找不到就仍报 None，并在结果里标 `*_outer_estimated=True`。
#:
#: ⚠️ **估出来的只是「位置提示」，不是「探到了」**（用户 2026-09-20 定）。两册看图查实：
#: 一部分（vol02 p39/p136）确实压在磨掉大半的残框墨上；另一部分（vol01 p33/p98）落在
#: 几乎没墨的纸上。试过「落点最长连续横段/版框宽」想把两者分开——**分不开**：
#: 0.05~0.29 连续分布，真残框 p39 的 0.13 比凭空的 p98 的 0.21 还低（同
#: `_rescue_bottom` 那段记的教训：磨损到这个程度单一几何量没有分辨力）。
#: 所以闸1 **不**把 estimated 当作「探到外框」——`outer_frame_missing` 照旧 flag；
#: 下游要用这个位置（比如裁图留边）可以取，要严格统计就按 `*_outer_estimated` 滤掉。
OUTER_INK_FALLBACK = 0.18
#: 按册基准估外框位置时，再往**外**让这么多像素（2026-09-22）。
#: 估位取册中位，真外框可能比它更外：实测 `真间距 - 册中位` 的 p95 是
#: 上 8.3/6.5、下 5.3/6.0，max 到 24.6/32.9（vol02/vol01）。让 p95 这一档
#: 就能盖住 95% 的页。
#:
#: **让多了几乎没有代价**：外框在内框**之外**，文字在**之内**——往外让只会
#: 离字更远，不可能切字。唯一的边界是让出纸面，而内框线到图像边缘还有
#: 262~324px（两册 n=120 实测 min=262），让 10px 用掉不到 4%。
#: 所以取两册四条边 p95 的上界 8.3 向上取整 = 9，再留 1px 余量。
#:
#: ⚠️ **只加在「一点墨都没见到、纯按册基准猜」的位置上**。弱档兜底找到了墨
#: 的（`OUTER_INK_FALLBACK`）是实测，外让会把探到的 11px 推成 22px——
#: 见 `test_fallback_window_reaches_frames_closer_than_the_book_median`。
OUTER_ESTIMATE_SLACK = 10.0
#: 兜底窗口：`[OUTER_GAP_MIN, 册基准 + OUTER_PRIOR_FALLBACK_WIN]`。
#: **下界不跟着册基准收**（2026-09-22）：两册 192 条报 None 的边逐条量剖面，58 条是
#: 「离内框有一段白、然后一个独立的墨峰、峰后回落」——**真外框**，只是这一页的内外间距
#: 比册基准近得多（峰位 8~23px，而册基准 27~39）。按 `基准±12` 开窗根本够不着。
#: 磨损页的内外间距本来就散（这批书 std 4.7~8.3，个别页更远），下界收紧没有道理：
#: 外框只可能在内框**之外**，`OUTER_GAP_MIN=12` 已经是物理下界。
#: 上界仍跟着基准收——再往外就是书口/版心的宽黑带（p133 峰 1.00@58、p47 0.34@56，
#: 逐条看图确认不是框线）。
OUTER_PRIOR_FALLBACK_WIN = 12.0


def measure_book_outer_gap(results) -> dict:
    """量一册的 `outer_gap`：上/下「外框外延 − 内框线」的中位数。

    `results`：整册的 `BorderDetectionResult`（只统计探到外框的页）。
    返回 `{"top": float, "bottom": float}`，样本不足 8 页的边不进字典——
    样本太少的中位数当先验会把整册带偏。
    ⚠️ 只在标定时跑一次写进 yaml，别放进逐页流水线。
    """
    acc: dict[str, list[float]] = {"top": [], "bottom": []}
    for res in results:
        if res is None:
            continue
        for kind in ("top", "bottom"):
            o = getattr(res, f"{kind}_outer_offset", None)
            if o is not None:
                acc[kind].append(abs(float(o)))
    return {k: float(np.median(v)) for k, v in acc.items() if len(v) >= 8}


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
        xs = xs[xs < w]                     # 同 detect_outer_borders：越过图宽的列去掉
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


# ── 外框线「先粗条、后细线」（`outer_bar`，2026-11-24，用户定）────────────────────────────
#: 左右外框内侧的细线（最外两条竖线）会磨没，粗外框条不容易磨掉。先沿线找粗条内沿（要求连续），再在粗条内沿往里
#: 找细线，量出「细线到粗条内沿」的间距；细线看得见的地方用细线，磨没的地方用「粗条内沿 − 局部间距」补，最后收成
#: 三段折线（折角小，单行跳点拽不动）。现线本来就压在细线上的横带不动。没有粗条的一侧（版心侧、脈經单线边）不动。
#: 79 页版面基准模拟（ai-team CV1 外框分析，2026-11-24）：146 条外框线 p95 合计 374→273、>5px 21→14
#: （殿本 vol02 p150 25.9→2.2、vol01 p9 33.5→4.1、史記 sj40 p58 25.4→2.7）。缺省关。
OBAR_STEP = 4             # 每隔这么多行取一个样本
OBAR_MARGIN = 70          # 离上下版框这么多 px 内不取样（横框条会被当成粗条）
OBAR_BAR_MIN = 8          # 粗条：≥这么宽的连续墨
OBAR_REACH = (-12, 90)    # 粗条在线位朝外 -12..+90px 里找
OBAR_THIN = (2, 9)        # 细线墨段宽
OBAR_THIN_WIN = 45        # 细线候选在线位 ±这么多 px 里
OBAR_GAP = (6, 60)        # 细线离粗条内沿的距离范围
OBAR_COVER = 0.8          # 粗条覆盖样本的比例不到这个＝这一侧没有粗条
OBAR_GAP_IQR = 6.0        # 间距四分位距超过这个＝量的不是同一对线，不动
OBAR_GAP_TOL = 3.0        # 间距样本离全页中位超过这个丢掉（多半是字的笔画）
OBAR_GAP_SMOOTH = 31      # 间距沿线滑动中位窗（样本数）
OBAR_THIN_TOL = 5.0       # 细线离「粗条内沿 − 间距」超过这个不当细线
OBAR_KEEP = 0.6           # 现线 ±2px 有窄墨（≤OBAR_THIN[1]）的样本比例（11 样本滑窗）≥ 这个就不动现线
OBAR_MIN_SAMPLES = 20


def _obar_runs(row: np.ndarray, lo: int) -> list[tuple[int, int]]:
    d = np.diff(np.concatenate([[0], row.astype(np.int8), [0]]))
    s, e = np.where(d == 1)[0], np.where(d == -1)[0]
    return [(int(a) + lo, int(b) + lo) for a, b in zip(s, e)]      # [a, b)


def _obar_track(cands: list[list[float]], miss: float, jump: float) -> np.ndarray:
    """每个样本一串候选位置，挑一条连续的路径（动态规划）。代价＝相邻取值差/jump 的平方（封顶 25），
    跳过一个样本罚 miss。返回每个样本选的值（nan＝这里不取）。"""
    n = len(cands)
    states = [list(c) + [None] for c in cands]
    cost = np.array([0.0 if v is not None else miss for v in states[0]])
    carry = list(states[0])
    backs = []
    for i in range(1, n):
        st = states[i]
        cs = np.full(len(st), np.inf)
        bk = np.zeros(len(st), dtype=int)
        cr: list = [None] * len(st)
        for j, v in enumerate(st):
            for k in range(len(states[i - 1])):
                pv = carry[k]
                if v is None:
                    c, nv = cost[k] + miss, pv
                else:
                    c = cost[k] + (0.0 if pv is None else min((abs(v - pv) / jump) ** 2, 25.0))
                    nv = v
                if c < cs[j]:
                    cs[j], bk[j], cr[j] = c, k, nv
        cost, carry = cs, cr
        backs.append(bk)
    j = int(np.argmin(cost))
    out = np.full(n, np.nan)
    for i in range(n - 1, -1, -1):
        v = states[i][j]
        out[i] = np.nan if v is None else v
        if i > 0:
            j = int(backs[i - 1][j])
    return out


def _obar_median(x: np.ndarray, win: int) -> np.ndarray:
    if len(x) < 2:
        return x.copy()
    h = win // 2
    p = np.concatenate([np.full(h, x[0]), x, np.full(h, x[-1])])
    return np.median(np.lib.stride_tricks.sliding_window_view(p, 2 * h + 1), axis=1)


def _obar_line(mask01: np.ndarray, v: VLine, yt: float, yb: float, w: int, sgn: int) -> list[float] | None:
    """一条外框线（新坐标 VLine）按粗条重定位，返回四个折点的旧坐标 x（在 yt、1/3、2/3、yb 处），不动返回 None。
    sgn：旧坐标里朝外的方向（右框线 +1，左框线 -1）。"""
    h = mask01.shape[0]
    ys = np.arange(int(yt) + OBAR_MARGIN, int(yb) - OBAR_MARGIN, OBAR_STEP)
    if len(ys) < 3 * OBAR_MIN_SAMPLES:
        return None
    px = (w - 1) - v.x_at(ys.astype(np.float64))               # 现线的旧坐标 x
    ecand, tcand, narrow = [], [], np.zeros(len(ys))
    for k, y in enumerate(ys):
        row = mask01[max(0, y - 2):min(h, y + 3)].mean(axis=0) >= 0.5
        c = int(round(px[k]))
        lo, hi = (c + OBAR_REACH[0], c + OBAR_REACH[1]) if sgn > 0 else (c - OBAR_REACH[1], c - OBAR_REACH[0])
        lo, hi = max(lo, 0), min(hi, w)
        e = []
        for a, b in (_obar_runs(row[lo:hi], lo) if hi > lo else []):
            if b - a >= OBAR_BAR_MIN:
                e.append(float(a if sgn > 0 else b - 1))         # 粗条朝页心那一边
        ecand.append(e)
        lo2, hi2 = max(0, c - OBAR_THIN_WIN), min(w, c + OBAR_THIN_WIN)
        tcand.append([(a + b - 1) / 2.0 for a, b in _obar_runs(row[lo2:hi2], lo2)
                      if OBAR_THIN[0] <= b - a <= OBAR_THIN[1]])
        hit = [q for q in range(c - 2, c + 3) if 0 <= q < w and row[q]]
        if hit:
            a = b = hit[0]
            while a > 0 and row[a - 1]:
                a -= 1
            while b < w - 1 and row[b + 1]:
                b += 1
            narrow[k] = 1.0 if b - a + 1 <= OBAR_THIN[1] else 0.0
    edge = _obar_track(ecand, miss=3.0, jump=2.0)
    fin = np.isfinite(edge)
    if fin.mean() < OBAR_COVER:
        return None
    tc2 = []
    for k in range(len(ys)):
        if fin[k]:
            tc2.append([x for x in tcand[k] if OBAR_GAP[0] <= (edge[k] - x) * sgn <= OBAR_GAP[1]])
        else:
            tc2.append(tcand[k])
    thin = _obar_track(tc2, miss=1.5, jump=1.5)
    gap = (edge - thin) * sgn
    okg = np.isfinite(gap)
    if okg.sum() < OBAR_MIN_SAMPLES:
        return None
    q1, q3 = np.percentile(gap[okg], [25, 75])
    if q3 - q1 > OBAR_GAP_IQR:
        return None
    okg &= np.abs(np.where(okg, gap, 0.0) - float(np.median(gap[okg]))) <= OBAR_GAP_TOL
    if okg.sum() < OBAR_MIN_SAMPLES:
        return None
    gloc = np.interp(ys, ys[okg], _obar_median(gap[okg], OBAR_GAP_SMOOTH))
    bridge = np.interp(ys, ys[fin], edge[fin]) - sgn * gloc
    thin_ok = np.isfinite(thin) & (np.abs(np.where(np.isfinite(thin), thin, 0.0) - bridge) <= OBAR_THIN_TOL)
    pred = np.where(thin_ok, thin, bridge)
    keep = np.convolve(narrow, np.ones(11) / 11.0, mode="same") >= OBAR_KEEP
    pred = np.where(keep, px, pred)
    # 收成三段折线：折点在 yt、1/3、2/3、yb，Huber 迭代重加权最小二乘
    ky = np.array([yt, yt + (yb - yt) / 3.0, yt + 2.0 * (yb - yt) / 3.0, yb])
    yy = ys.astype(np.float64)
    i = np.clip(np.searchsorted(ky, yy) - 1, 0, 2)
    t = (yy - ky[i]) / (ky[i + 1] - ky[i])
    A = np.zeros((len(yy), 4))
    A[np.arange(len(yy)), i] = 1 - t
    A[np.arange(len(yy)), i + 1] = t
    wts = np.ones(len(yy))
    c4 = None
    for _ in range(8):
        M = A.T @ (A * wts[:, None]) + 1e-6 * np.eye(4)
        c4 = np.linalg.solve(M, A.T @ (wts * pred))
        r = np.abs(pred - A @ c4)
        wts = np.where(r <= 2.0, 1.0, 2.0 / np.maximum(r, 1e-6))
    return [float(x) for x in c4]


def refit_outer_by_bar(mask: np.ndarray, top: HLine, bottom: HLine, verticals: list[VLine], w: int, h: int,
                       outer_side: str | None = None, skip_sides: tuple = ()) -> tuple[list[VLine], int]:
    """最外两条竖线按「先粗条、后细线」重定位（见 OBAR_*）。返回 (新线表, 换了几条)。换了的线是三段格式；
    调用方负责把整页统一成三段。`outer_side`（册配置 side_frame）给了就只做那一侧。
    `skip_sides`（含 "left"／"right"，册声明 frame_layers 该侧=1，四周單邊）：该侧不做——粗条本身就是版框，
    朝里没有细内框，不能按「粗条内沿 − 间距」补一条（朱楓林集 01 册 p87）。"""
    n = len(verticals)
    if n < 4:
        return verticals, 0
    mask01 = (np.asarray(mask) > 0)
    out, changed = list(verticals), 0
    for vi, sgn, side in ((0, 1, "right"), (n - 1, -1, "left")):
        if outer_side in ("left", "right") and side != outer_side:
            continue
        if side in skip_sides:
            continue
        v = verticals[vi]
        xc = v.x_at(h / 2.0)
        yt, yb = float(top.y_at(xc)), float(bottom.y_at(xc))
        if yb - yt < 600:
            continue
        kx_old = _obar_line(mask01, v, yt, yb, w, sgn)
        if kx_old is None:
            continue
        ky = [yt, yt + (yb - yt) / 3.0, yt + 2.0 * (yb - yt) / 3.0, yb]
        out[vi] = _from_knots([(w - 1) - x for x in kx_old], ky)
        changed += 1
    return out, changed


# ---------------------------------------------------------------- 逐线追细墨重拟（vline_track）
# 用户 2026-11-23 定的 B：「先找直线，不够好就找折线，不是按开关来」。每条竖线单独：沿现线追细墨，
# 先拟直线，贴不住（残差 80 分位 > TRK_STRAIGHT）再试折点位置自由的三段折线；三段折线要过护栏：
# 折角小（相邻段斜率差 ≤ TRK_DSLOPE，用户：折线之间角度不应很大）、每段都有细墨支撑（磨没处不许瞎折）。
# 整条线细墨支撑不足（磨没、只剩字的笔画）就不动现线。线旁宽墨（鱼尾、粗框条）边上的碎墨不当细线。
# 79 页版面金标（精修 r1/r2 后）上模拟：偏 >5px 的线 81→29。

TRK_STEP = 2              # 取样行距
TRK_WINS = (20, 8, 4)     # 逐轮收窄的追踪窗口半宽（px）
TRK_THIN = (2, 10)        # 细线墨段宽
TRK_WIDE = 12             # 宽于这个的墨段算宽墨（鱼尾、粗框条、字块）
TRK_WIDE_GAP = 8          # 离宽墨不足这么多 px 的细墨段丢掉
TRK_MIN_OBS = 60          # 观测行少于这个不动
TRK_STRAIGHT = 1.0        # 直线残差 80 分位 ≤ 这个就用直线
TRK_GAIN = 0.3            # 折线残差要比直线（或上一个候选）小这么多才换
TRK_KNOT_N = 13           # 折点候选个数（在线长 8%–92% 间均分）
TRK_DSLOPE = 0.03         # 相邻段斜率差上限（≈1.7°）
TRK_SUPPORT = 0.35        # 每段（及整条线）里残差 ≤ TRK_INLIER 的行占比下限
TRK_INLIER = 2.0
TRK_HUBER = 1.5
TRK_LW_K = (1.6, 2.0)     # 本线墨宽中位 lw：细线上限 max(TRK_THIN[1], 1.6·lw)，宽墨下限 max(TRK_WIDE, 2·lw)
                          # （殿本有的页界行粗到 12px，按死门槛 10 整条线都被当成宽墨，只剩毛边可追，vol01 p100）
TRK_FAINT_HALF = 4         # 淡线：横向闭运算半宽（px）；宽过细线、窄过粗框条（粗条、字块里暗度为 0）
TRK_DARK_CAP = 60.0        # 暗度封顶（字块、粗墨不压过淡线）
TRK_GSEC = 200             # 淡线兜底：分段长（px）
TRK_GWIN = 12              # 淡线兜底：每段平移搜索半宽（px）
TRK_GQ = 2.5               # 淡线兜底：段峰值 / 剖面中位 下限
TRK_GCOVER = 0.5           # 淡线兜底：看见的段占比下限
TRK_GBETTER = 1.1          # 淡线兜底：新线沿线平均暗度要比现线高这么多倍
TRK_HIT_DROP = 0.05       # 新线「线心 ±1px 压着墨」的行占比比现线低这么多 ⇒ 新线跑到白纸上了，不换


def _trk_hit(mask01: np.ndarray, ys: np.ndarray, xs: np.ndarray, w: int) -> float:
    """沿线逐行，线心 ±1px 内有墨的行占比。"""
    h = mask01.shape[0]
    n = hit = 0
    for y, x in zip(ys, xs):
        yi, xi = int(y), int(round(float(x)))
        if not (0 <= yi < h and 1 <= xi < w - 1):
            continue
        n += 1
        hit += bool(mask01[yi, xi - 1:xi + 2].any())
    return hit / n if n else 0.0


def _trk_linewidth(mask01: np.ndarray, ys: np.ndarray, xs: np.ndarray, w: int) -> float | None:
    """现线压着的墨段宽的中位（只算 ≤40px 的段，压在字块上的行不算）。"""
    h = mask01.shape[0]
    ws = []
    for y, x in zip(ys[::4], xs[::4]):
        yi, xi = int(y), int(round(float(x)))
        if not (0 <= yi < h and 0 <= xi < w) or not mask01[yi, xi]:
            continue
        a = b = xi
        while a > 0 and mask01[yi, a - 1] and xi - a < 40:
            a -= 1
        while b < w - 1 and mask01[yi, b + 1] and b - xi < 40:
            b += 1
        if b - a + 1 <= 40:
            ws.append(b - a + 1)
    return float(np.median(ws)) if len(ws) >= 20 else None


def _trk_cands(mask01: np.ndarray, y: int, x: float, win: int, w: int,
               thin_max: float = TRK_THIN[1], wide_min: float = TRK_WIDE) -> list[float]:
    lo, hi = max(0, int(x) - win - 20), min(w, int(x) + win + 21)
    row = mask01[y, lo:hi]
    runs = _obar_runs(row, lo)
    wide = [(a, b) for a, b in runs if b - a > wide_min or a == lo or b == hi]
    out = []
    for a, b in runs:
        c = (a + b - 1) / 2.0
        if TRK_THIN[0] <= b - a <= thin_max and abs(c - x) <= win \
                and all(b <= wa - TRK_WIDE_GAP or a >= wb + TRK_WIDE_GAP for wa, wb in wide):
            out.append(c)
    return out


def _trk_basis(ys: np.ndarray, knots) -> np.ndarray:
    return np.stack([np.ones_like(ys), ys] + [np.maximum(ys - k, 0.0) for k in knots], 1)


def _trk_fit(ys: np.ndarray, xs: np.ndarray, knots):
    a = _trk_basis(ys, knots)
    wt = np.ones(len(xs))
    co = np.zeros(a.shape[1])
    for _ in range(8):
        sw = np.sqrt(wt)
        co = np.linalg.lstsq(a * sw[:, None], xs * sw, rcond=None)[0]
        r = np.abs(a @ co - xs)
        wt = np.where(r <= TRK_HUBER, 1.0, TRK_HUBER / np.maximum(r, 1e-9))
    return co, float(np.percentile(r, 80))


def _trk_line(mask01: np.ndarray, v: VLine, yt: float, yb: float, w: int) -> VLine | None:
    """一条竖线（新坐标）按细墨重拟，返回新 VLine（直线或自由折点三段），不动返回 None。"""
    ys = np.arange(yt + 4, yb - 4, TRK_STEP, dtype=np.float64)
    if len(ys) < TRK_MIN_OBS:
        return None
    h = mask01.shape[0]
    cur = (w - 1) - v.x_at(ys)
    x_old = cur.copy()
    lw = _trk_linewidth(mask01, ys, cur, w)
    thin_max = max(float(TRK_THIN[1]), TRK_LW_K[0] * lw) if lw else float(TRK_THIN[1])
    wide_min = max(float(TRK_WIDE), TRK_LW_K[1] * lw) if lw else float(TRK_WIDE)
    span = yb - yt
    best_k: list[float] = []
    best_c = None
    for win in TRK_WINS:
        obs = np.full(len(ys), np.nan)
        for k, y in enumerate(ys):
            yi = int(y)
            if not 0 <= yi < h:
                continue
            c = _trk_cands(mask01, yi, float(cur[k]), win, w, thin_max, wide_min)
            if c:
                obs[k] = min(c, key=lambda t: abs(t - cur[k]))
        ok = np.isfinite(obs)
        if ok.sum() < TRK_MIN_OBS:
            return None
        yo, xo = ys[ok], obs[ok]
        co, s80 = _trk_fit(yo, xo, [])
        best = (s80, [], co)
        if s80 > TRK_STRAIGHT:
            g = np.linspace(yt + 0.08 * span, yb - 0.08 * span, TRK_KNOT_N)
            dist = np.where(ok, obs, 1e9)
            segs_cache = {}
            for i in range(len(g)):
                for j in range(i + 1, len(g)):
                    p, q = float(g[i]), float(g[j])
                    co2, s2 = _trk_fit(yo, xo, [p, q])
                    if s2 >= best[0] - TRK_GAIN or abs(co2[2]) > TRK_DSLOPE or abs(co2[3]) > TRK_DSLOPE:
                        continue
                    hit = np.abs(_trk_basis(ys, [p, q]) @ co2 - dist) <= TRK_INLIER
                    segs = (ys < p, (ys >= p) & (ys < q), ys >= q)
                    if min(float(hit[m].mean()) for m in segs) < TRK_SUPPORT:
                        continue
                    best = (s2, [p, q], co2)
        new = _trk_basis(ys, best[1]) @ best[2]
        if float((np.abs(new - np.where(ok, obs, 1e9)) <= TRK_INLIER).mean()) < TRK_SUPPORT:
            return None
        cur, best_k, best_c = new, best[1], best[2]
    if _trk_hit(mask01, ys, cur, w) < _trk_hit(mask01, ys, x_old, w) - TRK_HIT_DROP:
        return None
    c = [float(t) for t in best_c]
    if not best_k:
        return VLine((w - 1) - c[0], -c[1])
    k1, k2, k3 = -c[1], -(c[1] + c[2]), -(c[1] + c[2] + c[3])
    return VLine((w - 1) - c[0], k1, k2, k3, float(best_k[0]), float(best_k[1]))


def _trk_as_three(v: VLine, top: HLine, bottom: HLine, h: int) -> VLine:
    """直线写成三段格式（三段同斜率，折点在版框内三等分处）。"""
    xc = v.x_at(h / 2.0)
    yt, yb = float(top.y_at(xc)), float(bottom.y_at(xc))
    return VLine(v.x_at_top, v.slope, v.slope, v.slope, yt + (yb - yt) / 3.0, yt + 2.0 * (yb - yt) / 3.0)


def _trk_dark(gray: np.ndarray) -> np.ndarray:
    """每个像素比左右各 TRK_FAINT_HALF px 内最亮处（横向闭运算）暗多少（封顶 TRK_DARK_CAP）。"""
    import cv2
    g = np.asarray(gray)
    if g.dtype != np.uint8:
        g = np.clip(g, 0, 255).astype(np.uint8)
    bg = cv2.morphologyEx(g, cv2.MORPH_CLOSE, np.ones((1, 2 * TRK_FAINT_HALF + 1), np.uint8))
    return np.clip(bg.astype(np.float32) - g.astype(np.float32), 0, TRK_DARK_CAP)


def _trk_gray_line(dark: np.ndarray, v: VLine, yt: float, yb: float, w: int) -> VLine | None:
    """淡线兜底（逐行追不到细墨时）：沿现线分段（TRK_GSEC 长、半段步进），每段在 ±TRK_GWIN px 内平移，
    取沿线平均暗度最大的平移；段的峰值比该段平移剖面中位高 TRK_GQ 倍才算看见。看见的段够多就按段心
    拟直线、不够再自由折点三段（同 `_trk_line` 的护栏）；新线沿线平均暗度要比现线高才换。"""
    h = dark.shape[0]
    xs_old = lambda yy: (w - 1) - v.x_at(yy)
    dxs = np.arange(-TRK_GWIN, TRK_GWIN + 0.25, 0.5)
    cy, cx = [], []
    for a in np.arange(yt + 4, yb - 4 - TRK_GSEC / 2, TRK_GSEC / 2):
        yy = np.arange(a, min(a + TRK_GSEC, yb - 4), 1.0)
        yi = yy.astype(int)
        xo = xs_old(yy)
        prof = np.empty(len(dxs))
        for k, dx in enumerate(dxs):
            xi = np.clip(np.round(xo + dx).astype(int), 0, w - 1)
            prof[k] = float(dark[yi, xi].mean())
        k = int(np.argmax(prof))
        if prof[k] >= TRK_GQ * (float(np.median(prof)) + 1e-3):
            cy.append(float(yy.mean()))
            cx.append(float(np.interp(yy.mean(), yy, xo)) + float(dxs[k]))
    n_all = max(1, len(np.arange(yt + 4, yb - 4 - TRK_GSEC / 2, TRK_GSEC / 2)))
    if len(cy) < 4 or len(cy) < TRK_GCOVER * n_all:
        return None
    yo, xo_ = np.array(cy), np.array(cx)
    span = yb - yt
    co, s80 = _trk_fit(yo, xo_, [])
    best = (s80, [], co)
    if s80 > TRK_STRAIGHT:
        g = np.linspace(yt + 0.08 * span, yb - 0.08 * span, TRK_KNOT_N)
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                p, q = float(g[i]), float(g[j])
                if min((yo < p).sum(), ((yo >= p) & (yo < q)).sum(), (yo >= q).sum()) < 2:
                    continue
                co2, s2 = _trk_fit(yo, xo_, [p, q])
                if s2 >= best[0] - TRK_GAIN or abs(co2[2]) > TRK_DSLOPE or abs(co2[3]) > TRK_DSLOPE:
                    continue
                best = (s2, [p, q], co2)
    ys = np.arange(yt + 4, yb - 4, TRK_STEP)
    new = _trk_basis(ys, best[1]) @ best[2]
    yi = ys.astype(int)
    d_new = float(dark[yi, np.clip(np.round(new).astype(int), 0, w - 1)].mean())
    d_old = float(dark[yi, np.clip(np.round(xs_old(ys)).astype(int), 0, w - 1)].mean())
    if d_new < d_old * TRK_GBETTER:
        return None
    c = [float(t) for t in best[2]]
    if not best[1]:
        return VLine((w - 1) - c[0], -c[1])
    return VLine((w - 1) - c[0], -c[1], -(c[1] + c[2]), -(c[1] + c[2] + c[3]), float(best[1][0]), float(best[1][1]))


def refit_vlines_by_track(mask: np.ndarray, top: HLine, bottom: HLine, verticals: list[VLine],
                          w: int, h: int, gray: np.ndarray | None = None) -> tuple[list[VLine], int]:
    """每条竖线按 `_trk_line` 重拟（见 TRK_*）。返回 (新线表, 换了几条)；调用方负责把整页统一成三段。
    给了 `gray`，逐行追不到细墨的线再走淡线兜底（`_trk_gray_line`）。"""
    mask01 = (np.asarray(mask) > 0)
    dark = _trk_dark(gray) if gray is not None else None
    out, changed = list(verticals), 0
    for vi, v in enumerate(verticals):
        xc = v.x_at(h / 2.0)
        yt, yb = float(top.y_at(xc)), float(bottom.y_at(xc))
        nv = _trk_line(mask01, v, yt, yb, w)
        if nv is None and dark is not None:
            nv = _trk_gray_line(dark, v, yt, yb, w)
        if nv is None:
            continue
        out[vi] = nv
        changed += 1
    return out, changed


def _bend_verticals(mask: np.ndarray, binm: np.ndarray, top: HLine, bottom: HLine,
                    straight: list[VLine], w: int, h: int, vline_polyline: bool,
                    bend_w80_med: float | None = None, outer_bar: bool = False,
                    outer_side: str | None = None, vline_track: bool = False, gray: np.ndarray | None = None,
                    single_sides: tuple = ()):
    """直线竖线 → 本页最终竖线：弯页整页换三段折线（先量 w80 再决定，直线页原样通过），再按横带证据重定位
    （见 SNAP_*），换了线的页统一成三段格式。要在 top/bottom 之后，折点 y 取自这条线跟上下版框的交点。
    返回 (verticals, segments, w80_med, w80_max, snapped)。`detect_borders` 与列宽重拟合后的
    `refit_bends` 共用。"""
    verticals, vseg, w80_med, w80_max = fit_vlines_polyline(mask, top, bottom, list(straight), w, h,
                                                            fit=vline_polyline, w80_med_min=bend_w80_med)
    verticals, snapped = snap_verticals_to_evidence(binm, top, bottom, verticals, w, h,
                                                    straight=list(straight))
    if outer_bar:                  # 缺省关不走，与加参数前一模一样
        verticals, n_bar = refit_outer_by_bar(mask, top, bottom, verticals, w, h, outer_side=outer_side,
                                                  skip_sides=single_sides)
        snapped += n_bar
    if vline_track:                # 缺省关不走
        verticals, n_trk = refit_vlines_by_track(mask, top, bottom, verticals, w, h, gray=gray)
        snapped += n_trk
        if n_trk and vseg == 3:    # 本来就是三段页：换成直线的线也写成三段格式（整页统一，下游按 vline_segments 读）
            verticals = [v if v.segments == 3 else _trk_as_three(v, top, bottom, h) for v in verticals]
    if snapped and vseg == 1:
        conv = []
        for v in verticals:
            if v.segments == 3:
                conv.append(v); continue
            xc = v.x_at(h / 2.0)
            yt_, yb_ = float(top.y_at(xc)), float(bottom.y_at(xc))
            conv.append(VLine(v.x_at_top, v.slope, v.slope, v.slope,
                              yt_ + (yb_ - yt_) / 3.0, yt_ + 2.0 * (yb_ - yt_) / 3.0))
        verticals, vseg = conv, 3
    return verticals, vseg, w80_med, w80_max, snapped


def refit_bends(res, gray: np.ndarray, *, ink_threshold: int = 128, vline_polyline: bool = True,
                bend_w80_med: float | None = None, outer_bar: bool = False, outer_side: str | None = None,
                vline_track: bool = False):
    """列宽重拟合（`pitch_rescue`）换了线之后，按新的一串直线**重新拟合折线**。

    折线拟合的护栏（相邻对列宽沿高度的变化率、拟合失败的线借邻线位移）看的是相邻线；自由模式探出假线、
    漏掉真线时，护栏在错的一串线上退回／借形状，真线也被拗弯。重拟合只换了线的位置，旧折线形状
    原样跟着走（`shifted` 借最近线的形状），殿本 vol46 p78 左三条线下半段斜进字里 20–40px。
    在新的直线上重跑一遍同一套折线＋重定位，形状由新的相邻线决定。上下版框、抬头、外框不动。"""
    if res.top is None or res.bottom is None or res.vline_segments != 3:
        # 直线页不重拟合：线位本来就是直线，重拟合只会把网格线的三段格式（k2=k1）改成直线格式，
        # 几何不变、Step2 分带却变了（vol40 p1 卷首大印页题列首字丢格）
        return res
    h, w = gray.shape[:2]
    mask = (gray < ink_threshold).astype(np.float64)
    binm = (mask > 0).astype(np.uint8)
    straight = list(res.verticals_straight) or list(res.verticals)
    verticals, vseg, w80_med, w80_max, snapped = _bend_verticals(
        mask, binm, res.top, res.bottom, straight, w, h, vline_polyline, bend_w80_med,
        **({"outer_bar": True, "outer_side": outer_side} if outer_bar else {}),
        **({"vline_track": True, "gray": gray} if vline_track else {}))
    from dataclasses import replace
    return replace(res, verticals=verticals, vline_segments=vseg, bend_w80_med=w80_med,
                   bend_w80_max=w80_max, vlines_snapped=int(snapped))


def detect_borders(gray: np.ndarray, expected_cols: int,
                    ink_threshold: int = 128,
                    book_bottom_gap: float | None = None,
                    top_band_frac: float | None = None,
                    bottom_band_frac: float | None = None,
                    column_grid: bool = False,
                    col_pitch: float | None = None,
                    frame_height: float | None = None,
                    vline_polyline: bool = True,
                    outer_shift: dict | None = None,
                    book_outer_gap: dict | None = None,
                    frame_layers: dict | None = None,
                    outer_side: str | None = None,
                    inner_pull: bool = False,
                    head_raise_extend: bool = True,
                    head_raise_scale: float = 1.0,
                    grid_lattice_fallback: bool = False,
                    top_weak_ratio: float = TOP_WEAK_RATIO,
                    top_weak_floor: float | None = None,
                    bottom_weak_ratio: float = 0.0,
                    bend_w80_med: float | None = None,
                    outer_bar: bool = False,
                    vline_track: bool = False,
                    bottom_lock_reslope: bool = False,
                    top_edge_reslope: bool = False,
                    top_hint: float | None = None,
                    bottom_hint: float | None = None,
                    head_raise_notch: bool = False,
                    head_raise_fit: bool = False,
                    outer_scale: bool = False) -> BorderDetectionResult:
    """整页边框+界行探测，输出新坐标系约定的结果。

    `head_raise_notch`：一个抬头框都没认出的页，查主上框是不是认在了抬头框上（`notch_top`）。缺省关。
    `head_raise_fit`：抬头列认下以后校内框高度（`_fit_head_raise`），量上外框时跳过抬头列。缺省关。
    `outer_scale`：外框探测的像素量按列距缩放（见 `OUTER_REF_PITCH`）。缺省关。

    `top_hint` / `bottom_hint`：人给的上／下版框大致 y（页面横向中点处的行号），只在附近重找那条线，
    见 `seg/lines.find_horizontal_border` 的 `hint`。下游（折线、抬头框、外框）都在改后的线上算。缺省 None 不传。

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

    `grid_lattice_fallback`：网格模式选不出版框对时按细界行拟网格反推版框
    （`peak_line_search.lattice_frame_pair`）。缺省关，关着逐位不变；只在网格模式下有意义。

    `vline_polyline=False`：界行不做三段折线拟合，只量 w80。理由见
    `fit_vlines_polyline` 的 `fit` 参数。

    `bend_w80_med`：弯页门槛（页级 w80 中位），None＝`seg/polyline.BEND_W80_MED`；0＝整页一律三段折线。
    见 `fit_vlines_polyline` 的 `w80_med_min`。

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
    # 册声明左／右＝1（四周單邊）：该侧最外线就是版框，不往里找内框、不按粗条补内框（缺省空，逐位不变）
    _ns = tuple(k for k in ("left", "right") if (frame_layers or {}).get(k) == 1)

    if column_grid:
        # 阈值按本书的列距/框高换算；两个先验都不给时 grid_thresholds 原样返回
        # 北行日錄那组标定值，与加这套之前逐位相同。
        vlines_old, filled_old = find_vertical_lines_grid(
            mask, n_lines=expected_cols + 1, col_pitch=col_pitch,
            lattice_fallback=grid_lattice_fallback,
            **grid_thresholds(col_pitch, frame_height))
    else:
        vlines_old = find_vertical_lines(mask, expected_count=expected_cols + 1,
                                         **({"no_snap": _ns} if _ns else {}))
        filled_old = [False] * len(vlines_old)
    # 上下边框曾经各 1.4s、并成 2 线程有收益；分块 BLAS 之后各只剩 0.17s，
    # 线程开销反而更大——跟窗口级线程池一起撤了，理由见 peak_line_search.py 顶部。
    top_kw = {} if top_band_frac is None else {"band_frac": float(top_band_frac)}
    bot_kw = {} if bottom_band_frac is None else {"band_frac": float(bottom_band_frac)}
    if top_edge_reslope:           # 缺省关不传，与加参数前的调用一模一样
        top_kw["top_edge_reslope"] = True
    if top_hint is not None:       # 人给位置（页级覆盖），缺省不传
        top_kw["hint"] = float(top_hint)
    if bottom_hint is not None:
        bot_kw["hint"] = float(bottom_hint)
    top_old = find_horizontal_border(mask, "top", weak_top_ratio=top_weak_ratio,
                                     weak_top_floor=top_weak_floor, **top_kw)
    if bottom_weak_ratio > 0:      # 缺省关时不传，与加参数前的调用一模一样
        bot_kw["weak_bottom_ratio"] = float(bottom_weak_ratio)
    if bottom_lock_reslope:        # 同上，缺省关不传
        bot_kw["lock_reslope"] = True
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
    if bottom_hint is None:        # 人给了下框就不再推
        bottom, bottom_pushed = push_bottom_to_bar(binm_new, bottom, verticals, w, h)
    else:
        bottom_pushed = 0.0
    if inner_pull and (frame_layers or {}).get("bottom") == 2 and bottom_hint is None:
        bottom, _ = pull_inner_line(binm_new, bottom, "bottom", verticals, w, h, (book_outer_gap or {}).get("bottom"))
    if inner_pull and (frame_layers or {}).get("top") == 2 and top_hint is None:
        top, _ = pull_inner_line(binm_new, top, "top", verticals, w, h, (book_outer_gap or {}).get("top"))
    verticals_straight = list(verticals)
    verticals, vseg, w80_med, w80_max, vlines_snapped = _bend_verticals(
        mask, binm_new, top, bottom, verticals_straight, w, h, vline_polyline, bend_w80_med,
        **({"outer_bar": True, "outer_side": outer_side} if outer_bar else {}),
        **({"single_sides": _ns} if _ns else {}),
        **({"vline_track": True, "gray": gray} if vline_track else {}))
    fit_kw = {"fit": True} if head_raise_fit else {}
    head_raise = detect_head_raise(mask, top, verticals, w, extend=head_raise_extend,
                                   scale=head_raise_scale, **fit_kw)
    if head_raise_notch and not head_raise and top_hint is None:
        # 主上框认在抬头框上、没抬头的列反成缺口（见 NOTCH_*）：挪到缺口列的真上框重探抬头。缺省关不走
        nt = notch_top(mask, top, verticals, w, extend=head_raise_extend, scale=head_raise_scale, **fit_kw)
        if nt is not None:
            top, head_raise = nt
    skip_kw = {}
    if head_raise_fit and head_raise:
        spans = []
        for b in head_raise:
            if 1 <= b.col < len(verticals):
                y = float(b.inner_y)
                spans.append(((w - 1) - verticals[b.col - 1].x_at(y), (w - 1) - verticals[b.col].x_at(y)))
        if spans:
            skip_kw = {"skip_top": spans}
    outer = detect_outer_borders(mask, top, bottom, verticals, w, h,
                                 outer_shift=outer_shift, book_gap=book_outer_gap,
                                 frame_layers=frame_layers, outer_side=outer_side, **skip_kw,
                                 **({"outer_scale": True} if outer_scale else {}))
    return BorderDetectionResult(width=w, height=h, top=top, bottom=bottom,
                                  verticals=verticals, head_raise=head_raise,
                                  vline_segments=vseg, bend_w80_med=w80_med,
                                  bend_w80_max=w80_max,
                                  verticals_straight=verticals_straight,
                                  vline_filled=vline_filled,
                                  bottom_pushed=float(bottom_pushed),
                                  vlines_snapped=int(vlines_snapped),
                                  **outer)
