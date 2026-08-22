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
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ..utils.image_io import imread
from .extractor import CharExtractor
from .page_type import classify_page_type

BINARY_THRESHOLD = 128
EMPTY_INK_RATIO = 0.02     # 格内墨迹覆盖率低于此 → empty
MIN_COL_WIDTH_RATIO = 0.5  # 列宽低于中位列宽的此比例 → 非文字列（版心/界行缝），跳过
SEARCH_RATIO = 0.3         # 逐线微调搜索半径（× 格高）
CELL_H_TOL = 0.05          # 页格高偏离全书共识超此比例 → 判定锁错，强制重拟
                           # （修复后自然抖动 σ≈2.2%，0.10 曾放过 0.91 的漏网页）
PERIOD_TOL = 0.04          # 页列距偏离全书共识超此比例 → 判定拟错，改用共识值
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
CELL_FENCE_LINE_FRAC = 0.45  # 带内竖直开运算的长度比例。带高约 1/6 页高（≈3 个
                           # 字高），0.45 ≈ 1.4 个字高——字的竖笔够不着
CELL_RULE_TOL = 0.25       # 界行中心离列格边界不超过此比例（× 列距）也算证据
NARROW_TOL = 0.25          # 梳子跨度超出页宽此比例（× 列距）→ 标 narrow_page
                           # 实测被裁窄的页只有 7.5 个列距的宽度，差整整一列
INSET_TOL = 0.5            # 页内缩低于书级共识此比例 → 判为量塌了，改用共识值
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


