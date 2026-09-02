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

- 参数在 vol02/135（正文中段普通列）+ vol01/33（含抬头列）两页上验证过，
  仍未跨更多页/跨册验证。
- `p_shared` 需要调用方自己算（每列跑 `estimate_period` 取中位数），本模块
  不负责"这一页有几列"这类版面判断。
- 空白区间内部的分割点位置本质上没有真实信号支撑（纯合成候选撑住可行性），
  精度不如落在真实字缝上的点。
- **抬头列**：`top_slack` 把首锚点窗口往上放宽，**直接开到列图顶端**
  （`top_slack=border_top`）即可——vol01/33 四个抬头列均值误差 0.6/12.3/
  0.6/0.0px（对照人工金标）。别按 period 的倍数抠：早先用 1×period 时
  列2 误差 88px，根因不是"窗口里不干净"，是金标首点就落在窗口外面 3px，
  开大就进来了（1.2× 到 2.5× 逐档实测完全一样，见设计文档「修正」节）。
  开错代价也很小：把普通列全开也只从 0px 退化到 0.9~1.2px。
  **仍然没解决的是"这一列到底几个字"**（抬头列可能 21 也可能 22）——纯
  信号判据不可靠（试过的"上探测墨量占比"把普通列的角框装饰也误判成抬头
  字），`n_slots` 仍要调用方按版式先验/人工核校给。

详见 `.claude/doc/row_boundaries_design.md`（完整实验记录：从硬分等分到
DP 到有序匹配到最终版弹性 DP，中间十几版尝试及各自的失败模式）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import jiazhu_split


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


# ── Step 3 对外输出格式（→ Step 4）──────────────────────────
# 只有切分点是不够的：下游要知道每一格**是什么**（正文字/空白/双行小注的
# 哪一半），才谈得上装配文本与隔离字形。类型口径见 `CELL_KINDS`。

CELL_KINDS = ("char", "blank", "jiazhu_a", "jiazhu_b")
"""**不含 `"raised"`**（2026-09-01 改，用户定：「不需要区分抬头和普通字。
它们都是字，按坐标来区分位置」）。「抬头」不是一种跟"字/空白/夹注"并列的
内容类型——它是同一个字的**位置**信息（顶边有没有伸到版框线以上），跟
"这一格里是什么"是两个维度，硬塞进同一个 `kind` 枚举会让分类互相打架
（`Cell.raised` 见下）。

试标 5 列 39 格金标时踩出来的：`kind` 还叫 `"raised"` 那版，标注页给了
单格裁紧图，人只能看见格子本身，看不见它相对版框线的位置——两格真正
「顶边伸到版框线以上」的格子（vol01/33 col2 的"天""而"）人都标成了"字"，
不是标错，是那道题问的就是坐标问题、裁紧图里根本看不出坐标。改成
`Cell.raised` 之后，这两格重新算是 `kind="char", raised=True`，跟人标的
"字"完全对上——不用重标，是分类口径本来就问岔了。
"""


