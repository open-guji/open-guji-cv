# -*- coding: utf-8 -*-
"""版框横条判据：**几种策略并存，册配置挑一种**。

## 为什么要分策略

「哪几行是版框、哪几行是字的横笔」这件事没有一把尺子通吃，因为它依赖版式：

| 册 | 版框 | 抬头 | 能用的判据 |
|---|---|---|---|
| 北行日錄刻本（bxgb） | 清晰、直、整页一条线 | 无 | **位置**（Step1 版框线）+ 厚度 |
| 四库总目（vol01/vol02） | 模糊 | **抬头突破边框** | 只能用形态学（`side_gap`） |

四库那本「抬头突破边框」这一条尤其要命：抬头字本来就越过版框线，拿位置当判据
会把抬头字的笔画当框抹掉。所以位置判据**不能**设成全局默认。

## 三种策略

- `side_gap`（缺省，历史行为）：靠「横条填满文字带两侧空档、字的横笔到文字带边
  就停」。前提是**字的横笔不满宽**——对「巨/雲/二/亘」这类上下横横贯全字宽的字
  不成立（bxgb p4 实测：「巨」上横行墨 0.60 > 阈值 0.55，整条被抹）。
- `border_line`：用 Step1 拟合的**整页版框直线**定位，只在线附近的窄带里认框，
  再用**厚度**复核。要求版框清晰且不被抬头突破。
- `off`：不抹。没有版框的现代排印本用（等价于 `frame_guard=False`）。

## 位置与厚度这两条判据的实测依据（bxgb，54 页）

列图端区里真正的版框残留只落在两条窄带：

| | 段数 | 在列图中的位置 |
|---|---|---|
| 上端 | 114 | y = 3–16，中位 5 |
| 下端 | 456 | 距底 29–50，中位 40 |

而按「满宽段中心到 Step1 预测线的距离」分：

| 距预测线 | 段数 | 厚度中位 | 身份 |
|---|---|---|---|
| −10..+10 | 341 | **13px** | 版框 |
| +10..+20 | 3 | 2px | 字笔画 |
| +20..+40 | 40 | 2px | 字笔画 |

**位置与厚度都不重叠**：版框贴线且厚 13px，字横离线 ≥10px 且只有 2px。
「巨」的上横在列图 y=16–18（上带外沿）、厚 2px——位置卡在边缘，但厚度一票否决。
"""

from __future__ import annotations

import numpy as np

#: `border_line` 策略：框线行必须落在 Step1 预测线的这个半径内（列图行）。
#: bxgb 实测版框段中心距预测线 |d| ≤ 10 覆盖 341/341 真框段。
BORDER_LINE_TOL = 12.0

#: `border_line` 策略：框线段的最小厚度（行）。真框 13px、字横 2px，取中间。
#: ⚠️ 这是**本书刻印的框粗**，换一本要重新量（`measure_frame_thickness`）。
BORDER_LINE_MIN_THICK = 6

#: `border_line` 策略：框线段的最大厚度。超过这个多半是字身连成一片，不是框。
BORDER_LINE_MAX_THICK = 40


def runs_of(mask: np.ndarray) -> list[tuple[int, int]]:
    """布尔行掩码 → [(起, 止)] 闭区间连续段。"""
    ys = np.flatnonzero(mask)
    if not ys.size:
        return []
    out: list[tuple[int, int]] = []
    a = p = int(ys[0])
    for y in ys[1:]:
        y = int(y)
        if y == p + 1:
            p = y
            continue
        out.append((a, p))
        a = p = y
    out.append((a, p))
    return out


def frame_rows_border_line(rowink: np.ndarray, row_t: float,
                           top_line: float | None, bottom_line: float | None,
                           tol: float = BORDER_LINE_TOL,
                           min_thick: int = BORDER_LINE_MIN_THICK,
                           max_thick: int = BORDER_LINE_MAX_THICK) -> np.ndarray:
    """**位置 + 厚度**判据：贴着 Step1 版框线、且够厚的连续段才是框。

    `rowink`：条带逐行墨占比（0~1）。`top_line`/`bottom_line`：上/下版框在
    **该条带坐标系**里的行号（调用方负责换算），拿不到就传 None（该侧不抹）。

    与 `side_gap` 的根本区别：那个问「这一行像不像框」（只看形状，「巨」的
    满宽上横就像），这个问「这一行**在不在框该在的地方**」——版框是版面结构，
    位置由整页几何定死，字的横笔再满宽也长不到框线上去。
    """
    H = len(rowink)
    out = np.zeros(H, dtype=bool)
    cand = rowink >= row_t
    if not cand.any():
        return out
    for seg_a, seg_b in runs_of(cand):
        thick = seg_b - seg_a + 1
        if thick < min_thick or thick > max_thick:
            continue            # 太薄=字横，太厚=字身连片
        center = (seg_a + seg_b) / 2.0
        near = False
        for line in (top_line, bottom_line):
            if line is not None and abs(center - float(line)) <= tol:
                near = True
                break
        if near:
            out[seg_a:seg_b + 1] = True
    return out
