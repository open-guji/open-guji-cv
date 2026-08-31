"""Step 3 附属：双行小注（夹注）的检出与 a/b 子列拆分。

**这是从生产 `clustering/extractor.py` 迁移过来的**，不是新设计——生产那版
是在两册实审里逐条踩出来的（尺子选错、门槛标定、桥接、噪点段否决、段端
归属五个坑各自付过代价，见 `.claude/doc/char_clustering_design.md`
「双行夹注 a/b 子列拆分 + 读序」「异常宽列缝」两节）。迁移时**逐条保留了
原判据与阈值**，只做了两处必要的适配（见下）；改动任何一个常量之前请先
读原文档里那一节记的失败案例。

对应关系：

| 生产（`extractor.py`）        | 这里                    |
|---|---|
| `_jiazhu_gap_center`          | `gap_center`            |
| `flag_jiazhu_runs`            | `link_runs`             |
| `extract_page` 里的「段端收编」 | `adopt_run_tails`       |
| `extract_page` 里的「a/b 拆分」 | 调用方（`row_boundaries.segment_column`）|
| `jiazhu_reading_order`        | `row_boundaries.reading_order` |

## 新链路上的两处适配

1. **尺子（`ref_w`）**：生产用的是页级「列距」（`grid.period`，书级刚性
   常量 174~186px）。新链路里 Step 2 的列图宽度就是相邻两条界行的间距，
   物理上即列距，所以直接拿列图内容窗口宽度当尺子；**但仍应传页级中位数
   而不是本列自己的宽度**——生产踩过的坑正是"尺子随窗口宽窄漂移"
   （vol02/171 补宽缝之后 span 比从 0.88 掉到 0.83，整段夹注反而判不出来）。
2. **界行必须先剥掉**：生产的格框图块经过连通体归属清理，界行残墨已被
   抹掉；新链路的列图是 Step 2 直接矫正出来的，**两侧边缘就压着界行**，
   贯穿全高的竖线会让每一格的墨迹跨度都顶满列宽、`SPAN_T` 判据直接失效
   （所有格都"像夹注"）。所以调用方必须先用
   `row_boundaries.find_content_window` 把两侧的墙剥掉，只把内容窗口内的
   图块喂进来。这一条是新链路独有的，生产那边不存在。

其余口径一律不动：判据仍在**裁紧前的格框图块**上量（裁紧是 Step 4 的事，
裁紧后谁都是满宽、判据必然失效），同一列所有格共用同一个 x 原点（缝中心
才能直接跨格比较）。
"""

from __future__ import annotations

import cv2
import numpy as np

# ── 常量：逐条对应 extractor.py 的 JIAZHU_* / JZ_* ──────────────
# 迁移时值全部照搬。**不要凭感觉调**——每个值后面都跟着一个实测案例。
INK_THRESHOLD = 128        # = extractor.BINARY_THRESHOLD_PATCH
SPAN_T = 0.75              # 两子列合起来占**列距**的比例下限。两册抽样 4023
                           # 格：普通字跨度/列距中位 0.592、95 分位 0.676，
                           # 夹注 0.78~0.97。0.85 会漏掉写得略窄的夹注
                           # （vol01/184 col9「陰陽五行／相宅相墓」量到 0.785）
GAP_MIN = 3                # 子列间缝宽下限（px）。部首缝只有 2~3px
MASS_W = 0.6               # 单个子列宽度上限（× 墨迹跨度）
ALIGN = 8                  # 相邻格缝中心相差不超过此才算同一条夹注（px）
MIN_RUN = 2                # 至少连续这么多格才判夹注
CC_MIN = 500               # 段中位「两侧较小 maxCC」低于此 → 噪点段否决
                           # （真小字 ≥1242px，纸面碎点 ≤327px，实测）
# 段端收编（奇数字末行只剩一个字 / 末行两字量不出缝）
TAIL_MIN_INK = 100         # 收编候选的总墨下限（px）
TAIL_A_FRAC = 0.8          # 单字尾：缝右（a 侧）墨占比下限
TAIL_GAP_BAND = 3          # 缝带半宽（px）
TAIL_GAP_FRAC = 0.02       # 缝带内墨占比上限（正文字的中竖会露馅）
HALF_MIN_INK = 30          # 拆出来的半格墨少于此不发格子（段末单半）
ROW_B_CC = 250             # 分型看 b 侧最大连通体：≥此是真笔画（「一」实测
                           # ~700+）→ 整行拆分；<此只是邻字残渣 → 单字尾。
                           # **分型不能拿墨占比**——vol02/4:5:20 末行「一|璉」
                           # 的「一」只占 18% 墨，被比例判据划成残渣、整个字
                           # 被丢掉，是红线事故。


