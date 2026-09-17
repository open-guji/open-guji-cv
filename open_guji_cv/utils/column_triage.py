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
| `clean` | 边界处墨低，没有切进字身 | 放行 |
| `eat`  | 边界处墨 > `EAT_T` × 腹地墨，**边界已经吃进字身** | **拦** |

**`mixed` 这一档已取消**（2026-09-17，用户定）。它的语义是「这一列压根找不到
墨量归零的边界」——README 原话——**那是个程度问题，不是二元判据**，用任何单一
阈值切都会在中间地带大批误判：

- 写死绝对阈值 0.01 时，bxgb 88% 判 mixed、vol01 44%（两书带外底噪中位
  0.0124 vs 0.0080，阈值正好卡在 bxgb 的分布中间），复审率虚高到 85%；
- 换成相对腹地墨的自适应阈值，跨书一致了，但拿金标验分不开：
  人判 mixed 的 4 条相对值中位 0.139，人判 clean 的 111 条 p90 已到 0.162，
  阈值 0.1 时 mixed 判对 75%、clean 误判 14.4%。**而 mixed 只有 4 条，
  统计上立不住**。

所以只留 `eat` 这个**有向**判据（边界处墨高 = 切到字了），它分得开。
等上下方向的人裁金标攒够，再用同一批样本回头标定左右要不要重新引入 mixed。

上下（`end_class`，README 定义过但一直没标）：

| 类 | 含义 | 处置 |
|---|---|---|
| `none`  | 边缘没有框墨 | 放行（pad=0） |
| `clean` | 有框墨，峰之后跌到低位（框与首字之间有间隙） | 放行 |
| `glued` | 有框墨但一路没跌下来（框粘着首字，切不出界） | **拦** |
| `idk`   | 峰形怪、跌下去又立刻回高 | 复审 |

## 阈值的来历

- `EAT_T = 0.35`：边界处墨相对**文字带内 p90 墨**的比例。
  用相对量而不是绝对量——两书带外底噪中位 0.0124（bxgb）vs 0.0080（vol01），
  绝对阈值在一本上标好、换一本就整体偏移（同 `project_taitou_vol02_zero_recall`
  记的「绝对像素判据跨版式失效」）。
  基准取 **p90 而不是中位**：中位随「这一列有几个字」大幅变化——字少、留白多的
  列腹地中位只有 0.029（实测 p3c19），`0.35×` 之后阈值 0.010 比边界底噪
  （0.012~0.020）还低，整列被误判成 eat（8/8 抽样全是误报，字身其实完好）。
  p90 量的是「有字处的墨」，不受留白稀释：实测边界/p90 中位 0.042（bxgb）、
  0.027（vol01），比腹地中位的 0.056/0.032 更紧且跨书更一致。
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

#: 边界处墨 > 此比例 × 文字带内 p90 墨 = 已经吃进字身（拦）。相对量，见模块头。
EAT_T = 0.35
#: 算基准时取文字带中间这个比例的区段（避开两侧界行残墨的影响）
CORE_FRAC = 0.5
#: 基准用带内的这个分位（不是中位——中位随留白多少大幅变化，见模块头）
CORE_Q = 90
#: 基准墨低于此值就不下 `eat` 断言，改判 `idk`（复审）。
#: 稀疏列（整列只有一两个字）的带内 p90 只有 0.034，与边界底噪 0.014 太近，
#: `0.35×` 之后阈值 0.012 落在噪声里——实测 bxgb p8c6（整列一个「及」字）
#: 就是这么被误判成 eat 的。没有足够的字当基准，就不该断言「切到字了」。
MIN_BODY = 0.05
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
               eat_t: float = EAT_T, core_frac: float = CORE_FRAC) -> str:
    """左右分诊。`col_prof` 是列向（逐 x）墨占比，`band` 是 `column_text_band` 的返回。

    只判「有没有切进字身」（`eat`），不判「这条边界准不准」——后者就是取消掉的
    `mixed`，是程度问题，没有金标支撑定不出线（见模块头）。
    """
    lo, hi = int(band[0]), int(band[1])
    if hi - lo < 4 or lo < 0 or hi > len(col_prof):
        return "idk"
    k = int((hi - lo) * (1 - core_frac) / 2)
    core = col_prof[lo + k:hi - k]
    body = float(np.percentile(core, CORE_Q)) if core.size else 0.0
    if body < MIN_BODY:
        # 空白列 / 稀疏列：没有足够的字当基准，不下 eat 断言（见 MIN_BODY）
        return "idk" if body > 0 else "none"
    for idx in (lo, hi - 1):
        if float(col_prof[idx]) > eat_t * body:
            return "eat"
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
REVIEW = {"side": ("idk",), "end": ("idk",)}


def is_blocking(t: dict) -> bool:
    return (t["side_class"] in BLOCKING["side"]
            or t["top_class"] in BLOCKING["end"]
            or t["bot_class"] in BLOCKING["end"])


def needs_review(t: dict) -> bool:
    return (t["side_class"] in REVIEW["side"]
            or t["top_class"] in REVIEW["end"]
            or t["bot_class"] in REVIEW["end"])
