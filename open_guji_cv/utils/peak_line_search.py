"""投影峰匹配找版框线 — 界行/边框的另一把尺子。

跟 `border_detect.py`（LSD 检测线段 → 按共线性聚类）是完全不同的思路：
不找线段再拼，而是直接对墨迹做投影，找"又窄又尖"的峰。

## 算法

1. **投影**：竖直线（界行/左右边框）用逐列黑像素数（`mask.sum(axis=0)`）；
   水平线（上下边框）用逐行黑像素数（`mask.sum(axis=1)`）。
2. **半高宽匹配度**：对投影曲线上每个点 x，以它自己的值为基准，向左右各走到
   跌破自身一半（`alpha`）的位置为止（容忍 `<hyst` 个点的小凹陷，不算真跌出），
   两个边界之间的距离就是"半高宽"。**匹配度 = 投影值 ÷ 半高宽**：版框线又高又窄，
   比值大；正文字列虽然投影值也不低，但很宽，比值被拉得很低。
   宽度是每个点现算的，不用事先猜"这条线该多宽"。
3. **位置 + 角度联合搜索**：版框线可能有微小倾斜（原稿本身不完全垂直/水平，
   或裁切引入的残余倾斜），单纯竖直/水平投影会把斜线的峰"拖宽拖低"甚至完全看丢。
   对每个候选，允许峰的位置也跟着倾角一起变（重要：**不能把位置锁死在初始候选
   x₀ 上再单独搜角度**——峰的真实锚点会随倾角挪动，锁死位置等于把最优解排除在
   搜索范围外，这是本算法早期版本踩过的坑，参见 `.claude/doc/peak_line_search.md`）。
4. **性能优化**：a) 只在投影曲线自己的局部极大值上算半高宽分数，不用扫窗口里
   每个位置；b) 角度先粗后细两段扫（粗扫定位大致方向，细扫在附近精确定位），
   比一次性细扫全范围快，且因为最终分辨率更高，找到的分数往往还更高。

## 已知局限

- 位置搜索窗口需要卡在"跟相邻真实线的中点"，否则宽窗口搜索会越界抓到别的
  线（尤其页面文字密集时，宽范围搜索很容易被别的强峰"劫持"）。`find_vertical_lines`
  用相邻候选的中点自动切窗口；单独调用 `joint_search_coarse_to_fine` 时需要
  调用方自己控制窗口范围。
- 顶部边框在部分页面上信号本身就弱（磨损/浓墨粘连导致没有突兀尖峰，只有
  跟正文行同量级的宽驼峰），这种情况下即使方法本身没问题，找到的"最佳点"
  置信度也不如底部/竖直界行高——分数本身就能反映这一点，不需要额外判定。

详见 `.claude/doc/peak_line_search.md`（算法设计记录 + 踩过的坑 + 五页试跑结果）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

DEFAULT_ALPHA = 0.5
DEFAULT_HYST = 3


# ── 半高宽匹配度 ──────────────────────────────────────────────


def projection(mask: np.ndarray, axis: str) -> np.ndarray:
    """axis='v': 逐列黑像素数（找竖直线用）；axis='h': 逐行黑像素数（找水平线用）。"""
    return mask.sum(axis=0) if axis == "v" else mask.sum(axis=1)


def half_height_score_at(curve: np.ndarray, idx: int,
                          alpha: float = DEFAULT_ALPHA, hyst: int = DEFAULT_HYST) -> tuple[float, float]:
    """对曲线上 idx 位置算半高宽和匹配度。返回 (半高宽, 匹配度=投影值/半高宽)。"""
    v = curve[idx]
    if v <= 0:
        return 0.0, 0.0
    thresh = v * alpha
    n = len(curve)

    def walk(start: int, step: int) -> int:
        pos, last_above, consec_below = start, start, 0
        while True:
            nxt = pos + step
            if nxt < 0 or nxt >= n:
                break
            if curve[nxt] >= thresh:
                last_above, consec_below = nxt, 0
            else:
                consec_below += 1
                if consec_below >= hyst:
                    break
            pos = nxt
        return last_above

    left = walk(idx, -1)
    right = walk(idx, 1)
    width = (right - left) + 1
    return float(width), float(v / width)


def full_sweep_scores(curve: np.ndarray, alpha: float = DEFAULT_ALPHA,
                       hyst: int = DEFAULT_HYST) -> tuple[np.ndarray, np.ndarray]:
    """对整条曲线逐点算半高宽/匹配度（初筛候选用；联合搜索内部不用这个，太慢）。"""
    n = len(curve)
    widths = np.zeros(n)
    scores = np.zeros(n)
    for i in range(n):
        wd, sc = half_height_score_at(curve, i, alpha, hyst)
        widths[i], scores[i] = wd, sc
    return widths, scores


def find_peaks_nms(scores: np.ndarray, min_dist: int, thresh: float) -> list[int]:
    """按分数从高到低贪心挑选，跳过跟已选点距离 < min_dist 的候选。"""
    idx_sorted = np.argsort(-scores)
    picked: list[int] = []
    for i in idx_sorted:
        if scores[i] < thresh:
            break
        if all(abs(int(i) - p) >= min_dist for p in picked):
            picked.append(int(i))
    return sorted(picked)


# ── 位置 + 角度联合搜索 ────────────────────────────────────────


def sample_line_curve(mask: np.ndarray, axis: str, pos_lo: int, pos_hi: int,
                       slope: float) -> tuple[np.ndarray, np.ndarray]:
    """给定倾角，算一批候选位置(pos_lo..pos_hi)各自的倾斜投影值。

    axis='v'：position=x，直线 x = position + slope*(y - h/2)，逐 y 求和。
    axis='h'：position=y，直线 y = position + slope*(x - w/2)，逐 x 求和。
    越界坐标按 0（没有墨）处理，不外推复制边缘像素。
    """
    h, w = mask.shape
    positions = np.arange(pos_lo, pos_hi + 1, dtype=np.float64)
    if axis == "v":
        perp = np.arange(h, dtype=np.float64)
        center = h / 2.0
        coord = positions[:, None] + slope * (perp[None, :] - center)
        limit = w
    else:
        perp = np.arange(w, dtype=np.float64)
        center = w / 2.0
        coord = positions[:, None] + slope * (perp[None, :] - center)
        limit = h

    valid = (coord >= 0) & (coord < limit - 1)
    coord_c = np.clip(coord, 0, limit - 1.001)
    i0 = np.floor(coord_c).astype(int)
    frac = coord_c - i0
    i1 = np.clip(i0 + 1, 0, limit - 1)
    perp_i = perp.astype(int)

    if axis == "v":
        v0, v1 = mask[perp_i, i0], mask[perp_i, i1]
    else:
        v0, v1 = mask[i0, perp_i], mask[i1, perp_i]

    vals = np.where(valid, v0 * (1 - frac) + v1 * frac, 0.0)
    return positions, vals.sum(axis=1)


def local_maxima(curve: np.ndarray, radius: int = 2) -> list[int]:
    """曲线上"半径内自己最大"的点，作为半高宽算法的候选（不用扫全部位置）。"""
    n = len(curve)
    idx = []
    for i in range(n):
        lo, hi = max(0, i - radius), min(n, i + radius + 1)
        if curve[i] > 0 and curve[i] == curve[lo:hi].max():
            idx.append(i)
    dedup: list[int] = []
    for i in idx:
        if dedup and i - dedup[-1] <= radius:
            if curve[i] > curve[dedup[-1]]:
                dedup[-1] = i
        else:
            dedup.append(i)
    return dedup


def best_in_curve(curve: np.ndarray, alpha: float = DEFAULT_ALPHA,
                   hyst: int = DEFAULT_HYST, radius: int = 2) -> dict | None:
    cands = local_maxima(curve, radius=radius)
    if not cands:
        return None
    best = None
    for i in cands:
        wd, sc = half_height_score_at(curve, i, alpha, hyst)
        if best is None or sc > best["score"]:
            best = dict(idx=i, score=sc, width=wd, proj=float(curve[i]))
    return best


@dataclass
class LineMatch:
    position: float
    slope: float
    score: float
    width: float
    proj: float

    @property
    def angle_deg(self) -> float:
        return float(np.degrees(np.arctan(self.slope)))


def joint_search_coarse_to_fine(mask: np.ndarray, axis: str, pos_lo: int, pos_hi: int,
                                 coarse_range: float = 0.05, coarse_n: int = 35,
                                 fine_radius: float = 0.006, fine_n: int = 25,
                                 alpha: float = DEFAULT_ALPHA, hyst: int = DEFAULT_HYST) -> LineMatch:
    """位置 + 角度联合搜索：不把位置锁死在窗口中心，让峰的锚点跟角度一起找。

    先粗扫 ±coarse_range（coarse_n 档）定位大致倾角，再在附近 ±fine_radius
    精扫（fine_n 档）——两段合起来比一次性细扫全范围快，且因为最终分辨率
    更高，比固定粗网格找到的分数还更高。
    """
    best: dict | None = None

    def scan(slopes: np.ndarray) -> None:
        nonlocal best
        for s in slopes:
            positions, curve = sample_line_curve(mask, axis, pos_lo, pos_hi, float(s))
            b = best_in_curve(curve, alpha, hyst)
            if b is None:
                continue
            rec = dict(slope=float(s), position=float(positions[b["idx"]]),
                       score=b["score"], width=b["width"], proj=b["proj"])
            if best is None or rec["score"] > best["score"]:
                best = rec

    scan(np.linspace(-coarse_range, coarse_range, coarse_n))
    if best is not None:
        scan(np.linspace(best["slope"] - fine_radius, best["slope"] + fine_radius, fine_n))

    if best is None:
        # 窗口里没有任何有墨的候选点——退化为窗口中心、零角度、零分
        center = (pos_lo + pos_hi) / 2.0
        return LineMatch(position=center, slope=0.0, score=0.0, width=0.0, proj=0.0)
    return LineMatch(**best)


# ── 整页便捷入口 ──────────────────────────────────────────────


def _windows_from_candidates(candidates: list[int], lo_bound: int, hi_bound: int,
                              margin_lo: int, margin_hi: int) -> list[tuple[int, int]]:
    """候选位置排序后，用相邻中点切窗口——避免宽范围搜索越界抓到邻居的线。"""
    windows = []
    for i, c in enumerate(candidates):
        lo = int(round((candidates[i - 1] + c) / 2)) + 1 if i > 0 else lo_bound - margin_lo
        hi = int(round((c + candidates[i + 1]) / 2)) if i < len(candidates) - 1 else hi_bound + margin_hi
        windows.append((lo, hi))
    return windows


def find_vertical_lines(mask: np.ndarray, min_dist: int = 60, nms_percentile: float = 90,
                         edge_margin: int = 200, expected_count: int | None = None,
                         alpha: float = DEFAULT_ALPHA, hyst: int = DEFAULT_HYST) -> list[LineMatch]:
    """整页竖直线（左右边框 + 内部界行）一次性找齐，按 x 从小到大排序。

    先用整页列投影 + 半高宽全扫找候选峰位置（NMS 去重，`min_dist` 建议设成比
    真实线宽大一个数量级、比列距小——默认 60px 是经验值，太小会把同一条线
    的相邻局部峰重复收进来），再对每个候选做位置+角度联合精搜——窗口卡在
    相邻候选的中点，最左/最右两条各往页面外留 `edge_margin` px（版框线的
    真实位置可能跟粗投影找到的候选差几十像素，需要留够搜索空间，参见文档
    里 x=33/216 的案例）。

    粗筛之后可能还会剩下几个弱的假候选（文字笔画凑巧对齐产生的次级峰）。
    如果知道这一页应该有几列，传 `expected_count`（跟 `border_detect.py`
    里 `expected_cols` 的用法一致）——按匹配度只留分数最高的 N 条，比猜一个
    通用阈值更稳。不传的话把所有候选原样返回，由调用方按分数自行判断。
    """
    h, w = mask.shape
    curve = projection(mask, "v")
    _, scores = full_sweep_scores(curve, alpha, hyst)
    thresh = float(np.percentile(scores, nms_percentile))
    candidates = find_peaks_nms(scores, min_dist, thresh)
    if not candidates:
        return []

    windows = _windows_from_candidates(candidates, 0, w - 1, edge_margin, edge_margin)
    results = []
    for lo, hi in windows:
        results.append(joint_search_coarse_to_fine(mask, "v", lo, hi, alpha=alpha, hyst=hyst))

    if expected_count is not None and len(results) > expected_count:
        results = sorted(results, key=lambda r: -r.score)[:expected_count]

    results.sort(key=lambda r: r.position)
    return results


def find_horizontal_border(mask: np.ndarray, side: str, band_frac: float = 0.15,
                            alpha: float = DEFAULT_ALPHA, hyst: int = DEFAULT_HYST) -> LineMatch:
    """找页面顶部或底部的边框线（side='top'/'bottom'）。

    只在页面顶/底 `band_frac` 比例的窄带内搜——上下边框不像竖直界行那样有
    "相邻线"的概念，直接限定在页边margin区域内找最强峰即可。
    """
    h, w = mask.shape
    band = max(10, int(h * band_frac))
    if side == "top":
        lo, hi = 0, band
    else:
        lo, hi = h - band, h - 1
    return joint_search_coarse_to_fine(mask, "h", lo, hi, alpha=alpha, hyst=hyst)