@dataclass
class Cell:
    """一个字格。坐标一律在 **Step 2 输出的列图** 里（标准图像坐标系：
    左上角原点、x 向右、y 向下），不是页面坐标——列图矫正之后已经不是页面
    的一部分了（Step 2 的约定，这里沿用）。

    - `slot`：格号，从上到下递增，**正文格从 1 开始，抬头多出来的格用负数**
      （倒数第一个抬头格是 -1，再往上 -2、-3……），**跳过 0**——这样"同一个
      slot 数字"跨列指的是同一条物理网格线：正文列的 slot 1 和抬头列
      （不管抬头挤没挤出额外格）的 slot 1 永远是版框下同一条起始线，抬头
      多占的格另算在负数区，不会把正文格往后挤。一格夹注会发出两个 `Cell`，
      `slot` 相同、`kind` 分别是 `jiazhu_a`/`jiazhu_b`。
    - `x0/x1`：正常格是整个内容窗口（界行已剥掉）；夹注半格是各自那半边——
      `jiazhu_a` = 缝右（`[gap_center, x_hi]`），`jiazhu_b` = 缝左。
      **a 是右子列、先读**（双行小注先右行后左行）。
    - `order`：本列的阅读序，从 1 开始。正文格按 slot 升序；连续夹注段整体
      插在段位上，段内先 a 全部、再 b 全部（见 `reading_order`）。
    - `gap_center`：夹注格的缝中心 x（a/b 两半共用同一个值），非夹注为 None。
    - `ink_ratio`：格内墨占比（在裁紧前的格框上算，`< min_ink_ratio` 判空白）。
    - `raised`：这一格顶边有没有伸到 `border_top` 以上，纯几何量（`y0` 跟
      `border_top` 比大小），不进 `kind`——见上面 `CELL_KINDS` 的说明。跟
      `slot` 是不是负数是两件事：`n_raised=0` 的「抬头但格数不变」列，
      slot 1 本身也会是 `raised=True`；`slot` 负数只说明"这一格是多出来
      的格"，不代表它一定伸到版框线以上（理论上不会不伸，但这两个字段各自
      独立计算，不互相推导）。
    """

    slot: int
    y0: float
    y1: float
    x0: float
    x1: float
    kind: str
    order: int = 0
    gap_center: float | None = None
    ink_ratio: float = 0.0
    raised: bool = False

    @property
    def sub(self) -> str | None:
        """夹注半格的 `"a"`/`"b"`，非夹注为 None（对齐生产 CharInstance.sub）。"""
        if self.kind == "jiazhu_a":
            return "a"
        if self.kind == "jiazhu_b":
            return "b"
        return None


@dataclass
class RowBoundaryResult:
    boundaries: list[float]  # n_slots+1 个点，boundaries[k]..boundaries[k+1] 是第 k 格
    blank_intervals: list[tuple[int, int]]
    valleys: list[int]
    period: float
    cells: list[Cell] = field(default_factory=list)
    """格子列表（Step 3 的正式产物）。`fit_row_boundaries` 只有行投影、拿不到
    图像，判不了类型，所以留空；走 `segment_column`（Step 3 的正门，输入是
    Step 2 的列图）才会填。"""
    content_x: tuple[float, float] | None = None
    """内容窗口 `[x_lo, x_hi)`：列图两侧的界行/版框竖线剥掉之后剩下的范围。"""


