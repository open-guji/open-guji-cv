# -*- coding: utf-8 -*-
"""现代印刷体的单列文字切分：按墨段 + 字身盒模型的 DP，不是固定格数的弹性 DP。

为什么不能沿用刻本链的 `row_boundaries.segment_column`
------------------------------------------------------
刻本每列固定 N 格（《四庫全書總目》21 格），格高 = 页级 period，弹性 DP 就是在
这个前提下找 N+1 条格线。现代排印本（北行日錄实测）不是这样：

- 列高固定，但**每列的项数不同**（14～16 个汉字 + 2～4 个标点，17～19 项）；
- 标点占 0.35～0.7 格、**不固定**（挤压排版），字距随列在 111～132px 之间调整以撑满列长；
- 字与字之间有真正的纯白缝（3～30px），标点是靠列右侧的小墨块（宽、高都 ≤ 0.5 em）。

所以这里反过来：先按纯白缝把列切成**墨段**（run），再决定哪些段合成一个字。
难点只有一个——字内也有纯白缝（二、三、六、文、主……的分离笔画），而且字内缝
（二的两横相隔约 0.5 em）可以**比字间缝还宽**，单看缝宽分不开「一二」与「二一」。
能分开的是**字身盒**：每个字占一个 em 见方的盒子，盒子不重叠、相邻盒中心距
≈ 本列的字距 pitch。于是做一个小 DP：把连续若干墨段合成一项（跨度 ≤ 1.15 em），
代价 = 相邻两项中心距偏离 pitch 的程度（字–字之间的 pitch 很稳，标点两侧松），
全列最小代价的分法就是切分。`一`（单横）会自成一项——它的跨度虽小，但把它并进
邻字会让中心距塌成 0.5 pitch，代价反而高。

已知未处理（v1）：双行小注（两个子列在 y 投影上交错）、半角连串。前者标 `suspect_jiazhu`
（列的 x 投影出现两个峰）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

CELL_KINDS = ("char", "punct", "blank")


@dataclass
class InkRun:
    y0: int          # 含
    y1: int          # 不含
    x0: int          # 墨的 x 范围（列图坐标，含）
    x1: int
    ink: int
    kind: str        # big | small_right | frag

    @property
    def h(self) -> int:
        return self.y1 - self.y0

    @property
    def w(self) -> int:
        return self.x1 - self.x0 + 1

    @property
    def center(self) -> float:
        return (self.y0 + self.y1 - 1) / 2.0


@dataclass
class RunCell:
    y0: float
    y1: float
    kind: str                       # char | punct | blank
    ink_y0: int | None = None       # 墨的 y 范围（含 / 不含），blank 为 None
    ink_y1: int | None = None
    ink_ratio: float = 0.0
    flags: list[str] = field(default_factory=list)
    n_runs: int = 1


@dataclass
class RunSegResult:
    cells: list[RunCell]
    em: float
    pitch: float
    boundaries: list[float]
    flags: list[str] = field(default_factory=list)
    n_runs_total: int = 0          # 本列墨段数——调用方判断 em 自估靠不靠得住


def _runs(mask: np.ndarray, minlen: int = 1) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    s: int | None = None
    for i, v in enumerate(mask):
        if v and s is None:
            s = i
        elif not v and s is not None:
            if i - s >= minlen:
                out.append((s, i))
            s = None
    if s is not None and len(mask) - s >= minlen:
        out.append((s, len(mask)))
    return out


def ink_runs(ink: np.ndarray, *, min_h: int = 2, min_ink: int = 4) -> list[InkRun]:
    """列图（已裁到内容窗口）→ 沿列方向的墨段。极小的碎点（高 < min_h 或墨 < min_ink）丢掉。"""
    rf = ink.sum(axis=1)
    out: list[InkRun] = []
    for a, b in _runs(rf > 0, 1):
        seg = ink[a:b]
        n = int(seg.sum())
        if (b - a) < min_h and n < min_ink:
            continue
        cols = np.flatnonzero(seg.any(axis=0))
        out.append(InkRun(y0=a, y1=b, x0=int(cols[0]), x1=int(cols[-1]), ink=n, kind="frag"))
    return out


MIN_RUNS_FOR_EM = 6


def estimate_em(runs: list[InkRun], band_w: int, em_hint: float | None = None) -> float:
    """字身高：最高一族墨段的高度中位数（高 ≥ 0.6 × 第 90 百分位）。

    墨段太少（< MIN_RUNS_FOR_EM，短列如「二月」）时自估不可靠——两段里一段是薄字
    另一段就成了「最高一族」——退回 `em_hint`（调用方给页级 em，见
    `row_segment_runs` 的两遍法），没有 hint 才退回内容窗口宽。**别退回窗口宽当第一
    选择**：现代链的窗口宽是列距（≈1.8 em），不是字身。"""
    hs = np.array([r.h for r in runs], dtype=float)
    if hs.size >= MIN_RUNS_FOR_EM:
        top = float(np.percentile(hs, 90))
        big = hs[hs >= 0.6 * top]
        if big.size:
            return float(np.median(big))
    if em_hint:
        return float(em_hint)
    if hs.size:
        return float(hs.max())
    return float(band_w)


def classify_runs(runs: list[InkRun], em: float, band_w: int, *, small_frac: float = 0.55,
                  big_frac: float = 0.6, right_frac: float = 0.5) -> None:
    """big = 一个完整字身高的段；small_right = 靠右的小墨块（标点的形态）；其余 frag。"""
    for r in runs:
        if r.h >= big_frac * em:
            r.kind = "big"
        elif r.h <= small_frac * em and r.w <= small_frac * em and \
                (r.x0 + r.x1) / 2.0 >= right_frac * band_w:
            r.kind = "small_right"
        else:
            r.kind = "frag"


def _group_dp(runs: list[InkRun], em: float, pitch: float, *, max_span_frac: float = 1.15,
              punct_pitch_frac: float = 0.6, punct_weight: float = 0.3,
              punct_in_char_cost: float = 0.6, punct_group_span_frac: float = 0.6,
              max_group: int = 6, trans_weight: float = 1.0) -> list[tuple[int, int, str]]:
    """墨段序列 → [(起, 止, 项类型)]。DP：`best[i]` = 前 i 段的最小代价与最后一项。

    标点项 = 一个靠右小墨块，或**几个靠右小墨块合起来跨度 ≤ punct_group_span_frac em**
    （竖排冒号「︰」是两个点；连续两个标点「。」」合起来 ~0.9 em，不会被并）。"""
    n = len(runs)
    INF = float("inf")
    # best[i] = (cost, prev_i, kind, center)
    best: list[tuple[float, int, str, float]] = [(INF, -1, "", 0.0)] * (n + 1)
    best[0] = (0.0, -1, "", float("nan"))
    # 单个墨段必须总能自成一项：em 估小了（p9 c10 自估 87.5、字身实高 104）会让整列
    # 无解、退化成「每段一项、没有标点」
    max_span = max(max_span_frac * em, float(max(r.h for r in runs)) + 1.0)
    for i in range(n):
        c0, _, k0, cen0 = best[i]
        if c0 == INF:
            continue
        for j in range(i + 1, min(n, i + max_group) + 1):
            grp = runs[i:j]
            span = grp[-1].y1 - grp[0].y0
            if span > max_span:
                break
            n_small = sum(1 for r in grp if r.kind == "small_right")
            if n_small == len(grp) and span <= punct_group_span_frac * em:
                kind = "punct"
                item_cost = 0.0
            else:
                kind = "char"
                item_cost = punct_in_char_cost * n_small
            cen = (grp[0].y0 + grp[-1].y1 - 1) / 2.0
            if k0 == "":
                trans = 0.0
            elif k0 == "char" and kind == "char":
                # `trans_weight` > 1 = 刚性网格：偏离 pitch 罚得更重（见
                # `segment_column_runs` 的 rigid 说明）。标点那一路不加权——
                # 标点本来就不在网格上（占 0.35～0.7 格）。
                trans = trans_weight * abs((cen - cen0) - pitch) / pitch
            else:
                trans = punct_weight * abs((cen - cen0) - punct_pitch_frac * pitch) / pitch
            tot = c0 + item_cost + trans
            if tot < best[j][0]:
                best[j] = (tot, i, kind, cen)
    if best[n][0] == INF:        # 理论上不会：单段成项总可行
        return [(i, i + 1, "char") for i in range(n)]
    out: list[tuple[int, int, str]] = []
    j = n
    while j > 0:
        _, i, kind, _ = best[j]
        out.append((i, j, kind))
        j = i
    out.reverse()
    return out


def _estimate_pitch(runs: list[InkRun], em: float, pitch_hint: float | None) -> float:
    """相邻两个 big 段（中间没有别的段）的中心距中位数；没有就退回 hint 或 1.15 em。"""
    ds = [runs[i + 1].center - runs[i].center for i in range(len(runs) - 1)
          if runs[i].kind == "big" and runs[i + 1].kind == "big"]
    if len(ds) >= 3:
        return float(np.median(ds))
    if pitch_hint:
        return float(pitch_hint)
    return em * 1.15


def segment_column_runs(col_gray: np.ndarray, *, content_x: tuple[float, float] | None = None,
                        border_top: float = 0.0, border_bottom: float | None = None,
                        ink_threshold: int = 128, em_hint: float | None = None,
                        pitch_hint: float | None = None, blank_min_frac: float = 0.8,
                        small_char_frac: float = 0.8, extend_max_frac: float = 0.6,
                        rigid: bool = False, rigid_weight: float = 3.0,
                        interior_blank: bool = False, blank_gap_frac: float = 0.55
                        ) -> RunSegResult | None:
    """Step3（现代链）正门：清理后的单列灰度图 → 带类型的项（char / punct / blank）。

    - `content_x`：内容窗口（闸2 给的文字带）；
    - `border_top` / `border_bottom`：只在这个 y 范围内找墨（列图坐标）；
    - `em_hint` / `pitch_hint`：估不出来时的兜底（册级先验）。
    - `rigid`：**刚性网格模式**（三模式方案 §四.2）。见下。
    - `interior_blank`：项与项之间的墨缝宽到能装下整格时，补 `blank` 项（**项内空格位**）。
      默认关——北行日錄是撑满排版，列内没有真正的空格位，开了会把宽字缝误判成空格。
      考補萃編这类方格排版必须开：空格是「著者 ∥ 書名」的分隔符，吞掉就丢结构。
    返回 None 表示这一列没有墨。

    ## 刚性 vs 弹性（2026-09-15 加）

    两本现代书给出了相反的版式，所以这里是个开关而不是一条路：

    - **北行日錄（竖排）不刚性**：标点挤压 + 撑满列长，字距随列在 111～132px 间调整。
      pitch 必须**逐列估**、还要用第一轮结果重估一次——这是默认 (`rigid=False`)。
    - **考補萃編（横排）刚性**：全角方格排版，pitch 45.5px、跨页 σ<1px。
      这时逐列估 pitch 是**有害的**：短行（书目体只有五六个字）样本太少，
      估出来的中位数会被一两个宽字带偏；而页级 pitch 是排版常量，本来就更准。

    `rigid=True` 时：① pitch 锁死用 `pitch_hint`（页级/册级常量），不逐列估、
    不做第二轮重估；② DP 的 char→char 转移代价乘 `rigid_weight`，
    偏离网格惩罚更重，等价于「格心必须落在网格上」。
    """
    H, W = col_gray.shape[:2]
    x_lo, x_hi = (0, W) if content_x is None else (int(round(content_x[0])), int(round(content_x[1])))
    x_lo, x_hi = max(0, x_lo), min(W, x_hi)
    y_lo = max(0, int(round(border_top)))
    y_hi = H if border_bottom is None else min(H, int(round(border_bottom)))
    if x_hi - x_lo < 2 or y_hi - y_lo < 2:
        return None
    ink = col_gray[y_lo:y_hi, x_lo:x_hi] < ink_threshold
    band_w = x_hi - x_lo
    runs = ink_runs(ink)
    if not runs:
        return None
    em = estimate_em(runs, band_w, em_hint)
    # 小字多的列（人名注连排「張說、張掄、宋鈞」）自估会偏小（p9 c10 实测 88 vs 页级 101），
    # 随后 pitch 也偏小、标点全被吸进字里。页级 em / pitch 是排版常量，比列自估稳：
    # 自估明显**小于**页级值就用页级值；大于的不动（卷题列字号本来就大）。
    if em_hint and em < 0.9 * em_hint:
        em = float(em_hint)
    classify_runs(runs, em, band_w)
    if rigid and pitch_hint:
        # 刚性：pitch 是页级排版常量，逐列估只会被短行的少数样本带偏。
        pitch = float(pitch_hint)
        groups = _group_dp(runs, em, pitch, trans_weight=rigid_weight)
    else:
        pitch = _estimate_pitch(runs, em, pitch_hint)
        if pitch_hint and pitch < 0.85 * pitch_hint:
            pitch = float(pitch_hint)
        groups = _group_dp(runs, em, pitch)
        # 用第一轮结果重估 pitch（字–字中心距），再切一次；两轮足够收敛
        cen = [(runs[i].y0 + runs[j - 1].y1 - 1) / 2.0 for i, j, _ in groups]
        kinds = [k for _, _, k in groups]
        ds = [cen[t + 1] - cen[t] for t in range(len(cen) - 1)
              if kinds[t] == kinds[t + 1] == "char"]
        if len(ds) >= 3:
            p2 = float(np.median(ds))
            if pitch_hint and p2 < 0.85 * pitch_hint:
                p2 = float(pitch_hint)
            if abs(p2 - pitch) > 1.0:
                pitch = p2
                groups = _group_dp(runs, em, pitch)

    flags: list[str] = []
    # 双行小注嫌疑：内容窗口的 x 投影出现两个分离的峰
    xprof = ink.mean(axis=0)
    xr = _runs(xprof > 0.02, 3)
    if len(xr) >= 2 and all((b - a) >= 0.2 * band_w for a, b in xr[:2]) and \
            (xr[1][0] - xr[0][1]) >= 0.08 * band_w:
        flags.append("suspect_jiazhu")

    cells: list[RunCell] = []
    items: list[tuple[int, int, str, int, int]] = []   # (ink_y0, ink_y1, kind, i, j)
    for i, j, kind in groups:
        items.append((runs[i].y0 + y_lo, runs[j - 1].y1 + y_lo, kind, i, j))
    # 项边界：相邻项墨缝的中点；首末项向外最多扩 extend_max_frac em
    ext = extend_max_frac * em
    bounds: list[float] = []
    for t, (a0, a1, _, _, _) in enumerate(items):
        if t == 0:
            bounds.append(max(float(y_lo), a0 - ext))
        else:
            prev_end = items[t - 1][1]
            bounds.append((prev_end + a0) / 2.0)
    last_end = items[-1][1]
    bounds.append(min(float(y_hi), last_end + ext))
    # 首尾空白：块内空出 ≥ blank_min_frac em 的段落成一个 blank 项
    if items[0][0] - y_lo >= blank_min_frac * em + ext:
        cells.append(RunCell(y0=float(y_lo), y1=bounds[0], kind="blank"))
    # **项内空格位**（2026-09-15 加）：相邻两项的墨缝宽到能装下整格时，
    # 中间是排版上的空格，不是「上一个字很宽」。
    #
    # 不补的后果不是难看，是**丢结构**：考補萃編的书目体用空格分隔
    # 「著者 ∥ 書名」（張華集二卷　又　詩一卷），空格位被吞掉，Step9 就分不出
    # 哪里是著者哪里是書名；而且格心距会变成 1.75～1.91 × pitch，
    # 量漏切时全部记成漏切（p301 c9 那两条就是）。
    #
    # 只按**墨缝**判，不按项跨度判：项跨度里含 ext 外扩，判不准。
    # gap / pitch 四舍五入 ≥1 就补几个空格位，均分这段缝。
    # 判据用**墨缝**（上一项墨尾 → 本项墨头）而不是格跨度；补出来的空格位
    # 占的是**格位**，所以按 pitch 算个数：缝里除掉两侧各半个字身，还能站下几个整格。
    # 只在 char↔char 之间补——标点本来就不占整格（0.35～0.7），它两侧的缝是挤压，
    # 不是空格（p301 c9 的「卷␣」缝 35px 就是被这条挡住的）。
    interior: dict[int, int] = {}          # t → 这一项之前要补几个空格位
    if interior_blank and pitch > 0:
        for t in range(1, len(items)):
            if items[t - 1][2] != "char" or items[t][2] != "char":
                continue
            # 格心距比 pitch 多出来的部分就是空出来的格数
            cen_prev = (items[t - 1][0] + items[t - 1][1]) / 2.0
            cen_cur = (items[t][0] + items[t][1]) / 2.0
            n_blank = int(round((cen_cur - cen_prev) / pitch)) - 1
            if n_blank >= 1:
                interior[t] = n_blank
        # 补了空格位的地方，两侧格边界要重新定：原来的 `bounds` 是墨缝中点，
        # 整条缝都算给了相邻两格，空格位就只剩几个像素。改成把缝按
        # 「上一项吃一点、空格位站中间、本项吃一点」三份分：
        # 两侧各让出的余量取墨缝的 1/(n+2)，保证空格位拿到接近一格的宽度。
        # ⚠️ 别用 `ext`（0.6 em ≈ 23px）当余量——54px 的缝被两侧各吃 23px
        # 只剩 8px，空格位会瘦成一条线（2026-09-15 第一版就是这么错的）。
        for t in list(interior):
            n_b = interior[t]
            g0, g1 = items[t - 1][1], items[t][0]
            share = (g1 - g0) / (n_b + 2)
            lo, hi = g0 + share, g1 - share
            if hi > lo:
                bounds[t] = lo
                interior[t] = (n_b, lo, hi)        # type: ignore[assignment]
            else:
                interior.pop(t)
    for t, (a0, a1, kind, i, j) in enumerate(items):
        ent = interior.get(t)
        if ent:
            n_b, lo, hi = ent                      # type: ignore[misc]
            step = (hi - lo) / n_b if hi > lo else 0.0
            for b in range(n_b):
                cells.append(RunCell(y0=lo + b * step, y1=lo + (b + 1) * step, kind="blank"))
        seg = ink[a0 - y_lo:a1 - y_lo]
        ratio = float(seg.mean()) if seg.size else 0.0
        fl: list[str] = []
        h = a1 - a0
        if kind == "char":
            if h < small_char_frac * em:
                fl.append("small")           # 小字（单行小注）或薄字（一 / 二）
            if any(runs[k].kind == "small_right" for k in range(i, j)):
                fl.append("punct_absorbed")  # 一个靠右小墨块被并进了字：可能是真字的点，也可能是漏切的标点
            if h > 1.2 * em:
                fl.append("tall")            # 高出字身两成：两项粘连、或字与标点连在一起
        # `h` 是**墨高**（a1 - a0），不是格高——格高含外扩与均分的缝，
        # 一个正常句点的格能有 32px 而墨只有 11px，拿格高判会把好标点也标上。
        if kind == "punct" and pitch > 0 and h < 0.30 * pitch:
            # 墨高不到三成格：多半不是标点，而是**注码 ①②** 或被劈开的标点碎片
            # （考補萃編五页实测 12 处 = 0.64%，如「束哲集一卷①」的 ① 被切成 8px + 43px 两项）。
            # 只标不改切法：它们在 Step5 配不上库、会自己落到 unsure 交人裁，
            # 这个旗标是给人和体检看的线索。
            fl.append("tiny")
        # 补过空格位的项，起点跟着最后一个空格位走（不再是墨缝中点），
        # 否则本项会跨在空格上、格心又落回 1.5 pitch 处。
        y0 = cells[-1].y1 if interior.get(t) else bounds[t]
        cells.append(RunCell(y0=y0, y1=bounds[t + 1], kind=kind, ink_y0=a0, ink_y1=a1,
                             ink_ratio=round(ratio, 4), flags=fl, n_runs=j - i))
    if y_hi - items[-1][1] >= blank_min_frac * em + ext:
        cells.append(RunCell(y0=bounds[-1], y1=float(y_hi), kind="blank"))
    boundaries = [cells[0].y0] + [c.y1 for c in cells]
    return RunSegResult(cells=cells, em=em, pitch=pitch, boundaries=boundaries, flags=flags,
                        n_runs_total=len(runs))
