# -*- coding: utf-8 -*-
"""Step2 列清理的**分诊**：每列在左右与上下两个方向各属于哪一类。

## 为什么要有这一层

Step2 的职责是「射影变换 + 完整识别边框信息」，下游 Step3/4 只在 padding
以内操作（用户 2026-09-17 定的职责划分）。但「削到哪一行」这件事本身有
**拿得准与拿不准之分**，而此前 Step2 只输出一个数字，把这个区别丢掉了：
拿不准的列和拿得准的列在产物里长得一模一样，人不知道该复核哪些。

分诊就是把这个区别显式记下来，供两件事用：
1. **人裁审阅台**按类别抽样（`console` 的 Step2 页面）；
2. **闸**按类别决定拦不拦（`eat`/`glued` 会丢字 → 拦；`mixed`/`idk` 只复审）。

## 类别的语言沿用 column-warp 金标 README（2026-08 定，115 条在用）

左右（`side_class`）：

| 类 | 含义 | 处置 |
|---|---|---|
| `clean` | 两侧都有零区，边界落在里面 | 放行 |
| `mixed` | 某侧**压根没有零区**（一路 0.01~0.09）——人也标不出唯一坐标 | 复审 |
| `eat`  | 边界处墨 > `EAT_T`，**边界已经吃进字身** | **拦** |

上下（`end_class`，README 定义过但一直没标）：

| 类 | 含义 | 处置 |
|---|---|---|
| `none`  | 边缘没有框墨 | 放行（pad=0） |
| `clean` | 有框墨，峰之后跌到低位（框与首字之间有间隙） | 放行 |
| `glued` | 有框墨但一路没跌下来（框粘着首字，切不出界） | **拦** |
| `idk`   | 峰形怪、跌下去又立刻回高 | 复审 |

## 阈值的来历

- `ZERO_T = 0.01`：金标 README 的走廊判据。人标点处墨占比均值 0.0010、
  最大 0.0097——取 0.005 会把大批 `clean` 误判成 `mixed`（实测 bxgb 87% 全判
  mixed，而金标 115 条里 111 条是 clean）。
- `HI_T = 0.55` / `DROP = 0.45`：走峰法。**不能只看第一行**——框的边缘是渐变的，
  剥掉留白后第一行常是 0.03~0.22（实测 p21c5 0.03 / p40c11 0.12 / p6c14 0.22），
  第 3 行起才是 0.9~1.0 的框，所以在开头 `LEAD` 行的窗口里找峰。
  停止条件用**相对峰高**而不是「归零」：框之后不是干净的零，而是 0.05~0.21 的
  底噪（纸纹、界行残迹），要求归零会一路走到 30+ 行、把首字吃掉。

⚠️ 这些阈值**只在 bxgb + vol01 的 280 列上量过**，还没有上下方向的人裁金标
（左右有 115 条）。`column-warp` 分片补上 `border_class` 之后要回来复标定。
"""

from __future__ import annotations

import numpy as np

#: 走廊判据：边界处墨 ≤ 此值算「落在零区里」（金标 README 口径）
ZERO_T = 0.010
#: 边界处墨 > 此值 = 已经吃进字身（拦）
EAT_T = 0.020
#: 端部：开头窗口里的峰要 ≥ 此值才算「有框墨」
HI_T = 0.55
#: 端部：墨跌到峰高的此比例 → 峰过去了
DROP = 0.45
#: 端部：在开头这么多行里找峰（框边缘渐变，不能只看第一行）
LEAD = 6
#: 端部：最多走这么多行（安全上限，防把整个首字吃掉）
CAP = 40
#: 端部：跌下去之后要维持在这个低位才算真间隙
LOW_T = 0.20