def _bounded_elastic_dp(x1: float, x2: float, valleys: np.ndarray, valley_ink: np.ndarray,
                         period: float, eps: float, lo_ratio: float, hi_ratio: float,
                         y1_max_frac: float, y2_max_frac: float, lam: float,
                         n_slots: int, top_slack: float = 0.0) -> list[float] | None:
    y1_max = y1_max_frac * period
    y2_max = y2_max_frac * period
    x1_eff = x1 - top_slack
    cand0 = [(v, ink) for v, ink in zip(valleys, valley_ink) if x1_eff <= v <= x1 + y1_max]
    candN = [(v, ink) for v, ink in zip(valleys, valley_ink) if x2 - y2_max <= v <= x2]
    if not cand0:
        cand0 = [(x1 + y1_max * 0.4, 0.05)]
    if not candN:
        candN = [(x2 - y2_max * 0.4, 0.05)]

    n_interior = n_slots - 1
    mid = sorted(
        [(v, ink) for v, ink in zip(valleys, valley_ink) if x1_eff < v < x2], key=lambda t: t[0]
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
                        blank_thresh_frac: float = 0.08, synth_step: int = 20,
                        top_slack: float = 0.0) -> RowBoundaryResult | None:
    """一列的行投影 → n_slots 个字格的 n_slots+1 条边界。

    `period` 是这一页的共享周期先验（调用方用 `estimate_shared_period` 算，
    不要传本列自己的 `estimate_period` 结果——单列自估可能有系统偏差，正是
    共享先验要解决的问题）。返回 None 表示在给定约束下找不到可行解（约束
    卡太紧，或这一列的候选点确实撑不出 n_slots 个格子）。

    `top_slack`：**抬头列专用**，默认 0 不影响普通列。首锚点(cand0)的候选
    窗口从 `[border_top, border_top+y1_max]` 放宽成
    `[border_top-top_slack, border_top+y1_max]`，允许首字顶边界落在版框线
    以上——抬头惯例会把首字整体抬高、甚至顶到版框线以上表达尊重。
    **抬头列直接给 `top_slack=border_top`（开到列图顶端）**，不要按 period
    的倍数抠：vol01/33 实测 1×period 时列2 误差 88px（金标首点就在窗口外
    3px），开到顶端后降到 12.3px，且 1.2×~2.5× 逐档结果完全一样；开错的
    代价也只有 0.9~1.2px。
    **这只解决"首字在哪"，不解决"这一列到底该有几个字格"**：抬头列的实际
    字数可能比普通列多一个（腾出的抬头空间够塞一个字），也可能不多（只是
    整体往上挪），`n_slots` 仍需调用方按页面版式常识/人工核校提供，本模块
    不负责判断——vol01/33 的实测（4 个抬头列里 3 个多一字、1 个不多）表明
    这件事没有可靠的纯信号判据（装饰性花边墨量与真字墨量在这一页上分不
    开），见 `.claude/doc/row_boundaries_design.md`「抬头列」节。
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
        lo_ratio, hi_ratio, y1_max_frac, y2_max_frac, lam, n_slots, top_slack,
    )
    if boundaries is None:
        return None
    return RowBoundaryResult(
        boundaries=boundaries, blank_intervals=intervals, valleys=valleys_all, period=period,
    )


# ── Step 3 正门：列图 → 带类型的字格 ──────────────────────────


def find_content_window(col_gray: np.ndarray, ink_threshold: int = 128,
                         wall_ink_frac: float = 0.25, wall_pad: int = 3,
                         max_inset_frac: float = 0.15) -> tuple[int, int]:
    """列图两侧的界行/版框竖线占了几列像素 → 内容窗口 `[x_lo, x_hi)`。

    Step 2 的 `warp_column` 是**贴着两条界行**矫正的，列图最左最右两条就是
    界行本身。界行贯穿整列高度，不剥掉会连坐两处：
    - 行投影每一行凭空多出两坨常量墨（抬高空白判据的基线）；
    - 更要命的是夹注判据——`jiazhu_split.gap_center` 量的是"墨迹跨度占列距
      的比例"，界行让**每一格**的跨度都顶满列宽，`SPAN_T` 直接失效、所有格
      都像夹注。

    判据只用"贯穿性"：某个 x 上的墨占该列全高的比例 ≥ `wall_ink_frac` 才算
    墙。只从两侧往里啃，最多啃掉 `max_inset_frac` 的宽度——真字里也有又长又
    直的竖笔，限死啃食范围才不会把窗口啃穿。取窗口内**最靠内的那堵墙**
    （不是"第一个不是墙的 x"）：矫正后的界行常常是断续的，遇断口就停会把
    半条界行留在窗口里。

    两个阈值都是量出来的（vol02/171 九列）：
    - `wall_ink_frac=0.25`——真实界行**不是**贯穿到底的实线，这批页上量到的
      整列墨占比只有 0.30~1.00（刻版磨损 + 矫正错位），0.5 会漏掉一多半；
      正文字在边缘 28px 内的整列墨占比是 0.0x 量级，两者之间空得很。
    - `wall_pad=3`——界行的墨是**渐弱**的（实测某列 x=0..3 的单格墨量
      87/51/19/3），只按阈值切会把尾巴留在窗口里。留一格没关系（版式本来
      就有 20 多像素的 inset，生产量到 `inset_l=26/inset_r=22`），留半条
      界行则会让**每一格**的墨迹跨度都顶满列宽、夹注的 `SPAN_T` 判据直接
      失效——vol02/171 col4 的「出」「於」就是这么被误判成夹注的。
    """
    if col_gray.ndim == 3:
        col_gray = col_gray[:, :, 0]
    h, w = col_gray.shape[:2]
    ink = (col_gray < ink_threshold)
    frac = ink.sum(axis=0) / float(max(h, 1))
    max_inset = max(1, int(round(max_inset_frac * w)))
    x_lo = 0
    walls = np.flatnonzero(frac[:max_inset] >= wall_ink_frac)
    if walls.size:
        x_lo = int(walls[-1]) + 1 + wall_pad
    x_hi = w
    walls = np.flatnonzero(frac[w - max_inset:] >= wall_ink_frac)
    if walls.size:
        x_hi = w - max_inset + int(walls[0]) - wall_pad
    if x_hi - x_lo < w // 2:      # 啃过头了，宁可不剥
        return 0, w
    return x_lo, x_hi


def row_ink_projection(col_gray: np.ndarray, x_lo: int = 0, x_hi: int | None = None,
                        ink_threshold: int = 128) -> np.ndarray:
    """列图的行投影：每一行在内容窗口内的墨像素个数（喂给弹性 DP 的曲线）。"""
    if col_gray.ndim == 3:
        col_gray = col_gray[:, :, 0]
    if x_hi is None:
        x_hi = col_gray.shape[1]
    return (col_gray[:, x_lo:x_hi] < ink_threshold).sum(axis=1).astype(np.float64)


def reading_order(cells: list[Cell]) -> list[Cell]:
    """一列格子的**阅读顺序**（夹注读序的唯一权威，下游装文本用它，别自己按
    slot 排）。

    正文格按 slot 升序；**连续夹注段**（slot 连续的夹注格）作为整体插在段位
    上，段内先读右子列 a 全部（slot 升序）、再读左子列 b 全部——双行小注先
    右行后左行。逐条对应生产 `extractor.jiazhu_reading_order`，输入乱序也行。

    `slot` 在抬头/正文交界处跳过 0（`-1` 后面直接是 `1`），"连续"的判断
    要把这一格也算相邻——物理上它们本来就是相邻两格，只是显示编号跳了一格。
    """
    by_slot: dict[int, list[Cell]] = {}
    for c in cells:
        by_slot.setdefault(c.slot, []).append(c)
    out: list[Cell] = []
    slots = sorted(by_slot)

    def _adjacent(a: int, b: int) -> bool:
        return b == a + 1 or (a == -1 and b == 1)

    k = 0
    while k < len(slots):
        s = slots[k]
        if any(c.sub for c in by_slot[s]):
            run = [s]
            while (k + 1 < len(slots) and _adjacent(slots[k], slots[k + 1])
                   and any(c.sub for c in by_slot[slots[k + 1]])):
                k += 1
                run.append(slots[k])
            for sub in ("a", "b"):
                for j in run:
                    out.extend(c for c in by_slot[j] if c.sub == sub)
        else:
            out.extend(by_slot[s])
        k += 1
    return out


def _ink_ratio(patch: np.ndarray, ink_threshold: int) -> float:
    if patch.size == 0:
        return 0.0
    return float((patch < ink_threshold).sum()) / float(patch.size)


def _pos_to_slot(pos: int, n_raised: int) -> int:
    """物理位置(1..n_body_slots+n_raised，从上到下连续)→ 对外的 slot 号。

    `pos` 是内部处理（DP、夹注相邻性判断）用的连续编号，物理上永远
    `pos+1 == pos的下一格`；`slot` 是对外的显示编号，抬头多出来的
    `n_raised` 格排在最前面、编成 `-n_raised..-1`，正文接着从 `1` 编到
    `n_body_slots`，**跳过 0**。两者只在这一处转换，其余内部逻辑（DP、
    `jiazhu_split.link_runs` 的"相邻"判断）一律用 `pos`，不用 `slot`——
    `slot` 在抬头/正文交界处不连续（-1 后面直接是 1），拿它判断"是否相邻"
    会在这一格上出错。
    """
    return pos - n_raised - 1 if pos <= n_raised else pos - n_raised


def segment_column(col_gray: np.ndarray, period: float, n_body_slots: int = 21,
                    n_raised: int = 0, *,
                    border_top: float = 0.0, border_bottom: float | None = None,
                    ref_w: float | None = None, top_slack: float = 0.0,
                    content_x: tuple[float, float] | None = None,
                    ink_threshold: int = 128, min_ink_ratio: float = 0.01,
                    raise_tol: float = 2.0, detect_jiazhu: bool = True,
                    **dp_kwargs) -> RowBoundaryResult | None:
    """**Step 3 的正门**：Step 2 的单列矩形图 → 带类型的字格列表。

    输入是 `column_projection.warp_column`（+`denoise_column`）的输出，输出是
    填好 `cells` 的 `RowBoundaryResult`；返回 None 表示弹性 DP 在给定约束下
    无解（同 `fit_row_boundaries`）。

    参数：
    - `period`：**纵向**字距先验，页级共享（`estimate_shared_period`）。
    - `n_body_slots`：正文格数，版式常量（这两册都是 21）。
    - `n_raised`：抬头额外多出来的格数，默认 0（普通列，或"抬头但格数不变"
      的列——那种只需要 `top_slack`，不需要 `n_raised`）。**本模块不判断
      这两个数该给多少**——纯信号判据不可靠（见
      `.claude/doc/row_boundaries_design.md`「抬头列」节），由调用方按版式
      先验/人工核校给。给对了，`n_body_slots+n_raised` 就是这一列实际要切
      的总格数，DP 侧的行为跟改之前用一个 `n_slots` 完全一样；只是对外
      编号从"1..n_slots 连续"变成"负数区(抬头) + 正数区(正文)"，见 `Cell.slot`。
    - `border_top`/`border_bottom`：上下版框在**列图坐标**里的 y。抬头列要
      让 Step 2 多矫正一截页顶（`warp_column(top_y=版框y-抬头余量)`），再把
      版框自己的 y 从这里告诉 Step 3，配合 `top_slack` 才能让首格落到版框
      线以上——列图裁在版框上就没有抬头字可切了。抬头列的 `top_slack`
      **直接给 `border_top`（开到列图顶端）**，别按 period 的倍数抠，
      理由见 `fit_row_boundaries` 的 `top_slack` 说明。
    - `ref_w`：夹注跨度判据的尺子，应传**页级列距中位数**；不传退回本列内容
      窗口宽度（会随列宽漂移，生产为此栽过，见 `jiazhu_split` 模块头）。
    - `content_x`：内容窗口 `(x_lo, x_hi)`，给了就直接用、跳过内部的
      `find_content_window`。**Step 2 的产物如果已经先"抹白"了界行/版框
      （`column_projection.clean_column` 那条链路，`scripts/
      export_step3_input.py` 交出的 manifest 里带这个字段），这里必须传**
      ——`find_content_window` 靠"墨量贯穿"找墙，墙的墨被抹白之后它在图上
      一堵墙都找不到，会整幅宽度都当内容窗口（实测 24 列全部如此，宽
      9.6%~17%）。已经量过这条口径差的下游影响很小（24 列只 1 列的格类型
      判断不同），但既然 Step 2 已经把这条带定出来了，没道理让 Step 3 自己
      重猜一遍，猜错了还会悄悄退化不报错。**不传（默认 None）** 走的还是
      原来的路——只在图上自己找墙，适配的是"界行墨还在、没被抹白"的输入
      （比如 `denoise_column` 而非 `clean_column` 的产物），旧调用方零影响。
    - `min_ink_ratio`：格内墨占比低于此判空白格（口径同生产 `MIN_INK_RATIO`）。
    - `raise_tol`：格顶高出 `border_top` 超过此像素数就把 `Cell.raised` 置
      True。这是纯几何量，不影响 `kind`（见 `CELL_KINDS` 的说明），跟 `slot`
      是不是负数也是两回事——`n_raised=0` 的「抬头但格数不变」列，slot 1
      本身也会是 `raised=True`；只说"这一格伸到版框线以上了"，不代表它占了
      额外的格。
    - `detect_jiazhu`：关掉就只出 char/blank 两类（`raised` 仍照算，它跟
      夹注判定完全独立）。
    - `dp_kwargs`：透传给 `fit_row_boundaries`（`lam`/`lo_ratio`/`hi_ratio`/
      `y1_max_frac`/`y2_max_frac`/`blank_thresh_frac`/`synth_step`/`eps`）。

    `kind` 判定的优先级：空白 > 夹注 > 正文字。空白格不参与夹注判据（生产
    同口径：只在 char 格上量缝），夹注段的段端收编也只收非空白格。`raised`
    在这条优先级之外单独算，任何 `kind` 的格都可能是 `raised=True`。
    """
    if col_gray.ndim == 3:
        col_gray = col_gray[:, :, 0]
    h, w = col_gray.shape[:2]
    if border_bottom is None:
        border_bottom = float(h - 1)
    n_slots = n_body_slots + n_raised

    if content_x is not None:
        x_lo, x_hi = int(round(content_x[0])), int(round(content_x[1]))
    else:
        x_lo, x_hi = find_content_window(col_gray, ink_threshold=ink_threshold)
    dst_w = x_hi - x_lo
    row_proj = row_ink_projection(col_gray, x_lo, x_hi, ink_threshold)

    result = fit_row_boundaries(row_proj, dst_w, border_top, border_bottom, period,
                                n_slots=n_slots, top_slack=top_slack, **dp_kwargs)
    if result is None:
        return None
    result.content_x = (float(x_lo), float(x_hi))
    bounds = result.boundaries

    # 下面全程用 pos（1..n_slots，物理上连续）做字典键和相邻性判断；slot
    # （对外编号，抬头/正文交界处跳过 0）只在生成 Cell 的最后一步换算。
    patches: dict[int, np.ndarray] = {}
    inks: dict[int, float] = {}
    for k in range(n_slots):
        pos = k + 1
        y0i = max(0, min(h, int(round(bounds[k]))))
        y1i = max(0, min(h, int(round(bounds[k + 1]))))
        patch = col_gray[y0i:y1i, x_lo:x_hi]
        patches[pos] = patch
        inks[pos] = _ink_ratio(patch, ink_threshold)
    nonblank = {p for p in patches if inks[p] >= min_ink_ratio}

    runs: dict[int, float] = {}
    tail_a: set[int] = set()
    if detect_jiazhu:
        ruler = float(ref_w) if ref_w else float(dst_w)
        entries = [
            (p, jiazhu_split.gap_center(patches[p], ruler, ink_threshold)
                if p in nonblank else None)
            for p in sorted(patches)
        ]
        runs = jiazhu_split.link_runs(entries)
        runs, tail_a = jiazhu_split.adopt_run_tails(
            runs, patches, eligible=nonblank, ink_threshold=ink_threshold)

    cells: list[Cell] = []
    for k in range(n_slots):
        pos = k + 1
        slot = _pos_to_slot(pos, n_raised)
        y0, y1 = float(bounds[k]), float(bounds[k + 1])
        raised = y0 < border_top - raise_tol   # 纯几何量，跟 kind 判定分开算
        if pos in runs:
            cx_local = runs[pos]
            cx = float(x_lo) + cx_local
            cxi = int(round(cx_local))
            # 半边无墨（段末单半）不发格子——生产同口径（`ty.size < 30`）。
            # a=右子列先读、b=左子列；单字尾（tail_a）的 b 侧只有邻字残渣。
            for kind, xs, xe in (("jiazhu_a", cxi, x_hi - x_lo),
                                  ("jiazhu_b", 0, cxi)):
                if kind == "jiazhu_b" and pos in tail_a:
                    continue
                half = patches[pos][:, xs:xe]
                if int((half < ink_threshold).sum()) < jiazhu_split.HALF_MIN_INK:
                    continue
                cells.append(Cell(slot=slot, y0=y0, y1=y1,
                                  x0=float(x_lo + xs), x1=float(x_lo + xe),
                                  kind=kind, gap_center=cx, raised=raised,
                                  ink_ratio=round(_ink_ratio(half, ink_threshold), 4)))
            continue
        kind = "blank" if pos not in nonblank else "char"
        cells.append(Cell(slot=slot, y0=y0, y1=y1, x0=float(x_lo), x1=float(x_hi),
                          kind=kind, raised=raised, ink_ratio=round(inks[pos], 4)))

    for i, c in enumerate(reading_order(cells), start=1):
        c.order = i
    result.cells = cells
    return result
