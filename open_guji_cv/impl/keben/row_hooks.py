"""Step3 行切分的书级钩子（缺省实现：都不做，殿本等书产物不变）。

2026-11-12 A22（Sheldon 定方案《切分三方向》第 5 步）：全唐文书仓为了加三个小函数整份复制了 2485 行的
`row_boundaries`，复制后殿本那份的修复（下框越图底钳位、`grid_end_fit`…）就跟不上了。改成钩子：书仓 `code/` 只写
差异，在 `code/code.yaml` 的 `overrides` 写 `keben.row_hooks: <本书模块>`，`row_segment` 取来传给 `segment_column`。

覆盖本模块的书级代码给出下面任意几个同名函数（没给的照旧 None＝不调）：

- `grid_adjust(row_proj, bounds, period, dst_w) -> bounds`：等距格网（格位先验的候选之一）落缝**之前**改一次格线，
  格数不变（全唐文 k4 的节末短列重定相位）。每列都调，原样返回就是不改。
- `jiazhu_heads(entries, runs, patches, eligible, ink_threshold, ruler) -> {pos: 缝中心}`：在段端收编（`adopt_run_tails`）之前
  补认雙行小注段头（全唐文「字｜闕」＋「一」）；只在册配置开了 `row_segment.jiazhu_single_head` 时调。
  返回补进来的段，不改输入。列中间立着细竖线（两列正文当一列）时不调，同段端收编的护栏。
- `half_a_left(patch, cxi, ink_threshold) -> int | None`：表说只有一半有字的夹注格，右半格的左缘（格内 x）；
  None 交回「按墨多的一半发」。只在开了 `row_segment.jiazhu_half_a` 时调。
- `jiazhu_pair_ok(patch, ink_threshold, forced) -> bool`：这一格是不是真的并排两字（全唐文 k6：两行之间总有白缝，
  中段没有一列空白的是左右结构的整字）。两处调：人指认雙行小注的格（`forced=True`）判 False 就不拆；段端收编、
  摘掉人定整宽正文之后，段里除段尾收编的右半单字外判 False 的格从段里摘掉（`forced=False`）。每列都调。
  （2026-11-13 全唐文切分线，A22《切分开关收敛》QTW 第 3 条：row_boundaries fork 改钩子。）
- `edge_frame_only(gray, spans, content_x, border_top, border_bottom, period, ink_threshold) -> list[int]`：补认
  「列端格里只有版框线」（`row_segment` 的 P5 判据 `seg/profile.frame_only_edge_cells` 之外），返回 `spans`（一列全部格按 y
  排好的 (y0, y1)）的下标（0 或末位），与缺省判据取并集、照样记空打 frame_line。人裁整列不调。每列都调。
  （2026-11-14 全唐文 R018：空列首格把粗框条＋细线切成「一／幸／士」，框条离 border_top 远过缺省判据的 0.2 格高。）

开关开着而本书没给对应函数就拒跑（悄悄当关，这本书的切法变了没人知道）。
"""
from __future__ import annotations

#: None＝不调（缺省）。
grid_adjust = None
jiazhu_heads = None
half_a_left = None
jiazhu_pair_ok = None
edge_frame_only = None
