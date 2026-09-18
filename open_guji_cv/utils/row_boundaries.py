"""列内字格纵向边界 — 给定一列的行投影，切出 N 个字格(含空白格)的边界。

跟 `grid_segment.py` 里生产用的 `dp_boundaries`/`elastic_recut` 是同一条思路
（弹性 DP：位置代价看墨量、步长容许伸缩），但这里是从 `char-segmentation/
row-boundaries` 数据集上的单页（vol02/135）逐轮试出来的独立实现，重点解决的
是"整列往错误的相邻字缝滑一格"这一类失败——过程详见
`.claude/doc/row_boundaries_design.md`。

**已是生产实现**（`steps/row_segment.py` 直接调 `segment_column`）；下面
"已知局限"里"只在 vol02/135 一页验证过"那几条是**当初的**情况，现已跨册
跑过（四庫 vol01-03 + 北行日錄刻本/现代排印本），参数几经标定。要看当下
实测状态用 `guji status`，别信这段文字的年份。

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

import functools
from dataclasses import dataclass, field

import numpy as np

from . import jiazhu_split

#: 空白格的**下界**（× period）。空白格代表「这里本该有个字、但它是空的」，
#: 所以它的高度应当接近一格；此前只给了上界 1.25·period，没有下界，于是 DP 可以
#: 造出 8~20px 的「碎空白格」来凑够 `n_slots`——代价只有 `blank_cost`=0.05 加
#: 十分之一的间距惩罚（`blank_lam_frac`），比把两个字并成一格更划算。
#:
#: 后果是**相位错位**：北行日錄 p8c1 slot2 被塞成 13.5px 的空白格，后面每一格
#: 往上挤，累积到 slot12~14 变成 90/98.5/96px 的超大格，一格装两个字（人裁标
#: 「季+鷹」「鷹+陳」各半）。这类列格数是对的（21），所以字数对账查不出来。
#:
#: 0.6 的依据：全书 1842 个 blank 格的高/period 分布 p5=0.82、p50=1.07、p99=1.20，
#: 而 <0.5 的只有 43 个（正是凑数的那批）——0.6 落在两堆中间的空档里，两边都有余量。
BLANK_MIN_RATIO = 0.6


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

    ⚠️ **窗口必须含真周期、且把 2x 谐波关在外面**，两个条件缺一不可。
    缺省的 70–160 是给《四庫全書總目》标的（真值 113~115，稳稳落在窗口中间）。
    **真值顶在 `lag_lo` 上就会出事**：北行日錄刻本真值 70.6，窗口勉强表示得了它，
    却对 2x 谐波 141 敞开——自相关在 70 和 141 两处都有峰，逐列各自锁哪个看运气，
    全书 30.4% 的列锁到谐波。而 `estimate_shared_period` 取逐列中位数，两堆各半时
    中位落进中间的空档，给出一个**物理上不存在**的 106.5，DP 拿它当先验必然无解。
    所以窗口要由册的 `period_prior` 派生（见 `estimate_shared_period`），别写死。

    ⚠️ 另一条死路：**别换成另一组固定窄窗**。试过 [55,100]，北行日錄是好了，
    四庫總目当场全毁（115 被上界截成 99，抽 12 页里 10 页中位都变）。
    """
    seg = curve - curve.mean()
    n = len(seg)
    best_lag, best_val = lag_lo, -np.inf
    for lag in range(lag_lo, min(lag_hi, n - 1)):
        v = float(np.dot(seg[: n - lag], seg[lag:]))
        if v > best_val:
            best_val, best_lag = v, lag
    return best_lag


#: `period_prior` 派生自相关窗口的系数。真周期的逐页波动远小于 ±30%
#: （四庫總目 vol01 正文 108 页 115.0±1.67px），取这么宽是留足标定误差的余量；
#: 上界 1.4 < 2.0 保证 2x 谐波一定被关在窗外，这是这组数唯一的硬约束。
PERIOD_WINDOW_LO, PERIOD_WINDOW_HI = 0.7, 1.4


def estimate_shared_period(row_projs: list[np.ndarray], borders: list[tuple[float, float]],
                            dst_ws: list[int], blank_thresh_frac: float = 0.08,
                            period_prior: float | None = None) -> float:
    """页面级共享周期：每列自己 trim+估计一次，取中位数。

    单列自己的估计可能有系统性偏差（本列字距天生不齐时尤其明显），中位数
    对个别列的偏差不敏感，比直接用某一列自己的估计更适合当所有列共享的
    先验（vol02/135 九列实测：中位数 108.4px，个别列自己的估计低至 104px、
    高至 115px）。

    `period_prior`（册的 `BookSpec.period_prior`）：给了就用它派生自相关窗口
    `[0.7×prior, 1.4×prior]`，把 2x 谐波关在窗外；不给就沿用 `estimate_period`
    的缺省 70–160，**行为逐位不变**。为什么必须跟着书走、以及固定窄窗为什么
    是死路，见 `estimate_period` 的 docstring。

    实测（北行日錄刻本 prior=70.6 → 窗口 [49, 98]）：884 列锁 2x 谐波 30.4% → 0%，
    页级中位偏离真值 >10px 的页 3 → 0；四庫總目三册 501 页页级 period 逐页不变。
    """
    kw = {}
    if period_prior:
        kw = {"lag_lo": max(2, int(period_prior * PERIOD_WINDOW_LO)),
              "lag_hi": max(4, int(period_prior * PERIOD_WINDOW_HI))}
    periods = []
    for row_proj, (x1, x2), dst_w in zip(row_projs, borders, dst_ws):
        curve = smooth_curve(np.asarray(row_proj, dtype=np.float64))
        thresh = blank_thresh_frac * dst_w
        cs, ce = trim_content_span(curve, x1, x2, thresh)
        if ce - cs < 20:
            continue
        periods.append(float(estimate_period(curve[cs:ce], **kw)))
    if not periods:
        raise ValueError("no column produced a usable period estimate")
    return float(np.median(periods))


# ── 弹性 DP ──────────────────────────────────────────────────


# ── Step 3 对外输出格式（→ Step 4）──────────────────────────
# 只有切分点是不够的：下游要知道每一格**是什么**（正文字/空白/双行小注的
# 哪一半），才谈得上装配文本与隔离字形。类型口径见 `CELL_KINDS`。

# 极低墨候选（见 fit_row_boundaries 里的说明）：墨量低于此比例×列宽的行直接进候选，
# 不问凸出度。0.02 是金标标定——4 条漏网的人裁切点墨量为 0.006~0.116×列宽，取 0.02
# 能捞回墨量最低的那两条（另两条靠「矮格墨满」代价 + 已有候选解决）。
def _runs_of(mask: np.ndarray) -> list[tuple[int, int]]:
    """布尔序列里连续 True 的段 [(起, 止含), ...]。"""
    out: list[tuple[int, int]] = []
    start: int | None = None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i - 1)); start = None
    if start is not None:
        out.append((start, len(mask) - 1))
    return out


# 极低墨候选（见 fit_row_boundaries 里的说明）：墨量低于此比例×列宽的行直接进候选，
# 不问凸出度——`find_valleys` 的凸出度过滤会把「浅而干净」的谷滤掉（vol01/68 c8 的
# 理想切点墨量只有 1px 却落选），而**代价项选不了一个不在候选集里的点**。
# 0.12 是 47 条人裁切线金标扫出来的：0.02/0.05/0.08/0.12 四档里 0.12 命中最多
# （moved 14/19）且不弄坏任何 ok（25/25 仍 0px）；0.05、0.08 反而各弄坏 1 条
# ——**不是单调的，别顺手往中间调**。
LOW_INK_FRAC = 0.12
LOW_INK_SEP = 12          # 与已有候选的最小间距（px），免得同一条缝挤进两个点

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
    suspect_jiazhu_body: bool = False  # 这一格可能是被缝位骗过的整宽正文字
                                        # （型 1），见
                                        # jiazhu_split.suspect_full_width_cells；
                                        # 只标记不改切分，人工审查用
    seam_top: list[int] | None = None
    seam_bottom: list[int] | None = None
    """折线切分（2026-09-05，见 `utils/seam.py`）：与上/下邻格之间的缝，列图坐标下每个 x
    （从内容窗口 `x0` 起）一个 y。None = 直线切点处没墨，格线就是直线。上缝：行 < y 的
    像素属上一格；下缝：行 ≥ y 的像素属下一格。只在 char–char 相邻且直线穿墨时才算。"""

    @property
    def sub(self) -> str | None:
        """夹注半格的 `"a"`/`"b"`，非夹注为 None（对齐生产 CharInstance.sub）。"""
        if self.kind == "jiazhu_a":
            return "a"
        if self.kind == "jiazhu_b":
            return "b"
        return None