def _binary(patch: np.ndarray, ink_threshold: int = INK_THRESHOLD) -> np.ndarray:
    if patch.ndim == 3:
        patch = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    return (patch < ink_threshold).astype(np.uint8)


def gap_center(patch: np.ndarray, ref_w: float | None = None,
               ink_threshold: int = INK_THRESHOLD) -> tuple[float, float] | None:
    """单格判据：图块若呈「双列小字」形态，返回 `(缝中心 x, strength)`。

    `patch` 是**内容窗口内的格框图块**（界行已剥掉、未裁紧），返回的 x 是
    patch 局部坐标。`ref_w` 是量跨度用的尺子，应传页级列距；不给退回图块
    宽度（只在没有页级量时用，判据会随列宽漂移，见模块头）。

    判据（逐条来自生产实测）：
    - 墨的总跨度占满列距（`span/ref_w ≥ SPAN_T`）——夹注两子列合起来跟正文
      一样宽，单字只占 0.6~0.7，这是唯一不重叠的量；
    - 中缝 ≥ `GAP_MIN` px（部首缝只有 2~3px），且缝要落在**墨迹跨度**的
      中段 30%~70%——不是图块的中段，图块两侧留白多少由窗口宽窄决定；
    - 两侧墨量均衡（各 ≥40px、比值 ≥0.25），单侧宽度 ≤ `MASS_W × span`；
    - `strength` = 两侧较小的最大连通体面积，交给 `link_runs` 按段中位数
      否决噪点段（单格不卡，薄字「一/三」会误伤）。

    单格判据会被个别左右结构字骗到，**必须配合 `link_runs` 的列上下文使用**。
    """
    binary = _binary(patch, ink_threshold)
    h, w = binary.shape
    if binary.sum() < 80:
        return None
    xp = binary.sum(axis=0)
    ink = np.flatnonzero(xp > 0)
    if len(ink) < 10:
        return None
    x0, x1 = int(ink[0]), int(ink[-1])
    span = x1 - x0 + 1
    if span / float(ref_w or w) < SPAN_T:
        return None
    runs: list[tuple[int, int]] = []
    start = None
    for i, v in enumerate(xp[x0:x1 + 1]):
        if v == 0 and start is None:
            start = i
        elif v > 0 and start is not None:
            runs.append((start, i))
            start = None
    gaps = [(a, b) for a, b in runs
            if a > span * 0.30 and b < span * 0.70 and b - a >= GAP_MIN]
    if not gaps:
        return None
    ga, gb = max(gaps, key=lambda r: r[1] - r[0])
    left = binary[:, x0:x0 + ga]
    right = binary[:, x0 + gb:x1 + 1]
    if min(int(left.sum()), int(right.sum())) < 40:
        return None
    if min(left.sum(), right.sum()) / max(left.sum(), right.sum()) < 0.25:
        return None
    if max(left.shape[1], right.shape[1]) > MASS_W * span:
        return None
    strength = float(w * h)
    for side in (left, right):
        n, _lab, stats, _c = cv2.connectedComponentsWithStats(
            np.ascontiguousarray(side))
        strength = min(strength, float(stats[1:, 4].max()) if n > 1 else 0.0)
    return float(x0 + (ga + gb) / 2), strength