def _vline_cov_banded(binary: np.ndarray,
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
    h = binary.shape[0]
    out = np.zeros(binary.shape[1], dtype=float)
    for i in range(n_bands):
        a, b = h * i // n_bands, h * (i + 1) // n_bands
        if b - a < 3:
            continue
        k = cv2.getStructuringElement(
            cv2.MORPH_RECT, (1, max(3, int((b - a) * line_frac))))
        seg = binary[a:b]
        out = np.maximum(out,
                         cv2.dilate(cv2.erode(seg, k), k).sum(axis=0) / (b - a))
    return out


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


def rule_segments(gray: np.ndarray) -> list[tuple[int, int]]:
    """页面上「竖直长线」的 x 区间（界行/版框竖线）。

    必须在**去错切帧**里调用——斜着走的界行覆盖率只有 0.1~0.2，
    根本过不了 RULE_COV_T。
    """
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    cov = _vline_cov((gray < BINARY_THRESHOLD).astype(np.uint8))
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
    d = np.diff(np.sort(centers))
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
    segs = rule_segments(gray)
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
    cov = _vline_cov_banded((gray < BINARY_THRESHOLD).astype(np.uint8))
    w = len(cov)
    centers = [(a + b) / 2 for a, b in rule_segments(gray)]
    tol = period * CELL_RULE_TOL
    # 文字带本身也先内缩一点：界行正好压在带边上时，这一点点就是全部的余量
    shrink = min(max(period - inset_l - inset_r, 0.0) * 0.03, 4.0)
    out: list[tuple[float, float]] = []
    for k in range(n_cols):
        bl, br = cx0 + period * k, cx0 + period * (k + 1)
        lo = cx0 + period * k + inset_l + shrink
        hi = cx0 + period * (k + 1) - inset_r - shrink
        x = int(round(lo))
        while x - 1 >= bl and x - 1 >= 0 and cov[x - 1] <= CELL_COV_STOP:
            x -= 1
        if (x - 1 >= 0 and cov[x - 1] > CELL_COV_STOP) \
                or any(abs(c - bl) <= tol for c in centers):
            lo = min(lo, max(bl, x + CELL_RULE_CLEARANCE))
        x = int(round(hi))
        while x + 1 <= br and x + 1 < w and cov[x + 1] <= CELL_COV_STOP:
            x += 1
        if (x + 1 < w and cov[x + 1] > CELL_COV_STOP) \
                or any(abs(c - br) <= tol for c in centers):
            hi = max(hi, min(br, x - CELL_RULE_CLEARANCE))
        if hi - lo < period * 0.2:            # 证据自相矛盾 → 退回文字带
            lo = cx0 + period * k + inset_l
            hi = cx0 + period * (k + 1) - inset_r
        out.append((float(lo), float(hi)))
    return out


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


def fit_page_grid(projs: list[np.ndarray], n_chars: int,
                  full_widths: list[float] | None = None,
                  cell_step: float = 0.5, phase_step: int = 2,
                  cell_h_fixed: float | None = None
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
    for cell_h in cell_hs:
        span = cell_h * n_chars
        # 相位范围：允许首格空/框偏差，网格可高于内容顶一格出头。
        # 格高固定时不再按 L-span 收窄上界——共识格高下整版可能略高于
        # 裁切后的页面（末格出界由 cells_from_bounds 裁掉）。
        p_lo = max(0.0, top - 1.2 * cell_h)
        p_hi = top + 1.2 * cell_h if cell_h_fixed \
            else min(top + 1.2 * cell_h, max(p_lo, L - span))
        for phase in np.arange(p_lo, p_hi + phase_step, phase_step):
            cost = _grid_cost(smooth, phase, cell_h, n_chars)
            if cost < best_cost:
                best_cost = cost
                best = (float(phase), float(cell_h))
    return best


def rigid_bounds(proj: np.ndarray, page_phase: float, cell_h: float,
                 n_chars: int, micro: float = 0.12,
                 phase_step: int = 1) -> list[float]:
    """单列刚性网格：格高固定，相位在页面相位 ±micro×格高 内微调。

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
    return [best_phase + cell_h * k for k in range(n_chars + 1)]


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

    触发条件（证据不足返回 None 走刚性网格）：合并组件 ≥3、
    组件中心间距中至少 2 个 > 2.2 格、组件总数 ≤ 12、单个组件不超过
    8 格高。密排正文列组件会连成大段且间距小，绝不会误触发——这四条
    本身没变，变的只是"触发之后怎么切"。
    """
    col_bin = (col_gray < BINARY_THRESHOLD).astype(np.uint8)
    comps = _merged_components(col_bin, cell_h)
    if len(comps) < 3 or len(comps) > 12:
        return None
    # 碎屑（< 0.3 格高：版框残迹、贴边墨点）丢弃而非否决整列——
    # p108 职名列曾因列顶一条 0.09 格的框线残迹被一票否决。
    # 局限：拉开列里真正的"一"字也会被当碎屑丢掉（官衔中几乎不出现）。
    comps = [c for c in comps if (c[2] - c[1]) >= 0.3 * cell_h]
    if len(comps) < 3:
        return None
    centers = [c[0] for c in comps]
    gaps = np.diff(centers)
    if int((gaps > 2.2 * cell_h).sum()) < 2:
        return None
    heights = [(b - a) for _, a, b in comps]
    if not all(h <= 8.0 * cell_h for h in heights):
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
                if inset_l < inset_prior[0] * INSET_TOL:
                    inset_l = float(inset_prior[0])
                if inset_r < inset_prior[1] * INSET_TOL:
                    inset_r = float(inset_prior[1])
            # left_x/right_x 是**文字带**（正常居中字的范围，网格拟合用）；
            # cell_left_x/cell_right_x 是**图块裁切边**（贴着实测界行内缘，
            # 量不到界行则退回文字带）。两者都要给下游：职名列的「臣」写在
            # 文字带之外的留白里，按文字带裁会被切掉；见 cell_bounds_from_rules。
            cell_bounds = cell_bounds_from_rules(image, cx0, period, n_cols,
                                                 inset_l, inset_r)
            columns_info = [
                {"index": n_cols - k,          # 从右到左编号，最右列=1
                 "left_x": cx0 + period * k + inset_l,
                 "right_x": cx0 + period * (k + 1) - inset_r,
                 "cell_left_x": cell_bounds[k][0],
                 "cell_right_x": cell_bounds[k][1]}
                for k in range(n_cols)]
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
                page_phase, cell_h = fit_page_grid(
                    [p for _, _, p in text_cols], n,
                    full_widths=[crop.shape[1] for _, crop, _ in text_cols],
                    cell_h_fixed=cell_h_prior)
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
        for lf in layout_files:
            stem = lf.stem.replace("_layout", "")
            img_path = CharExtractor._find_page_image(src, stem)
            if img_path is None:
                print(f"  跳过 {stem}: 找不到页面图")
                continue
            image = imread(str(img_path))
            if image is None:
                continue
            with open(lf, encoding="utf-8") as f:
                layout = json.load(f)
            # 页型闸门：封面/书签/空白页没有正文栏格，套网格是无中生有。
            # 实测不加闸门时 vol01/2（书签页）被切成 126 个块、bad_seg 94%，
            # vol01/158（近空白页）格高锁到 37.8px、切出 0 个字。
            # 判不准时默认走网格——误跳过一页正文是丢真数据，代价远大于
            # 多切一页废页（判据与余量见 page_type.classify_page_type）。
            ptype, policy = classify_page_type(
                image if image.ndim == 2
                else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
            if policy == "skip":
                results[stem] = {"image_size": {"width": int(image.shape[1]),
                                                "height": int(image.shape[0])},
                                 "page_type": ptype, "skipped": "page_type",
                                 "grid": {}, "columns": []}
                skipped_pages.append((stem, ptype))
                continue
            pages.append((stem, img_path, layout))   # 不缓存像素，弱页重读
            r = self.segment_page(image, layout)
            r["page_type"] = ptype
            results[stem] = r

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
        cell_hs = [r["grid"]["cell_h"] for r in results.values()
                   if r.get("grid", {}).get("cell_h")]
        if len(cell_hs) >= 5:
            consensus_h = float(np.median(cell_hs))
            off_grid = [s for s, r in results.items()
                        if r.get("grid", {}).get("cell_h")
                        and abs(r["grid"]["cell_h"] - consensus_h)
                        > CELL_H_TOL * consensus_h]
            for stem, img_path, layout in pages:
                if stem not in off_grid:
                    continue
                image = imread(str(img_path))
                if image is None:
                    continue
                # 格高偏离共识本身即失败证据（物理上不可能），无需择优
                # 门控——rule_in_col 度量的是列相位，对行格高无判别力，
                # 且这些页它已经是 0，任何门控都会一律拒绝校正。
                results[stem] = self.segment_page(
                    image, layout, cell_h_prior=consensus_h)
                row_prior[stem] = consensus_h
                n_row_fix += 1
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
                   and abs(r["grid"]["period"] - consensus_p)
                   > PERIOD_TOL * consensus_p]
            for stem, img_path, layout in pages:
                if stem not in off:
                    continue
                image = imread(str(img_path))
                if image is None:
                    continue
                redone = self.segment_page(
                    image, layout, period_prior=consensus_p,
                    # 这两个 pass 只改**列**参数，行网格不该重新拟合——
                    # 原样带过去（Pass 2a 修过的用修后的值）
                    cell_h_prior=(row_prior.get(stem)
                                  or results[stem]["grid"].get("cell_h")),
                    shear_override=results[stem]["grid"].get("shear", 0.0))
                # 择优：列距偏离本身已是失败证据，但相位仍可能没救回来，
                # 所以仍按 rule_in_col 把关，绝不允许改差
                if redone["grid"].get("rule_in_col", 1.0) <= \
                        results[stem]["grid"].get("rule_in_col", 1.0):
                    results[stem] = redone
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
                       and (r["grid"]["inset_l"] < prior[0] * INSET_TOL
                            or r["grid"]["inset_r"] < prior[1] * INSET_TOL)]
                for stem, img_path, layout in pages:
                    if stem not in off:
                        continue
                    image = imread(str(img_path))
                    if image is None:
                        continue
                    redone = self.segment_page(
                        image, layout, inset_prior=prior,
                        # 这两个 pass 只改**列**参数，行网格不该重新拟合——
                    # 原样带过去（Pass 2a 修过的用修后的值）
                    cell_h_prior=(row_prior.get(stem)
                                  or results[stem]["grid"].get("cell_h")),
                        shear_override=results[stem]["grid"].get("shear", 0.0))
                    # 择优：内缩塌掉本身即失败证据，但仍按 rule_in_col 把关
                    if redone["grid"].get("rule_in_col", 1.0) <= \
                            results[stem]["grid"].get("rule_in_col", 1.0):
                        redone["page_type"] = results[stem].get("page_type")
                        results[stem] = redone
                        n_inset_fix += 1
                if n_inset_fix:
                    print(f"  书级内缩共识 ({prior[0]:.0f},{prior[1]:.0f})px，"
                          f"校正内缩塌掉页 {n_inset_fix} 张")

        # ── Pass 2b: 行相位骑线重扫 ──
        # 直接质量信号：骑线比（straddle_score）。稀疏页（职名/目录）
        # 谷-峰代价欠定导致相位错拟半格，字被上下腰斩——batch2 人工
        # 反馈 31 例 truncated 全部源于此。相位不能跟随书级中位
        # （相对版框不一致，见 sweep_row_phase 注），本页全周期自扫，
        # 骑线比至少改善 STRADDLE_GAIN 才接受。
        n_phase_fix = 0
        if cell_hs and len(cell_hs) >= 5:
            for stem, img_path, layout in pages:
                res = results[stem]
                if not res.get("grid", {}).get("cell_h"):
                    continue
                image = imread(str(img_path))
                if image is None:
                    continue
                cur = straddle_score(image, res)
                if cur <= STRADDLE_OK:
                    continue
                y_best, sc_best = sweep_row_phase(image, res, consensus_h)
                if sc_best < cur - STRADDLE_GAIN:
                    redone = self.segment_page(
                        image, layout, cell_h_prior=consensus_h,
                        row_phase_abs=y_best,
                        shear_override=res["grid"].get("shear", 0.0))
                    if straddle_score(image, redone) < cur - STRADDLE_GAIN:
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