@dataclass
class SeamCandidate:
    """切点的一条可选切线（列图坐标）。见 `products/kinds/cells.py` 同名模型。"""
    kind: str                      # straight | seam_narrow | seam_wide | unet_seam | period_up | period_dn（后三种是 L3 扩池加的）
    y: list[int] | None = None     # 折线逐列 y（从 content_x[0] 起）；straight 为 None
    seam_ink: int = 0
    dev_max: int = 0
    agree: float | None = None     # U-Net 裁判给的一致率 [0,1]（utils/cut_select.py）；没过裁判为 None
    dis_unet: int | None = None    # 与 U-Net 归属分歧的最大连通块面积 px（L2′ 升级门槛看它）


@dataclass
class CutPointCandidates:
    """第 k 个切点（slot k 与 slot k+1 之间）的全部候选。见 `products/kinds/cells.py`。"""
    k: int
    y: float                       # 直线位置（= boundaries[k]）
    slot_above: int
    slot_below: int
    candidates: list[SeamCandidate] = field(default_factory=list)
    chosen: int | None = None
    chosen_by: str | None = None   # rule（现役规则）| unet（裁判改选）| human（裁决表收敛）
    escalate: bool = False         # L2′：所选切法与 U-Net 分歧块 ≥ ESCALATE_BLOB，本层拿不准，交下游再审（不改选法）
    escalate_reason: str | None = None
    origin: str = "touching"       # touching（直线穿墨的粘连切点）| split_suspect（L0′：直线干净但一矮一高且矮格墨满）


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
    cut_candidates: list[CutPointCandidates] = field(default_factory=list)
    """直线格线穿墨的 char–char 相邻处的全部候选切线；下游可据此选切分方案。"""