def link_runs(entries: list[tuple[int, tuple[float, float] | None]]
              ) -> dict[int, float]:
    """列上下文：连续、缝对齐的夹注格 → `{格号: 缝中心}`。

    `entries` 是本列每一格的 `(格号, gap_center()结果|None)`，格号必须同序
    可比（相邻格号差 1 表示物理相邻）。

    两条保护逐条来自实测：
    - **桥接**：段里个别行单侧墨太少（vol02/5「一／辨」），单格判据因均衡
      不足落空、把连段拦腰截断。两侧紧邻格都有**实测**且对齐的缝中心时，
      中间这格按邻格均值补上（一次只桥 1 格、邻居必须实测，防自我扩散）。
    - **噪点段否决**：纸面碎点列（vol01/3 col2）span/缝/均衡全能骗过、还能
      连成 7 格长段。唯一分得开的是连通体结构，按**段中位** strength <
      `CC_MIN` 整段否决（单格不卡，薄字由段里其他字撑住中位数）。
    """
    ents = sorted(entries)
    measured = {i: c for i, c in ents if c is not None}
    cmap: dict[int, float] = {i: c[0] for i, c in measured.items()}
    smap: dict[int, float] = {i: c[1] for i, c in measured.items()}
    for i, c in ents:
        if c is not None:
            continue
        a, b = measured.get(i - 1), measured.get(i + 1)
        if a is not None and b is not None and abs(a[0] - b[0]) <= ALIGN:
            cmap[i] = (a[0] + b[0]) / 2
    out: dict[int, float] = {}

    def _commit(run: list[int]) -> None:
        if len(run) < MIN_RUN:
            return
        strengths = sorted(smap[j] for j in run if j in smap)
        if not strengths or strengths[len(strengths) // 2] < CC_MIN:
            return
        out.update({j: cmap[j] for j in run})

    run: list[int] = []
    prev_i = None
    for i in sorted(cmap):
        ok = (prev_i is not None and i == prev_i + 1
              and abs(cmap[i] - cmap[prev_i]) <= ALIGN)
        if ok:
            run.append(i)
        else:
            _commit(run)
            run = [i]
        prev_i = i
    _commit(run)
    return out


def adopt_run_tails(runs: dict[int, float], patches: dict[int, np.ndarray],
                    eligible: set[int] | None = None,
                    ink_threshold: int = INK_THRESHOLD
                    ) -> tuple[dict[int, float], set[int]]:
    """段端收编：夹注段**下一格**是不是这段的末行。

    返回 `(补齐后的 runs, 只发 a 半的格号集合)`；输入的 `runs` 不被修改。
    `patches` 是每格内容窗口内的格框图块（同一 x 原点），`eligible` 限制
    哪些格可以被收编（调用方一般传"非空白格"）。

    单格判据**永远量不出末行**：奇数字的末行只有右半一个字（跨度只有半列，
    过不了 `SPAN_T`）；偶数字的末行两个小字合起来也常不够跨度。桥接也救不了
    段端——只有一侧邻格。收编改拿**邻格的缝中心**当尺子分两型：

    - **漏拆行**：缝两侧各有实墨、b 侧有真笔画级连通体、缝带内几乎无墨、
      两半各自够窄 → 正常拆 a/b；
    - **单字尾**：墨 ≥`TAIL_A_FRAC` 落在缝右（a 侧）、a 侧够窄、b 侧只有
      碎渣 → 只发 a 半。

    全尺寸正文窄字（大/督/撫）居中、缝带上有墨，两条都过不了。
    """
    runs = dict(runs)
    tail_a: set[int] = set()
    if not runs:
        return runs, tail_a
    for e in [i for i in sorted(runs) if i + 1 not in runs]:
        t = e + 1
        if t in runs or t not in patches:
            continue
        if eligible is not None and t not in eligible:
            continue
        pre_t = patches[t]
        cx = int(round(runs[e]))
        if cx <= 0 or cx >= pre_t.shape[1]:
            continue
        bin_t = _binary(pre_t, ink_threshold)
        ys_t, xs_t = np.nonzero(bin_t)
        if xs_t.size < TAIL_MIN_INK:
            continue
        frac_a = float((xs_t >= cx).mean())
        in_band = int(((xs_t >= cx - TAIL_GAP_BAND)
                       & (xs_t <= cx + TAIL_GAP_BAND)).sum())
        a_xs = xs_t[xs_t >= cx]
        b_xs = xs_t[xs_t < cx]
        w_full = pre_t.shape[1]
        a_narrow = bool(a_xs.size) and (
            a_xs.max() - a_xs.min() + 1 <= MASS_W * w_full)
        b_cc = 0
        if b_xs.size:
            nb, _lb, stb, _cb = cv2.connectedComponentsWithStats(
                np.ascontiguousarray(bin_t[:, :max(1, cx)]), 8)
            if nb > 1:
                b_cc = int(stb[1:, 4].max())
        row_ok = (a_xs.size >= TAIL_MIN_INK
                  and b_xs.size >= TAIL_MIN_INK
                  and b_cc >= ROW_B_CC
                  and in_band <= TAIL_GAP_FRAC * xs_t.size
                  and a_narrow
                  and b_xs.max() - b_xs.min() + 1 <= MASS_W * w_full)
        if row_ok:
            runs[t] = float(runs[e])
        elif frac_a >= TAIL_A_FRAC and a_narrow and b_cc < ROW_B_CC:
            runs[t] = float(runs[e])
            tail_a.add(t)
    return runs, tail_a
