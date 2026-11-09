# -*- coding: utf-8 -*-
"""刻本链的列类型：版框/界行探出来的列位 → `body` / `margin` / `edge`。

## 为什么要有这个

现代印刷链的 Step1（`line_detect`）本来就产 `line_index`，逐列记类型
（`body | empty | footnote | margin | wide | noise`），下游据此跳过非正文列。
刻本链的 Step1（`border_detect`）只产 `borders`——因为《四庫全書總目》那批书
一页就是一个半叶，版框内九列全是正文，没有"哪一列不是正文"的问题。

**筒子页把这个问题带进来了**：一张扫描页 = 一整版 = 两个半叶，中间夹着版心
（书口），印的是书名、叶次、丛书名。它落在版框内、两侧有界行，`border_detect`
把它当成一个普通列位探出来（这正是"筒子页不必先分页"成立的原因，见
`BookSpec.leaf_layout`），但它**不是正文**，Step3 起必须跳过。

## 判据：只能用位置

版心在物理上就是整版正中间那一条。北行日錄刻本 54 页实测：

- **位置判据**（跨版框中点的那个列位）：51/54 页命中 col11，离中点 −13~+11px；
  剩下 3 页（p7/p16/p41）是 **Step1 自己漏探/误探了界行**（p16 少一条竖线整体
  错位、p7 有个 257px 的并列和 31px 的碎片、p41 整页偏斜且间距 60~253px 乱跳），
  在那些页上位置判据**仍然指向真正的版心**，是上游几何坏了、不是判据坏了。

⚠️ **两个统计判据试过都不行，别再走**（8 页实测，记在这里免得后人重做）：

- **列内最长连续空白段**：普通正文页分得很开（正文 236~247px vs 版心 431px），
  但卷题页/卷末页的短正文列比版心更空——8 页里 3 页认错（p3/p39/p56）；
- **列内墨占比**：版心并不是每页最稀的那列，8 页里只有 1 页对。

根子在于版心"稀"是内容属性，而卷题页/末页的正文列同样稀；只有"在正中间"
是版式属性，与内容无关。

## `edge`：版框外的那个列位

`border_detect` 的 `verticals` 有时把 x≈0 的页边当成一条线（北行日錄刻本
54 页里每页都有），于是最右多出一个 250~270px 宽的"列"。它本来就会被闸2 的
L1c 拒掉（"本列宽偏离本页中位数 +127%"），这里显式标成 `edge`，让人看产物时
一眼知道那不是漏切的正文。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ColumnType:
    col: int                 # 列位号，右→左从 1（与 page_column_windows 一致）
    kind: str                # body | margin | edge
    x0: float                # 该列位左右两条界行的 x（原图坐标，左上原点）
    x1: float
    width: float
    reason: str = ""         # 非 body 时说明判据


def classify_columns(verticals_x: list[float], *, leaf_layout: str = "single",
                     edge_width_ratio: float = 1.8) -> list[ColumnType]:
    """列位 → 类型。`verticals_x` 是 Step1 的界行 x（右→左，N+1 条 → N 个列位）。

    `leaf_layout='folio'`（筒子页）才找版心；`single` 只标 `edge`。

    版框由**去掉贴页边的线**之后的最左最右两条定；版心 = 中心最接近版框中点的
    那个列位。不设距离阈值——哪怕几何坏了也要给出一个答案，因为"这一页没有版心"
    对筒子页是不可能的；真正的坏页由闸1/闸2 按几何判据拦，不靠这里。
    """
    n = len(verticals_x) - 1
    if n < 1:
        return []
    widths = [verticals_x[i + 1] - verticals_x[i] for i in range(n)]
    med = sorted(widths)[len(widths) // 2]
    out = [ColumnType(col=i + 1, kind="body", x0=verticals_x[i], x1=verticals_x[i + 1],
                      width=widths[i]) for i in range(n)]

    # ── edge：贴着页边、且宽得离谱的列位 ────────────────────────────
    for i, c in enumerate(out):
        if med > 0 and c.width > edge_width_ratio * med and (i == 0 or i == n - 1):
            c.kind = "edge"
            c.reason = f"贴页边且宽 {c.width:.0f}px 是本页中位 {med:.0f}px 的 {c.width / med:.1f} 倍"

    if leaf_layout != "folio":
        return out

    # ── margin：跨版框中点的那个列位 ───────────────────────────────
    inner = [c for c in out if c.kind != "edge"]
    if not inner:
        return out
    lo, hi = inner[0].x0, inner[-1].x1
    mid = (lo + hi) / 2.0
    best = min(inner, key=lambda c: abs((c.x0 + c.x1) / 2.0 - mid))
    best.kind = "margin"
    best.reason = (f"跨版框中点（框 {lo:.0f}~{hi:.0f}，中点 {mid:.0f}，"
                   f"本列中心 {(best.x0 + best.x1) / 2.0:.0f}）→ 版心，非正文")
    return out