def _bounded_elastic_dp(x1: float, x2: float, valleys: np.ndarray, valley_ink: np.ndarray,
                         period: float, eps: float, lo_ratio: float, hi_ratio: float,
                         y1_max_frac: float, y2_max_frac: float, lam: float,
                         n_slots: int, top_slack: float = 0.0,
                         curve: np.ndarray | None = None, blank_thresh: float = 0.0,
                         blank_cost: float = 0.05, blank_min_gap: float = 2.0,
                         tail_trim: bool = True,
                         blank_full_ratio: float = 0.8,
                         blank_cost_full: float = 0.01,
                         blank_lam_frac: float = 0.1,
                         blank_min_ratio: float = BLANK_MIN_RATIO,
                         drop_lam: float = 0.3,
                         lam4: float = 0.0,
                         mass_lam: float = 1.0,
                         mass_h: float = 0.79,
                         mass_min: float = 0.100,
                         cell_w: float = 0.0) -> list[float] | None:
    """弹性 DP。三层约束见模块头；2026-09-05 按切线金标（250 条）加了两条规则：

    **空白格不吃间距下界。** 列里少一个字（段末、抬头留白、脱字）时，原来每格硬性
    ≥ 0.7·period，缺的那一格只能摊到邻近 2–4 个字上，每条格线偏 30–58px——金标里
    21 条大幅错切有 19 条是这个（`.claude/doc/step3_touching_and_jiazhu.md` §1.2）。
    现在两候选之间**没有墨**（`curve` 在区间内最大值 < `blank_thresh`）就算空白格：
    高度只需 ≥ `blank_min_gap`，不吃 λ 的间距惩罚，但每个收固定代价 `blank_cost`
    ——不收的话 DP 会在宽缝里白造空白格、把两个矮字并成一格（实测最大偏差 243px）；
    0.05 与"切在墨上"的典型代价同量级，只有确实缺字时才划算。

    **列尾格按墨算高。** 列尾常有留白/版框残渣，最后一格若把它们全算进去就超过
    上界，DP 只好把倒数第二条格线往上挪进末字（金标里列尾格线占大幅错切 6/21）。
    `tail_trim` 时，到末锚点这一步的高度只算到最后一行有墨处。

    **整格空白便宜，碎空白贵（2026-09-08）。** `blank_cost` 一律 0.05 时，DP 宁可把
    首字劈成两格也不认那个空格位：vol01/17 c7「示」——首格空白 100px 后是「示」，
    顶横与「小」之间那道字内空隙墨量为 0，切在那里两格 127/85 的间距代价只有 0.025，
    而认空白格要 0.05，于是空格位被「示」的两半吃掉、整列格位错一位（两册前 50 页
    同型 6 列）。反过来 vol01/5 整页每列把 120px 的首格空白劈成两个 60px 空白格
    （21 格硬凑）。空白段高度 ≥ `blank_full_ratio`·period 的是**一个字位**，只收
    `blank_cost_full`；短的仍收 `blank_cost`——0.05 挡的是「宽缝里白造空白格、
    两个矮字并成一格」，那种缝远不到 0.8 格。

    **锚点之外的墨要计价（2026-09-08）。** 首锚点之上、末锚点之下的墨行不属于任何
    格，等于被丢掉，原来一分钱不收。于是 vol01/48 c5「五朝聖訓」抬头列：首锚点落
    在「五」的字内空隙（y=54），上半个「五」扔在格外，「五」的下半与「朝」并成一格
    （1.33 格高，代价只有 0.033），再用一个空白格凑满格数；vol01/60 c7「畜」、
    vol02/71 c7「殆」的末锚点落在字内，字的下沿留在格外被截断。现在两端各按
    `drop_lam × 丢掉的墨行数 / period` 计价——只数「有墨但不是框线级密行」的行
    （行墨 ≥ blank_thresh 且 < 0.5 列宽）：版框横线是密行，不该逼着锚点往框外跑。

    `curve` 为 None 时退回旧行为（无空白格规则、无尾裁）。
    """
    y1_max = y1_max_frac * period
    y2_max = y2_max_frac * period
    x1_eff = x1 - top_slack
    cand0 = [(v, ink) for v, ink in zip(valleys, valley_ink) if x1_eff <= v <= x1 + y1_max]
    candN = [(v, ink) for v, ink in zip(valleys, valley_ink) if x2 - y2_max <= v <= x2]
    if top_slack > 0:
        # **顶格 / 抬头列要显式补一个「窗口最上端」候选**（2026-09-03 加）。
        # 这类列的首字顶边贴着列图边缘，它**上面没有字缝**——`find_valleys`
        # 在那一带只挑得到首字**内部**的笔画间隙。实测：
        #   vol01/141 c7「諭」顶边 y=0，窗口 [-58,58] 内唯一候选 y=52（字内部）；
        #   vol01/33 c8 真墨起 y=33，窗口 [0,206] 内候选 72/150，全在墨之后。
        # DP 只能在这些点里挑，首字的头必然被切掉。把窗口往上开（`top_slack`）
        # 解决不了：开出去的区间里根本没有候选点。
        # 所以补一个 `max(0, x1 - top_slack)`（窗口最上端，夹到图内），墨量给 0
        # ——那一行要么是版框、要么是列图边缘，都不是字。DP 于是能在「切在字
        # 内」和「从窗口顶端起」之间按代价选，后者间距更接近 period、代价更低。
        # `top_slack > 0` 是 column_gate 给的「这一列可能顶格/抬头」信号。
        head = max(0.0, x1 - top_slack)
        if not any(abs(v - head) < 1e-6 for v, _ in cand0):
            cand0.append((head, 0.0))
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

    cmax = None if curve is None else np.asarray(curve, dtype=np.float64)
    # 曲线本身就是「每行的墨像素数」，前缀和一取就是任意区间的墨像素总数——
    # 「矮格墨满」判据要的绝对墨量正是它，不必另喂图（2026-09-08）。
    csum = None if cmax is None else np.concatenate(([0.0], np.cumsum(cmax)))

    # 性能（2026-09-10）：这几个内部函数在一列的 DP 里要调 3~8 万次，每次都是
    # 几十元素的小数组——numpy 的调用开销（连续几次 dtype 检查/ufunc 分派）比
    # 数据本身的计算量还大。数值上完全等价的前提下，改用 Python list + 前缀和，
    # 把「跨语言边界」的次数从 O(调用数×4) 降到 O(1)（这里，一次性转换）。
    cmax_list: list[float] = [] if cmax is None else cmax.tolist()
    csum_list: list[float] = [] if csum is None else csum.tolist()
    n_cmax = len(cmax_list)

    # 记忆化（2026-09-10）：DP 表填充时同一个候选点会在不同 (k, mp) 组合里反复
    # 当 y_prev/y 用——实测同一列里 round() 的实参重复率 99.8%（128 万次调用只有
    # 1948 个不同取值）。这几个函数只依赖取整后的 (a, b) 整数区间，缓存住就把
    # 「同一区间是否空白/墨量多少」的重复计算免掉，不改变任何返回值。

    @functools.lru_cache(maxsize=None)
    def _ink_mass_i(a: int, b: int) -> float:
        if not csum_list or cell_w <= 0:
            return 0.0
        a = min(max(a, 0), n_cmax)
        b = min(max(b, 0), n_cmax)
        return (csum_list[b] - csum_list[a]) / (period * cell_w)

    def _ink_mass(ya: float, yb: float) -> float:
        """[ya, yb) 的绝对墨量 = 墨像素 ÷（一格标准面积 period × 格宽）。

        分母用 **period** 而不是本格高：要问的正是「这一格里的墨够不够一个整字」，
        拿本格高归一化会把矮格自动抹平，恰恰抹掉信号（判据来源见
        `eval/touching.split_char_boundaries`，47 条人裁金标标定）。
        """
        return _ink_mass_i(round(min(ya, yb)), round(max(ya, yb)))

    @functools.lru_cache(maxsize=None)
    def _is_blank_i(a: int, b: int) -> bool:
        if not cmax_list:
            return False
        if b <= a:
            return True
        lo, hi = max(0, a), min(n_cmax, b + 1)
        if lo >= hi:
            return True
        # 手写短路循环，不切片：一旦见到 ≥ 阈值的行就能提前退出，不必扫完整段
        # 再取 max——「是否空白」本来就是「有没有一行墨够多」，不需要真的求最大值。
        for i in range(lo, hi):
            if cmax_list[i] >= blank_thresh:
                return False
        return True

    def _is_blank(ya: float, yb: float) -> bool:
        return _is_blank_i(round(min(ya, yb)), round(max(ya, yb)))

    dense_thresh = blank_thresh * (0.5 / 0.08)   # blank_thresh = 0.08·列宽 → 0.5·列宽

    @functools.lru_cache(maxsize=None)
    def _dropped_rows_i(a: int, b: int) -> int:
        if not cmax_list or drop_lam <= 0:
            return 0
        lo, hi = max(0, a), min(n_cmax, b)
        if lo >= hi:
            return 0
        return sum(1 for i in range(lo, hi) if blank_thresh <= cmax_list[i] < dense_thresh)

    def _dropped_rows(ya: float, yb: float) -> int:
        """[ya, yb) 里会被丢掉的字墨行数：有墨、且不是框线级密行。"""
        return _dropped_rows_i(round(min(ya, yb)), round(max(ya, yb)))

    @functools.lru_cache(maxsize=None)
    def _ink_end_i(a: int, b: int) -> int | None:
        """返回最后一行有墨的下标；没有就 None（由外层退回原始 ya）。"""
        lo, hi = max(0, a), min(n_cmax, b + 1)
        for i in range(hi - 1, lo - 1, -1):
            if cmax_list[i] >= blank_thresh:
                return i
        return None

    def _ink_end(ya: float, yb: float) -> float:
        """[ya, yb] 内最后一行有墨的位置；没有就返回 ya。"""
        if not cmax_list:
            return yb
        i = _ink_end_i(round(ya), round(yb))
        return ya if i is None else float(i)

    @functools.lru_cache(maxsize=None)
    def _near_blank_i(a: int, b: int) -> bool:
        lo, hi = max(0, a), min(n_cmax, b)
        if lo >= hi:
            return True
        # 本步里最长的零墨段 ≥0.45 格高 → 这一格多半是「留白 + 字」，不是纯字距
        need = 0.45 * period
        blank_run = 0
        for i in range(lo, hi):
            if cmax_list[i] < blank_thresh:
                blank_run += 1
                if blank_run >= need:
                    return True
            else:
                blank_run = 0
        return False

    def _near_blank(ya: float, yb: float) -> bool:
        """这一步的上下邻区间里有没有空白——有就别用四次方（见 step_cost）。

        邻区间按**一格 period** 量，不按本步高度：本步被留白撑大时，用本步高度去量
        会越过空白段、量到再上面的字，漏判（vol02/29 c6「不」、47 c3「言」两列的
        首字就这么被四次方切掉顶横）。再加一条：本步区间自身若含大段零墨（首字前的
        留白），也算挨着空白。"""
        if not cmax_list:
            return False
        if _is_blank(ya - period, ya) or _is_blank(yb, yb + period):
            return True
        return _near_blank_i(round(ya), round(yb))

    def step_cost(y_prev: float, y: float, last: bool = False,
                  interior: bool = True) -> float | None:
        gap = y - y_prev
        if gap < blank_min_gap:
            return None
        if _is_blank(y_prev, y):
            # 空白格：固定代价 + 很轻的间距项（λ 的 1/10）——只用来在等价切法之间
            # 偏向"接近一格高"，不然 DP 在整段空白里随便放，落点看候选顺序碰运气。
            # 上界收到 1.25·period：空白格是"一个字位"，1.7 格高的留白该是两个空白格
            # （vol01/141 c3：单个 160px 空白格让整列格位比人裁时少 1，裁决键全错位）。
            if gap > 1.25 * period:
                return None
            # 下界（2026-09-17）：空白格是「一个空着的字位」，不该只有十几像素。
            # 没有下界时 DP 会造碎空白格凑格数，害得后面整列相位错位——理由与
            # 实测分布见 BLANK_MIN_RATIO。首尾锚点那两段不走这里（它们由
            # y1_max/y2_max 管），所以这条只约束**列内**的空白格。
            if gap < blank_min_ratio * period:
                return None
            base = blank_cost_full if gap >= blank_full_ratio * period else blank_cost
            return base + blank_lam_frac * lam * ((gap - period) / period) ** 2
        g = gap
        lo_eff = lo_ratio * period
        if last and tail_trim:
            # 末格只算到最后一行有墨处；**墨的跨度本身仍要够半个字**——不能用下界去
            # 兜（vol01/141 c3：24px 的版框残渣被兜成"末格"，当成字送进识别），但也不能
            # 用整格下界 0.7 卡（vol01/140 c1：末字墨跨 75px = 0.67·period 是真字）。
            # 字的墨跨通常是 0.75–0.85 格，残渣 0.1–0.3 格，取 0.5 分界。
            g = _ink_end(y_prev, y) - y_prev
            lo_eff = 0.5 * period
        if not (lo_eff <= g <= hi_ratio * period):
            return None
        dev = (g - period) / period
        if not interior:
            return lam * dev ** 2
        # 紧挨空白格的那一步也不吃四次方：空白格的高度本来就被留白撑得不规则，
        # 加四次方会逼 DP 少认一个空白格、把首字劈成两格（实测 vol02/37 c3「京」
        # 0.076+0.196、41 c8「事」0.037+0.174 两列）。
        # lam4：极端偏离的四次方项（2026-09-08，vol01/36 c9「辩」、vol02/107 c8「書」）。
        # 上字与本字粘连、本字内部又有一道零墨空隙时，DP 把格线放进字内：一格 1.3P
        # + 一格 0.73P 的二次方代价只有 0.049，而切在粘连处要穿 0.15~0.3 的墨。四次方
        # 项在 ±15% 内几乎为零（0.0076×lam4/15），到 ±30% 才起作用，专治这种劈法。
        # **默认关（lam4=0）**：它确实能治 vol01/36 c9「辩」、vol02/107 c8「書」这类
        # 「上字粘连 + 本字内有零墨空隙」的劈字，但两册 p1–50 全量 A/B 显示它同时会把
        # 首字的顶横切掉——不设边界时误伤 6 列（京/注/事/言/割/不），限定「不挨锚点」
        # 后仍误伤 2 列，再补「不挨空白格」后 vol02/29 c6「不」仍救不回来。收益与代价
        # 纠缠在同一个量（格高偏离）上，靠加条件分不开；**要分开得有切线金标说话**
        # ——现有金标 243 条里没有这类样本。参数与实测留着，等金标扩到这类样本再定。
        # 打开前必读：`.claude/doc/segmentation_v2_pipeline.md`「切分缺陷逐类清账」。
        cost = lam * dev ** 2
        # 「矮格墨满」代价（2026-09-08，47 条人裁金标标定）：这一格既比正常字矮
        # （≤mass_h×period），墨量却够一个整字（≥mass_min）——那是被劈开的半个字，
        # 不是「一」「二」那样的扁字。金标实测扁字 0.034~0.066、半个字 0.105~0.195。
        # 只罚不禁：真有连续两个矮字时 DP 仍走得通，只是代价高一点。
        if mass_lam > 0 and g <= mass_h * period:
            m = _ink_mass(y_prev, y)
            if m >= mass_min:
                cost += mass_lam * (m - mass_min) / mass_min
        if _near_blank(y_prev, y):
            return cost
        return cost + lam4 * dev ** 4

    best: tuple[float, float, list[float], float] | None = None
    drop_cost_N = {vN: drop_lam * _dropped_rows(vN, x2) / period for vN, _ in candN}
    # 性能（2026-09-14）：内部转移代价 step_cost(mid[mp], mid[m]) 只依赖 (mp, m)，与格序 k、
    # 首锚点 v0 都无关，原来却在 k × v0 的循环里反复算（一列 150 万次调用，占 Step3 94% 时间）。
    # 先算一张 (m_count × m_count) 的代价矩阵 C（mp ≥ m 置 inf，等价于原来只遍历 mp < m），
    # 再按 k 向量化填表。**数值逐位相同**：total 的加法顺序保持 ((prev + c) + ink) + eps，
    # argmin 取首个最小值 = 原来「严格小于才更新」的取法（最小的 mp 胜出）。
    mid_y = [y for y, _ in mid]
    mid_ink = np.array([ink for _, ink in mid], dtype=np.float64)
    C = np.full((m_count, m_count), np.inf)
    for m in range(m_count):
        y = mid_y[m]
        for mp in range(m):
            c = step_cost(mid_y[mp], y)
            if c is not None:
                C[mp, m] = c
    col_idx = np.arange(m_count)
    for v0, _ink0 in cand0:
        drop_cost_0 = drop_lam * _dropped_rows(x1_eff, v0) / period
        dp_cost = np.full((n_interior, m_count), np.inf)
        dp_prev = np.full((n_interior, m_count), -1, dtype=int)
        for m in range(m_count):
            y, ink = mid[m]
            c = step_cost(v0, y, interior=False)
            if c is not None:
                dp_cost[0, m] = c + ink + eps + drop_cost_0
        for k in range(1, n_interior):
            tot = dp_cost[k - 1][:, None] + C
            tot = tot + mid_ink[None, :]
            tot = tot + eps
            arg = np.argmin(tot, axis=0)
            mn = tot[arg, col_idx]
            fin = np.isfinite(mn)
            dp_cost[k, fin] = mn[fin]
            dp_prev[k, fin] = arg[fin]
        k_last = n_interior - 1
        for m in range(m_count):
            if not np.isfinite(dp_cost[k_last, m]):
                continue
            y, _ = mid[m]
            for vN, _inkN in candN:
                c = step_cost(y, vN, last=True, interior=False)
                if c is None:
                    continue
                total = dp_cost[k_last, m] + c + drop_cost_N[vN]
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
                        lo_ratio: float = 0.7, hi_ratio: float = 1.5,
                        y1_max_frac: float = 0.5, y2_max_frac: float = 0.3,
                        blank_thresh_frac: float = 0.08, synth_step: int = 20,
                        top_slack: float = 0.0, snap_raw: int = 3,
                        blank_cost: float = 0.05, tail_trim: bool = True,
                        blank_full_ratio: float = 0.8,
                        blank_cost_full: float = 0.01,
                        blank_lam_frac: float = 0.1,
                        blank_min_ratio: float = BLANK_MIN_RATIO,
                        drop_lam: float = 0.3,
                        lam4: float = 0.0,
                        mass_lam: float = 1.0,
                        mass_h: float = 0.79,
                        mass_min: float = 0.100) -> RowBoundaryResult | None:
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
    # **空白区间里的真波谷要留下**（2026-09-03 改）。原先这里无条件剔除
    # `in_any_interval` 的真波谷、只留合成候选，于是 DP 在一堆假墨 0.03 的
    # 等间隔点里挑，挑中的点真实墨量可能远高于 0.03 —— 实测 vol01/24c1 格13：
    # 真波谷 y=1357 墨 0.000 被扔掉，换成合成点 y=1345（假墨 0.03、真墨 0.039），
    # DP 选了后者，格线穿字。按代价函数算干净点优 25 倍（0.0016 vs 0.0410），
    # 不是权重问题，是那个点**根本没进候选集**。
    # dev_set 实测：穿字格线 693 条里 318 条（46%）附近就有这样被扔掉的干净波谷。
    valid = list(valleys_all)
    valley_ink = [curve[v] / dst_w for v in valid]

    # **极低墨的行一律进候选**（2026-09-08，47 条人裁金标）：`find_valleys` 的凸出度
    # 过滤（prom_frac=0.10）会把「浅而干净」的谷滤掉——vol01/68 c8 人裁切点 y=698 墨量
    # 只有 1px（几乎全白，理想切点），却因为两侧抬升不够而落选，DP 只好切在 716（切进
    # 字里）。19 条 moved 里有 4 条是这个原因，加「矮格墨满」代价也救不回来：**代价项
    # 选不了一个不在候选集里的点**。
    # 只补墨量 < LOW_INK_FRAC×列宽 的行，且离已有候选 ≥`synth_guard`，不放宽凸出度
    # ——后者会让每列的候选点暴涨、把真字缝淹掉。
    # 连成一段的低墨行**只取一个代表点**（段中心）：整段逐行进候选时，DP 会在这一段
    # 里随便挑一个，把本来已经对的切点挤掉——实测 vol02/127 c1 人裁点 1520 自己就是
    # 波谷，却因为 1516~1533 同样零墨、全部进了候选而被挤到 1532（差 12px）。
    lowmask = np.asarray(curve) < LOW_INK_FRAC * dst_w
    for a, b in _runs_of(lowmask):
        y = (a + b) // 2
        if in_any_interval(y, intervals):
            continue          # 空白区间自有合成候选（synth），别在整段留白里再撒点
        if all(abs(y - v) >= LOW_INK_SEP for v in valid):
            valid.append(float(y))
            valley_ink.append(float(curve[y]) / dst_w)

    # 空白区间里若没有真波谷，仍补一批合成候选撑住可行性——**墨量必须用真值**
    # （2026-09-03 二改）。原先一律给固定 0.03，而空白区间的判据是
    # `< blank_thresh_frac`（默认 0.08），所以合成点的真实墨量最高可以到 0.08，
    # 给 0.03 等于**系统性低报**，DP 拿它跟真波谷比就被骗了：
    # 实测 vol01/26c2 格3 选中的合成点真墨 0.231（该处在"空白区间"里是因为
    # 区间按 8% 门槛切、这一小段冲高没把区间断开），旁边 23px 处有真波谷墨 0.000，
    # 代价 0.2554 vs 0.0524 干净点优 5 倍却没选上。
    # 一改（只保留区间内真波谷）之后仍有 90/462 条穿字是这个原因，全部
    # `选中点 ∉ find_valleys`——即全是合成点。用真墨之后它们不再有虚假优势；
    # 空白区真正空的地方墨本来就是 0，撑可行性的作用一点没丢。
    # 只在**离真波谷足够远**的位置补，免得同一条字缝既有真点又有假点。
    synth_guard = max(6, synth_step // 3)
    synth: list[float] = []
    synth_ink: list[float] = []
    for lo, hi in intervals:
        y = lo
        while y <= hi:
            if all(abs(y - v) >= synth_guard for v in valid):
                synth.append(float(y))
                synth_ink.append(float(curve[int(y)]) / dst_w if 0 <= int(y) < len(curve) else 0.03)
            y += synth_step

    all_valleys = np.array(valid + synth, dtype=np.float64)
    all_ink = np.array(valley_ink + synth_ink, dtype=np.float64)
    order = np.argsort(all_valleys)
    all_valleys, all_ink = all_valleys[order], all_ink[order]

    # hi_ratio 默认 1.35 → 1.5（2026-09-05）：高字 + 矮字相邻时 1.35 卡死在真缝外 2px
    # （vol01/46 c7：真缝 2274 到底 2432 是 158px = 1.36×period），DP 被迫把线挪进末字；
    # 1.45 / 1.5 / 1.6 在 250 条金标上结果相同，取 1.5。并字的风险由 blank_cost 与
    # 墨量代价挡住（实测 R2 未增）。
    boundaries = _bounded_elastic_dp(
        border_top, border_bottom, all_valleys, all_ink, period, eps,
        lo_ratio, hi_ratio, y1_max_frac, y2_max_frac, lam, n_slots, top_slack,
        curve=curve, blank_thresh=thresh, blank_cost=blank_cost, tail_trim=tail_trim,
        blank_full_ratio=blank_full_ratio, blank_cost_full=blank_cost_full,
        blank_lam_frac=blank_lam_frac, blank_min_ratio=blank_min_ratio,
        drop_lam=drop_lam, lam4=lam4,
        mass_lam=mass_lam, mass_h=mass_h, mass_min=mass_min, cell_w=float(dst_w),
    )
    if boundaries is None and blank_min_ratio > 0.0:
        # 空白格下界是**偏好**不是硬约束：它挡的是「造碎空白格凑格数」，可有些列
        # （版式本身就有半格留白、或列尾残段）加了下界就整列无解——无解比相位错位
        # 更糟（这一列一个字都切不出来）。北行日錄全书 952 列实测：不回退时 7 列
        # 由有解变无解，回退后 0 列。所以先按下界解，解不出来再放开重来。
        boundaries = _bounded_elastic_dp(
            border_top, border_bottom, all_valleys, all_ink, period, eps,
            lo_ratio, hi_ratio, y1_max_frac, y2_max_frac, lam, n_slots, top_slack,
            curve=curve, blank_thresh=thresh, blank_cost=blank_cost, tail_trim=tail_trim,
            blank_full_ratio=blank_full_ratio, blank_cost_full=blank_cost_full,
            blank_lam_frac=blank_lam_frac, blank_min_ratio=0.0,
            drop_lam=drop_lam, lam4=lam4,
            mass_lam=mass_lam, mass_h=mass_h, mass_min=mass_min, cell_w=float(dst_w),
        )
    if boundaries is None:
        return None
    boundaries = _snap_to_raw_minimum(boundaries, np.asarray(row_proj, dtype=np.float64),
                                      snap_raw)
    return RowBoundaryResult(
        boundaries=boundaries, blank_intervals=intervals, valleys=valleys_all, period=period,
    )


def _snap_to_raw_minimum(bounds: list[float], raw: np.ndarray, radius: int) -> list[float]:
    """DP 定完位后，把每条边界在**原始**投影上微调到最近的更低点（±radius）。

    DP 全程跑在 `smooth_curve`（5 点均值）上——平滑是必须的，否则笔画间的小
    凹陷会制造大量噪声候选（模块头「候选只从波谷来」那条）。代价是**只有一
    两行宽的真字缝会被抹平**：实测 vol01/70c1，原始投影 y=1495 是 0.0000 的
    真缝，平滑后变成 0.0365，反而高于 y=1494 的 0.0343，DP 于是选了 1494，
    格线压在笔画上。这类窄缝正是刻本字距紧时的常态。

    微调只在 ±`radius` 内找原始投影的更低点，**不改变格位归属**（radius 远
    小于半个字距），也不影响 DP 的可行性判断——间距变化至多 2·radius。
    平局取离 DP 原选最近的，保持确定性。radius=0 关掉。
    """
    if radius <= 0 or raw.size == 0:
        return bounds
    n = raw.size
    out: list[float] = []
    for b in bounds:
        i = int(round(b))
        if not (0 <= i < n):
            out.append(b)
            continue
        lo, hi = max(0, i - radius), min(n, i + radius + 1)
        seg = raw[lo:hi]
        best_v = float(seg.min())
        if best_v < raw[i]:
            ties = [j for j in range(lo, hi) if raw[j] == best_v]
            out.append(float(min(ties, key=lambda j: (abs(j - i), j))))
        else:
            out.append(b)
    return out


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


def effective_body_slots(n_body: int, border_top: float | None, border_bottom: float | None,
                         period: float | None, tol: float = 0.55) -> int:
    """这一列的版框装得下几格正文：装不下 `n_body` 就少一格。

    2026-09-08 两册前 50 页普查：vol01/5、vol02/26、vol02/47 的版框高只有 20.0~20.4
    个 period（书的版式常量是 21 行），硬切 21 格时 DP 只能造一格假空白——vol01/5
    整页每列把 120px 的首格空白劈成两个 60px 空白格，vol02/26、47 劈成三个
    60/80/80，整列格位错一位，人裁标注的键也跟着漂。

    只往下调**一格**：版框高比 `n_body - tol` 个 period 还矮就按实际行数；矮得更多
    的（版框探测本身失败）不动，让 DP 照旧无解报错，别把探测失败静默成少切几格。
    """
    if border_bottom is None or not period or period <= 0:
        return n_body
    rows = (float(border_bottom) - max(0.0, float(border_top or 0.0))) / float(period)
    if n_body - 1 - tol <= rows < n_body - tol:
        return n_body - 1
    return n_body


RESOLVED_CHOSEN = "chosen"
"""`ResolvedCut.kind` 的特殊值：人说「现役那条折线就对」（`seam_ok`），收敛到
`cands[chosen]`——前提是现役选中的确实是折线，现役走直线时这条裁决对不上，不动。"""

RESOLVED_Y_TOL = 3.0
"""裁决带参考 y 时，现役直线切点与它差超过这个像素数就不套用：裁决是对着**当时**
的切点做的（touching-cuts README「坐标系」节），切点挪了就不是同一条格线了。
touching-cuts 评测口径 ≤3 / ≤5 / ≤10 px，取最严一档。"""


RESOLVED_SEAM_TOL = 4.0

SPLIT_SHORT, SPLIT_TALL, SPLIT_MASS_MIN = 0.79, 1.05, 0.10
"""L0′「切进字里」嫌疑（2026-09-15，10 卡）：直线格线不穿墨、看着干净，但相邻两格一个 ≤0.79·中位格高、
一个 ≥1.05·中位格高，且**矮格的绝对墨量**（墨像素 ÷ 中位格高×格宽）≥0.10——矮格里装的不是「一」「二」那种扁字
而是被劈开的半个字。判据与门槛照搬 `eval/touching.split_char_boundaries`（47 条人裁金标标定：ok 0.034~0.066、
moved 0.105~0.195）。vol02 全书 23089 条干净 char–char 格线里一高一矮的 109 条（0.6/页），再经墨量过滤更少。
这类格线以前根本不建切点（文言 vol02:163:1:6：DP 把言的顶横切给文，直线落在言字内部的空隙上，全链路视而不见）；
现在建一个只有直线的切点并过 U-Net 探针，分歧大就 `escalate`，选法不改。"""
"""`seam_ok` 收敛的折线护栏：候选折线与人当时看到的折线（裁决里的 polyline）逐 x 最大偏差
超过这个像素数就不是同一条缝。2026-09-14 vol02 p33 c9 s18 实锤：人确认的是窄走廊（偏 12px），
重跑后规则改选了宽走廊（偏 21px、直线 y 没变），`RESOLVED_CHOSEN` 按「现役选中」收敛就把宽走廊
当成了人裁（金标误差 8→198px）。有 polyline 就按折线找，池里没有一致的就**不收敛**（留给裁判/人）。"""


def _polyline_to_seam(points: list, x0: int, x1: int) -> list[int]:
    """人标折线（列图坐标 [[x, y], …]）→ 每个 x∈[x0, x1) 一个 y（线性插值，两端水平延伸）。
    与 `eval/touching.polyline_to_seam` 同口径（utils 不 import eval，抄一份）。"""
    pts = sorted((float(x), float(y)) for x, y in points)
    if not pts:
        return []
    xs = [x for x, _ in pts]
    ys = [y for _, y in pts]
    out = []
    for x in range(int(x0), int(x1)):
        if x <= xs[0]:
            out.append(int(round(ys[0])))
            continue
        if x >= xs[-1]:
            out.append(int(round(ys[-1])))
            continue
        j = 1
        while xs[j] < x:
            j += 1
        xa, ya, xb, yb = xs[j - 1], ys[j - 1], xs[j], ys[j]
        t = (x - xa) / (xb - xa) if xb > xa else 0.0
        out.append(int(round(ya + t * (yb - ya))))
    return out


@dataclass
class ResolvedCut:
    """一条切点的人裁结论（来自 workspace 裁决表，见 `feedback/lookup.py`）。"""
    kind: str                      # straight / seam_narrow / seam_wide / RESOLVED_CHOSEN
    y_ref: float | None = None     # 裁决时的直线切点 y（列图坐标）；None = 不设护栏
    seam_ref: list | None = None   # `seam_ok` 时人看到的折线 [[x, y], …]（列图坐标）；None = 老裁决，按现役选中收敛


def _apply_resolved_cut(cands: list[SeamCandidate], chosen: int,
                         resolved: "str | ResolvedCut | None",
                         y_line: float | None = None,
                         x_lo: int | None = None) -> tuple[list[SeamCandidate], int]:
    """人裁回流（2026-09-13）：`resolved` 是裁决表对这条切点的结论，命中候选池里
    同 kind 的那条就把候选收敛成它一个——顺序闸按 `len(candidates)>=2` 判阻塞
    （`review/cards.py::cut_pending`），收敛后自动放行，不用改闸的代码。

    三种不动的情况（静默套错误的收敛比继续挡人更危险）：
    - `resolved` 为 None（未裁决）；
    - 候选池里没有这个 kind（几何变了、这次没算出裁决认定的那种切法）；
    - 裁决带 `y_ref` 而现役直线 `y_line` 与它差 > `RESOLVED_Y_TOL`（切点已不是当时那条）。
    `kind == RESOLVED_CHOSEN`（`seam_ok`）：裁决带 `seam_ref`（人看到的折线）且给了 `x_lo` 时，
    在池里找逐 x 最大偏差 ≤ `RESOLVED_SEAM_TOL` 的折线候选（现役选中优先）收敛，找不到就不动
    ——规则这次选的缝可能已不是人看到的那条；没有 `seam_ref`（老裁决）沿用旧口径：收敛到现役选中的折线，
    现役是直线时不动。"""
    if resolved is None:
        return cands, chosen
    if isinstance(resolved, str):
        resolved = ResolvedCut(resolved)
    if (resolved.y_ref is not None and y_line is not None
            and abs(float(y_line) - float(resolved.y_ref)) > RESOLVED_Y_TOL):
        return cands, chosen
    if resolved.kind == RESOLVED_CHOSEN:
        if resolved.seam_ref and x_lo is not None and cands:
            for i in [chosen] + [j for j in range(len(cands)) if j != chosen]:
                c = cands[i]
                if c.y is None:
                    continue
                ref = _polyline_to_seam(resolved.seam_ref, x_lo, x_lo + len(c.y))
                if len(ref) == len(c.y) and max(abs(int(a) - int(b)) for a, b in zip(c.y, ref)) <= RESOLVED_SEAM_TOL:
                    return [c], 0
            return cands, chosen
        if not cands or cands[chosen].kind == "straight":
            return cands, chosen
        return [cands[chosen]], 0
    match_idx = next((i for i, c in enumerate(cands) if c.kind == resolved.kind), None)
    if match_idx is None:
        # 人裁说「直线就对」，但第 3 步的收缩规则（窄走廊零墨且贴线 → 直线不算真候选）把直线删了：
        # 卡片上仍画着直线、人也能选它，收敛却落空（2026-09-15 实锤 23 条）。直线不依赖几何搜索，
        # 按切点位置补回一条即可；其余 kind 找不到仍原样不动（那是几何真的变了）。
        if resolved.kind == "straight":
            return [SeamCandidate(kind="straight", y=None, seam_ink=0, dev_max=0)], 0
        return cands, chosen
    return [cands[match_idx]], 0


def segment_column(col_gray: np.ndarray, period: float, n_body_slots: int = 21,
                    n_raised: int = 0, *,
                    border_top: float = 0.0, border_bottom: float | None = None,
                    ref_w: float | None = None, top_slack: float = 0.0,
                    content_x: tuple[float, float] | None = None,
                    ink_threshold: int = 128, min_ink_ratio: float = 0.01,
                    raise_tol: float = 2.0, detect_jiazhu: bool = True,
                    seam_band: int = 20,
                    resolved_cuts: "dict[int, str | ResolvedCut] | None" = None,
                    cut_judge=None,
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
    - `resolved_cuts`：`{slot_above: 候选 kind 或 ResolvedCut}`，人裁回流用（2026-09-13）。
      `ResolvedCut` 可带 `y_ref`（裁决时的直线 y）做护栏，`kind=RESOLVED_CHOSEN`
      表示「现役折线就对」；细节见 `_apply_resolved_cut`。
      命中的切点直接把 `cut_candidates` 收敛成那一条候选（`chosen=0`），
      不再是"多候选"——顺序闸（`review/cards.py::cut_pending`）按
      `len(candidates)>=2` 判阻塞，收敛之后这条切点自动放行，不用改闸的代码。
      **数据来源是 workspace 里的裁决表**（`feedback/lookup.py::resolved_cuts`），
      不是 `open-guji-dataset` 的金标——生产管线运行时不读测试集仓（用户裁定；
      第一版从 dataset 取、已撤）。取的时候只收人从候选池里选中了某一 kind 的
      裁决（`overlap`/`idk` 是真难例，仍要留给人，见
      `.claude/doc/row_boundaries_design.md`「5 条都不对」节）。裁决认定的 kind
      不在候选池里（比如几何变了，候选池不再产出 `seam_narrow`）时
      **原样不收敛**——按旧逻辑走多候选，静默套错误的收敛比继续挡人更危险。
    - `cut_judge`：候选池裁判（`utils/cut_select.get_judge()` 的 U-Net），None = 只用现役规则。
      候选池经现役规则、收缩、**人裁回流**之后仍 ≥2 条（人没裁过）时，用它给每条候选打一致率、
      改选高出门槛的最优者。人裁在前：`seam_ok` 收敛的是人当时看到的现役折线。见 `utils/cut_select.py` 模块头。
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
    suspect: set[int] = set()
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
        suspect = jiazhu_split.suspect_full_width_cells(runs, patches, ink_threshold)
        # 單行小注（小字只占右半、左半空着）：zongmu 两册没有这种版式，原判据
        # 测不到（跨度比正文还窄，方向相反），bxgb 大量用它给人名作注。
        # 只在非空白、且不属于双行段的格上找；找到的一律只发 a 半。
        solo = jiazhu_split.solo_notes(
            {p: patches[p] for p in nonblank}, runs, ruler, ink_threshold)
        runs.update(solo)
        tail_a |= set(solo)

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
                                  ink_ratio=round(_ink_ratio(half, ink_threshold), 4),
                                  suspect_jiazhu_body=(pos in suspect)))
            continue
        kind = "blank" if pos not in nonblank else "char"
        cells.append(Cell(slot=slot, y0=y0, y1=y1, x0=float(x_lo), x1=float(x_hi),
                          kind=kind, raised=raised, ink_ratio=round(inks[pos], 4)))

    for i, c in enumerate(reading_order(cells), start=1):
        c.order = i

    # ── 折线切分：直线格线穿墨的 char–char 相邻处，在 ±seam_band 走廊里找最小墨量缝 ──
    # 用户 2026-09-05 观察 + 实验（doc §1.4）：人标"重叠"的 205 条里 183 条存在无墨折线。
    # 缝只在走廊里走，"哪两个字之间"仍由上面的 DP 决定。
    #
    # 2026-09-10：候选不再丢弃。每个切点把「直线／窄走廊／宽走廊」记进
    # `cut_candidates`，`chosen` 标出现役规则选中的那条——**选择规则一字未改**，
    # 下游（Step5）可据此对每个候选各认一次上下两字再挑。留着的候选是攒给
    # 打分函数的样本（用户 2026-09-10：样本多了就容易设计新的）。
    # 当日查「多候选但差异极小」：结论是**池子已经是最小的**——全册 2798 条入池折线
    # 候选里，0 条不省墨（即每一条都既偏了又真绕开了墨）。下面第 2 步的过滤是把这个
    # 不变量**显式写出来**，现在恒不触发，是留给将来放宽 append 条件时的守卫。
    if seam_band > 0:
        from . import seam as _seam
        ink_bin = (col_gray[:, x_lo:x_hi] < ink_threshold)
        by_pos: dict[int, list[Cell]] = {}
        for c in cells:
            by_pos.setdefault(_slot_to_pos_local(c.slot, n_raised), []).append(c)
        cut_cands: list[CutPointCandidates] = []
        char_hs = sorted(c.y1 - c.y0 for c in cells if c.kind == "char" and c.sub is None)
        med_h = float(char_hs[len(char_hs) // 2]) if char_hs else 0.0
        content_w = max(1, x_hi - x_lo)

        def _split_suspect(u: Cell, d: Cell) -> bool:
            """L0′ 嫌疑：一矮一高，且矮格墨满（见 SPLIT_* 常量）。"""
            if med_h <= 0:
                return False
            hu, hd = u.y1 - u.y0, d.y1 - d.y0
            if hu <= SPLIT_SHORT * med_h and hd >= SPLIT_TALL * med_h:
                short = u
            elif hd <= SPLIT_SHORT * med_h and hu >= SPLIT_TALL * med_h:
                short = d
            else:
                return False
            a, b = max(0, int(round(short.y0))), min(h, int(round(short.y1)))
            if b <= a:
                return False
            mass = float(ink_bin[a:b].sum()) / (med_h * content_w)
            return mass >= SPLIT_MASS_MIN

        def _resolve_and_probe(cands, chosen, up_c, dn_c, k_):
            """第 4 步人裁回流 + 第 5 步 U-Net 探针/裁判；两类切点（粘连 / L0′ 嫌疑）共用。"""
            chosen_by = "rule"
            resolved = (resolved_cuts or {}).get(up_c.slot)
            n_before = len(cands)
            cands, chosen = _apply_resolved_cut(cands, chosen, resolved,
                                                y_line=float(bounds[k_]), x_lo=int(x_lo))
            if len(cands) < n_before:
                chosen_by = "human"
            escalate, escalate_reason = False, None
            if cut_judge is not None and cands:
                res = cut_judge.assess(col_gray, x_lo, x_hi, int(round(up_c.y0)), int(round(dn_c.y1)),
                                       float(bounds[k_]), [c.y for c in cands], ink_threshold=ink_threshold)
                if res is not None and len(res[0]) == len(cands):
                    from .cut_select import ESCALATE_BLOB, JUDGE_MARGIN, PENDING_BLOB
                    sc, dis = res
                    for c, s_, d_ in zip(cands, sc, dis):
                        c.agree = s_
                        c.dis_unet = int(d_)
                    if len(cands) >= 2:
                        best = max(range(len(cands)), key=lambda i: (sc[i], i == chosen))
                        if best != chosen and sc[best] - sc[chosen] >= JUDGE_MARGIN and chosen_by != "human":
                            chosen = best
                            chosen_by = "unet"          # 只有真改选了才记 unet
                    if chosen_by != "human" and dis[chosen] >= PENDING_BLOB:
                        # L3 扩池的触发点与**顺序闸**同门槛（2026-09-15 夜改）：原来只在 ≥ESCALATE_BLOB(100)
                        # 时扩池，于是 60–100 这一档（顺序闸要挡、人要裁的那 82 条）卡片上根本没有 U-Net 缝
                        # 可选——用户实裁时发现「这些 U-Net 都能找到更好结果」。凡是要交给人或下游的切点，
                        # 都该先把候选补齐（原则 ①：给人最好的选项）。
                        cands = _expand_pool(cands, up_c, dn_c, k_)
                        if dis[chosen] >= ESCALATE_BLOB:
                            escalate = True
                            escalate_reason = f"dis_unet={dis[chosen]}>={ESCALATE_BLOB} n_cand={len(cands)}"
                        # 人裁**指向 L3 才生成的候选**（unet_seam / period_*）时，第 4 步收敛必然落空
                        # ——那时池里还没有这个 kind。扩池之后再试一次（2026-09-15 实锤：147 条人裁里
                        # 119 条因此没生效）。收敛成功就不再是「升级」，人是终审。
                        if resolved is not None and chosen_by != "human":   # 扩池后人裁可能才匹配得上
                            n2_ = len(cands)
                            cands, chosen = _apply_resolved_cut(cands, chosen, resolved,
                                                               y_line=float(bounds[k_]), x_lo=int(x_lo))
                            if len(cands) < n2_:
                                chosen_by = "human"
                                escalate, escalate_reason = False, None
            return cands, chosen, chosen_by, escalate, escalate_reason

        def _expand_pool(cands, up_c, dn_c, k_):
            """L3 扩池（2026-09-15，10 卡）：只对升级的切点，**只加候选不改选法**。
            新候选：`unet_seam`（U-Net 引导缝，见 cut_select.guided_seam_from_owner）、`period_up`/`period_dn`
            （以「上格顶 + 中位格高」「下格底 − 中位格高」为中心搜的最小墨缝——DP 把格线放偏时正确缝常在这里）。
            与池里已有的逐 x 相同就不重复加；每条都补 agree / dis_unet 供下游（L4 / 人）比较。
            实验十（vol02 152 条升级点）：有金标的 3 条正确缝全部由 unet_seam 进池；扩池后仍与 U-Net 分歧 ≥100 的 33 条
            是整字翻边 / 两字并一格这类结构性错，留给人。"""
            y_line = float(bounds[k_])
            n = x_hi - x_lo
            extra: list[tuple[str, np.ndarray]] = []
            gs = getattr(cut_judge, "guided_seam", None)
            if gs is not None:
                sm = gs(col_gray, x_lo, x_hi, int(round(up_c.y0)), int(round(dn_c.y1)), y_line, ink_threshold=ink_threshold)
                if sm is not None and len(sm) == n:
                    extra.append(("unet_seam", np.asarray(sm, dtype=int)))
            if med_h > 0:
                from . import seam as _seam2
                for kind, center in (("period_up", int(round(up_c.y0 + med_h))), ("period_dn", int(round(dn_c.y1 - med_h)))):
                    if 0 < center < h and abs(center - y_line) >= 4:
                        sm = _seam2.find_seam(ink_bin, center, band=_seam2.SEAM_BAND)
                        extra.append((kind, np.asarray(sm, dtype=int)))
            have = [tuple(int(v) for v in (c.y if c.y is not None else np.full(n, int(round(y_line))))) for c in cands]
            new_c: list[SeamCandidate] = []
            for kind, sm in extra:
                key = tuple(int(v) for v in sm)
                if key in have:
                    continue
                have.append(key)
                new_c.append(SeamCandidate(kind=kind, y=[int(v) for v in sm],
                                           seam_ink=int(ink_bin[np.clip(sm, 0, h - 1), np.arange(n)].sum()),
                                           dev_max=int(np.abs(sm - y_line).max())))
            if not new_c:
                return cands
            res = cut_judge.assess(col_gray, x_lo, x_hi, int(round(up_c.y0)), int(round(dn_c.y1)), y_line,
                                   [c.y for c in new_c], ink_threshold=ink_threshold)
            if res is not None and len(res[0]) == len(new_c):
                for c, s_, d_ in zip(new_c, res[0], res[1]):
                    c.agree = s_
                    c.dis_unet = int(d_)
            return list(cands) + new_c

        for k in range(1, n_slots):
            up, dn = by_pos.get(k, []), by_pos.get(k + 1, [])
            if len(up) != 1 or len(dn) != 1 or up[0].kind != "char" or dn[0].kind != "char":
                continue
            y = int(round(bounds[k]))
            if not (0 <= y < h):
                continue
            if not ink_bin[y].any():
                # L0′（2026-09-15）：干净格线里的「切进字里」嫌疑也建切点（只有直线一条）并过探针，
                # 其余干净格线仍旧不建切点。见 SPLIT_* 常量的说明。
                if not _split_suspect(up[0], dn[0]):
                    continue
                cands = [SeamCandidate(kind="straight", y=None, seam_ink=0, dev_max=0)]
                cands, chosen, chosen_by, escalate, escalate_reason = _resolve_and_probe(cands, 0, up[0], dn[0], k)
                if escalate_reason:
                    escalate_reason = "split_suspect " + escalate_reason
                cut_cands.append(CutPointCandidates(k=k, y=float(bounds[k]),
                                                    slot_above=up[0].slot, slot_below=dn[0].slot,
                                                    candidates=cands, chosen=chosen, chosen_by=chosen_by,
                                                    escalate=escalate, escalate_reason=escalate_reason,
                                                    origin="split_suspect"))
                if cands[chosen].kind != "straight":   # 人裁收敛到折线时照写 seam_*
                    up[0].seam_bottom = cands[chosen].y
                    dn[0].seam_top = cands[chosen].y
                continue
            # 1) 直线永远是候选（dev_max=0，也是不切时的兜底）
            cands = [SeamCandidate(kind="straight", y=None, seam_ink=0, dev_max=0)]
            straight_ink = int(ink_bin[y].sum())
            sm = _seam.find_seam(ink_bin, y, band=seam_band)
            if int(np.abs(sm - y).max()) > 0:
                cands.append(SeamCandidate(kind="seam_narrow", y=sm.tolist(),
                                           seam_ink=int(_seam.seam_ink(ink_bin, sm)),
                                           dev_max=int(np.abs(sm - y).max())))
            if _seam.seam_ink(ink_bin, sm) > _seam.SEAM_MAX_INK and seam_band < _seam.SEAM_BAND_WIDE:
                # 分级走廊：窄走廊绕不开就到宽走廊再找一次（只对"本来要放弃"的格线放宽）
                sm = _seam.find_seam(ink_bin, y, band=_seam.SEAM_BAND_WIDE)
                if int(np.abs(sm - y).max()) > 0:
                    cands.append(SeamCandidate(kind="seam_wide", y=sm.tolist(),
                                               seam_ink=int(_seam.seam_ink(ink_bin, sm)),
                                               dev_max=int(np.abs(sm - y).max())))
            # 2) 现役选择规则 + 候选池过滤，**两件事分开算**。
            #
            # `chosen` 是「现役本来走直线还是折线」的开关（决定要不要写 `seam_*`），
            # 规则一字未改：走完上面两步后的 `sm` 若绕不开墨就保持直线。
            # `chosen` 用**旧池**下标算完再随过滤重指，不跟过滤后的列表长度互相推
            # （两者耦合过：过滤一旦真的删掉东西，`len(cands)-1` 就指错了）。
            #
            # `candidates` 是**攒给下游打分函数的样本池**（见 products/kinds/cells.py
            # 的 `CutPointCandidates`），它的职责不是被现役的选法裁剪。过滤判据按
            # 「这条缝值不值得记为一条**不同的**切线」定，而**不能按偏离量**：
            # 实测（vol01 全册 2651 条有墨格线）偏离量与「直线穿墨量」单调正相关
            # （dev 0–2px 时直线平均 2.8 墨，dev 20px+ 时 15.0 墨）——偏离大是直线
            # 本身更差的结果，拿它当尺度会优先砍掉干活最多的候选。用户 2026-09-10：
            # 「一个字上面少 5px 有时还是很明显」——偏得小但绕开了墨，是真的切得好些。
            #
            # 所以判据用**省墨量**：`seam_ink >= straight_ink` 的缝与直线是同一把刀。
            # 但注意这条**现在恒不成立**：上面两处 append 都要求 `dev > 0`，而实测
            # 每条 `dev > 0` 的缝都省墨（`find_seam` 的代价函数本身在最小化路径墨量）。
            # 也就是说过滤现在一条都删不掉，全册 A/B 与不设过滤逐位相同。
            # 留着它是因为它把「入池的必须真的绕开了墨」这条不变量写在代码里——
            # 将来若放宽 append 条件（如允许记 `dev == 0` 的缝），它就会开始起作用。
            #
            # 上面第 1057 行的 `ink_bin[y].any()` 保证走到这里直线一定有墨，
            # 所以 `straight_ink >= 1`，判据不会因直线本来无墨而空转。
            chosen = 0 if (int(np.abs(sm - y).max()) == 0
                           or _seam.seam_ink(ink_bin, sm) > _seam.SEAM_MAX_INK) else len(cands) - 1
            # 过滤：剔掉一点墨都不省的折线候选（与直线是同一把刀），直线恒在池首。
            # 现在恒删不掉任何一条，理由见上面长注释；`chosen` 仍按旧池下标定位、
            # 随过滤重指，这样将来过滤真的生效时它不会指错。
            chosen_seam = None if chosen == 0 else cands[chosen].y
            kept = [SeamCandidate(kind="straight", y=None, seam_ink=0, dev_max=0)]
            chosen = 0
            for c in cands[1:]:
                if c.seam_ink >= straight_ink:
                    continue
                if chosen_seam is not None and np.array_equal(np.asarray(c.y),
                                                              np.asarray(chosen_seam)):
                    chosen = len(kept)
                kept.append(c)
            cands = kept
            # 3) 窄走廊「零墨且贴着直线」、且现役本就选中了它时，直线不算真
            # 候选——用户 2026-09-11 实测：Step7 待裁里 72%（vol02 181/250）
            # 是「直线穿墨、窄走廊完全绕开且偏移 <10px」这类，窄走廊明显
            # 更好，不该占用人力去比。判据三个都要：**现役已选中这条折线**
            # （`chosen == 1`，不改变现役切分行为，只是不再挡人）+ **零墨**
            # （不是"省墨"，是绕得干干净净）+ **偏移小**（用户原话「一个字
            # 上面少 5px 有时还是很明显」——偏移大时仍是真候选，留给人判）。
            # 只在「唯一折线候选就是它」时收，别处（如还有 seam_wide）留给
            # 下游打分，不在这里拍。
            #
            # ⚠️ 收缩后 `chosen` 恒为 0，但那是「候选池第 0 项」不是「选中了
            # 直线」——下面第 1183 行判断改用 `cands[chosen].kind != "straight"`，
            # 不能再用 `chosen != 0`（候选池不再保证 straight 恒在池首）。
            if (chosen == 1 and len(cands) == 2 and cands[1].kind == "seam_narrow"
                    and cands[1].seam_ink == 0 and cands[1].dev_max < 10):
                cands = [cands[1]]
                chosen = 0
            # 4) 人裁回流（必须在裁判之前——`seam_ok` 收敛的是人当时看到的现役折线；2026-09-14 vol02 p33 实锤）
            # 5) L2 裁判 + L2′ 分歧探针（2026-09-15，10 卡）：所有粘连切点（含单候选、含人裁收敛后的）都过一次
            #    U-Net，记一致率与分歧块；池 ≥2 时按门槛改选；所选分歧块 ≥ ESCALATE_BLOB 标 `escalate`（人裁过的
            #    不标）。只记录不改选法：拿不准的交下游再审。两步都在 `_resolve_and_probe` 里，与 L0′ 嫌疑切点共用。
            cands, chosen, chosen_by, escalate, escalate_reason = _resolve_and_probe(cands, chosen, up[0], dn[0], k)
            cp = CutPointCandidates(k=k, y=float(bounds[k]),
                                    slot_above=up[0].slot, slot_below=dn[0].slot,
                                    candidates=cands, chosen=chosen, chosen_by=chosen_by,
                                    escalate=escalate, escalate_reason=escalate_reason)
            cut_cands.append(cp)
            if cands[chosen].kind != "straight":   # 现役行为：选中折线才写 seam_*
                up[0].seam_bottom = cands[chosen].y
                dn[0].seam_top = cands[chosen].y
        result.cut_candidates = cut_cands
    result.cells = cells
    return result


def _slot_to_pos_local(slot: int, n_raised: int) -> int:
    return slot + n_raised + 1 if slot < 0 else slot + n_raised


def measure_book_period(store, book_id: str, pages=None,
                        body_pages=None) -> float | None:
    """整册正文页 `period` 的中位数，给 `Book.period_prior` 当标定值。

    **不需要金标**：正文页的字格高是版式常量，实测 vol01 正文 108 页
    115.0±1.67px、vol02 186 页 113.0±2.37px——std 不到 2.5px，比逐页当场估
    稳得多（与 `border_geometry.measure_book_bottom_gap` 那条跨页一致性先验
    同一个套路）。

    ⚠️ **只能用正文页**。职名/目录页的字距本来就不同（vol01 roster 中位 70、
    std 15.6，toc std 13.2），混进来会把中位数拉偏十几个 px。`body_pages`
    不给时用一个粗筛兜底：取全书 period 的中位数并剔掉偏离超过 15% 的页
    ——那批偏得远的正是职名/目录页。**能拿到 page_type 金标时应当直接传
    `body_pages`**，粗筛只是没有金标时的退路。

    读现成的闸2产物，不重跑管线；返回 None 表示可用样本不足。
    """
    import statistics

    from ..core.spec import page_key

    vals: list[float] = []
    for pg in (pages if pages is not None else []):
        if body_pages is not None and pg not in body_pages:
            continue
        g = store.read(book_id, "column_gate", page_key(pg), "gate_manifest")
        # 兜底来的 period 不能再参与标定——那是循环论证（拿先验算先验）。
        if g is None or not g.period or getattr(g, "period_from_prior", False):
            continue
        vals.append(float(g.period))
    if len(vals) < 5:
        return None
    if body_pages is None:
        med = statistics.median(vals)
        vals = [v for v in vals if abs(v - med) <= 0.15 * med]
        if len(vals) < 5:
            return None
    return round(statistics.median(vals), 2)
