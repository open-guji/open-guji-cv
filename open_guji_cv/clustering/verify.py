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