def side_class(col_prof: np.ndarray, band: tuple[int, int],
               zero_t: float = ZERO_T, eat_t: float = EAT_T) -> str:
    """左右分诊。`col_prof` 是列向（逐 x）墨占比，`band` 是 `column_text_band` 的返回。"""
    lo, hi = int(band[0]), int(band[1])
    out: list[str] = []
    for edge, idx in (("left", lo), ("right", hi - 1)):
        if idx < 0 or idx >= len(col_prof):
            out.append("idk")
            continue
        seg = col_prof[:idx + 1] if edge == "left" else col_prof[idx:]
        if seg.size == 0:
            out.append("idk")
        elif float(col_prof[idx]) > eat_t:
            out.append("eat")
        elif float(seg.min()) <= zero_t:
            out.append("clean")
        else:
            out.append("mixed")
    # 两侧取最坏：一侧吃字就是 eat，一侧没零区就是 mixed
    for worst in ("eat", "mixed", "idk"):
        if worst in out:
            return worst
    return "clean"


def end_class(row_prof: np.ndarray, hi_t: float = HI_T, drop: float = DROP,
              lead: int = LEAD, cap: int = CAP, low_t: float = LOW_T) -> tuple[str, int]:
    """端部分诊（一端）。`row_prof` 从**端部向内**排列。返回 `(类别, pad)`。

    `pad` 只在 `clean` 时有意义（该削几行）；其余一律 0——`none` 无框可削，
    `glued`/`idk` 拿不准时**宁可留残墨也不切字**（本模块的红线，与
    `column_border_trim` 一致）。
    """
    p = np.asarray(row_prof, dtype=np.float64)
    if p.size == 0:
        return "idk", 0
    head = p[:lead]
    if float(head.max()) < hi_t:
        return "none", 0
    start = int(np.argmax(head))
    peak = float(head.max())
    for y in range(start + 1, min(len(p), cap)):
        peak = max(peak, float(p[y]))
        if p[y] <= drop * peak:
            tail = p[y:y + 4]
            floor = max(low_t, drop * peak)
            return ("clean" if (tail.size and float(tail.max()) <= floor) else "idk"), y
    return "glued", 0


def strip_trailing_blank(row_prof: np.ndarray, eps: float = 0.02) -> np.ndarray:
    """剥掉序列开头的纯留白，返回从**首个真墨**起的切片。

    下端要用：`page_column_windows` 给下界多开了 `BOTTOM_PAD`（40 行）余量，
    列图末尾是留白，不剥的话端部找峰的窗口全落在白区里、一律判 `none`。
    """
    p = np.asarray(row_prof, dtype=np.float64)
    nz = np.flatnonzero(p > eps)
    return p[int(nz[0]):] if nz.size else p


def triage_column(gray: np.ndarray) -> dict:
    """一列矫正图（**清理前**）→ 分诊结果。供 Step2、审阅台、评测共用。"""
    from .column_projection import (column_profile, column_row_profile,
                                     column_text_band, denoise_column,
                                     strip_column_rules)
    dn = denoise_column(gray)
    band = column_text_band(dn)
    sc = side_class(column_profile(dn), band)
    rp = column_row_profile(strip_column_rules(dn), band)
    tc, tpad = end_class(rp)
    bc, bpad = end_class(strip_trailing_blank(rp[::-1]))
    return {"side_class": sc, "top_class": tc, "bot_class": bc,
            "pad_top": tpad, "pad_bottom": bpad, "band": (int(band[0]), int(band[1]))}


#: 会丢字、必须人裁才能走下一步的类别
BLOCKING = {"side": ("eat",), "end": ("glued",)}
#: 可疑但放行、事后抽审的类别
REVIEW = {"side": ("mixed", "idk"), "end": ("idk",)}


def is_blocking(t: dict) -> bool:
    return (t["side_class"] in BLOCKING["side"]
            or t["top_class"] in BLOCKING["end"]
            or t["bot_class"] in BLOCKING["end"])


def needs_review(t: dict) -> bool:
    return (t["side_class"] in REVIEW["side"]
            or t["top_class"] in REVIEW["end"]
            or t["bot_class"] in REVIEW["end"])
