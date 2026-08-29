"""列内字格纵向边界 — 给定一列的行投影，切出 N 个字格(含空白格)的边界。

跟 `grid_segment.py` 里生产用的 `dp_boundaries`/`elastic_recut` 是同一条思路
（弹性 DP：位置代价看墨量、步长容许伸缩），但这里是从 `char-segmentation/
row-boundaries` 数据集上的单页（vol02/135）逐轮试出来的独立实现，重点解决的
是"整列往错误的相邻字缝滑一格"这一类失败——过程详见
`.claude/doc/row_boundaries_design.md`。**尚未接入生产管线**，只在这一页上
验证过，先作为可复用工具落地。

## 核心设计

1. **候选只从波谷来**：局部最小值 + 凸出度过滤，不直接对每个像素算代价——
   笔画间的小凹陷会制造大量噪声候选，之前踩过（见设计文档"波谷候选"节）。
2. **空白区间单独探测**、其中补一批等间隔的"合成候选"（墨量给个统一的低值），
   保证没有真实波谷的空白段也有地方可选，不会因为没候选就整列判"无解"。
3. **周期(gap)不是常数，也不是本列自己算的**——单列自己拟合的周期可能有
   系统性偏差（本列信号有歧义时尤其明显），改用同页多列共享的周期先验
   `p_shared`（页面级，调用方传入或用 `estimate_period` 逐列估完取中位数）。
4. **弹性 DP，三层约束缺一不可**：
   - 相邻两点间距必须落在 `[lo_ratio, hi_ratio] × p_shared` 内（硬约束，
     超出直接不可行——不是软惩罚，惩罚拦不住"多走几步换更低墨量"的诱惑）；
   - 首尾锚点各自的 padding 分开限制：上 padding < `y1_max_frac × p_shared`，
     下 padding < `y2_max_frac × p_shared`（下限更紧——上下留白的物理量级本来
     就不对称，且"过渡点算错"这类失败的症状正是下 padding 异常大，见设计
     文档"根源"节）；
   - 在硬约束范围内，再用二次惩罚 `lam×((gap-p_shared)/p_shared)²` 拉着实际
     间距靠近先验，不是"只要在范围内怎样都一样"。

默认参数（`lo_ratio=0.7, hi_ratio=1.35, y1_max_frac=0.5, y2_max_frac=0.3,
lam=0.3`）是在 vol02/135 九列上网格搜出来的，九列全部收敛到均值误差
2.5~4.2px（对照人工核校金标）。样本只有一页，参数大概率需要随更多页数据
微调，但整体设计（候选=波谷、周期用页面先验、三层约束）在这一页上是稳的。

## 已知局限

- 只在 1 页（vol02/135，正文中段普通页）上验证过，参数未跨页/跨册验证。
- `p_shared` 需要调用方自己算（每列跑 `estimate_period` 取中位数），本模块
  不负责"这一页有几列"这类版面判断。
- 空白区间内部的分割点位置本质上没有真实信号支撑（纯合成候选撑住可行性），
  精度不如落在真实字缝上的点。

详见 `.claude/doc/row_boundaries_design.md`（完整实验记录：从硬分等分到
DP 到有序匹配到最终版弹性 DP，中间十几版尝试及各自的失败模式）。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


# ── 波谷 / 空白区间探测 ──────────────────────────────────────────


def smooth_curve(curve: np.ndarray, win: int = 5) -> np.ndarray:
    kernel = np.ones(win) / win
    return np.convolve(curve, kernel, mode="same")


def _prominence(curve: np.ndarray, i: int) -> float:
    """i 点的凸出度：往左/右走到"比 i 更低的点"之前，各自见过的最高点，
    取较小的那个减去 i 自己的值——两侧都要有一堵"墙"才算数的局部最小值。"""
    v = curve[i]
    n = len(curve)
    left_max = v
    j = i
    while j > 0:
        j -= 1
        if curve[j] < v:
            break
        left_max = max(left_max, curve[j])
    right_max = v
    j = i
    while j < n - 1:
        j += 1
        if curve[j] < v:
            break
        right_max = max(right_max, curve[j])
    return min(left_max, right_max) - v


def find_valleys(curve: np.ndarray, dst_w: int, min_sep: int = 20,
                  prom_frac: float = 0.10) -> list[int]:
    """局部最小值 + 凸出度过滤，只留"字缝级"波谷，不要笔画间的小凹陷。

    `prom_frac` 是凸出度阈值相对列宽的比例——列宽即墨量的理论上限（整行黑），
    用它归一化比用绝对像素数更能跨列宽度不同的列复用。
    """
    n = len(curve)
    prom_thresh = prom_frac * dst_w
    raw: list[int] = []
    i = 1
    while i < n - 1:
        if curve[i] <= curve[i - 1] and curve[i] <= curve[i + 1]:
            j = i
            while j + 1 < n and curve[j + 1] == curve[i]:
                j += 1
            mid = (i + j) // 2
            if _prominence(curve, mid) >= prom_thresh:
                raw.append(mid)
            i = j + 1
        else:
            i += 1
    raw = sorted(set(raw))
    merged: list[int] = []
    for y in raw:
        if merged and y - merged[-1] < min_sep:
            if curve[y] < curve[merged[-1]]:
                merged[-1] = y
        else:
            merged.append(y)
    return merged


def find_blank_intervals(curve: np.ndarray, thresh: float,
                          min_width: int = 25) -> list[tuple[int, int]]:
    """连续一段投影值 < thresh 的区间标"空白"；太窄的（笔画间噪声）不算。"""
    n = len(curve)
    intervals: list[tuple[int, int]] = []
    start: int | None = None
    for y in range(n):
        if curve[y] < thresh:
            if start is None:
                start = y
        elif start is not None:
            if y - start >= min_width:
                intervals.append((start, y - 1))
            start = None
    if start is not None and n - start >= min_width:
        intervals.append((start, n - 1))
    return intervals


def in_any_interval(y: float, intervals: list[tuple[int, int]]) -> bool:
    return any(lo <= y <= hi for lo, hi in intervals)


def trim_content_span(curve: np.ndarray, x1: float, x2: float, thresh: float,
                       border_margin: int = 15) -> tuple[int, int]:
    """从 x1 往下走到第一个 >= thresh 的点（内容起点），从 x2 往上走到最后一个
    >= thresh 的点（内容终点）——只剔除头尾连续空白，中间不动。

    `border_margin`：版框线自己那几像素墨量很高，紧贴 x1/x2 出发会立刻判成
    "非空白"、trim 直接失效（第一版真实踩过的 bug：不跳过这几像素，算出来
    content_start 恒等于 x1 本身）。
    """
    n = len(curve)
    y = min(int(round(x1)) + border_margin, n - 1)
    while y < n and curve[y] < thresh:
        y += 1
    content_start = min(y, n - 1)
    y = max(int(round(x2)) - border_margin, 0)
    while y > 0 and curve[y] < thresh:
        y -= 1
    content_end = max(y, 0)
    return content_start, content_end


def estimate_period(curve: np.ndarray, lag_lo: int = 70, lag_hi: int = 160) -> int:
    """自相关估计字符高度周期：曲线自身在"位移=真实字高"处有明显峰值，
    不依赖版框跨度这个可能带偏差的外部假设（版框到网格起点通常还有一段
    不属于任何格子的偏移，直接拿 (border_bottom-border_top)/n_slots 当典型
    格高会系统性偏大，见设计文档）。

    `lag_lo/lag_hi`：只在合理的单字高度量级里找峰，避开"半个字"和"两个字"
    这类谐波峰——范围本身不依赖任何一列的版框位置。
    """
    seg = curve - curve.mean()
    n = len(seg)
    best_lag, best_val = lag_lo, -np.inf
    for lag in range(lag_lo, min(lag_hi, n - 1)):
        v = float(np.dot(seg[: n - lag], seg[lag:]))
        if v > best_val:
            best_val, best_lag = v, lag
    return best_lag


def estimate_shared_period(row_projs: list[np.ndarray], borders: list[tuple[float, float]],
                            dst_ws: list[int], blank_thresh_frac: float = 0.08) -> float:
    """页面级共享周期：每列自己 trim+估计一次，取中位数。

    单列自己的估计可能有系统性偏差（本列字距天生不齐时尤其明显），中位数
    对个别列的偏差不敏感，比直接用某一列自己的估计更适合当所有列共享的
    先验（vol02/135 九列实测：中位数 108.4px，个别列自己的估计低至 104px、
    高至 115px）。
    """
    periods = []
    for row_proj, (x1, x2), dst_w in zip(row_projs, borders, dst_ws):
        curve = smooth_curve(np.asarray(row_proj, dtype=np.float64))
        thresh = blank_thresh_frac * dst_w
        cs, ce = trim_content_span(curve, x1, x2, thresh)
        if ce - cs < 20:
            continue
        periods.append(float(estimate_period(curve[cs:ce])))
    if not periods:
        raise ValueError("no column produced a usable period estimate")
    return float(np.median(periods))


# ── 弹性 DP ──────────────────────────────────────────────────


@dataclass
class RowBoundaryResult:
    boundaries: list[float]  # n_slots+1 个点，boundaries[k]..boundaries[k+1] 是第 k 格
    blank_intervals: list[tuple[int, int]]
    valleys: list[int]
    period: float


def _bounded_elastic_dp(x1: float, x2: float, valleys: np.ndarray, valley_ink: np.ndarray,
                         period: float, eps: float, lo_ratio: float, hi_ratio: float,
                         y1_max_frac: float, y2_max_frac: float, lam: float,
                         n_slots: int) -> list[float] | None:
    y1_max = y1_max_frac * period
    y2_max = y2_max_frac * period
    cand0 = [(v, ink) for v, ink in zip(valleys, valley_ink) if x1 <= v <= x1 + y1_max]
    candN = [(v, ink) for v, ink in zip(valleys, valley_ink) if x2 - y2_max <= v <= x2]
    if not cand0:
        cand0 = [(x1 + y1_max * 0.4, 0.05)]
    if not candN:
        candN = [(x2 - y2_max * 0.4, 0.05)]

    n_interior = n_slots - 1
    mid = sorted(
        [(v, ink) for v, ink in zip(valleys, valley_ink) if x1 < v < x2], key=lambda t: t[0]
    )
    m_count = len(mid)
    if m_count < n_interior:
        return None

    def step_cost(y_prev: float, y: float) -> float | None:
        gap = y - y_prev
        if not (lo_ratio * period <= gap <= hi_ratio * period):
            return None
        return lam * ((gap - period) / period) ** 2

    best: tuple[float, float, list[float], float] | None = None
    for v0, _ink0 in cand0:
        dp_cost = np.full((n_interior, m_count), np.inf)
        dp_prev = np.full((n_interior, m_count), -1, dtype=int)
        for m in range(m_count):
            y, ink = mid[m]
            c = step_cost(v0, y)
            if c is not None:
                dp_cost[0, m] = c + ink + eps
        for k in range(1, n_interior):
            for m in range(m_count):
                y, ink = mid[m]
                best_c, best_p = np.inf, -1
                for mp in range(m):
                    if not np.isfinite(dp_cost[k - 1, mp]):
                        continue
                    c = step_cost(mid[mp][0], y)
                    if c is None:
                        continue
                    total = dp_cost[k - 1, mp] + c + ink + eps
                    if total < best_c:
                        best_c, best_p = total, mp
                dp_cost[k, m] = best_c
                dp_prev[k, m] = best_p
        k_last = n_interior - 1
        for m in range(m_count):
            if not np.isfinite(dp_cost[k_last, m]):
                continue
            y, _ = mid[m]
            for vN, _inkN in candN:
                c = step_cost(y, vN)
                if c is None:
                    continue
                total = dp_cost[k_last, m] + c
                if best is None or total < best[0]:
                    path = [0.0] * n_interior
                    idx = m
                    for kk in range(k_last, -1, -1):
                        path[kk] = mid[idx][0]
                        idx = dp_prev[kk, idx]
                        if idx == -1:
                            break
                    best = (total, v0, path, vN)
    if best is None:
        return None
    _, v0, path, vN = best
    return [v0] + path + [vN]


def fit_row_boundaries(row_proj: np.ndarray, dst_w: int, border_top: float, border_bottom: float,
                        period: float, n_slots: int = 21, eps: float = 0.01, lam: float = 0.3,
                        lo_ratio: float = 0.7, hi_ratio: float = 1.35,
                        y1_max_frac: float = 0.5, y2_max_frac: float = 0.3,
                        blank_thresh_frac: float = 0.08, synth_step: int = 20) -> RowBoundaryResult | None:
    """一列的行投影 → n_slots 个字格的 n_slots+1 条边界。

    `period` 是这一页的共享周期先验（调用方用 `estimate_shared_period` 算，
    不要传本列自己的 `estimate_period` 结果——单列自估可能有系统偏差，正是
    共享先验要解决的问题）。返回 None 表示在给定约束下找不到可行解（约束
    卡太紧，或这一列的候选点确实撑不出 n_slots 个格子）。
    """
    curve = smooth_curve(np.asarray(row_proj, dtype=np.float64))
    valleys_all = find_valleys(curve, dst_w)
    thresh = blank_thresh_frac * dst_w
    intervals = find_blank_intervals(curve, thresh)
    valid = [v for v in valleys_all if not in_any_interval(v, intervals)]
    valley_ink = [curve[v] / dst_w for v in valid]

    # 空白区间没有真实波谷，补一批合成候选撑住可行性（墨量给个较低但非零的
    # 固定值——真波谷因为墨量更低仍然优先，但空白区不会因为没候选就无解）。
    synth: list[float] = []
    synth_ink: list[float] = []
    for lo, hi in intervals:
        y = lo
        while y <= hi:
            synth.append(float(y))
            synth_ink.append(0.03)
            y += synth_step

    all_valleys = np.array(valid + synth, dtype=np.float64)
    all_ink = np.array(valley_ink + synth_ink, dtype=np.float64)
    order = np.argsort(all_valleys)
    all_valleys, all_ink = all_valleys[order], all_ink[order]

    boundaries = _bounded_elastic_dp(
        border_top, border_bottom, all_valleys, all_ink, period, eps,
        lo_ratio, hi_ratio, y1_max_frac, y2_max_frac, lam, n_slots,
    )
    if boundaries is None:
        return None
    return RowBoundaryResult(
        boundaries=boundaries, blank_intervals=intervals, valleys=valleys_all, period=period,
    )
