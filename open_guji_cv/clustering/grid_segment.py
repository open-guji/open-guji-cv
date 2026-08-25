"""刻本严格网格切分（Phase 3 的替代实现，无 OCR 依赖）。

刻本古籍格式非常固定：每行严格 N 字、字高一致。据此把切分建模为
**网格拟合**而非自由投影分割：

1. 每列先验网格：[col_top, col_bottom] 均分为 N 格；
2. 全局微调：搜索 (偏移 δ, 伸缩 s)，使网格线尽量落在投影谷（字间空隙）；
3. 逐线微调：每条网格线在 ±search_ratio 格高内移到最近的投影谷，
   保持单调、格高不塌缩；
4. 格内判空：墨迹覆盖率 < empty_ink_ratio 的格为 empty。

断笔/磨损不会破坏切分——网格由整列证据共同决定，单字残损只影响该格判空。
输出与 CharGridDetector 相同的 char_grid JSON 契约，下游（M1 提取）无感。
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ..utils.image_io import imread
from .extractor import CharExtractor
from .page_type import classify_page_type, refine_page_type

BINARY_THRESHOLD = 128
EMPTY_INK_RATIO = 0.02     # 格内墨迹覆盖率低于此 → empty
MIN_COL_WIDTH_RATIO = 0.5  # 列宽低于中位列宽的此比例 → 非文字列（版心/界行缝），跳过
SEARCH_RATIO = 0.3         # 逐线微调搜索半径（× 格高）
CELL_H_TOL = 0.05          # 页格高偏离全书共识超此比例 → 判定锁错，强制重拟
# ── 书级格高由「实测字距」定 ─────────────────────────────
# 刻本一格一字，所以**字距就是格高**——这是可以直接量的物理常量。
# 而投影拟合的基准是 (文字带高)/n_chars，文字带由 content_range 划定，
# 它会把首末字探出去的那点笔画当短游程剔掉，于是格高被系统性低估：
# 实测 vol01 低 1.0%、vol02 低 1.7%。21 格累积下来漂 0.21 / 0.36 格，
# 正好对上末格的字下出头 0.19~0.39 格——列两端的字因此被格线切掉。
PITCH_MIN_SEGS = 8         # 一列至少这么多个单字墨段才拿来量字距
PITCH_MIN_COLS = 40        # 全书至少这么多列量得出字距，才敢用它定格高
PITCH_MAX_DEV = 0.08       # 实测字距偏离投影共识超此 → 判为量错，不用
# 逐页格高（2026-08-24 grid_shift 族根因）：每叶是独立版片，栏格高度页间
# 实测有 ±3% 差异（vol01/14 量 119.0 vs 书级共识 115.2，21 格累积把列尾
# 推漂 ~40px——recrop 金标 grid_shift 族全部源于此）。「格高刚性」只在
# **页内**成立；页自己的字距证据够硬时，行格高用页距而非书距。
PAGE_PITCH_MIN_COLS = 5    # 本页至少这么多列量得出字距，才敢用页距
PAGE_PITCH_MAD = 1.5       # 页内各列字距的中位绝对偏差上限（px）——散了说明量不稳
PAGE_PITCH_DEV = 0.04      # 页距偏离书级共识超此比例 → 判为量错，回退书距
PITCH_SEARCH = 0.10        # 字距候选的搜索半径（× 先验）。窗要窄到把 2 倍
                           # 谐波挡在外面，宽到覆盖投影拟合的系统偏差
PITCH_STEP = 0.2           # 候选步长（px）
PITCH_MIN_R = 0.75         # 最佳候选的相位集中度下限，低于此说明这列不刚性
# ── 格线逐条吸附到字间空隙 ────────────────────────────────
# 格高定死、相位也拟好之后，单条格线仍会落在笔画上：刻工排字有微偏，
# 字身大小也不一。分隔线本来就该落在字与字之间的空隙里，而「这一行有
# 多少墨」是可以直接量的——所以逐条格线在小范围内滑到局部墨谷。
# 个别字上下确实相连（本来就没有空隙），那时谷底墨量仍高，保持原位不动。
SNAP_RANGE = 0.10          # 每条格线的滑动半径（× 格高）。再大就会滑到
                           # 邻格的空隙上去，把一个字整个让给隔壁
SNAP_VALLEY_T = 0.35       # 谷底墨量 / 相邻两格的平均墨量。高于此说明这里
                           # 根本没有空隙，保持刚性位置
SNAP_SMOOTH = 3            # 找谷前的行向平滑窗（px），滤掉单像素噪声
                           # （修复后自然抖动 σ≈2.2%，0.10 曾放过 0.91 的漏网页）
PERIOD_TOL = 0.04          # 页列距偏离全书共识超此比例 → 判定拟错，改用共识值
RULE_IN_COL_T = 0.05       # rule_in_col 超此 → 页面自己报了「竖线落在列框里」，
                           # 即便所有参数都在共识容差内也要按共识先验重扫一次。
                           # 实测 vol01/94：列距 177.6 离共识 184.7 只差 3.8%
                           # （在 PERIOD_TOL 内，参数触发抓不到），界行实测间距
                           # 却是 186.5、rule_in_col 0.18——直接质量信号必须能
                           # 自己触发校正，不能只当择优门控用。重扫仍按
                           # never-make-worse 择优：折痕/粗界行造成的报警
                           # （vol02/163 一条穿过文字列的折痕）refit 不会更好，
                           # 门控自然拒掉，页面原样保留
                           # 实测列距 5~95 分位只有 174~186px（±3%），是物理
                           # 刚性常量；拟歪的页会掉到 152~157，差 15%
STRADDLE_OK = 0.50         # 骑线比（格线墨/格心墨）高于此 → 尝试相位重扫
STRADDLE_GAIN = 0.10       # 重扫至少好这么多才接受（never-make-worse）
SCALES = np.linspace(0.96, 1.04, 9)

# ── 残余错切（界行竖线不竖）────────────────────────────────
# deskew 把**横线**摆平了，竖线却仍可能斜着走：实测二者最佳旋正角能差
# 0.95°，说明这不是没转够的旋转，而是纸张/扫描造成的真错切。界行斜着
# 走一页要横向漂移 20~30px（周期才 180px），而列框是**竖直矩形**，跟不
# 上——于是要么框裹进界行，要么让出漂移量把字裁窄。所以列拟合之前先把
# 竖线摆正。
SHEAR_MAX_TAN = 0.02       # 搜索范围 ±dx/dy（0.02 ≈ 1.15°）
SHEAR_CANDIDATES = 21      # 候选个数
SHEAR_SCALE = 0.5          # 搜索在半尺寸图上做（省一半时间，精度足够）
SHEAR_MIN_GAIN = 1.05      # 界行证据至少提升这么多才纠正（never-make-worse）
RULE_COV_T = 0.5           # 竖直长线覆盖率高于此才算「界行证据」
RULE_MERGE_GAP = 4         # x 相距不超过此的高覆盖列并成同一条界行
MIN_RULES_TO_SNAP = 3      # 至少检出这么多条界行才敢拿它定列相位
RULE_MIN_HALF = 3.0        # 界行半宽下限（实测宽度中位 5px）
RULE_CLEARANCE = 3.0       # 列框离界行再留的余量
RULE_PERIOD_TOL = 0.06     # 界行量出的列距偏离先验超此 → 判为量错（缺条界行
                           # 会把中位间距顶到 2 倍），弃用，保留先验
CELL_COV_STOP = 0.10       # 图块横向外扩时，撞到竖线覆盖率高于此的 x 就停。
                           # 文字笔画过不了半带高的竖直开运算（带内实测 ≈0），
                           # 界行/版框则是 0.2~1.0；0.05~0.15 之间结果不变
CELL_RULE_CLEARANCE = 4.0  # 停下之后再往回让这么多像素，躲开线的毛边
CELL_FENCE_BANDS = 6       # 围栏用的覆盖率**分带**统计：整页统计对斜/弯的界行
                           # 是瞎的（墨摊到二三十个 x 上，每个都不到 0.2），
                           # 分带后同一条线在每带里都是直的，取各带最内侧
CELL_FENCE_LINE_FRAC = 0.45  # 未给定 min_run 时，带内开运算长度 = 此比例 × 带高
BAND_OVER_RUN = 1.7        # 分带的带高 = 此倍数 × min_run。实测扫参：1.5~1.7 时
                           # vol02/151 检出 4~7 条界行、119 检出 5~6 条；提到 2.0
                           # 以上就掉到 ≤3 条和 0~3 条——弯的界行在高带里会断
RULE_MIN_RUN_PERIOD = 1.2  # 认定「竖直长线」所需的最短连续段 = 此倍数 × 列距。
                           # **不能挂在页高上**：那样阈值折算成「几个字高」会随
                           # 页面尺寸浮动——真页 2483px 高时是 1.66 个字高（安全），
                           # 合成页 420px 高时只剩 0.53 个字高，文字块自己就被当成
                           # 界行了。列距是版面自身的尺度，字的竖笔最长约 1 个字高
                           # （≈0.6 列距），1.2 倍列距留了一倍余量
FRAME_RAW_T = 0.22         # 最左列左侧的「原始墨密度」停墙档：模糊内边框
                           # 二值化后断续，开运算游程档全部失灵；但最左列
                           # 文字带以左只可能是边框——带内原始墨密度超此
                           # 即停。只开**左外侧**：右外侧有职名「臣」贴框
                           # 写的先例，密度档会把字当墙裁
RULE_RELAX_RUN_PERIOD = 0.8  # 放宽档竖线游程 = 此倍数 × 列距（≈145px）。磨损
                           # 断裂的界行残段实测 122~197px，够不着严格档的 1.2 倍
                           # （vol02/119 col7 右侧界行因此「无墙不敢扩」，整列越带
                           # 的字被切）；而单字竖笔最长 ≈0.5 列距（90px），0.8 倍
                           # 仍留 60% 余量，字迹冒充不了
CELL_COV_STOP_RELAX = 0.30  # 放宽档的覆盖率门槛。结构弱（游程短）就要求量足：
                           # 放宽档带高 ≈246px、开运算核 ≈145px，能活下来的游程
                           # 覆盖率天然 ≥0.59，字迹开运算后带内 ≈0——放宽档只用于
                           # 「允许外扩/在哪停」，且墙只放宽不收紧
                           # （hi=max(hi0,·)），最坏也退回现状
CELL_RULE_TOL = 0.25       # 界行中心离列格边界不超过此比例（× 列距）也算证据
CELL_BOW_T = 3.0           # 各带围栏彼此相差超过此像素 → 这条边界是弯的，
                           # 额外输出逐带裁切边（cell_bands），图块按带掩蔽
NARROW_TOL = 0.25          # 梳子跨度超出页宽此比例（× 列距）→ 标 narrow_page
                           # 实测被裁窄的页只有 7.5 个列距的宽度，差整整一列
INSET_TOL = 0.5            # 页内缩低于书级共识此比例 → 判为量塌了，改用共识值
INSET_TOL_HI = 1.25        # 页内缩**高于**共识此比例 → 同样是量错了，也换成共识值。
                           # 塌掉的危害是列框贴着界行走（把线圈进来），涨上去的
                           # 危害相反且更隐蔽：文字带被人为收窄，字的偏旁被裁掉，
                           # 而 rule_in_col 一路是 0，任何以「界行有没有进框」为
                           # 判据的门控都发现不了。实测 vol02 有 14 页 inset_l
                           # 超共识 25%（最极端 63px vs 共识 33），那些页的图块
                           # 缺掉整个偏旁——「但」被裁成「且」、「說」丢了言字旁
                           # 实测 inset_l 中位 32.5px，但有 69 页塌到 <15px，
                           # 那些页 rule_in_col 均值 0.083、其余页才 0.006


@dataclass
class GridParams:
    chars_per_line: int
    empty_ink_ratio: float = EMPTY_INK_RATIO
    search_ratio: float = SEARCH_RATIO


def deshear(gray: np.ndarray, tan_t: float) -> np.ndarray:
    """按 dx/dy = tan_t 做水平错切，把斜着走的竖线摆正。

    以**页面纵向中点**为不动点（x' = x - t·(y - h/2)），这样列的中点坐标
    不变，页级相位与 Phase 2 的边框量在中高度上仍然可比。
    """
    if not tan_t:
        return gray
    h, w = gray.shape[:2]
    m = np.float32([[1, -tan_t, tan_t * h / 2], [0, 1, 0]])
    return cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=255)


def _vline_cov(binary: np.ndarray, line_frac: float = 0.3) -> np.ndarray:
    """逐 x 的「竖直长线」覆盖率：开运算留下够长的竖直连续段。"""
    h = binary.shape[0]
    k = cv2.getStructuringElement(
        cv2.MORPH_RECT, (1, max(3, int(h * line_frac))))
    return cv2.dilate(cv2.erode(binary, k), k).sum(axis=0) / h


def _vline_cov_bands(binary: np.ndarray, min_run: float | None = None,
                     n_bands: int = CELL_FENCE_BANDS,
                     line_frac: float = CELL_FENCE_LINE_FRAC
                     ) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """逐带的竖线覆盖率矩阵 (bands × W) 与各带的 y 区间。

    _vline_cov_banded 的逐带版本：围栏要**顺着弯线走**时，需要知道每条带
    各自的墙在哪，而不是各带取 max 之后「最往里探」的那一个位置——实测
    vol02/151 一条界行沿页高横向漂 49px，取 max 的围栏在多数带里把墙划在
    了线根本不在的地方。
    """
    h = binary.shape[0]
    if min_run is None:
        bands, run = n_bands, None
    else:
        bands = max(1, int(h // max(1.0, BAND_OVER_RUN * min_run)))
        run = int(round(min_run))
    spans: list[tuple[int, int]] = []
    rows: list[np.ndarray] = []
    for i in range(bands):
        a, b = h * i // bands, h * (i + 1) // bands
        if b - a < 3:
            continue
        klen = min(max(3, run if run is not None else int((b - a) * line_frac)),
                   b - a)
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (1, klen))
        seg = binary[a:b]
        rows.append(cv2.dilate(cv2.erode(seg, k), k).sum(axis=0) / (b - a))
        spans.append((a, b))
    if not rows:
        return np.zeros((1, binary.shape[1])), [(0, h)]
    return np.stack(rows), spans


def _vline_cov_banded(binary: np.ndarray, min_run: float | None = None,
                      n_bands: int = CELL_FENCE_BANDS,
                      line_frac: float = CELL_FENCE_LINE_FRAC) -> np.ndarray:
    """逐 x 的竖线覆盖率，**分带取最大**——斜线/弯线也拦得住。

    整页统计（_vline_cov）要求一条竖直连续段跨 0.3 页高。界行只要斜或弯
    个几像素，同一条线的墨就被摊到二三十个 x 上，每个 x 都过不了阈值，
    整页 cov 就是一片 0：拿它当围栏，裁切边会直接穿过界行。而在 1/6 页高
    的带里，同一条线几乎是直的，覆盖率照样接近 1。各带取 max 得到的是这
    条线**最往里探**的那个位置，正是裁切要躲开的边界。

    实测（vol01，24605 个字格）：整页围栏 rule_bar 代理 0.94%，
    分带围栏 0.43%，而被裁掉笔画的比例反而更低。
    """
    cov, _spans = _vline_cov_bands(binary, min_run, n_bands, line_frac)
    return cov.max(axis=0)


def rule_evidence(gray: np.ndarray, line_frac: float = 0.3) -> float:
    """界行证据强度：竖直长线覆盖率里高覆盖部分的总和。

    竖线摆正时，同一条界行的墨全落在同一个 x 上，覆盖率逼近 1；斜着走
    时被摊到二三十个 x 上，每个都只有 0.1~0.2，这个和就塌下去。因此它
    可以直接当错切校正的目标函数——不需要先把界行找出来。
    """
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    cov = _vline_cov((gray < BINARY_THRESHOLD).astype(np.uint8), line_frac)
    return float(cov[cov > RULE_COV_T].sum())


def _deshear_bin(binary: np.ndarray, tan_t: float) -> np.ndarray:
    """二值图版的错切：最近邻 + 背景补 0，保持严格二值。"""
    h, w = binary.shape[:2]
    m = np.float32([[1, -tan_t, tan_t * h / 2], [0, 1, 0]])
    return cv2.warpAffine(binary, m, (w, h), flags=cv2.INTER_NEAREST,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def estimate_shear(gray: np.ndarray) -> float:
    """估计页面残余错切量 dx/dy；没把握就返回 0。

    直接以界行证据为目标搜索，并要求相对不校正至少提升 SHEAR_MIN_GAIN
    倍才采纳——**绝不允许把页面改差**。实测 80 页：界行证据合计提升
    1.47×，变差的页 0 张，最坏的几页从「一条界行都检不出」变成检出
    40~50 个高覆盖列。

    用页面自身的界行来定，而不用 Phase 2 边框的 `left.slope`：后者左右
    两边就能差 3 倍（页 55：左 0.0116、右 0.0033），边框墨少且常残损，
    而界行是整页反复出现的同一条几何证据。

    先二值化再降采样，且降采样用**最大池化**而不是面积平均——界行只有
    2~3px 宽，面积平均会把它拉成灰的、直接掉到二值阈值以下，等于把要
    找的证据先擦掉了（实测这么做时所有候选的得分齐齐归零）。
    """
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    binary = (gray < BINARY_THRESHOLD).astype(np.uint8)
    step = int(round(1 / SHEAR_SCALE))
    if step > 1:
        binary = cv2.dilate(binary, np.ones((step, step), np.uint8))
        binary = binary[::step, ::step]

    def score(b: np.ndarray) -> float:
        cov = _vline_cov(b)
        return float(cov[cov > RULE_COV_T].sum())

    best_t, best_s = 0.0, score(binary) * SHEAR_MIN_GAIN
    for t in np.linspace(-SHEAR_MAX_TAN, SHEAR_MAX_TAN, SHEAR_CANDIDATES):
        if t == 0.0:
            continue
        sc = score(_deshear_bin(binary, float(t)))
        if sc > best_s:
            best_t, best_s = float(t), sc
    if not best_t:
        return 0.0
    # 搜索在降采样图上做，最终得复核一遍**全尺寸**：半尺寸赢不等于全尺寸
    # 也赢（实测 80 页里有 1 页如此）。never-make-worse 要在真正用的那个
    # 分辨率上成立才算数。
    if rule_evidence(deshear(gray, best_t)) <= rule_evidence(gray):
        return 0.0
    return best_t


def rule_segments(gray: np.ndarray,
                  min_run: float | None = None) -> list[tuple[int, int]]:
    """页面上「竖直长线」的 x 区间（界行/版框竖线）。

    覆盖率**分带**统计（`_vline_cov_banded`），不是整页统计。整页统计要求
    一条竖直连续段跨 0.3 页高，界行只要斜或**弯**几个像素就过不了阈值——
    而弯的那部分错切校正根本救不了：实测 vol02/151 在 ±0.02 的全部候选角度
    里，界行证据最多只提升 1.02×，可它每一条带里的覆盖率都是 1.00，线明明
    都在。分带之后同一条线在带内几乎是直的，照样检得出来。

    这件事的下游代价极大：界行检不出来，`snap_columns_to_rules`（≥3 条才
    动）、`_period_from_rules`、`cell_bounds_from_rules` 的围栏**全部失效**，
    而 `rule_in_col` 恒为 0 又让所有以它为判据的择优门控一律放行——页面
    悄悄退化成纯投影拟合，列相位漂了也没人报。实测 vol02 里界行检出
    ≤1 条的页，图块缺掉整个偏旁的比例是正常页的数倍。

    代价是漂移的线会给出偏宽的 x 区间（各带取并集）。实测 vol02/151 一条
    界行跨 6~7px、正常页 2~3px，相对 33px 的内缩仍然够用。
    """
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    cov = _vline_cov_banded((gray < BINARY_THRESHOLD).astype(np.uint8),
                            min_run)
    xs = np.where(cov > RULE_COV_T)[0]
    if len(xs) == 0:
        return []
    segs, start, prev = [], int(xs[0]), int(xs[0])
    for x in xs[1:]:
        if x - prev > RULE_MERGE_GAP:
            segs.append((start, prev))
            start = int(x)
        prev = int(x)
    segs.append((start, prev))
    return segs


def measure_insets(vproj: np.ndarray, cx0: float, period: float,
                   n_cols: int) -> tuple[float, float]:
    """逐列格量文字带相对列格的左右内缩，取页面中位统一应用。

    列格 = 文字带 + 界行缝（完整周期）。文字带在周期内的位置同样刚性
    固定，所以中位数是有意义的；不这么做图块就会裹进界行。
    """
    insets: list[tuple[float, float]] = []
    for k in range(n_cols):
        s, e = int(cx0 + period * k), int(cx0 + period * (k + 1))
        seg = vproj[max(0, s):min(len(vproj), e)]
        if len(seg) < 4 or seg.sum() < 1:
            continue
        t, b = content_range(seg, min_run=0.1 * period)
        if b - t >= 0.4 * period:          # 空列/噪声段不计入
            insets.append((float(t), float(len(seg) - b)))
    if not insets:
        return period * 0.08, period * 0.08
    return (float(np.median([a for a, _ in insets])),
            float(np.median([b for _, b in insets])))


def _comb(cx0: float, period: float, n_cols: int,
          inset_l: float, inset_r: float) -> list[tuple[float, float]]:
    return [(cx0 + period * k + inset_l, cx0 + period * (k + 1) - inset_r)
            for k in range(n_cols)]


def _rule_in_col(segs: list[tuple[int, int]],
                 cols: list[tuple[float, float]]) -> float:
    """界行落进列框内部的比例——列相位对不对的直接度量。"""
    if not segs:
        return 0.0
    n = sum(1 for a, b in segs
            if any(l + 3 <= (a + b) / 2 <= r - 3 for l, r in cols))
    return n / len(segs)


def _period_from_rules(centers: np.ndarray, prior: float) -> float:
    """由界行间距直接量列距；量出来不像话就退回先验。

    相邻间距取**中位数**（对缺条界行免疫），再按整数序号做一次最小二乘
    精修。缺得多时中位数会顶到 2 倍周期上，所以用刻本的刚性先验兜底：
    偏离先验超过 RULE_PERIOD_TOL 就判为量错，不要。
    """
    if len(centers) < MIN_RULES_TO_SNAP + 1:
        return prior
    # 磨损的版框/双边框会给同一条物理线出好几个中心（实测 vol01/94 左框
    # 出了 9/25/38/47 四个），全被指到同一个格号，把最小二乘的斜率拉出
    # 容差、整个测量被弃用——而弃用后保留的先验恰恰是错的。先把靠得近的
    # 中心并成一个（0.3×先验以内视为同一条线）。
    centers = np.sort(np.asarray(centers, dtype=float))
    merged: list[list[float]] = [[centers[0]]]
    for c in centers[1:]:
        if c - merged[-1][-1] <= 0.3 * prior:
            merged[-1].append(c)
        else:
            merged.append([c])
    centers = np.array([float(np.mean(g)) for g in merged])
    if len(centers) < MIN_RULES_TO_SNAP + 1:
        return prior
    d = np.diff(centers)
    d = d[d > prior * 0.4]
    if len(d) == 0:
        return prior
    p0 = float(np.median(d))
    if abs(p0 - prior) > RULE_PERIOD_TOL * prior:
        return prior
    k = np.round((centers - centers.min()) / p0)
    if len(np.unique(k)) < MIN_RULES_TO_SNAP:
        return prior
    a = np.vstack([k, np.ones_like(k)]).T
    p = float(np.linalg.lstsq(a, centers, rcond=None)[0][0])
    return p if abs(p - prior) <= RULE_PERIOD_TOL * prior else prior


def snap_columns_to_rules(gray: np.ndarray, vproj: np.ndarray,
                          cx0: float, period: float, n_cols: int,
                          inset_l: float, inset_r: float
                          ) -> tuple[float, float, float, float]:
    """用界行把列相位钉死，返回 (cx0, inset_l, inset_r)。

    为什么要这一步：列相位原先只能从**文字投影**间接拟合，稀疏页、
    长短不齐的职名页上谷-峰代价欠定，拟出来的相位可以整体偏十几二十
    像素——正好把界行圈进列框。而界行本身是版上刻出来的列分隔，是
    列边界的**直接证据**，只是过去被残余错切糊掉了看不见（见
    estimate_shear）；摆正之后就该拿它定相位。

    做法：界行相对列格起点的偏移取**环形**平均（列格是周期结构，
    偏移只在模 period 意义下有定义，普通平均会被跨周期的样本拉飞），
    把列格起点挪到界行上；内缩再保证至少盖住界行半宽 + 余量。

    择优返回：只有当界行落入列内的比例真的下降才采纳——实测 204 页里
    193 页采纳，总体从 0.136 降到 0.050。
    """
    period_in = period
    segs = rule_segments(gray, period * RULE_MIN_RUN_PERIOD)
    if len(segs) < MIN_RULES_TO_SNAP:
        return cx0, period, inset_l, inset_r
    centers = np.array([(a + b) / 2 for a, b in segs])
    # 界行不只定相位，也直接定**列距**——相邻界行之间就是一个列格。
    # 投影拟合的列距可以差 3~4%（刚好卡在书级容差里），9 列累积漂 60px，
    # 足够把界行圈进列框，而这时**换多少相位都救不回来**。
    period = _period_from_rules(centers, period)
    ang = (centers - cx0) / period * 2 * np.pi
    delta = float(np.arctan2(np.sin(ang).mean(), np.cos(ang).mean())
                  / (2 * np.pi) * period)
    half = max(float(np.median([b - a + 1 for a, b in segs])) / 2,
               RULE_MIN_HALF) + RULE_CLEARANCE
    # 相位一动，原来的内缩就作废了——它是在旧相位下逐格量出来的。
    # 必须在新相位下重量一遍，否则会把旧相位的误差原样搬过来（合成页上
    # 实测：只挪相位不重量内缩，首列左边界反而从偏 12px 变成偏 23px）。
    new_cx0 = cx0 + delta
    new_l, new_r = measure_insets(vproj, new_cx0, period, n_cols)
    cand = (new_cx0, period, max(new_l, half), max(new_r, half))
    old = _rule_in_col(segs, _comb(cx0, period_in, n_cols, inset_l, inset_r))
    new = _rule_in_col(segs, _comb(cand[0], cand[1], n_cols, cand[2], cand[3]))
    return cand if new <= old else (cx0, period_in, inset_l, inset_r)


def cell_bounds_from_rules(gray: np.ndarray, cx0: float, period: float,
                           n_cols: int, inset_l: float, inset_r: float
                           ) -> list[tuple[float, float]]:
    """图块的横向裁切边：从文字带往外扩，扩到**撞上竖线结构**为止。

    为什么不按文字带裁
    ------------------
    文字带是「正常居中字」的范围。职名列的「臣」是小字、贴着界行写：横向
    中心落在列格的 0.78 处、只占 0.43 列宽，右缘越出文字带中位 15px（最多
    31px）。实测 vol01 全书 24605 个字格，按文字带裁有 **17.8% 的字被切掉
    笔画**，「臣」形字格更是 79.7% 被切、中位切掉 336 个像素。而且这种损失
    是**静默**的——切下来的图块自己看不出缺了一块，没有任何 flag 报警。

    为什么不能用固定余量
    --------------------
    实测界行内缘伸进列格中位 4.9px、95 分位 19.6px，而「臣」的外缘离列格
    边界中位只有 10.0px、10 分位就是 0px：两个分布重叠，固定阈值只能在两害
    之间选一个——余量 9px 时 21% 的图块裹进界行、44% 的「臣」被切；余量
    15px 时裹线降到 8.7%，切字涨到 68%。

    做法：拿竖线覆盖率当围栏
    ------------------------
    从文字带边缘一格一格往外走，覆盖率一超过 CELL_COV_STOP 就停，再退
    CELL_RULE_CLEARANCE 个像素。文字笔画过不了半带高的竖直开运算（带内实测
    ≈0），界行和版框则是 0.2~1.0，两者在这个量上不重叠。两个细节缺一不可：

    - 覆盖率必须**分带**统计（_vline_cov_banded）。整页统计对斜/弯的界行
      是瞎的，围栏形同虚设——离线对比 rule_bar 代理 0.94% vs 分带 0.43%。
    - 只有**撞到墙**（或这一侧本来就检出了界行）才敢扩。一路走到列格边界
      都没碰到东西，说明这一侧没有分隔物，再扩就是往邻列的墨里扩。

    最外两列挨着的是**版框**：双边框加磨损，实测是一条 40px 宽、覆盖率在
    0.0~0.4 之间忽高忽低的乱带（vol01/33 右侧 1636~1685），实心核心只占最
    外面 12px。贴着检出的界行裁会把外侧那一大片一起圈进来，而一格一格走的
    围栏在乱带外面就停住了。

    取 min/max 保证本函数**只放宽、不收紧**图块。实测（vol01 全书 24605 个
    字格，端到端跑完 segment+chars）：被切掉笔画的字格 44.8% → 9.2%，
    「臣」形字格 79.7% → 35.1%，而 rule_bar 只从 47 块动到 53 块（都是
    0.2%）、无标记块 67.7% → 67.0%——救回大量字形，几乎不付代价。
    """
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    run = period * RULE_MIN_RUN_PERIOD
    binary = (gray < BINARY_THRESHOLD).astype(np.uint8)
    covs, spans = _vline_cov_bands(binary, run)
    # 放宽档：磨损断裂的界行残段（实测 122~197px）够不着严格档 1.2×列距，
    # 「无墙不敢扩」会拒绝外扩、切掉越出文字带的字（vol02/119 col7 整列）。
    # 放宽档用**自己的更细带划分**（带高 1.7×0.8×列距 ≈ 246px）：弯的界行
    # 在粗带里墨摊开、每个 x 都不够游程，细带里同一段线更直（vol02/151
    # 全页左墙在 6 条粗带下全部拒扩）。门槛相应抬高（结构弱要量足）。
    run_rel = period * RULE_RELAX_RUN_PERIOD
    covs_rel, spans_rel = _vline_cov_bands(binary, run_rel)
    # 对齐到严格档的带：每条严格带取与之重叠的放宽带的最大覆盖率
    rel_aligned = np.stack([
        covs_rel[[i for i, (ra, rb) in enumerate(spans_rel)
                  if not (rb <= a or ra >= b)]].max(axis=0)
        for a, b in spans])
    stops = (covs > CELL_COV_STOP) | (rel_aligned > CELL_COV_STOP_RELAX)
    stop_any = stops.any(axis=0)
    # 最左列左侧的密度档：模糊内边框断续到两档游程都检不出（实测
    # vol02/158 等页边框墨进条带），但文字带以左只可能是边框——
    # 原始墨密度（不开运算，跟严格档同带划分）超阈即算墙
    raw_rows = []
    for a, b in spans:
        raw_rows.append(binary[a:b].mean(axis=0))
    raws = np.stack(raw_rows) > FRAME_RAW_T
    stops_frame = stops | raws
    stop_frame_any = stops_frame.any(axis=0)
    w = stops.shape[1]
    # 界行中心：放宽档检出的也算「这一侧有分隔物」的证据——界行弯到列格
    # 名义边界之外时，走到边界都撞不上墙，只能靠 near_* 放行扩到边界
    centers = [(a + b) / 2 for a, b in rule_segments(gray, run)]
    centers += [(a + b) / 2 for a, b in rule_segments(gray, run_rel)]
    tol = period * CELL_RULE_TOL
    # 文字带本身也先内缩一点：界行正好压在带边上时，这一点点就是全部的余量
    shrink = min(max(period - inset_l - inset_r, 0.0) * 0.03, 4.0)

    def walk(stop_row, start, stop_at, step):
        x = int(round(start))
        while 0 <= x + step < w and (x + step - stop_at) * step < 0 \
                and not stop_row[x + step]:
            x += step
        hit = 0 <= x + step < w and bool(stop_row[x + step])
        return x, hit

    out: list[tuple[float, float]] = []
    band_out: list[list[list[float]] | None] = []
    for k in range(n_cols):
        bl, br = cx0 + period * k, cx0 + period * (k + 1)
        lo0 = cx0 + period * k + inset_l + shrink
        hi0 = cx0 + period * (k + 1) - inset_r - shrink
        near_l = any(abs(c - bl) <= tol for c in centers)
        near_r = any(abs(c - br) <= tol for c in centers)
        # 最左列（k=0）的左侧启用密度档（见 stops_frame 注）
        l_any = stop_frame_any if k == 0 else stop_any
        x, hit = walk(l_any, lo0, bl, -1)
        lo = min(lo0, max(bl, x + CELL_RULE_CLEARANCE)) if (hit or near_l) \
            else lo0
        x, hit = walk(stop_any, hi0, br, +1)
        hi = max(hi0, min(br, x - CELL_RULE_CLEARANCE)) if (hit or near_r) \
            else hi0
        if hi - lo < period * 0.2:            # 证据自相矛盾 → 退回文字带
            lo = cx0 + period * k + inset_l
            hi = cx0 + period * (k + 1) - inset_r
        out.append((float(lo), float(hi)))

        # ── 逐带围栏：弯的界行各带的墙不在同一个 x，取 max 的围栏在多数
        # 带里把墙划在线根本不在的地方（实测 vol02/151 一条界行沿页高漂
        # 49px）。每条带用**自己带内**的覆盖率重走一遍；带里量不到墙就用
        # 整体值兜底。仅当各带彼此差得够大（CELL_BOW_T）才输出，直边界
        # 保持原有的扁平表示。
        rows: list[list[float]] = []
        for bi, (ya, yb) in enumerate(spans):
            srow = stops[bi]
            lrow = stops_frame[bi] if k == 0 else srow
            x, hit = walk(lrow, lo0, bl, -1)
            blo = min(lo0, max(bl, x + CELL_RULE_CLEARANCE)) \
                if (hit or near_l) else lo
            x, hit = walk(srow, hi0, br, +1)
            bhi = max(hi0, min(br, x - CELL_RULE_CLEARANCE)) \
                if (hit or near_r) else hi
            if bhi - blo < period * 0.2:
                blo, bhi = lo, hi
            rows.append([float(ya), float(yb), float(blo), float(bhi)])
        spread = max(max(r[2] for r in rows) - min(r[2] for r in rows),
                     max(r[3] for r in rows) - min(r[3] for r in rows))
        if spread > CELL_BOW_T:
            band_out.append(rows)
            # 弯边界的扁平裁切边改为逐带边界的**外包络**：整体 max-cov 的
            # 墙是所有带的并集、停在最靠内的那一堵，比逐带的墙保守——条带
            # 若仍按它裁，掩蔽只能删像素、加不回来，逐带围栏就白算了
            # （第一版集成实测 p151 截断纹丝不动，正是这一步漏了）。
            # 包络放宽的部分全部落在某条带的墙外，由 cell_bands 掩蔽兜住。
            out[-1] = (float(min(r[2] for r in rows)),
                       float(max(r[3] for r in rows)))
        else:
            band_out.append(None)
    return out, band_out


def column_projection(col_gray: np.ndarray,
                      line_frac: float = 0.3) -> np.ndarray:
    """列区域的水平投影（每行黑像素数）。输入灰度或二值图。

    先用竖直开运算剔除长竖线（边框/界行残留：连续贯穿 ≥ line_frac×列高；
    字的竖笔最长 ~1 字高，绝不会被误剔）——竖线给每行加常量偏置，
    会把字间谷填平，淹没网格拟合的相位信号。只减线像素，同 x 的文字保留。"""
    binary = (col_gray < BINARY_THRESHOLD).astype(np.uint8)
    k = max(3, int(binary.shape[0] * line_frac))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, k))
    vlines = cv2.dilate(cv2.erode(binary, kernel), kernel)
    cleaned = binary & (1 - vlines)
    return cleaned.sum(axis=1).astype(np.float64)


def content_range(proj: np.ndarray, rel_thresh: float = 0.05,
                  min_run: float = 0.0,
                  max_fill: float | None = None) -> tuple[int, int]:
    """投影的实际内容范围 [top, bottom)。

    版面检测的 inner_frame 常有偏差（裁进空白或裁掉首末字），网格必须
    摊在文字实际占据的范围上，否则整体相位偏移。

    min_run > 0 时，首尾的**短游程**（连续非零段长 < min_run）被忽略——
    边框横线（3~10 行）和贴边残迹是短游程，文字块是 ~字高 的长游程；
    比"单行接近满宽"判据稳健（"一"类横笔也能占满列宽，但它属于长游程）。
    空投影返回全范围。
    """
    if proj.max() <= 0:
        return 0, len(proj)
    # 参考值用非零 90 分位而非 max —— max 会被边框线尖峰抬高，
    # 连带阈值过高/过低都失真
    ref = float(np.percentile(proj[proj > 0], 90))
    mask = proj > max(ref * rel_thresh, 1.0)
    idx = np.nonzero(mask)[0]
    if idx.size == 0:
        # 有墨但全在阈值（≥1）以下：整段只有零星单像素。当作"没有内容"，
        # 返回全范围而不是崩——proj.max()>0 挡不住这种情况，实测换了列距
        # 之后就有列格切出这样的切片。
        return 0, len(proj)
    if min_run <= 1:
        return int(idx[0]), int(idx[-1]) + 1
    # 游程分解
    splits = np.nonzero(np.diff(idx) > 1)[0]
    starts = np.concatenate([[idx[0]], idx[splits + 1]])
    ends = np.concatenate([idx[splits] + 1, [idx[-1] + 1]])
    runs = [(int(s), int(e)) for s, e in zip(starts, ends)]

    def _is_junk(run: tuple[int, int]) -> bool:
        s, e = run
        if e - s < min_run:
            return True   # 短游程：边框线/贴边残迹
        if max_fill is not None and float(np.median(proj[s:e])) > max_fill:
            return True   # 近满宽实心块：扫描黑边/粗边框，文字远达不到
        return False

    while len(runs) > 1 and _is_junk(runs[0]):
        runs.pop(0)
    while len(runs) > 1 and _is_junk(runs[-1]):
        runs.pop()
    return runs[0][0], runs[-1][1]


def fit_global_grid(proj: np.ndarray, n_chars: int,
                    scales: np.ndarray = SCALES,
                    full_width: float | None = None) -> tuple[float, float]:
    """全局网格拟合：搜索 (偏移 δ, 伸缩 s) 使网格线落在投影谷、
    格中心落在投影峰。

    cost = mean(proj[网格线]) − 0.5 · mean(proj[格中心])
    —— 排版紧凑、谷很浅时，峰项仍提供可靠的相位信息。
    网格严格限制在内容范围内（不允许线出界"作弊"降 cost）。

    Returns:
        (offset, cell_h): 首线位置与格高（proj 坐标系）。
    """
    L = len(proj)
    top, bottom = content_range(
        proj, min_run=0.25 * L / n_chars,
        max_fill=0.9 * full_width if full_width else None)
    span_max = bottom - top
    base_h = span_max / n_chars
    smooth = _smooth(proj, base_h)

    best = (float(top), base_h)
    best_cost = float("inf")
    for s in scales:
        cell_h = base_h * s
        span = cell_h * n_chars
        max_off = span_max - span
        if max_off < -1e-6:      # 网格比内容还长：不合法
            continue
        offsets = top + np.linspace(0.0, max(0.0, max_off), num=15)
        for off in offsets:
            cost = _grid_cost(smooth, off, cell_h, n_chars)
            if cost < best_cost:
                best_cost = cost
                best = (float(off), float(cell_h))
    return best


def _smooth(proj: np.ndarray, cell_h: float) -> np.ndarray:
    kernel = max(3, int(cell_h * 0.08)) | 1
    return np.convolve(proj, np.ones(kernel) / kernel, mode="same")


def _grid_cost(smooth: np.ndarray, off: float, cell_h: float,
               n_chars: int) -> float:
    """网格代价：线落谷（小） − 0.5×格中心落峰（大）。"""
    L = len(smooth)
    li = np.clip(np.round(off + cell_h * np.arange(n_chars + 1)).astype(int),
                 0, L - 1)
    ci = np.clip(np.round(off + cell_h * (np.arange(n_chars) + 0.5)).astype(int),
                 0, L - 1)
    return float(smooth[li].mean()) - 0.5 * float(smooth[ci].mean())


def page_column_projection(gray: np.ndarray, line_frac: float = 0.3,
                           return_rule_xs: bool = False):
    """整页垂直投影（每 x 的黑像素数），供列网格拟合。

    先剔两类长线：竖直长线（界行/边框竖线——它们在垂直投影上是假峰，
    恰好位于列边界处）与水平长线（边框横线——给每 x 加常量偏置）。
    剔完后投影呈现纯净的周期结构：文字列=台地、列间缝=谷，
    与行方向的字/空隙结构同构，谷/峰代价模型可直接复用。

    return_rule_xs=True 时额外返回界行/边框竖线所在的 x 布尔掩码
    ——供列拟合质量评估（界行应落在列格之间，落入列内即拟合失败）。"""
    binary = (gray < BINARY_THRESHOLD).astype(np.uint8)
    h, w = binary.shape
    kv = cv2.getStructuringElement(
        cv2.MORPH_RECT, (1, max(3, int(h * line_frac))))
    vlines = cv2.dilate(cv2.erode(binary, kv), kv)
    kh = cv2.getStructuringElement(
        cv2.MORPH_RECT, (max(3, int(w * line_frac)), 1))
    hlines = cv2.dilate(cv2.erode(binary, kh), kh)
    cleaned = binary & (1 - vlines) & (1 - hlines)
    proj = cleaned.sum(axis=0).astype(np.float64)
    if return_rule_xs:
        return proj, vlines.any(axis=0)
    return proj


def column_pitch(proj: np.ndarray, prior: float,
                 ink_t: float) -> float | None:
    """量一列的**字距**：在 ±10% 的候选里挑「中心点相位最集中」的那个。

    为什么不用「间距的中位数」：列里总有空格位，间距会混进 2×、3×，
    中位数被它们带偏。

    为什么不用「给中心配整数格号再拟斜率」：**它对先验敏感**。先验偏
    3% 时，列末的格号会配错一位，斜率被带偏——实测这么做把 vol02 的
    格高从真值 110.6 推到 112.6（偏 +1.8%），末格反而更容易吃到版框。
    量物理常量的估计量必须对先验不敏感。

    环形集中度对先验只依赖搜索窗：候选 p 下把每个中心折算成相位
    2π·y/p，中心都落在格线上时这些相位聚成一束（|均值| → 1），
    p 不对就散开。实测先验故意给 ±6%，估出来的值只差 0.1%。

    返回 None 的情况：单字墨段少于 PITCH_MIN_SEGS、或最佳候选的集中度
    低于 PITCH_MIN_R（这列本来就不是刚性的）。
    """
    on = proj > ink_t
    segs: list[tuple[int, int]] = []
    start = None
    for j, v in enumerate(on):
        if v and start is None:
            start = j
        elif not v and start is not None:
            segs.append((start, j)); start = None
    if start is not None:
        segs.append((start, len(on)))
    # 只要**单字**段：太短是碎屑，太长是上下字粘连
    segs = [(a, b) for a, b in segs if 0.35 * prior < b - a < 1.5 * prior]
    if len(segs) < PITCH_MIN_SEGS:
        return None
    c = np.array([(a + b) / 2 for a, b in segs], dtype=float)
    best_p, best_r = None, -1.0
    for p in np.arange(prior * (1 - PITCH_SEARCH), prior * (1 + PITCH_SEARCH),
                       PITCH_STEP):
        r = float(abs(np.exp(1j * 2 * np.pi * c / p).mean()))
        if r > best_r:
            best_p, best_r = float(p), r
    return best_p if best_r >= PITCH_MIN_R else None


def measure_page_pitch(gray: np.ndarray, result: dict) -> list[float]:
    """一页里所有刚性列量出的字距。"""
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    cell_h = result.get("grid", {}).get("cell_h")
    if not cell_h:
        return []
    binary = (gray < BINARY_THRESHOLD).astype(np.uint8)
    out: list[float] = []
    for col in result.get("columns", []):
        if col.get("layout") != "rigid" or col.get("cell_left_x") is None:
            continue
        x0 = int(round(col["cell_left_x"])); x1 = int(round(col["cell_right_x"]))
        x0, x1 = max(0, x0), min(binary.shape[1], x1)
        if x1 - x0 < 20:
            continue
        p = column_pitch(binary[:, x0:x1].sum(axis=1).astype(float),
                         float(cell_h), 0.02 * (x1 - x0))
        if p:
            out.append(p)
    return out


# ── 版框行锚定（2026-08-24 用户 p20 实审回流）────────────────
# 栏格是版框等分出来的：**首格上沿物理上贴着上框线**（实测健康页
# 相位-框顶 0.1~0.2 格）。抬头空格页（首格空白、字从第 2 格起）的
# 谷/峰代价对「上下错开一格」的两族解等价——上面是空白格、下面是
# 页外，哪边都没内容可罚，整版下坠一格（末格挂到页外、末字并进
# 下框条），全书扫出 174 页。框证据可用时按 |相位-框顶| 决定性收罚。
FRAME_ROW_T = 0.5          # 行墨 ≥ 此比例 × 页宽 → 横框线行
FRAME_ROW_T2 = 0.28        # 磨损框线档：行墨 ≥ 此值且最长段够长也认
FRAME_RUN_T = 0.22         # 磨损档的最长横向连续墨段下限（× 页宽；字最长段 ~0.1）
FRAME_ROW_ZONE = 0.08      # 页顶搜索窗比例（裁切贴上框，框就在最顶上）
FRAME_ROW_ZONE_B = 0.20    # 页底搜索窗比例：下框磨损时 s3 的内线搜索会在框上
                           #   方停下，页底留出大段空白（vol01/22 实测 300px，
                           #   框落在 8% 窗外）。长横段判据挡得住字行，扩窗安全。
ANCHOR_TOL = 0.35          # 相位偏离框顶超此比例 × 格高才罚（框线厚度 ~0.1 格）
ANCHOR_SPAN_TOL = 0.06     # |框高/n - 格高| 超此比例 × 格高 → 框证据不可信，不锚
ANCHOR_W = 1e4             # 决定性罚款权重（谷/峰项在平族间差值只有个位数）


def measure_row_frames(gray: np.ndarray) -> tuple[int | None, int | None]:
    """页顶/页底窗内最靠外的横框线行。检不出为 None。

    磨损/波浪框线单行墨量掉到 0.3~0.5，纯行墨阈值漏检；补一条
    **最长横向连续墨段**判据（框线断成段也远长于字宽，字行最长段
    ≤ 单字宽 ~0.1 页宽）：行墨 ≥0.5 直接认，或行墨 ≥FRAME_ROW_T2
    且最长段 ≥FRAME_RUN_T × 页宽。"""
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    binary = gray < BINARY_THRESHOLD
    h, w = binary.shape
    rowink = binary.sum(axis=1) / max(1, w)
    zone = max(4, int(FRAME_ROW_ZONE * h))
    zone_b = max(4, int(FRAME_ROW_ZONE_B * h))

    def maxrun(y: int) -> float:
        row = binary[y]
        best = run = 0
        for v in row:
            run = run + 1 if v else 0
            if run > best:
                best = run
        return best / max(1, w)

    def is_bar(y: int) -> bool:
        if rowink[y] >= FRAME_ROW_T:
            return True
        return rowink[y] >= FRAME_ROW_T2 and maxrun(y) >= FRAME_RUN_T

    ft = next((y for y in range(zone) if is_bar(y)), None)
    fb = next((y for y in range(h - 1, h - zone_b, -1) if is_bar(y)), None)
    return ft, fb


def fit_page_grid(projs: list[np.ndarray], n_chars: int,
                  full_widths: list[float] | None = None,
                  cell_step: float = 0.5, phase_step: int = 2,
                  cell_h_fixed: float | None = None,
                  frame_top: float | None = None,
                  frame_bottom: float | None = None
                  ) -> tuple[float, float]:
    """页级刚性网格拟合：在全部文字列的聚合投影上搜索 (相位, 格高)。

    刻本整版先划栏格再上字：**格高固定、跨列统一**；列首/列尾的空格
    占格位但无墨——因此网格必须锚定栏格证据（聚合投影的周期结构），
    而非单列的内容范围（抬头空格列按内容锚定会整体错位一格）。

    Args:
        cell_h_fixed: 给定时格高不再搜索（书级共识值），只搜相位。
            自由拟合的格高基准 `base=(bottom-top)/n_chars` 假设列是满的，
            稀疏页（目录、职名）与谐波锁定页会得到 1/2、1/3 的伪解，
            ±8% 的搜索窗永远跳不出去——格高只能由全书刚性先验给定。

    Returns:
        (phase, cell_h): 网格首线位置与固定格高。
    """
    page = np.sum(projs, axis=0)
    L = len(page)
    if page.sum() < 1:
        return 0.0, float(cell_h_fixed or L / n_chars)
    fw = float(sum(full_widths)) if full_widths else None
    top, bottom = content_range(page, min_run=0.25 * L / n_chars,
                                max_fill=0.9 * fw if fw else None)
    base = float(cell_h_fixed) if cell_h_fixed else (bottom - top) / n_chars
    smooth = _smooth(page, base)

    if cell_h_fixed:
        cell_hs = [float(cell_h_fixed)]
    else:
        cell_hs = list(np.arange(base * 0.92, base * 1.08, cell_step))

    best = (float(top), base)
    best_cost = float("inf")
    # 盖不住的内容要付钱。谷/峰代价对「整体错开 k 格」的解族近乎无感：
    # 相位以上的真字没有线去碰、页外的线剪裁到空白处，都不进代价——
    # 实测 vol01/66 书级格高差 0.013px 就让相位在两族解之间翻转，坏解
    # 把网格整体压低 2 格、顶部两行真字落在网格外、丢 11 个字；vol01/65
    # 的旧产物就长期锁在这种坏解上（相位 403、末两格悬在页外空转）。
    # 惩罚 = 网格跨度外（留 0.5 格出头余量：末格字下探、首格字上冒是
    # 正常现象）的墨量 ÷ 格高——量纲与谷/峰项同阶但对整格错开是
    # 压倒性的；半格以内的细对齐仍由谷/峰项主导。
    # 两道防误伤，缺一不可（都是实测踩出来的）：
    # 1) **两端各让开 1/4 格保护带**：content_range 已剔短游程废墨，但上
    #    边框横杠与首行字连成一个长游程时它分不开（vol02/17 实测 top 直
    #    接落在横杠上），贴边小段里的墨不可信。第一版不设保护带，vol01
    #    有 56 页被拉高一格去「盖住」顶部废墨、净丢 129 个字。带宽只能
    #    1/4 格：半格会把末行字的出头证据也吃掉，1 格错位就分不出了。
    # 2) **逐列算、取中位**：聚合投影会让一列非规范的墨压过多数列——
    #    vol02/17 卷首页的题名列顶格写、高出正文一行，聚合惩罚为了盖住
    #    这一个字把 8 列正文的末行全甩掉。刻本栏格跨列统一，相位由多数
    #    列的证据定（与全书「列间共识」原则同构）；跨全列的坏证据（边框
    #    横杠人人有份，中位滤不掉）由保护带兜住。
    # 代价是「只错开一格」的解族分不出——保护带正好吃掉一行——这类页
    # 回到谷/峰代价的原判（与历史产物一致）；错开 ≥2 格的病（vol01/65
    # 长期锁坏解、66 一触即翻）保护带外仍有整行真字墨，惩罚决定性。
    # 3) **每行墨量门槛**：保护带外仍可能有跨列的低强度渗墨/晕染
    #    （vol02/17 实测 ~4 墨/行/列，真字行是它的 20 倍），行墨低于该列
    #    内容区 75 分位的 15% 就不算「没盖住的内容」。
    csums = []
    for p in projs:
        seg = p[int(top):int(bottom)]
        nz = seg[seg > 0]
        thr = 0.15 * float(np.percentile(nz, 75)) if nz.size else 0.0
        masked = np.where(p >= thr, p, 0.0)
        csums.append(np.concatenate([[0.0], np.cumsum(masked)]))

    def _uncovered(phase: float, span: float, g: float) -> float:
        lo1, hi1 = top + g, phase - g
        lo2, hi2 = phase + span + g, bottom - g
        vals = []
        for cs in csums:
            v = 0.0
            for a, b in ((lo1, hi1), (lo2, hi2)):
                a = int(np.clip(round(a), top + g, bottom - g))
                b = int(np.clip(round(b), top + g, bottom - g))
                if b > a:
                    v += float(cs[b] - cs[a])
            vals.append(v)
        return float(np.median(vals))

    for cell_h in cell_hs:
        span = cell_h * n_chars
        # 版框锚定门控：上下框都检得出、且框高与 n 格吻合才启用
        anchored = (frame_top is not None and frame_bottom is not None
                    and abs((frame_bottom - frame_top) / n_chars - cell_h)
                    <= ANCHOR_SPAN_TOL * cell_h)
        # 相位范围：允许首格空/框偏差，网格可高于内容顶一格出头。
        # 格高固定时不再按 L-span 收窄上界——共识格高下整版可能略高于
        # 裁切后的页面（末格出界由 cells_from_bounds 裁掉）。
        p_lo = max(0.0, top - 1.2 * cell_h)
        p_hi = top + 1.2 * cell_h if cell_h_fixed \
            else min(top + 1.2 * cell_h, max(p_lo, L - span))
        if anchored:
            # 内容顶远低于框顶的页（职名首列低开等），原范围够不到框顶
            # ——锚定罚了却无解可选。范围必须罩住 框顶 ± 容差。
            p_lo = min(p_lo, max(0.0, frame_top - ANCHOR_TOL * cell_h))
            p_hi = max(p_hi, frame_top + ANCHOR_TOL * cell_h)
        for phase in np.arange(p_lo, p_hi + phase_step, phase_step):
            # 中位是列数一半的量级，聚合(smooth=各列之和)是全列量级，
            # 补上列数因子让惩罚与谷/峰项同纲
            uncovered = _uncovered(phase, span, 0.25 * cell_h) * len(csums)
            cost = _grid_cost(smooth, phase, cell_h, n_chars) \
                + uncovered / cell_h
            if anchored:
                excess = max(0.0, abs(phase - frame_top)
                             - ANCHOR_TOL * cell_h)
                cost += excess / cell_h * ANCHOR_W
            if cost < best_cost:
                best_cost = cost
                best = (float(phase), float(cell_h))
    return best


def snap_bounds_to_gaps(proj: np.ndarray, bounds: list[float],
                        cell_h: float) -> list[float]:
    """逐条格线滑到**字间空隙**（局部墨谷）。

    等距格线只保证「格高对」，不保证每一条线都落在空隙里：刻工排字有
    微偏、字身大小不一，一条线偏个七八像素就从笔画上切过去。而「这一行
    有多少墨」是可以直接量的，谷底就是该切的地方。

    三条约束：

    - **滑动半径只有 SNAP_RANGE×格高。** 再大就会滑到邻格的空隙上，
      等于把一个字整个让给隔壁——那是比切一刀更严重的错误。
    - **没有谷就不滑。** 上下两字真的连在一起时（谷底墨量仍高于相邻两格
      平均墨量的 SNAP_VALLEY_T），保持刚性位置：宁可在原处切一刀，也不要
      滑到别处去切。这类「必须带墨的分隔线」由下游 `_split_touching`
      在颈部处理。
    - **平局偏向原位。** 整段空白时谷底到处都是 0，取离刚性位置最近的那个。

    首末两条线同样吸附——版框与首/末字之间也有一道小空隙，让线落进去，
    首末字才不会被切掉（实测末格的字下出头中位 0.19 格）。
    """
    if len(bounds) < 2 or cell_h <= 0:
        return bounds
    k = max(1, int(SNAP_SMOOTH))
    sm = np.convolve(np.asarray(proj, dtype=float),
                     np.ones(k) / k, mode="same")
    L = len(sm)
    r = max(1, int(round(SNAP_RANGE * cell_h)))
    out: list[float] = []
    for i, b in enumerate(bounds):
        bi = int(round(b))
        lo, hi = max(0, bi - r), min(L, bi + r + 1)
        if hi - lo < 3:
            out.append(float(b)); continue
        win = sm[lo:hi]
        # 参考墨量：这条线两侧各半格（没有相邻格时用有的那一侧）
        a0 = max(0, bi - int(cell_h * 0.5)); a1 = min(L, bi + int(cell_h * 0.5))
        ref = float(sm[a0:a1].mean()) if a1 > a0 else 0.0
        m = float(win.min())
        if ref > 0 and m > SNAP_VALLEY_T * ref:
            out.append(float(b)); continue          # 这里本来就没有空隙
        cand = np.flatnonzero(win <= m + 1e-9) + lo
        out.append(float(cand[np.argmin(np.abs(cand - bi))]))
    # 保序：吸附半径 < 半格，正常不会交叉；真交叉了就退回原位
    for i in range(1, len(out)):
        if out[i] <= out[i - 1]:
            return list(bounds)
    return out


def rigid_bounds(proj: np.ndarray, page_phase: float, cell_h: float,
                 n_chars: int, micro: float = 0.12,
                 phase_step: int = 1, snap: bool = True) -> list[float]:
    """单列刚性网格：格高固定，相位在页面相位 ±micro×格高 内微调，
    再把每条格线**逐条**吸附到字间空隙（见 snap_bounds_to_gaps）。

    微调只容忍板歪/扫描形变；空列/稀疏列信号弱时代价面平坦，
    平局偏向页面相位（刻本栏格跨列统一）。"""
    L = len(proj)
    smooth = _smooth(proj, cell_h)
    r = micro * cell_h
    best_phase, best_cost = max(0.0, page_phase), float("inf")
    for phase in np.arange(max(0.0, page_phase - r),
                           page_phase + r + phase_step, phase_step):
        cost = _grid_cost(smooth, phase, cell_h, n_chars) \
            + 1e-3 * abs(phase - page_phase) / cell_h * max(1.0, smooth.mean())
        if cost < best_cost:
            best_cost, best_phase = cost, float(phase)
    bounds = [best_phase + cell_h * k for k in range(n_chars + 1)]
    return snap_bounds_to_gaps(proj, bounds, cell_h) if snap else bounds


def straddle_score(image: np.ndarray, result: dict) -> float:
    """骑线比：网格线上的墨 / 格中心的墨（逐列取中位）。

    这是切分质量的**直接**度量——字骑在格线上时线上墨接近格心墨
    （比值→1），对齐良好时线落字间空隙（比值→0.2±）。实测全书
    中位 0.38，骑线页 >0.8。"""
    if image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # result 里的坐标在**去错切帧**，量图必须先摆到同一帧，否则列框会
    # 整体错位、骑线比失去意义
    image = deshear(image, result.get("grid", {}).get("shear", 0.0))
    cell_h = result.get("grid", {}).get("cell_h") or 100.0
    ratios = []
    for col in result.get("columns", []):
        cells = [c for c in col.get("cells", []) if c.get("type") != "margin"]
        if not cells:
            continue
        x0 = int(col["left_x"]) + 2
        x1 = int(col["right_x"]) - 2
        if x1 - x0 < 8:
            continue
        crop = image[:, x0:x1]
        if crop.size == 0:
            continue
        sm = _smooth(column_projection(crop), cell_h)
        if sm.sum() < 1:
            continue
        L = len(sm)
        lines = [int(c["y_top"]) for c in cells] + [int(cells[-1]["y_bottom"])]
        centers = [int((c["y_top"] + c["y_bottom"]) / 2) for c in cells]
        lv = float(np.mean([sm[min(max(y, 0), L - 1)] for y in lines]))
        cv_ = float(np.mean([sm[min(max(y, 0), L - 1)] for y in centers]))
        if cv_ > 1:
            ratios.append(lv / cv_)
    return float(np.median(ratios)) if ratios else 0.0


def sweep_row_phase(image: np.ndarray, result: dict, cell_h: float,
                    n_steps: int = 32) -> tuple[float, float]:
    """全周期扫描行相位，返回 (最优首线全图 y, 该相位的骑线比)。

    直接优化骑线度量本身。相位**不能**跟随书级中位：实测相位相对
    版框全书并不一致（对齐良好页之间 σ≈0.45 格）——只能本页自扫。
    稀疏页（职名/目录）的谷-峰代价欠定正是原相位错拟的根源，
    骑线比对这类页仍然判别明确（字在格心 vs 骑线是硬事实）。"""
    if image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    image = deshear(image, result.get("grid", {}).get("shear", 0.0))
    cols = []
    for col in result.get("columns", []):
        cells = [c for c in col.get("cells", []) if c.get("type") != "margin"]
        if not cells:
            continue
        x0, x1 = int(col["left_x"]) + 2, int(col["right_x"]) - 2
        if x1 - x0 < 8:
            continue
        crop = image[:, x0:x1]
        if crop.size == 0:
            continue
        sm = _smooth(column_projection(crop), cell_h)
        if sm.sum() >= 1:
            cols.append(sm)
    if not cols:
        return 0.0, float("inf")
    first = min(float(c["cells"][0]["y_top"]) if c.get("cells") else 0.0
                for c in result["columns"]
                if any(x.get("type") != "margin" for x in c.get("cells", [])))
    n = sum(1 for c in result["columns"][0].get("cells", [])
            if c.get("type") != "margin") or 21
    best_y, best_score = first, float("inf")
    for delta in np.linspace(-0.5, 0.5, n_steps, endpoint=False) * cell_h:
        y0 = first + delta
        ratios = []
        for sm in cols:
            L = len(sm)
            lines = np.clip(np.round(y0 + cell_h * np.arange(n + 1)).astype(int),
                            0, L - 1)
            centers = np.clip(
                np.round(y0 + cell_h * (np.arange(n) + 0.5)).astype(int),
                0, L - 1)
            cv_ = float(sm[centers].mean())
            if cv_ > 1:
                ratios.append(float(sm[lines].mean()) / cv_)
        score = float(np.median(ratios)) if ratios else float("inf")
        if score < best_score:
            best_score, best_y = score, float(y0)
    return best_y, best_score


def dp_boundaries(proj: np.ndarray, cell_h: float, n_chars: int,
                  phase_prior: float | None = None,
                  elastic: float = 0.15, step: int = 2,
                  beta: float = 1.0,
                  full_width: float | None = None) -> list[float]:
    """弹性网格动态规划：全局最优地选 n_chars+1 条网格线。

    写刻本手写上版，字距列内局部不均——刚性等距网格误差沿列累积。
    DP 保持"恰好 N 格"硬约束，允许每格高度在 ±elastic 内伸缩：

        cost = Σ smooth[线] − 0.5·Σ smooth[格中心]
             + β·mean(smooth)·Σ ((格高−cell_h)/(elastic·cell_h))²

    phase_prior 给定时（稀疏列，如职名页），首线锚定在先验相位附近，
    末线由 N×cell_h 推算——弱信号列跟随页面主流相位。
    """
    L = len(proj)
    smooth = _smooth(proj, cell_h)
    ys = np.arange(0, L, step)
    M = len(ys)
    line_cost = smooth[ys]
    d_lo = max(1, int((1.0 - elastic) * cell_h / step))
    d_hi = max(d_lo, int(np.ceil((1.0 + elastic) * cell_h / step)))
    pen_scale = beta * max(1.0, float(smooth.mean()))

    top, bottom = content_range(
        proj, min_run=0.25 * cell_h,
        max_fill=0.9 * full_width if full_width else None)
    if phase_prior is not None:
        s_lo, s_hi = phase_prior - 0.3 * cell_h, phase_prior + 0.3 * cell_h
        e_lo = phase_prior + n_chars * cell_h - 0.5 * cell_h
        e_hi = phase_prior + n_chars * cell_h + 0.5 * cell_h
    else:
        # 首末窗口各放宽到 2 格：content_range 只是粗定位（长游程可能
        # 混入边框/黑角），格中心峰项会驱动 DP 覆盖真实文字而非空白
        s_lo, s_hi = top - 0.5 * cell_h, top + 1.5 * cell_h
        e_lo, e_hi = bottom - 1.5 * cell_h, bottom + 0.5 * cell_h

    INF = 1e18
    dp = np.where((ys >= s_lo) & (ys <= s_hi), line_cost, INF)
    if phase_prior is not None:
        # 平局时偏向先验相位（零信号列锚定页面主流网格，而非窗口边缘）
        dp = dp + 1e-3 * pen_scale * np.abs(ys - phase_prior) / cell_h
    back = np.zeros((n_chars, M), dtype=np.int32)
    for k in range(n_chars):
        ndp = np.full(M, INF)
        nb = np.zeros(M, dtype=np.int32)
        for d in range(d_lo, d_hi + 1):
            if d >= M:
                break
            h = d * step
            pen = pen_scale * ((h - cell_h) / (elastic * cell_h)) ** 2
            mid = np.clip((ys[d:] - h // 2), 0, L - 1)
            cand = dp[:-d] + line_cost[d:] - 0.5 * smooth[mid] + pen
            better = cand < ndp[d:]
            ndp[d:][better] = cand[better]
            nb[d:][better] = np.arange(M - d)[better]
        dp, back[k] = ndp, nb

    end_mask = (ys >= e_lo) & (ys <= e_hi) & (dp < INF)
    dp_end = np.where(end_mask, dp, INF)
    if not np.isfinite(dp_end.min()) or dp_end.min() >= INF:
        dp_end = dp   # 末端约束不可满足时放开（严重残页兜底）
    j = int(np.argmin(dp_end))
    bounds = [float(ys[j])]
    for k in range(n_chars - 1, -1, -1):
        j = int(back[k][j])
        bounds.append(float(ys[j]))
    return list(reversed(bounds))


def refine_boundaries(proj: np.ndarray, offset: float, cell_h: float,
                      n_chars: int,
                      search_ratio: float = SEARCH_RATIO) -> list[float]:
    """逐线微调：每条内部网格线在 ±search_ratio×格高 内移到投影最低点。

    首尾线不动（列边界）；保持单调且相邻线距 ≥ 0.6×格高。
    """
    L = len(proj)
    kernel = max(3, int(cell_h * 0.08)) | 1
    smooth = np.convolve(proj, np.ones(kernel) / kernel, mode="same")

    lines = [min(max(offset + cell_h * k, 0.0), float(L))
             for k in range(n_chars + 1)]
    refined = [lines[0]]
    for k in range(1, n_chars):
        y = lines[k]
        r = cell_h * search_ratio
        lo = max(int(y - r), int(refined[-1] + 0.6 * cell_h), 0)
        hi = min(int(y + r), L - 1)
        if hi <= lo:
            refined.append(min(max(y, refined[-1] + 0.6 * cell_h), float(L)))
            continue
        window = smooth[lo:hi + 1]
        # 同值谷取离先验位置最近者
        min_v = window.min()
        cand = np.nonzero(window <= min_v + 1e-9)[0] + lo
        best = cand[np.argmin(np.abs(cand - y))]
        refined.append(float(best))
    refined.append(lines[-1])
    return refined


def _junk_free_ink(cell_gray: np.ndarray) -> float:
    """格内去「界行竖线段 + 贴边框横线」后的墨量占比（判空用）。

    界行竖线段与版框横线的墨量足以骗过朴素判空（0.05~0.15 ≫ 0.02），
    batch3 人工反馈 147 例 not_text 大多如此。剔除规则：
    - 竖直长线（≥0.55 格高）整体剔——字的竖笔不会纵贯半格以上还落单；
    - 水平长线（≥0.55 格宽）仅当**贴边**（组件 y 中心在格高 22% 以外
      边带）才剔——版框线贴格顶/格底，「一」的横笔在格中央。
    实测：真值垃圾 48% 直接判空，用户确认真字/截断半字 0 误杀。"""
    b = (cell_gray < BINARY_THRESHOLD).astype(np.uint8)
    h, w = b.shape
    if h < 6 or w < 6:
        return float(b.sum()) / max(1, b.size)
    kv = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(3, int(h * 0.55))))
    vl = cv2.dilate(cv2.erode(b, kv), kv)
    # 竖线还须**窄**（≤12% 格宽）：界行 4~8px / 格宽 110px ≈ 5%，
    # 字的竖笔虽长但更宽且带弯曲——不加宽度条件会误剔理想化直笔
    nv, labv, statsv, _ = cv2.connectedComponentsWithStats(vl, 8)
    vl_narrow = np.zeros_like(vl)
    for k in range(1, nv):
        if statsv[k][2] <= max(6, 0.12 * w):
            vl_narrow[labv == k] = 1
    kh = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(w * 0.55)), 1))
    hl = cv2.dilate(cv2.erode(b, kh), kh)
    n, lab, statsh, cent = cv2.connectedComponentsWithStats(hl, 8)
    hl_edge = np.zeros_like(hl)
    for k in range(1, n):
        cy = cent[k][1] / h
        if (cy < 0.22 or cy > 0.78) and statsh[k][3] <= max(6, 0.15 * h):
            hl_edge[lab == k] = 1
    clean = b & (1 - vl_narrow) & (1 - hl_edge)
    return float(clean.sum()) / b.size


def cells_from_bounds(col_gray: np.ndarray, bounds: list[float],
                      params: GridParams) -> list[dict]:
    """按给定网格线产出 cells（局部 y 坐标）。"""
    n_chars = len(bounds) - 1
    w = col_gray.shape[1]
    L = col_gray.shape[0]
    cells: list[dict] = []
    if bounds[0] > 0.5:
        cells.append({"type": "margin", "y_top": 0.0, "y_bottom": bounds[0]})
    for i in range(n_chars):
        y0, y1 = bounds[i], bounds[i + 1]
        ink = _junk_free_ink(col_gray[int(y0):int(y1)])
        if ink < params.empty_ink_ratio:
            cells.append({"type": "empty", "index": i,
                          "y_top": y0, "y_bottom": y1,
                          "text": None, "confidence": 0.0})
        else:
            cells.append({"type": "char", "index": i,
                          "y_top": y0, "y_bottom": y1,
                          "text": None, "confidence": 0.0})
    if bounds[-1] < L - 0.5:
        cells.append({"type": "margin", "y_top": bounds[-1],
                      "y_bottom": float(L)})
    return cells


SPREAD_PITCH = 1.4         # 列内组件中位间距超此倍格高 → 判定"拉开列"


def _merged_components(col_bin: np.ndarray, cell_h: float
                       ) -> list[tuple[float, float, float]]:
    """列内合并连通体：返回 [(y_center, y_min, y_max)]，按 y 升序。

    同字的多部件（上下结构、断笔）按间距 < 0.5 格合并；
    过滤噪点与贯穿线（高 > 1.6 格 = 界行）。"""
    n, _, stats, cent = cv2.connectedComponentsWithStats(col_bin, 8)
    parts = []
    for (x, y, w, h, area), (cx, cy) in zip(stats[1:], cent[1:]):
        if area < cell_h * 2.5 or h > 1.6 * cell_h or h < 6:
            continue
        parts.append((float(y), float(y + h)))
    parts.sort()
    merged: list[list[float]] = []
    for y0, y1 in parts:
        if merged and y0 - merged[-1][1] < 0.35 * cell_h:
            merged[-1][1] = max(merged[-1][1], y1)
        else:
            merged.append([y0, y1])
    return [((a + b) / 2, a, b) for a, b in merged]


DENSE_SPLIT_MIN_H = 0.35    # 密排段切分：子字符最小高度（× 格高）
DENSE_SPLIT_VALLEY = 0.35   # 谷点判据：局部极小值 ≤ 段自身峰值的这个比例
OVERFLOW_CAP_RATIO = 3.0    # 单列格数硬上限（× n_chars），防噪声爆炸
# 组件锚定切分的**可行性**闸门（不是列型判据——列型由 classify_column_layout
# 定；这里只管「组件证据够不够撑起一次切分」）。原先这两个数是 12 / 2.2×格高
# 的**间距触发**，那是在 3.5 格拉开的职名列上定的，把 2 格拉开的官衔列全挡在
# 外面：判了 elastic 却切不出来 → 据实回落刚性 → 一个字被格线腰斩成两块。
# 实测 vol01/121 第 1 列字距 1.95 格、13 个组件，两条都不满足。
COMP_MAX = 30               # 组件数上限：正文密排列合并后远超此数
COMP_MIN = 3                # 少于此谈不上「一列」
COMP_MAX_H = 8.0            # 单组件高度上限（× 格高），超此是粘连/线条
COMP_JUNK_H = 0.3           # 低于此格高的组件当碎屑丢弃


def _split_dense_segment(col_gray: np.ndarray, a: float, b: float,
                         cell_h: float) -> list[tuple[float, float]]:
    """密排/压缩段内按墨迹谷点切分，不假定子字符等高。

    职名页标题过长时，刻工会把字压小塞进同一列高度——按标准格高猜
    这段有几个字必然低估（压缩后单字高度小于格高：实测一段 23 字的
    压缩标题按格高只猜出 15 字，导致整列因"格数超限"被打回刚性网格，
    23 字摊进 9 格，好几个字挤一格）。

    改用这段自己的行投影找局部墨量谷点：不管字被压缩到多小，真实字
    与字之间总有一处墨量低谷，谷点数 + 1 就是真实字数——不依赖任何
    绝对尺寸假设，一次性覆盖"拉开的人名段"（原逻辑已覆盖）和"压缩的
    超长标题段"（新增）。找不到清晰谷点（真·连笔）时按 0.95×格高
    均分兜底，不比原逻辑更差。
    """
    seg = col_gray[int(round(a)):int(round(b))]
    h = b - a
    proj = column_projection(seg)
    min_h = DENSE_SPLIT_MIN_H * cell_h

    def even_fallback() -> list[tuple[float, float]]:
        n_sub = max(1, int(round(h / (cell_h * 0.95))))
        step = h / n_sub
        return [(a + k * step, a + (k + 1) * step) for k in range(n_sub)]

    if proj.sum() < 1:
        return even_fallback()
    win = max(3, int(cell_h * 0.10)) | 1
    sm = np.convolve(proj, np.ones(win) / win, mode="same")
    peak = float(sm.max())
    if peak <= 0:
        return even_fallback()
    # 谷点：每一段"低于阈值"的连续区间取其最小值点，而不是逐点找局部
    # 极小值——后者对间距设下限会把压缩到比 min_h 还密的真实字距一并
    # 挡掉（实测把 11 字的压缩段只切出 6 段）；不设下限又会让平坦谷底
    # 上的每个像素都各算一个"局部极小"。按阈值分段取一个代表点两个
    # 问题一起解决，间距过近的伪谷交给下面的 merged_bounds 按 min_h 合并。
    below = sm < DENSE_SPLIT_VALLEY * peak
    valleys: list[int] = []
    i = 1
    while i < len(sm) - 1:
        if below[i]:
            j = i
            while j < len(sm) - 1 and below[j]:
                j += 1
            valleys.append(i + int(np.argmin(sm[i:j])))
            i = j
        else:
            i += 1
    bounds = [0.0] + [float(v) for v in valleys] + [float(len(sm))]
    merged_bounds = [bounds[0]]
    for x in bounds[1:]:
        if x - merged_bounds[-1] >= min_h:
            merged_bounds.append(x)
        else:
            merged_bounds[-1] = x          # 太窄的切段并回前一段
    if merged_bounds[-1] < bounds[-1]:
        merged_bounds[-1] = bounds[-1]
    if len(merged_bounds) < 3:             # 切不出像样的谷 → 均分兜底
        return even_fallback()
    return [(a + merged_bounds[i], a + merged_bounds[i + 1])
            for i in range(len(merged_bounds) - 1)]


# ── 列型判别：先分类，再分别切分 ────────────────────────

LAYOUT_MID_LO = 0.25       # 格墨量占比落在 [LO, HI] 视为"半格"
LAYOUT_MID_HI = 0.75
LAYOUT_MID_T = 0.20        # 半格比例超此 → 压缩型弹性
LAYOUT_RUN_T = 2           # 连续占位段长度中位数低于此 → 拉开型弹性
LAYOUT_FILL_T = 0.5        # 格墨量占比超此算"占位"


def column_occupancy(col_gray: np.ndarray, page_phase: float,
                     cell_h: float) -> tuple[float, float]:
    """列相对**书级刚性格线**的占位形态，返回 (连续段长度中位数, 半格比例)。

    这两个量把三类列分开，而单看"间距有多大"分不开（实测间距 AUC 仅
    0.61，是所有候选特征里最弱的一个，偏偏旧触发用的就是它）：

      正文密排   连续段长 ~20，半格比例 ~0.05
      目录稀疏   连续段长 ~4（「卷一百四十八」连着六个字），半格 ~0.05
      职名拉开   连续段长 1（字被拉开到 ~3.5 格，格格孤立）
      长题压缩   连续段长虽长，但一格挤进两个字 → 半格比例高

    关键是目录与职名的区分：两者都"字少、间距大"，但目录的字是**连续
    成段**的，职名的字是**逐格孤立**的。
    """
    proj = column_projection(col_gray)
    ink = np.flatnonzero(proj > 0)
    if ink.size < 3:
        return 0.0, 0.0
    y0, y1, L = int(ink[0]), int(ink[-1]), len(proj)
    occ: list[float] = []
    k = 0
    while True:
        a = page_phase + cell_h * k
        if a > y1:
            break
        b = a + cell_h
        if b >= y0:
            lo, hi = max(0, int(a)), min(L, int(b))
            if hi > lo:
                occ.append(float((proj[lo:hi] > 0).mean()))
        k += 1
        if k > 200:
            break
    if not occ:
        return 0.0, 0.0
    arr = np.array(occ)
    mid = float(((arr > LAYOUT_MID_LO) & (arr < LAYOUT_MID_HI)).mean())
    runs, run = [], 0
    for f in arr > LAYOUT_FILL_T:
        if f:
            run += 1
        elif run:
            runs.append(run); run = 0
    if run:
        runs.append(run)
    return (float(np.median(runs)) if runs else 0.0), mid


def component_spread_trigger(col_gray: np.ndarray, cell_h: float,
                             col_w: float) -> bool:
    """旧的组件间距触发：职名页召回好（实测精确率 1.00 / 召回 0.82），
    但会把目录页的稀疏列一并误报——所以只拿它当**候选生成**，
    最终由 classify_column_layout 里的占位形态否决。"""
    comps = _merged_components((col_gray < BINARY_THRESHOLD).astype(np.uint8),
                               cell_h)
    if len(comps) < 3 or len(comps) > 12:
        return False
    comps = [c for c in comps if (c[2] - c[1]) >= 0.3 * cell_h]
    if len(comps) < 3:
        return False
    gaps = np.diff([c[0] for c in comps])
    if int((gaps > 2.2 * cell_h).sum()) < 2:
        return False
    return all((b - a) <= 8.0 * cell_h for _, a, b in comps)


def classify_column_layout(col_gray: np.ndarray, page_phase: float,
                           cell_h: float, col_w: float) -> str:
    """列型判别：rigid（字距 = 1×格高）| elastic（字距 ≠ 1×格高）。

    规则在 36 页 322 列的人工金标上标定（open-guji-dataset/column-layout），
    页级二折交叉验证 F1 0.837±0.072，对照旧的纯间距触发 0.773：

      elastic ⇔ 连续段长 ≤1                          （拉开型，逐格孤立）
             ∨ (组件间距触发 ∧ ¬(连续段长 ≥2 ∧ 半格比例 <0.20))
                                                     （压缩型；括号内是
                                                       目录页的形态，否决之）
    """
    run_med, mid_frac = column_occupancy(col_gray, page_phase, cell_h)
    if run_med <= 1.0 and run_med > 0.0:
        return "elastic"
    if component_spread_trigger(col_gray, cell_h, col_w):
        toc_like = run_med >= LAYOUT_RUN_T and mid_frac < LAYOUT_MID_T
        if not toc_like:
            return "elastic"
    return "rigid"


def cells_from_components(col_gray: np.ndarray, cell_h: float, n_chars: int,
                          params: GridParams) -> list[dict] | None:
    """拉开列（职名/奉旨列名）的组件锚定混合切分。

    职名页排版有两种偏离刚性网格的方式，处理都基于同一套组件分析：
    - 官衔字**拉开**（字距 3.4~3.7 格，非整数倍，任何行相位都躲不开
      腰斩）——单字组件（高 ≤1.55 格）独立成格；
    - 标题过长时刻工把字**压缩**塞进同一列高度，格数因此**超过**
      n_chars——密排/压缩段组件（高 >1.55 格）按内部墨迹谷点切分
      （见 _split_dense_segment），而非假定子字符等于标准格高。

    idx 不再映射到 0..n_chars-1 的刚性网格位——超载列的字数本就超过
    n_chars，映射必然产生碰撞（实测把 23 字的列砸扁成 9 格）。组件
    已经是按 y 升序的真实阅读顺序，直接顺序编号即可，格数就是真实
    字数，不再向 n_chars 补齐空位。

    **闸门只管可行性，不再重判列型。** 列型已由 classify_column_layout 定；
    这里若再用一套「像不像拉开列」的阈值否决它，被否的列会据实回落刚性——
    而它本来就不该走刚性。原先的闸门（组件数 ≤12、至少 2 个中心间距 >2.2 格）
    是在 3.5 格拉开的职名列上定的，把 2 格拉开的官衔列整类挡在门外：实测
    vol01/121 第 1 列字距 1.95 格、13 个组件，两条都不满足，于是 13 个字被
    刚性格线切成 19 块（其中 4 块是空的、3 块是半个字）。

    现在只保留三条**输出是否可用**的条件：组件数落在 [COMP_MIN, COMP_MAX]、
    单组件不超过 COMP_MAX_H 格高（更高的是粘连或线条）、切出的格数不超过
    OVERFLOW_CAP_RATIO × n_chars。
    """
    col_bin = (col_gray < BINARY_THRESHOLD).astype(np.uint8)
    comps = _merged_components(col_bin, cell_h)
    if len(comps) < COMP_MIN or len(comps) > COMP_MAX:
        return None
    # 碎屑（< 0.3 格高：版框残迹、贴边墨点）丢弃而非否决整列——
    # p108 职名列曾因列顶一条 0.09 格的框线残迹被一票否决。
    # 局限：拉开列里真正的"一"字也会被当碎屑丢掉（官衔中几乎不出现）。
    comps = [c for c in comps if (c[2] - c[1]) >= COMP_JUNK_H * cell_h]
    if len(comps) < COMP_MIN:
        return None
    heights = [(b - a) for _, a, b in comps]
    if not all(h <= COMP_MAX_H * cell_h for h in heights):
        return None
    L = col_gray.shape[0]
    pad = 0.10 * cell_h
    boxes: list[tuple[float, float]] = []      # 每格 (y0, y1)，已按 y 升序
    for cy, a, b in comps:
        h = b - a
        if h <= 1.55 * cell_h:                 # 单字组件
            boxes.append((max(0.0, a - pad), min(float(L), b + pad)))
        else:                                   # 密排/压缩段：谷点切分
            for sa, sb in _split_dense_segment(col_gray, a, b, cell_h):
                boxes.append((max(0.0, sa - pad * 0.5),
                              min(float(L), sb + pad * 0.5)))
    if len(boxes) > OVERFLOW_CAP_RATIO * n_chars:
        return None                            # 谷点也切不出数——噪声，放弃
    cells: list[dict] = []
    for idx, (y0, y1) in enumerate(boxes):
        kind = ("char" if _junk_free_ink(col_gray[int(y0):int(y1)])
                >= params.empty_ink_ratio else "empty")
        cells.append({"type": kind, "index": idx,
                      "y_top": y0, "y_bottom": y1,
                      "text": None, "confidence": 0.0})
    return cells


def segment_column(col_gray: np.ndarray, n_chars: int, params: GridParams,
                   shared_grid: tuple[float, float] | None = None) -> list[dict]:
    """单列切分 → cells（局部 y 坐标）。

    shared_grid=(offset, cell_h) 给定时从页面级共享网格出发做小范围微调
    （刻本整版同刻、跨列行对齐，稀疏列跟随全页网格不漂移）；
    缺省时独立拟合本列（单列场景/测试用）。
    """
    proj = column_projection(col_gray)
    L = len(proj)
    if shared_grid is not None:
        offset, cell_h = shared_grid
        bounds = dp_boundaries(proj, cell_h, n_chars, phase_prior=offset)
    elif proj.sum() < 1:   # 独立模式下的整列空白：均分
        cell = L / n_chars
        return [{"type": "empty", "index": i,
                 "y_top": i * cell, "y_bottom": (i + 1) * cell,
                 "text": None, "confidence": 0.0} for i in range(n_chars)]
    else:
        _, cell_h = fit_global_grid(proj, n_chars)
        bounds = dp_boundaries(proj, cell_h, n_chars)
    return cells_from_bounds(col_gray, bounds, params)


# ── 页级并行 ──────────────────────────────────────────────
# run_book 各 pass 的逐页循环彼此独立（读图→拟合→返回 dict，页间无
# 状态），是全流程最大的耗时（Pass 1 + Pass 2a 合计 ~384s/482s）。
# 并行只改执行顺序不改任何计算：所有共识/门控/择优判断都留在父进程，
# 且按输入顺序收集结果——产物必须与串行逐字节等价（验证法见
# handbook §6）。


def _n_workers() -> int:
    """页级并行度。GUJI_WORKERS 优先（run_pipeline.sh 多册并行时给每册
    分核，避免 2 册 × 满核在 4 核机上互相挤），未设则用满核。"""
    env = os.environ.get("GUJI_WORKERS", "").strip()
    if env:
        return max(1, int(env))
    return max(1, os.cpu_count() or 1)


def _wk_init() -> None:
    # 工作进程各占一核；OpenCV 内部线程池在进程池之上只会互相挤占，
    # 进池后收成单线程。
    cv2.setNumThreads(1)


def _pmap(fn, jobs: list[tuple]) -> list:
    """按输入顺序返回 [fn(*job) for job in jobs]，进程池并行。
    并行度 <=1 或只有一个任务时原地串行，行为与旧实现完全一致。

    必须用 spawn 不能用 fork：父进程跑过 cv2 之后自带 OpenCV 线程池，
    fork 只复制调用线程、锁状态照抄，子进程一碰 cv2 就死锁在 futex 上
    （实测在 pytest 里 100% 复现，父子全部挂起、负载归零）。spawn 子进
    程干净起步，代价是重新 import 本模块（~1s/池，相对每 pass 几十秒
    的并行收益可忽略）。"""
    n = min(_n_workers(), len(jobs))
    if n <= 1:
        return [fn(*j) for j in jobs]
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=n, mp_context=ctx,
                             initializer=_wk_init) as ex:
        return list(ex.map(fn, *zip(*jobs), chunksize=1))


def _job_pass1(seg: "GridSegmenter", img_path: str, layout: dict):
    """Pass 1 单页：读图 → 页型闸门 → 整页拟合 → 量字距。"""
    image = imread(img_path)
    if image is None:
        return None
    gray = image if image.ndim == 2 \
        else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    ptype, policy = classify_page_type(gray)
    if policy == "skip":
        return {"skip": True, "ptype": ptype,
                "width": int(image.shape[1]), "height": int(image.shape[0])}
    r = seg.segment_page(image, layout)
    return {"skip": False, "ptype": ptype, "r": r,
            "pitches": measure_page_pitch(gray, r)}


def _job_refit(seg: "GridSegmenter", img_path: str, layout: dict, kw: dict):
    """共识校正 pass 的单页重扫（Pass 2a/2a2/2a3 共用）；择优在父进程。"""
    image = imread(img_path)
    if image is None:
        return None
    return seg.segment_page(image, layout, **kw)


def _job_repitch(seg: "GridSegmenter", img_path: str, layout: dict,
                 res: dict, used_h: float, consensus_h: float,
                 col_p=None, ins_p=None):
    """Pass 2a-bis 单页：在重切后的网格上二次量页距，够硬且与所用先验
    差 >0.5px 就再重切一轮。Pass 1 自由拟合失败的页量不出页距，第一轮
    只能用书距——vol01/25 实测 Pass1 量不出 → 用书距 115.2，而终网格上
    实测 113.9（-1.1%），差值在列中部累积 ~25px，格界切到邻字头上
    （用户朱批 grid_shift 8 例的根因）。返回 (重切结果, 页距) 或 None。"""
    image = imread(img_path)
    if image is None:
        return None
    gray = image if image.ndim == 2 \
        else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    sh = res.get("grid", {}).get("shear", 0.0) or 0.0
    ps = measure_page_pitch(deshear(gray, sh) if sh else gray, res)
    if os.environ.get("GUJI_REPITCH_DBG"):
        med0 = float(np.median(ps)) if ps else None
        print(f"[repitch] {Path(img_path).stem}: n={len(ps)} "
              f"med={None if med0 is None else round(med0, 2)} used={round(used_h, 2)}",
              flush=True)
    if len(ps) < PAGE_PITCH_MIN_COLS:
        return None
    med = float(np.median(ps))
    mad = float(np.median(np.abs(np.asarray(ps) - med)))
    if mad > PAGE_PITCH_MAD \
            or abs(med - consensus_h) > PAGE_PITCH_DEV * consensus_h \
            or abs(med - used_h) <= 0.5:
        return None
    redone = seg.segment_page(image, layout, cell_h_prior=med,
                              period_prior=col_p, inset_prior=ins_p,
                              shear_override=sh)
    return (redone, med)


def _job_phase(seg: "GridSegmenter", img_path: str, layout: dict, res: dict,
               consensus_h: float, col_p, ins_p):
    """Pass 2b 单页：骑线评分 → 全周期相位自扫 → 择优重切。
    判据（骑线比对比）只依赖本页，可整段搬进工作进程。"""
    image = imread(img_path)
    if image is None:
        return None
    cur = straddle_score(image, res)
    if cur <= STRADDLE_OK:
        return None
    y_best, sc_best = sweep_row_phase(image, res, consensus_h)
    if sc_best >= cur - STRADDLE_GAIN:
        return None
    redone = seg.segment_page(
        image, layout, cell_h_prior=consensus_h, row_phase_abs=y_best,
        period_prior=col_p, inset_prior=ins_p,
        shear_override=res["grid"].get("shear", 0.0))
    if straddle_score(image, redone) < cur - STRADDLE_GAIN:
        return redone
    return None


class GridSegmenter:
    """刻本网格切分器：phase2 layout + 页面图 → char_grid JSON。"""

    def __init__(self, chars_per_line: int, n_cols: int | None = None,
                 empty_ink_ratio: float = EMPTY_INK_RATIO,
                 search_ratio: float = SEARCH_RATIO):
        """n_cols 给定时启用列网格拟合（每半页列数，profile.lines_per_page），
        不再依赖 Phase 2 的列检测结果；None 时沿用 layout 的列。"""
        self.params = GridParams(chars_per_line, empty_ink_ratio, search_ratio)
        self.n_cols = n_cols

    # ── 纯函数核心 ────────────────────────────────────────

    def segment_page(self, image: np.ndarray, layout: dict,
                     grid_override: dict | None = None,
                     cell_h_prior: float | None = None,
                     row_phase_abs: float | None = None,
                     shear_override: float | None = None,
                     period_prior: float | None = None,
                     inset_prior: tuple[float, float] | None = None) -> dict:
        """grid_override 给定时跳过本页拟合，用书级共享网格参数
        （period/col_phase_rel/inset_l/inset_r/cell_h/row_phase_rel，
        相位以本页 inner_frame 为基准换算）——弱信号页专用。

        cell_h_prior 给定时只固定行格高（书级共识），相位仍按本页投影
        重搜——格高锁错（谐波/稀疏页）的页专用：这类页列网格正常，
        相位也是本页自身的，不该跟随书级中位。

        row_phase_abs 给定时行相位钉死为该值（全图 y 坐标的网格首线），
        供骑线重扫（Pass 2c）择优后回填——注意**不能**跟随书级中位相位：
        实测相位相对版框全书并不一致（版框检测基准页间漂移），
        对齐良好的页之间相位标准差高达 0.45 格。"""
        if image.ndim == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        h, w = image.shape[:2]
        n = self.params.chars_per_line

        # 先把斜着走的界行摆正，再谈列在哪：列框是竖直矩形，界行斜着走
        # 一页要漂 20~30px（周期才 180px），不摆正就只能二选一——框裹进
        # 界行，或让出漂移量把字裁窄。之后的一切坐标都在**去错切帧**里，
        # 通过 grid.shear 传给下游（chars 会做同样的变换再裁图块）。
        shear = shear_override if shear_override is not None \
            else estimate_shear(image)
        if shear:
            image = deshear(image, shear)

        borders = layout.get("borders", {})
        inner = borders.get("inner_frame", {})
        col_top = inner.get("top", {}).get("intercept", 0)
        col_bottom = inner.get("bottom", {}).get("intercept", h)
        # 边框竖线取**中高度**的 x：去错切以纵向中点为不动点，中高度的 x
        # 不受变换影响，而 intercept（y=0 处的 x）会被整条线的斜率带偏。
        frame_left = (inner.get("left", {}).get("intercept", 0)
                      + inner.get("left", {}).get("slope", 0.0) * h / 2)

        grid_meta: dict = {"shear": round(float(shear), 5)}
        if self.n_cols:
            # 列网格拟合：列宽/列距与行网格同为刻本刚性先验，
            # 页级拟合一个 (相位, 列距)，替代 Phase 2 的自由列检测
            # （自由检测会劈裂/粘连列，切残的字残形趋同致跨字污染）。
            vproj, rule_xs = page_column_projection(image,
                                                    return_rule_xs=True)
            page_ink = float(vproj.sum())
            if grid_override:
                # 书级共享网格（刻本整书同版式）：弱信号页（空白余纸、
                # 稀疏职名页）自身拟合不可靠，跟随书级中位参数，
                # 相位以本页边框为基准换算。
                period = grid_override["period"]
                cx0 = frame_left + grid_override["col_phase_rel"]
                inset_l = grid_override["inset_l"]
                inset_r = grid_override["inset_r"]
            else:
                cx0, period = fit_page_grid([vproj], self.n_cols,
                                            full_widths=[image.shape[0]])
                if period_prior:
                    # 列距是**书级刚性常量**（实测 5~95 分位 174~186px），
                    # 一页不可能比别页窄 15%。拟歪的页只需换回共识列距，
                    # 相位随后由界行吸附重新钉。
                    period = float(period_prior)
                inset_l, inset_r = measure_insets(vproj, cx0, period,
                                                  self.n_cols)
            # 列梳子的起点自由度只有 W - 跨度 这么多——列数与列距都是刚性
            # 先验，梳子整体必须落在页面内。原先相位由 fit_page_grid 按
            # **文字带的 content_range** 锚定，而 content_range 会把长度不足
            # 的游程当噪声跳过：卷尾页左侧整片**空列**（有界行、无字）正好
            # 是这种情况，于是梳子从版面中间起步——实测 vol02/38 起点落在
            # x=981（图宽 1714），末 5 列全部出图；vol01/164 偏右 1.1 个列距，
            # 把最左边那列真有字的列排除在外。
            n_cols = self.n_cols
            narrow = period * n_cols > w + period * NARROW_TOL
            if narrow:
                # 页面装不下 n_cols 列 —— 实测这类页被上游裁掉了一整列：
                # 图宽 1460~1530（正常 1696，差一个列距），且**图上真的只有
                # 8 条文字带**（正常页 9 条）。既然那一列在图上就不存在，
                # 就按装得下的列数切；硬凑 n_cols 会把 8 列文字摊到 9 个框
                # 上，全部错位。真正该修的是上游裁切，这里只如实反映 + 标记。
                n_cols = max(1, int((w + period * NARROW_TOL) // period))
            span = period * n_cols
            cx0 = float((w - span) / 2) if span > w \
                else float(min(max(cx0, 0.0), w - span))
            # 界行是列边界的直接证据（摆正之后才看得见），拿它把相位钉死。
            # 放在夹逼之后：夹逼只管"别跑出页面"（误差可达几个列距），
            # 界行吸附管一个列距以内的精调，两者互补。
            cx0, period, inset_l, inset_r = snap_columns_to_rules(
                image, vproj, cx0, period, n_cols, inset_l, inset_r)
            if inset_prior:
                # 文字带在列格内的位置是**书级刚性常量**（整版先划栏格再上字），
                # 和格高、列距同理。逐页量出来的内缩在稀疏页上会塌到 0~6px，
                # 列框于是贴着界行走、把界行圈进去——实测内缩塌掉的 69 页
                # rule_in_col 均值 0.083，内缩正常的页只有 0.006，差 14 倍。
                # 放在界行吸附**之后**：吸附会按新相位重量一遍内缩，早设会被覆盖。
                if not (inset_prior[0] * INSET_TOL <= inset_l
                        <= inset_prior[0] * INSET_TOL_HI):
                    inset_l = float(inset_prior[0])
                if not (inset_prior[1] * INSET_TOL <= inset_r
                        <= inset_prior[1] * INSET_TOL_HI):
                    inset_r = float(inset_prior[1])
            # left_x/right_x 是**文字带**（正常居中字的范围，网格拟合用）；
            # cell_left_x/cell_right_x 是**图块裁切边**（贴着实测界行内缘，
            # 量不到界行则退回文字带）。两者都要给下游：职名列的「臣」写在
            # 文字带之外的留白里，按文字带裁会被切掉；见 cell_bounds_from_rules。
            cell_bounds, cell_bands = cell_bounds_from_rules(
                image, cx0, period, n_cols, inset_l, inset_r)
            columns_info = []
            for k in range(n_cols):
                info = {"index": n_cols - k,   # 从右到左编号，最右列=1
                        "left_x": cx0 + period * k + inset_l,
                        "right_x": cx0 + period * (k + 1) - inset_r,
                        "cell_left_x": cell_bounds[k][0],
                        "cell_right_x": cell_bounds[k][1]}
                if cell_bands[k] is not None:
                    # 弯的边界：额外给逐带裁切边，图块裁剪按带掩蔽
                    info["cell_bands"] = cell_bands[k]
                columns_info.append(info)
            # 列拟合质量：界行竖线落入列格内部的比例。拟合正确时
            # 界行全在列格之间的缝里；错位半周期则大量进入列内——
            # 这正是下游"图块裹线被隔离"的直接前因。
            in_col = total_rule = 0
            for c in columns_info:
                lo, hi = int(c["left_x"]) + 3, int(c["right_x"]) - 3
                if hi > lo:
                    in_col += int(rule_xs[lo:hi].sum())
            total_rule = max(1, int(rule_xs.sum()))
            grid_meta = {"shear": grid_meta["shear"],
                         # 页面装不下 n_cols 列 → 上游裁切少了一列，
                         # 这里只标记不硬凑（硬凑会把 8 列文字摊到 9 个框上）
                         "narrow_page": bool(narrow),
                         "n_cols_used": int(n_cols),
                         "page_ink": page_ink, "period": float(period),
                         "col_phase_rel": float(cx0 - frame_left),
                         "inset_l": float(inset_l),
                         "inset_r": float(inset_r),
                         "rule_in_col": round(in_col / total_rule, 4)}
        else:
            columns_info = layout.get("columns", {}).get("columns", []) \
                or borders.get("columns", [])

        # 刻本文字列宽度一致：过滤版心/界行缝等窄列
        widths = [c["right_x"] - c["left_x"] for c in columns_info]
        median_w = float(np.median(widths)) if widths else 0.0

        # 纵向外扩一格：inner_frame 检测偏差可接近一个字高，外扩不足会
        # 裁掉首/末字；网格真实范围由投影内容决定（content_range 会剔除
        # 外扩带进来的边框线短游程）。
        pad = int((col_bottom - col_top) / n) if col_bottom > col_top else 0
        y1 = max(0, int(col_top) - pad)
        y2 = min(h, int(col_bottom) + pad)

        # 第一遍：收集文字列裁切与投影
        text_cols: list[tuple[dict, np.ndarray, np.ndarray]] = []
        result_columns = []
        for col in columns_info:
            left_x, right_x = float(col["left_x"]), float(col["right_x"])
            col_w = right_x - left_x
            col_result = {"index": col["index"], "left_x": left_x,
                          "right_x": right_x, "ocr_text": "", "cells": []}
            if col.get("cell_left_x") is not None:
                col_result["cell_left_x"] = float(col["cell_left_x"])
                col_result["cell_right_x"] = float(col["cell_right_x"])
                if col.get("cell_bands") is not None:
                    col_result["cell_bands"] = col["cell_bands"]
            result_columns.append(col_result)
            x1 = max(0, int(left_x) + 2)
            x2 = min(w, int(right_x) - 2)
            if col_w < median_w * MIN_COL_WIDTH_RATIO or x2 <= x1 or y2 <= y1:
                col_result["skipped"] = "non_text_column"
                continue
            crop = image[y1:y2, x1:x2]
            text_cols.append((col_result, crop, column_projection(crop)))

        # 刚性网格模型：刻本整版先划栏格再上字，**格高固定、跨列统一**；
        # 列首/列尾空格占格位但无墨（判空处理），网格锚定栏格周期证据
        # （页级聚合投影），绝不按单列内容范围锚定——抬头空格列会错一格。
        # 每列仅允许相位 ±0.12 格微调（板歪/扫描形变），格高不变。
        if text_cols:
            if row_phase_abs is not None:
                cell_h = cell_h_prior or (col_bottom - col_top) / n
                page_phase = float(row_phase_abs) - y1
            elif grid_override:
                cell_h = grid_override["cell_h"]
                # row_phase_rel 以 frame_top 为基准 → 换算到 crop 坐标
                page_phase = float(col_top) + grid_override["row_phase_rel"] - y1
            else:
                # 版框行锚定：在去错切帧上量上下框线，换算到裁剪窗坐标。
                # 框线磨没检不出时的兜底：上框用裁剪顶 0（s3 的上边就是按
                # 框线裁的，构造性事实）；下框用**墨底**而非页底 H——下框
                # 磨损时 s3 内线搜索会在框上方停下、页底留大段空白
                # （vol01/22 实测 300px，H 兜底差 13.4% 被跨度门拒），而
                # 框碎渣 + 末行字仍让墨迹恰好断在框位（实测差 +1.6%）。
                # 跨度门控仍在 fit 里把关，框高与 n 格不合的特殊页不锚。
                ft, fb = measure_row_frames(image)
                if ft is None:
                    ft = 0
                if fb is None:
                    g2 = image if image.ndim == 2 \
                        else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                    ri = (g2 < BINARY_THRESHOLD).sum(axis=1) \
                        / max(1, g2.shape[1])
                    nz = np.nonzero(ri >= 0.05)[0]
                    fb = int(nz[-1]) + 6 if nz.size else image.shape[0]
                page_phase, cell_h = fit_page_grid(
                    [p for _, _, p in text_cols], n,
                    full_widths=[crop.shape[1] for _, crop, _ in text_cols],
                    cell_h_fixed=cell_h_prior,
                    frame_top=None if ft is None else float(ft - y1),
                    frame_bottom=None if fb is None else float(fb - y1))
            grid_meta.update({"cell_h": float(cell_h),
                              "row_phase_rel": float(y1 + page_phase - col_top)})
            for col_result, crop, proj in text_cols:
                # 先判列型，再分别切分。原先是「先试弹性切分、证据不足
                # 退回刚性」的隐式回退：判错了下游无从发现，实测把 63 列
                # 目录页里的 26 列误当职名页拉开列切坏。
                layout = classify_column_layout(
                    crop, page_phase, cell_h, float(crop.shape[1]))
                col_result["layout"] = layout
                cells = None
                if layout == "elastic":
                    cells = cells_from_components(crop, cell_h, n, self.params)
                if cells is None:
                    if layout == "elastic":
                        col_result["layout"] = "rigid"   # 判弹性但切不出 → 据实回落
                    bounds = rigid_bounds(proj, page_phase, cell_h, n)
                    cells = cells_from_bounds(crop, bounds, self.params)
                else:
                    col_result["spread_col"] = True
                for c in cells:   # 局部 → 全图坐标
                    c["y_top"] += y1
                    c["y_bottom"] += y1
                col_result["cells"] = cells

        return {
            "image_size": {"width": w, "height": h},
            "chars_per_line": n,
            "segmenter": "grid_strict",
            "grid": grid_meta,
            "columns": result_columns,
        }

    # ── IO 壳 ────────────────────────────────────────────

    def run_book(self, book_out_dir: Path,
                 source_dir: Path | None = None,
                 name_filter: set[str] | None = None) -> dict:
        """遍历 phase2_layout/*_layout.json → 写 phase3_char_grid/。"""
        book_out_dir = Path(book_out_dir)
        layout_dir = book_out_dir / "phase2_layout"
        layout_files = sorted(layout_dir.glob("*_layout.json"))
        if name_filter is not None:
            layout_files = [f for f in layout_files
                            if f.stem.replace("_layout", "") in name_filter]
        if not layout_files:
            raise FileNotFoundError(f"未找到 layout JSON: {layout_dir}"
                                    "（请先运行 extract --steps layout）")

        src = Path(source_dir) if source_dir \
            else CharExtractor._resolve_source_dir(book_out_dir)
        out_dir = book_out_dir / "phase3_char_grid"
        out_dir.mkdir(parents=True, exist_ok=True)

        # ── Pass 1: 逐页独立拟合，收集网格参数与墨量 ──
        results: dict[str, dict] = {}
        pages: list[tuple[str, Path, dict]] = []
        skipped_pages: list[tuple[str, str]] = []
        pitches: list[float] = []
        page_pitches: dict[str, list[float]] = {}
        # 页型单独存：后续各 pass 用 segment_page 的返回值**整体替换**
        # results[stem]，替换时字段就丢了。逐个 pass 补「保留 page_type」
        # 已经踩过一次坑（Pass 2a3 保留到了一个 None），治本是把页型放在
        # results 之外，写盘前统一盖章。
        ptypes: dict[str, str] = {}
        loaded: list[tuple[str, Path, dict]] = []
        for lf in layout_files:
            stem = lf.stem.replace("_layout", "")
            img_path = CharExtractor._find_page_image(src, stem)
            if img_path is None:
                print(f"  跳过 {stem}: 找不到页面图")
                continue
            with open(lf, encoding="utf-8") as f:
                layout = json.load(f)
            loaded.append((stem, img_path, layout))
        # 页型闸门在 _job_pass1 里：封面/书签/空白页没有正文栏格，套网格
        # 是无中生有。实测不加闸门时 vol01/2（书签页）被切成 126 个块、
        # bad_seg 94%，vol01/158（近空白页）格高锁到 37.8px、切出 0 个字。
        # 判不准时默认走网格——误跳过一页正文是丢真数据，代价远大于
        # 多切一页废页（判据与余量见 page_type.classify_page_type）。
        outs = _pmap(_job_pass1,
                     [(self, str(p), lo) for _, p, lo in loaded])
        for (stem, img_path, layout), out in zip(loaded, outs):
            if out is None:
                continue
            if out["skip"]:
                results[stem] = {"image_size": {"width": out["width"],
                                                "height": out["height"]},
                                 "page_type": out["ptype"],
                                 "skipped": "page_type",
                                 "grid": {}, "columns": []}
                skipped_pages.append((stem, out["ptype"]))
                continue
            pages.append((stem, img_path, layout))   # 不缓存像素，弱页重读
            r = out["r"]
            r["page_type"] = out["ptype"]
            ptypes[stem] = out["ptype"]
            results[stem] = r
            pitches.extend(out["pitches"])
            page_pitches[stem] = out["pitches"]

        # ── Pass 2a0: 书级格高改由**实测字距**定 ──
        # 刻本一格一字，字距就是格高，可以直接量；而投影拟合的基准
        # (文字带高)/n_chars 系统性偏低——content_range 会把首末字探出去的
        # 那点笔画当短游程剔掉。实测低 1.0%(vol01) / 1.7%(vol02)，21 格累积
        # 漂 0.21 / 0.36 格，正好对上末格的字下出头 0.19~0.39 格。
        # 只在证据够、且与投影共识差得不离谱时采用（量错宁可不用）。
        pitch_h = None
        fit_hs = [r["grid"]["cell_h"] for r in results.values()
                  if r.get("grid", {}).get("cell_h")]
        if len(pitches) >= PITCH_MIN_COLS and fit_hs:
            cand = float(np.median(pitches))
            fit_med = float(np.median(fit_hs))
            if abs(cand - fit_med) <= PITCH_MAX_DEV * fit_med:
                pitch_h = cand
                print(f"  书级格高改由实测字距定：{fit_med:.2f} → {cand:.2f}px"
                      f"（{len(pitches)} 列，+{(cand / fit_med - 1) * 100:.1f}%）")

        # ── Pass 2a: 书级格高共识，校正格高锁错的页 ──
        # 刻本全书同版：格高是**物理刚性常量**，一页不可能是别页的 1/2。
        # 自由拟合的基准 base=(bottom-top)/n_chars 假设列满，稀疏页
        # （目录/职名）与密排页的谐波锁定都会落到 1/2、1/3 的伪解上，
        # ±8% 搜索窗跳不出来。这类页列网格与墨量都正常，现有"弱页"
        # 判据（低墨量 / rule_in_col 高）完全抓不到——必须用格高本身判。
        n_row_fix = 0
        # 后续各 pass 会**重跑** segment_page，必须把这里修好的行格高带上，
        # 否则行网格会被重新自由拟合、再次锁到谐波上。实测漏带这个参数时
        # 格高坏掉的页从 3 张涨到 17 张（页 168 整页格高 59px = 书级 113.7 的一半）。
        row_prior: dict[str, float] = {}
        # 同理，列距与内缩修好之后也必须带给后续 pass。这一条当初只给格高
        # 做了，列距漏了：实测 vol02/38 的自由拟合列距是 70.2px（书级 184.4），
        # Pass 2a2 修成 187.3，Pass 2a3 重跑时没带列距先验，又被自由拟合掉回
        # 70.2——而它的择优判据 rule_in_col 在这种退化几何下恒为 0（列框小到
        # 界行根本落不进去），门控一律放行。那一页 88 个图块全部 bad_seg。
        col_prior: dict[str, float] = {}
        ins_prior: dict[str, tuple[float, float]] = {}
        cell_hs = [r["grid"]["cell_h"] for r in results.values()
                   if r.get("grid", {}).get("cell_h")]
        if len(cell_hs) >= 5:
            consensus_h = pitch_h or float(np.median(cell_hs))

            # 逐页格高：每叶是独立版片，页间字距实测差 ±3%（见常量注释）。
            # 页自己的字距证据够硬（列数够、页内散布小、离共识不离谱）时
            # 用页距；否则回退书距。column_pitch 是先验不敏感的估计量
            # （环形集中度，实测先验偏 ±6% 只差 0.1%），页距可信。
            def _page_h(stem: str) -> float:
                ps = page_pitches.get(stem) or []
                if len(ps) < PAGE_PITCH_MIN_COLS or not pitch_h:
                    return consensus_h
                med = float(np.median(ps))
                mad = float(np.median(np.abs(np.asarray(ps) - med)))
                if mad > PAGE_PITCH_MAD \
                        or abs(med - consensus_h) > PAGE_PITCH_DEV * consensus_h:
                    return consensus_h
                return med

            if pitch_h:
                # 字距定的格高与每一页原来的拟合值都差 1~2%，不是只有
                # 「锁错的页」要改——全书都得按新格高重扫。
                off_grid = [s for s, r in results.items()
                            if r.get("grid", {}).get("cell_h")]
            else:
                off_grid = [s for s, r in results.items()
                            if r.get("grid", {}).get("cell_h")
                            and abs(r["grid"]["cell_h"] - consensus_h)
                            > CELL_H_TOL * consensus_h]
            off_set = set(off_grid)
            todo = [pg for pg in pages if pg[0] in off_set]
            # 格高偏离共识本身即失败证据（物理上不可能），无需择优
            # 门控——rule_in_col 度量的是列相位，对行格高无判别力，
            # 且这些页它已经是 0，任何门控都会一律拒绝校正。
            # 错切在 Pass 1 已估过且与格高无关，带上省掉 21 个候选
            # 角度的重估（实测 0.25s/页；本 pass 重扫全书，省 ~50s/册）
            outs = _pmap(_job_refit,
                         [(self, str(p), lo,
                           {"cell_h_prior": _page_h(s),
                            "shear_override":
                                results[s]["grid"].get("shear", 0.0)})
                          for s, p, lo in todo])
            n_page_h = 0
            for (stem, _, _), redone in zip(todo, outs):
                if redone is None:
                    continue
                results[stem] = redone
                row_prior[stem] = _page_h(stem)
                n_page_h += (abs(row_prior[stem] - consensus_h) > 0.2)
                n_row_fix += 1
            if n_page_h:
                print(f"  逐页格高：{n_page_h} 页用本页实测字距替代书距")

            if n_row_fix:
                print(f"  书级格高共识 {consensus_h:.1f}px，"
                      f"校正格高锁错页 {n_row_fix} 张")

        # ── Pass 2a2: 书级列距共识，校正列距拟错的页 ──
        # 与格高同理：列距也是物理刚性常量（同一版反复刷印）。实测全书
        # 5~95 分位只有 174~186px，拟歪的页会掉到 152~157——差 15%，
        # 界行必然被列框圈进去，且**换多少相位都救不回来**（周期错了，
        # 误差沿列号线性累积）。这类页墨量正常，旧的「弱信号页」判据
        # 抓不到，只能用列距本身判。
        n_period_fix = 0
        periods = [r["grid"]["period"] for r in results.values()
                   if r.get("grid", {}).get("period")]
        if self.n_cols and len(periods) >= 5:
            consensus_p = float(np.median(periods))
            off = [s2 for s2, r in results.items()
                   if r.get("grid", {}).get("period")
                   and (abs(r["grid"]["period"] - consensus_p)
                        > PERIOD_TOL * consensus_p
                        # 直接质量信号也能触发：参数全在容差内、页面却报告
                        # 竖线落在列框里（见 RULE_IN_COL_T 的注释）
                        or r["grid"].get("rule_in_col", 0) > RULE_IN_COL_T)]
            off_set = set(off)
            todo = [pg for pg in pages if pg[0] in off_set]
            # 这两个 pass 只改**列**参数，行网格不该重新拟合——
            # 原样带过去（Pass 2a 修过的用修后的值）
            outs = _pmap(_job_refit,
                         [(self, str(p), lo,
                           {"period_prior": consensus_p,
                            "cell_h_prior":
                                (row_prior.get(s)
                                 or results[s]["grid"].get("cell_h")),
                            "shear_override":
                                results[s]["grid"].get("shear", 0.0)})
                          for s, p, lo in todo])
            for (stem, _, _), redone in zip(todo, outs):
                if redone is None:
                    continue
                # 择优：列距偏离本身已是失败证据，但相位仍可能没救回来，
                # 所以仍按 rule_in_col 把关，绝不允许改差
                if redone["grid"].get("rule_in_col", 1.0) <= \
                        results[stem]["grid"].get("rule_in_col", 1.0):
                    results[stem] = redone
                    col_prior[stem] = consensus_p
                    n_period_fix += 1
            if n_period_fix:
                print(f"  书级列距共识 {consensus_p:.1f}px，"
                      f"校正列距拟错页 {n_period_fix} 张")

        # ── Pass 2a3: 书级内缩共识，校正内缩塌掉的页 ──
        # 与格高、列距同理：文字带在列格内的位置是物理刚性常量（整版先划
        # 栏格再上字）。但内缩是**逐页从投影量**出来的，稀疏页（目录/职名）
        # 的列格切片里内容范围量不准，会塌到 0~6px——列框于是贴着界行走。
        # 实测全书 inset_l 中位 32.5px，却有 69 页塌到 <15px，那些页
        # rule_in_col 均值 0.083、内缩正常的页只有 0.006，差 14 倍。
        #
        # **两个方向都要管。** 涨上去的那一侧危害相反且更隐蔽：文字带被人为
        # 收窄，字的偏旁被裁掉，而 rule_in_col 一路是 0——以「界行有没有进框」
        # 为判据的门控完全发现不了。实测 vol02 有 14 页 inset_l 超共识 25%，
        # 那些页的图块缺掉整个偏旁（「但」裁成「且」、「說」丢了言字旁）。
        n_inset_fix = 0
        if self.n_cols:
            ils = [r["grid"]["inset_l"] for r in results.values()
                   if r.get("grid", {}).get("inset_l") is not None]
            irs = [r["grid"]["inset_r"] for r in results.values()
                   if r.get("grid", {}).get("inset_r") is not None]
            if len(ils) >= 5:
                prior = (float(np.median(ils)), float(np.median(irs)))
                off = [s2 for s2, r in results.items()
                       if r.get("grid", {}).get("period")
                       and not (prior[0] * INSET_TOL <= r["grid"]["inset_l"]
                                <= prior[0] * INSET_TOL_HI
                                and prior[1] * INSET_TOL <= r["grid"]["inset_r"]
                                <= prior[1] * INSET_TOL_HI)]
                off_set = set(off)
                todo = [pg for pg in pages if pg[0] in off_set]
                # 这两个 pass 只改**列**参数，行网格不该重新拟合——
                # 原样带过去（Pass 2a 修过的用修后的值）
                outs = _pmap(_job_refit,
                             [(self, str(p), lo,
                               {"inset_prior": prior,
                                "period_prior": col_prior.get(s),
                                "cell_h_prior":
                                    (row_prior.get(s)
                                     or results[s]["grid"].get("cell_h")),
                                "shear_override":
                                    results[s]["grid"].get("shear", 0.0)})
                              for s, p, lo in todo])
                for (stem, _, _), redone in zip(todo, outs):
                    if redone is None:
                        continue
                    # 择优：内缩塌掉本身即失败证据，但仍按 rule_in_col 把关
                    if redone["grid"].get("rule_in_col", 1.0) <= \
                            results[stem]["grid"].get("rule_in_col", 1.0):
                        results[stem] = redone
                        ins_prior[stem] = prior
                        n_inset_fix += 1
                if n_inset_fix:
                    print(f"  书级内缩共识 ({prior[0]:.0f},{prior[1]:.0f})px，"
                          f"校正内缩塌掉页 {n_inset_fix} 张")

        # ── Pass 2a-bis: 二次页距（放在 2a2/2a3 之后）──
        # Pass 1 拟合失败的页量不出页距，Pass 2a 只能给书距；且必须等
        # 列距/内缩修完才量——p25 实测在 2a 后立刻量只剩 4 列（内缩塌着，
        # 列框坏），修完列后 8 列齐（113.9 vs 书距 115.2）。补切带上
        # 列距/内缩先验，别把 2a2/2a3 修好的列又自由拟合掉。
        if cell_hs and len(cell_hs) >= 5 and pitch_h:
            todo_bis = [pg for pg in pages
                        if results[pg[0]].get("grid", {}).get("cell_h")]
            outs2 = _pmap(_job_repitch,
                          [(self, str(p), lo, results[s],
                            row_prior.get(s, consensus_h), consensus_h,
                            col_prior.get(s), ins_prior.get(s))
                           for s, p, lo in todo_bis])
            n_re = 0
            for (stem, _, _), r2 in zip(todo_bis, outs2):
                if r2 is None:
                    continue
                redone, med = r2
                results[stem] = redone
                row_prior[stem] = med
                n_re += 1
            if n_re:
                print(f"  二次页距：{n_re} 页补切: "
                      f"{sorted(s for (s, _, _), r in zip(todo_bis, outs2) if r)}")

        # ── Pass 2b: 行相位骑线重扫 ──
        # 直接质量信号：骑线比（straddle_score）。稀疏页（职名/目录）
        # 谷-峰代价欠定导致相位错拟半格，字被上下腰斩——batch2 人工
        # 反馈 31 例 truncated 全部源于此。相位不能跟随书级中位
        # （相对版框不一致，见 sweep_row_phase 注），本页全周期自扫，
        # 骑线比至少改善 STRADDLE_GAIN 才接受。
        n_phase_fix = 0
        if cell_hs and len(cell_hs) >= 5:
            todo = [pg for pg in pages
                    if results[pg[0]].get("grid", {}).get("cell_h")]
            outs = _pmap(_job_phase,
                         [(self, str(p), lo, results[s],
                           row_prior.get(s, consensus_h),
                           col_prior.get(s), ins_prior.get(s))
                          for s, p, lo in todo])
            for (stem, _, _), redone in zip(todo, outs):
                if redone is not None:
                    results[stem] = redone
                    n_phase_fix += 1
            if n_phase_fix:
                print(f"  行相位骑线重扫修正 {n_phase_fix} 张")

        # ── Pass 2c: 书级共享网格校正弱信号页 ──
        # 刻本整书同版式：列距/字高/相位（相对边框）全书一致。
        # 空白余纸页、稀疏职名页自身拟合不可靠（相位骑到界行/乱套），
        # 用**强信号页的中位参数**重建其网格。
        n_weak = 0
        if self.n_cols and len(pages) >= 5:
            inks = {s: r["grid"].get("page_ink", 0.0)
                    for s, r in results.items() if r.get("grid")}
            median_ink = float(np.median(list(inks.values()))) if inks else 0.0
            strong = [s for s, v in inks.items() if v >= 0.5 * median_ink]
            if strong and median_ink > 0:
                keys = ("period", "col_phase_rel", "inset_l",
                        "inset_r", "cell_h", "row_phase_rel")
                override = {
                    key: float(np.median(
                        [results[s]["grid"][key] for s in strong
                         if key in results[s]["grid"]]))
                    for key in keys}

                # 失败判据（直接质量信号，不用参数偏离——相位的边框基准
                # 页间天然抖动，偏离判据会把好页错判失败并套上不准的中位）:
                # 1) 墨量过低: 空白余纸页, 纯界行上拟合乱套;
                # 2) rule_in_col 高: 界行竖线大量落入列格内部 = 列相位错.
                weak = {s for s, v in inks.items()
                        if v < 0.3 * median_ink
                        or results[s]["grid"].get("rule_in_col", 0) > 0.2}
                for stem, img_path, layout in pages:
                    if stem in weak:
                        image = imread(str(img_path))
                        if image is None:
                            continue
                        redone = self.segment_page(
                            image, layout, grid_override=override,
                            shear_override=results[stem]["grid"].get(
                                "shear", 0.0))
                        # 择优：校正绝不允许把页面改差（书级相位的边框
                        # 基准对个别页也可能不准）
                        old_q = results[stem]["grid"].get("rule_in_col", 1.0)
                        new_q = redone["grid"].get("rule_in_col", 1.0)
                        # rule_in_col 只度量列相位；行相位跟随书级中位曾把
                        # 多页字腰斩（相对版框不一致）——骑线比不得恶化
                        if new_q <= old_q and (
                                straddle_score(image, redone)
                                <= straddle_score(image, results[stem]) + 0.05):
                            results[stem] = redone
                            n_weak += 1
                if n_weak:
                    print(f"  书级网格校正弱信号页 {n_weak} 张")

        # ── 页型盖章 + 细化：先把 Pass 1 的页型统一写回（后续 pass 的整体
        # 替换会丢字段），再用产物特征把 body 里的职名页分出来。
        # （只改标签不改切分；toc 不判，见 refine_page_type 的注释）
        n_refined = 0
        for stem, _, _ in pages:
            results[stem]["page_type"] = ptypes.get(stem, "body")
            new_type = refine_page_type(results[stem])
            if new_type != results[stem]["page_type"]:
                results[stem]["page_type"] = new_type
                n_refined += 1
        if n_refined:
            print(f"  页型细化：{n_refined} 页由 body 改判 roster")

        n_pages = n_chars = n_empty = 0
        for stem, _, _ in pages:
            result = results[stem]
            with open(out_dir / f"{stem}_char_grid.json", "w",
                      encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            pc = sum(1 for c in result["columns"] for x in c["cells"]
                     if x["type"] == "char")
            pe = sum(1 for c in result["columns"] for x in c["cells"]
                     if x["type"] == "empty")
            n_chars += pc
            n_empty += pe
            n_pages += 1

        # 跳过的页也要落盘：下游据此知道"这一页有意不切"，而不是产物缺失
        for stem, ptype in skipped_pages:
            with open(out_dir / f"{stem}_char_grid.json", "w",
                      encoding="utf-8") as f:
                json.dump(results[stem], f, ensure_ascii=False, indent=2)
        if skipped_pages:
            from collections import Counter as _C
            kinds = dict(_C(t for _, t in skipped_pages))
            print(f"  页型闸门跳过 {len(skipped_pages)} 页: {kinds}")

        meta = {"segmenter": "grid_strict",
                "params": {"chars_per_line": self.params.chars_per_line,
                           "empty_ink_ratio": self.params.empty_ink_ratio,
                           "search_ratio": self.params.search_ratio},
                "stats": {"pages": n_pages, "chars": n_chars,
                          "empty": n_empty, "weak_pages": n_weak,
                          "row_fixed_pages": n_row_fix,
                          "phase_fixed_pages": n_phase_fix,
                          "inset_fixed_pages": n_inset_fix,
                          "skipped_pages": len(skipped_pages),
                          "skipped_kinds": dict(__import__("collections")
                                                .Counter(t for _, t
                                                         in skipped_pages))}}
        with open(out_dir / "grid_meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return meta
