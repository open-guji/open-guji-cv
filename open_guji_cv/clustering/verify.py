"""M3 两两配准验证 —— 保守聚类的核心判据。

两套判据（.claude/doc/g3g4_error_analysis.md 的实测结论）：

**coverage（默认，2026-08-23 起）**：有界位移覆盖率 + 局部窗口残差。
同一个字在不同字位是**不同的手工雕刻**，天然带 2~3px 局部笔画位移——
刚性重叠 F1 对此的上限就在 0.67~0.75（扩大配准搜索只救回 1.2%，几何
变换不是原因）。覆盖率把「B 的墨在 A 的 r=2 邻域内」都算命中，吸收
刻工位移；12×12 窗口残差当形近护栏（一笔之差在窗口里是集中的，刻工
噪声是弥散的）。基准（char-clustering 三分片）：purity 全部 ≥ 基线
（vol02/human 达 1.0），碎片率 2.86→2.80 / 3.71→3.58 / 3.21→2.92。
已知漏网家族（更宽松操作点下）：整部件替换型形近字（諭/論、太/大、
間/問、曾/會…），密度自适应半径 / 骨架失配 / 部件失配否决均实测无效，
出路在 OCR 候选 + 上下文（18.4 结论），几何层用回归难例对钉死操作点。

**overlap（旧默认，保留作对照）**：配准 F1（2·|A∩B| / (|A|+|B|)）三档：
- same:   f1 ≥ theta_high 且局部差异块不超限
- unsure: theta_low ≤ f1 < theta_high，或整体相似但差异集中（曰/日防线）
- diff:   f1 < theta_low
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

import cv2
import numpy as np

THETA_HIGH = 0.80
THETA_LOW = 0.62
MAX_SHIFT = 3
SCALES = (0.95, 1.0, 1.05)
DIFF_BLOB_RATIO = 0.06

# coverage 判据的操作点：在 880 同字对 + 879 异字对 + 173 形近对上扫出，
# 并经三分片全量聚类验证 never-make-worse（g3g4_error_analysis.md §2）。
COV_HIGH = 0.992       # same 所需覆盖率
COV_LOW = 0.85         # unsure 下限（低于此 diff）
MISS_WMAX = 12         # 12×12 窗口内未覆盖墨的上限（像素）——形近护栏
MISS_WIN = 12

_KERNEL3 = np.ones((3, 3), dtype=np.uint8)
_KERNEL5 = np.ones((5, 5), dtype=np.uint8)   # r=2 覆盖邻域


@dataclass
class PairVerdict:
    verdict: str            # "same" | "unsure" | "diff"
    f1: float               # 最优对齐下的墨迹 F1
    dilated_f1: float       # 双方膨胀 1px 后的 F1（磨损容忍度参考）
    shift: tuple[int, int]  # 最优 (dx, dy)
    scale: float            # 最优缩放
    diff_blob_ratio: float  # 最大局部差异块面积 / 平均墨迹面积


def _rescale(binary: np.ndarray, scale: float) -> np.ndarray:
    """围绕图心等比缩放，输出尺寸不变（裁切/补零）。"""
    if scale == 1.0:
        return binary
    size = binary.shape[0]
    n = max(1, int(round(size * scale)))
    resized = cv2.resize(binary * 255, (n, n), interpolation=cv2.INTER_AREA)
    resized = (resized > 127).astype(np.uint8)
    out = np.zeros_like(binary)
    if n >= size:
        off = (n - size) // 2
        out[:, :] = resized[off:off + size, off:off + size]
    else:
        off = (size - n) // 2
        out[off:off + n, off:off + n] = resized
    return out


def _shifted_view(padded: np.ndarray, dx: int, dy: int, size: int,
                  max_shift: int) -> np.ndarray:
    """从 pad 过的图上取平移 (dx, dy) 后的 size×size 视图。"""
    return padded[max_shift + dy:max_shift + dy + size,
                  max_shift + dx:max_shift + dx + size]


def _f1(a: np.ndarray, b: np.ndarray, na: int, nb: int) -> float:
    if na == 0 or nb == 0:
        return 0.0
    inter = int(np.count_nonzero(a & b))
    return 2.0 * inter / (na + nb)


def _largest_diff_blob(a: np.ndarray, b_aligned: np.ndarray) -> int:
    """单侧差异（互相膨胀 1px 后仍不重叠的部分）的最大连通块面积。

    膨胀容忍 1px 配准/笔画粗细误差，剩下的才是"缺一笔/多一笔"式的真实差异。
    """
    a_d = cv2.dilate(a, _KERNEL3)
    b_d = cv2.dilate(b_aligned, _KERNEL3)
    diff = ((a & (1 - b_d)) | (b_aligned & (1 - a_d))).astype(np.uint8)
    if not diff.any():
        return 0
    n, _, stats, _ = cv2.connectedComponentsWithStats(diff, connectivity=8)
    return int(stats[1:, cv2.CC_STAT_AREA].max()) if n > 1 else 0


def verify_pair_cov(a: np.ndarray, b: np.ndarray,
                    max_shift: int = MAX_SHIFT,
                    scales: tuple[float, ...] = SCALES,
                    cov_high: float = COV_HIGH,
                    cov_low: float = COV_LOW,
                    miss_wmax: float = MISS_WMAX) -> PairVerdict:
    """coverage 判据：a, b 为 S×S uint8 {0,1} 归一二值图。

    f1 字段放覆盖率（供排序/报告），diff_blob_ratio 字段放窗口残差
    ——字段语义随判据走，报告里连着 params 读。
    """
    size = a.shape[0]
    na = int(np.count_nonzero(a))

    best_f1, best_shift, best_scale = 0.0, (0, 0), 1.0
    best_b: np.ndarray | None = None
    for scale in scales:
        b_s = _rescale(b, scale)
        nb = int(np.count_nonzero(b_s))
        padded = np.zeros((size + 2 * max_shift, size + 2 * max_shift), dtype=np.uint8)
        padded[max_shift:max_shift + size, max_shift:max_shift + size] = b_s
        for dy in range(-max_shift, max_shift + 1):
            for dx in range(-max_shift, max_shift + 1):
                view = _shifted_view(padded, dx, dy, size, max_shift)
                f1 = _f1(a, view, na, nb)
                if f1 > best_f1:
                    best_f1, best_shift, best_scale = f1, (dx, dy), scale
                    best_b = view.copy()
    if best_b is None:
        return PairVerdict("diff", 0.0, 0.0, (0, 0), 1.0, 0.0)

    b_cov = cv2.dilate(best_b, _KERNEL5)
    a_cov = cv2.dilate(a, _KERNEL5)
    miss_a = (a & (1 - b_cov)).astype(np.uint8)
    miss_b = (best_b & (1 - a_cov)).astype(np.uint8)
    na2 = max(1, int(a.sum()))
    nb2 = max(1, int(best_b.sum()))
    cov = 1.0 - (int(miss_a.sum()) + int(miss_b.sum())) / (na2 + nb2)
    k = (MISS_WIN, MISS_WIN)
    wmax = max(
        float(cv2.boxFilter(miss_a.astype(np.float32), -1, k, normalize=False).max()),
        float(cv2.boxFilter(miss_b.astype(np.float32), -1, k, normalize=False).max()))

    if cov >= cov_high and wmax <= miss_wmax:
        verdict = "same"
    elif cov >= cov_low:
        verdict = "unsure"
    else:
        verdict = "diff"
    return PairVerdict(verdict, float(cov), float(best_f1),
                       best_shift, best_scale, wmax)


# ---------------------------------------------------------------- elastic
# elastic 判据（2026-08-24 起默认）：coverage 的两处放宽方向反过来做——
# **距离容忍收紧成软的，位移容忍放宽成局部的**。
#
# coverage 的 r=2 硬膨胀对「整部件替换型形近字」不敏感（glyph_match_stack
# §4.1）：差一个偏旁的墨量占比小，膨胀把它抹平；而它给刻工位移的容忍是
# **全局刚性**的——同一个字在不同字位是不同的手工雕刻，位移是**逐部件
# 各走各的**，刚性对齐吃不下，只能靠把半径放大来硬凑，于是形近字跟着
# 沾光。两件事拧在一个半径里，调不开。
#
# elastic 把它们拆开：
#   1. 距离容忍改成高斯软权 w(d)=exp(-(d/tau)^2)，tau=1.5——2px 外仍算
#      命中但只算 0.17，形近字缺的那一笔不再白拿满分；
#   2. 位移容忍改成**分块弹性**：全局 (scale, dx, dy) 之上，每 16×16 块
#      再各自搜 ±1px。同字的局部刻痕位移每块自己找补回来；形近字缺的
#      部件挪到哪儿都还是缺，块内位移救不了。
#
# 靶子（glyph-match/triplets）：hard 排序正确率 0.079 → 0.684，control
# 1.000 不动、平均 margin 0.068 → 0.103（分离度还变宽了）。
ELASTIC_TAU = 1.5       # 高斯软覆盖的尺度（像素）
ELASTIC_BLOCK = 16      # 弹性块边长（64 归一图 = 4×4 块）
ELASTIC_LOCAL = 1       # 每块在全局位移之上的额外搜索半径（像素）

# elastic 的 same 闸，两个消费方各标各的——它们的**证据强度和错的代价
# 都不一样**：
#
# - **库匹配（GlyphMatcher/seeding）**：一条 same 边就直接继承库里的字，
#   没有共识机制兜底，错一次就是把错标写进库。硬约束是 eval_db_match 的
#   match_precision ≥ 0.999。闸沿用 coverage 的 0.992（校准后同一个数
#   放行同一批量级的对）。放到 0.988 实测会漏两条形近（朱←宋、匕←七，
#   两个都在 0.9917~0.9918），计门精度掉到 0.9982/0.9970，破门。
# - **聚类（ConservativeClusterer）**：合并要过多代表一致性与抽查，单条
#   边的误判有兜底；漏并只是多一个碎片，进审查队列。所以可以松一档。
#   char-clustering 三分片扫 0.980~0.992，0.988 是唯一 never-make-worse：
#     purity  0.99967/0.99967/0.98901 → 1.0/1.0/1.0（諭/論 脏簇也没了）
#     碎片率  2.99/3.45/3.00 → 2.97/3.38/3.04
#     难例对  40/80、34/74、14/65 全部持平
#   0.992 会把碎片率抬到 3.10/3.60/3.38、human 分片同字难例对 14→10；
#   0.985 起 vol02 purity 掉到 0.99934，破 purity 硬约束。
ELASTIC_COV_HIGH = 0.992          # 库匹配（逐对单证据）
ELASTIC_CLUSTER_COV_HIGH = 0.988  # 聚类（有共识兜底）

# elastic 原始分与 coverage 的数值分布不同（软权 + 局部位移），而 COV_HIGH /
# MATCH_SOLO_COV 这些闸是按 coverage 的分布标定的。这里用**单调分位映射**
# 把 elastic 原始分搬回 coverage 的刻度上：同一个分位对应同一个数值，
# 于是所有既有阈值的**操作点（放行比例）**原样保留，改变的只是**放行谁**
# ——这正是本次优化要改的东西。锚点由 scripts/calibrate_elastic.py 在
# char-clustering 两个大分片的 kNN 对群上拟合，重标方法见该脚本。
_CAL_RAW: tuple[float, ...] = (0.0, 0.3019, 0.6758, 0.7091, 0.729, 0.7452, 0.759, 0.7715, 0.7841, 0.7974, 0.8119, 0.8268, 0.8441, 0.8616, 0.8763, 0.8891, 0.8998, 0.91, 0.9198, 0.9307, 0.9356, 0.9413, 0.9483, 0.9529, 0.9581, 0.9657, 1.0)
_CAL_COV: tuple[float, ...] = (0.0, 0.306, 0.757, 0.8014, 0.8281, 0.8473, 0.8626, 0.8762, 0.8883, 0.8995, 0.9105, 0.9212, 0.932, 0.9422, 0.9513, 0.9592, 0.966, 0.9722, 0.9778, 0.9835, 0.9858, 0.9884, 0.9912, 0.9929, 0.9948, 0.9971, 1.0)
_CAL_WRAW: tuple[float, ...] = (0.0, 12.3657, 16.2269, 19.3623, 22.3354, 25.2338, 28.3445, 31.53, 34.6437, 37.4849, 39.9215, 42.1869, 44.4516, 46.7773, 49.1988, 51.7835, 54.7105, 58.1193, 62.707, 65.199, 68.1902, 72.6119, 75.6193, 79.8322, 87.6575, 95.2282, 104.9741, 109.4116, 129.7701, 194.6551)
_CAL_WMAX: tuple[float, ...] = (0.0, 6.0, 9.0, 12.0, 15.0, 17.0, 20.0, 23.0, 26.0, 29.0, 32.0, 35.0, 37.0, 40.0, 42.0, 45.0, 48.0, 52.0, 57.0, 60.0, 63.0, 68.0, 72.0, 77.0, 85.0, 93.0, 102.0, 109.0, 131.0, 196.5)


def _calibrate(x: float, src: tuple[float, ...], dst: tuple[float, ...]) -> float:
    """单调分段线性映射（锚点为空时恒等）。"""
    if not src:
        return x
    return float(np.interp(x, src, dst))


# 逐对精验里有两类**反复重算的纯函数结果**：
#   1. 位移网格（offsets/pick/radius）只依赖 (size, block, local, max_shift)，
#      是彻头彻尾的常量，却每次调用都重建；
#   2. 一张图块的权重场 / 分块排序 / 三档缩放，只依赖图块自己——而库匹配
#      是「一个 query 打 k 个候选」、聚类是「几万对反复撞同一批图块」，
#      同一张图的这份活会被重算几十上百遍。
# 两个缓存都存**算出来的同一份数组**，结果逐位不变，纯省时间：实测
# 逐对 3.94 ms → 2.4 ms。图块缓存按内容（tobytes）索引，不用 id()——
# 数组回收后 id 会被复用，那是错的来源。容量有上限，超了按 LRU 淘汰。
ELASTIC_PREP_CACHE = 512        # 图块预处理缓存条目上限（每条 ~70 KB）

_GRID_CACHE: dict[tuple, tuple] = {}
_PREP_CACHE: "OrderedDict[tuple, dict]" = OrderedDict()


def _grids(size: int, block: int, local: int, max_shift: int) -> tuple:
    """(offsets, pick, radius, span, stride, n_side)——纯常量，按参数缓存。"""
    key = (size, block, local, max_shift)
    hit = _GRID_CACHE.get(key)
    if hit is not None:
        return hit
    span = max_shift + local
    stride = size + 2 * span
    n_side = (size + block - 1) // block
    grid = np.arange(-span, span + 1)
    offsets = (grid[:, None] * stride + grid[None, :]).ravel()
    ids = np.arange(offsets.size).reshape(2 * span + 1, 2 * span + 1)
    pick = np.stack([ids[dy:dy + 2 * local + 1, dx:dx + 2 * local + 1].ravel()
                     for dy in range(2 * max_shift + 1)
                     for dx in range(2 * max_shift + 1)])
    radius = np.array([(dy - max_shift) ** 2 + (dx - max_shift) ** 2
                       for dy in range(2 * max_shift + 1)
                       for dx in range(2 * max_shift + 1)], dtype=np.float64)
    out = (offsets, pick, radius, span, stride, n_side)
    _GRID_CACHE[key] = out
    return out


def _prepare(patch: np.ndarray, scale: float, tau: float, block: int,
             span: int, stride: int, n_side: int) -> tuple:
    """图块在某个缩放档下的 (二值图, 墨量, 权重场, 平坦基址, 块起点)。"""
    key = (patch.tobytes(), scale, tau, block, span)
    hit = _PREP_CACHE.get(key)
    if hit is not None:
        _PREP_CACHE.move_to_end(key)
        return hit
    q = _rescale(patch, scale)
    ys, xs, starts = _blocks(q, block, n_side)
    # 基址保持 intp：花式索引内部就要 intp，改 int32 反而多一次转换（实测更慢）
    out = (q, int(q.sum()), _weight_field(q, tau, span),
           ((ys + span) * stride + (xs + span)), starts)
    _PREP_CACHE[key] = out
    if len(_PREP_CACHE) > ELASTIC_PREP_CACHE:
        _PREP_CACHE.popitem(last=False)
    return out


def _weight_field(binary: np.ndarray, tau: float, pad: int) -> np.ndarray:
    """到墨迹的距离 → 高斯软覆盖权重，pad 后展平（越界处权重 0）。

    用「预分配零 + 切片赋值」而不是 `np.pad`：本函数每对要调 6 次，
    而 np.pad 的 Python 层开销比这点数据搬运本身还大（实测占逐对总耗时
    的 ~8%）。两者结果完全一样。
    """
    dist = cv2.distanceTransform((1 - binary).astype(np.uint8), cv2.DIST_L2, 5)
    w = np.exp(-(dist / tau) ** 2, dtype=np.float32)
    n = binary.shape[0]
    out = np.zeros((n + 2 * pad, n + 2 * pad), dtype=np.float32)
    out[pad:pad + n, pad:pad + n] = w
    return out.ravel()


def _blocks(binary: np.ndarray, block: int, n_side: int
            ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """墨点按所属块排序，返回 (ys, xs, 段起点)——段起点喂 reduceat 求块和。"""
    ys, xs = np.nonzero(binary)
    if len(ys) == 0:
        return ys, xs, np.zeros(0, dtype=np.int64)
    gid = (ys // block) * n_side + (xs // block)
    order = np.argsort(gid, kind="stable")
    ys, xs, gid = ys[order], xs[order], gid[order]
    starts = np.flatnonzero(np.r_[True, gid[1:] != gid[:-1]])
    return ys, xs, starts


def _elastic_align(a: np.ndarray, b: np.ndarray, max_shift: int,
                   scales: tuple[float, ...], tau: float, block: int, local: int
                   ) -> tuple[float, tuple[int, int], float, np.ndarray | None]:
    """搜最优 (scale, dx, dy)：目标是分块弹性软覆盖率本身。

    末位一并返回胜出档的 b_s，省得调用方再 `_rescale` 一遍。
    """
    size = a.shape[0]
    na = int(a.sum())
    offsets, pick, radius, span, stride, n_side = _grids(size, block, local,
                                                         max_shift)
    _, _, wa, base_a, sa = _prepare(a, 1.0, tau, block, span, stride, n_side)

    # 全局位移 (dy,dx) × 块内位移 (ly,lx) 合成后仍是一个平移，所以先把所有
    # 合成位移的块和一次算完，再按 (dy,dx) 取各块在 9 个块内位移里的最优。
    # 平局的打破：块内 ±local 能吸收同样多的位移，最优位往往是一**连片**
    # 而非一点，取其中最居中（|shift| 最小、scale 最近 1）的那个——分数
    # 一样，但报告出来的 shift/scale 才读得懂，wmax 也从最居中的那次量。
    best, best_key, best_shift, best_scale = -1.0, None, (0, 0), 1.0
    best_bs: np.ndarray | None = None
    for scale in scales:
        b_s, nb, wb, base_b, sb = _prepare(b, scale, tau, block, span, stride,
                                           n_side)
        if nb == 0:
            continue
        t_b = np.add.reduceat(wa[base_b[None, :] + offsets[:, None]], sb, axis=1)
        t_a = np.add.reduceat(wb[base_a[None, :] - offsets[:, None]], sa, axis=1)
        cov = (t_b[pick].max(axis=1).sum(axis=1)
               + t_a[pick].max(axis=1).sum(axis=1)) / (na + nb)
        top = float(cov.max())
        k = int(np.lexsort((radius, -cov))[0])
        key = (-top, radius[k], abs(scale - 1.0))
        if best_key is None or key < best_key:
            best, best_key, best_bs = top, key, b_s
            # 网格里的 (dy, dx) 是「把 b 的墨搬到 a 的坐标系」的位移；
            # _shifted_view 取的是反向视图，故取负号后与 coverage 同约定。
            best_shift = (max_shift - k % (2 * max_shift + 1),
                          max_shift - k // (2 * max_shift + 1))
            best_scale = scale
    return best, best_shift, best_scale, best_bs


def _elastic_miss(a: np.ndarray, b_aligned: np.ndarray, tau: float,
                  block: int, local: int) -> tuple[np.ndarray, np.ndarray]:
    """最优对齐下逐像素的**未覆盖权重** (1-w)，双向各一张图。

    这里的块划分在**对齐后的公共坐标系**里（boxFilter 要求同一张图），
    而 `_elastic_align` 是各自在自己的坐标系里分块——两者在块边界上会
    差一点点，所以本函数反推的覆盖率与 `raw` 不完全相等。wmax 是护栏、
    自己按自己的分布标定，这点差异不影响它的操作点。
    """
    size = a.shape[0]
    n_side = (size + block - 1) // block
    out = []
    for src, dst in ((a, b_aligned), (b_aligned, a)):
        miss = np.zeros((size, size), dtype=np.float32)
        ys, xs = np.nonzero(src)
        if len(ys) == 0:
            out.append(miss)
            continue
        stride = size + 2 * local
        wd = _weight_field(dst, tau, local).reshape(stride, stride)
        cand = np.stack([wd[ys + local + ly, xs + local + lx]
                         for ly in range(-local, local + 1)
                         for lx in range(-local, local + 1)])
        gid = (ys // block) * n_side + (xs // block)
        # 每块选块内总权重最大的那个块内位移
        sums = np.stack([np.bincount(gid, weights=c, minlength=n_side * n_side)
                         for c in cand])
        best_local = sums.argmax(axis=0)[gid]
        w = cand[best_local, np.arange(len(ys))]
        miss[ys, xs] = 1.0 - w
        out.append(miss)
    return out[0], out[1]


def verify_pair_elastic(a: np.ndarray, b: np.ndarray,
                        max_shift: int = MAX_SHIFT,
                        scales: tuple[float, ...] = SCALES,
                        cov_high: float = ELASTIC_COV_HIGH,
                        cov_low: float = COV_LOW,
                        miss_wmax: float = MISS_WMAX,
                        tau: float = ELASTIC_TAU,
                        block: int = ELASTIC_BLOCK,
                        local: int = ELASTIC_LOCAL) -> PairVerdict:
    """elastic 判据：软覆盖 + 分块弹性对齐。字段语义与 verify_pair_cov 一致
    （f1 放覆盖率、diff_blob_ratio 放窗口残差），数值已校准回 coverage 刻度。
    """
    if a.shape != b.shape:
        raise ValueError("a/b 尺寸不一致")
    size = a.shape[0]
    na = int(np.count_nonzero(a))
    if na == 0 or int(np.count_nonzero(b)) == 0:
        return PairVerdict("diff", 0.0, 0.0, (0, 0), 1.0, 0.0)

    raw, (dx, dy), scale, b_s = _elastic_align(a, b, max_shift, scales, tau,
                                               block, local)
    if b_s is None:
        return PairVerdict("diff", 0.0, 0.0, (0, 0), 1.0, 0.0)
    padded = np.zeros((size + 2 * max_shift, size + 2 * max_shift), dtype=np.uint8)
    padded[max_shift:max_shift + size, max_shift:max_shift + size] = b_s
    b_aligned = _shifted_view(padded, dx, dy, size, max_shift)
    rigid_f1 = _f1(a, b_aligned, na, int(np.count_nonzero(b_aligned)))

    miss_a, miss_b = _elastic_miss(a, b_aligned, tau, block, local)
    k = (MISS_WIN, MISS_WIN)
    w_raw = max(
        float(cv2.boxFilter(miss_a, -1, k, normalize=False).max()),
        float(cv2.boxFilter(miss_b, -1, k, normalize=False).max()))

    cov = _calibrate(raw, _CAL_RAW, _CAL_COV)
    wmax = _calibrate(w_raw, _CAL_WRAW, _CAL_WMAX)

    if cov >= cov_high and wmax <= miss_wmax:
        verdict = "same"
    elif cov >= cov_low:
        verdict = "unsure"
    else:
        verdict = "diff"
    return PairVerdict(verdict, float(cov), float(rigid_f1),
                       (dx, dy), scale, float(wmax))


def verify_pair(a: np.ndarray, b: np.ndarray,
                max_shift: int = MAX_SHIFT,
                scales: tuple[float, ...] = SCALES,
                theta_high: float = THETA_HIGH,
                theta_low: float = THETA_LOW,
                diff_blob_ratio: float = DIFF_BLOB_RATIO) -> PairVerdict:
    """a, b: S×S uint8 {0,1} 归一二值图。"""
    size = a.shape[0]
    na = int(np.count_nonzero(a))

    best_f1, best_shift, best_scale = 0.0, (0, 0), 1.0
    best_b: np.ndarray | None = None

    for scale in scales:
        b_s = _rescale(b, scale)
        nb = int(np.count_nonzero(b_s))
        padded = np.zeros((size + 2 * max_shift, size + 2 * max_shift), dtype=np.uint8)
        padded[max_shift:max_shift + size, max_shift:max_shift + size] = b_s
        for dy in range(-max_shift, max_shift + 1):
            for dx in range(-max_shift, max_shift + 1):
                view = _shifted_view(padded, dx, dy, size, max_shift)
                f1 = _f1(a, view, na, nb)
                if f1 > best_f1:
                    best_f1, best_shift, best_scale = f1, (dx, dy), scale
                    best_b = view.copy()

    if best_b is None:  # 双方或一方无墨迹
        return PairVerdict("diff", 0.0, 0.0, (0, 0), 1.0, 0.0)

    nb_best = int(np.count_nonzero(best_b))
    a_d = cv2.dilate(a, _KERNEL3)
    b_d = cv2.dilate(best_b, _KERNEL3)
    dilated_f1 = _f1(a_d, b_d, int(np.count_nonzero(a_d)), int(np.count_nonzero(b_d)))

    ink_area = max(1.0, (na + nb_best) / 2.0)
    blob_ratio = _largest_diff_blob(a, best_b) / ink_area

    if best_f1 >= theta_high:
        # 形近字防线：整体够像但差异集中在一处 → 降级 unsure
        verdict = "unsure" if blob_ratio > diff_blob_ratio else "same"
    elif best_f1 >= theta_low:
        verdict = "unsure"
    else:
        verdict = "diff"

    return PairVerdict(verdict, float(best_f1), float(dilated_f1),
                       best_shift, best_scale, float(blob_ratio))
