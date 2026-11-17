"""整理本缺字占位符（A23 2026-11-16 设计，Sheldon 审定）。

殆知阁逐列整理本里有两类「有字、读不出」的占位，原来都写 `〓`，下游分不开：

- `〓`（U+3013）私用码：源里一个私用区码位，一码一字形，同码同字。码表（config/pua/pua_table.jsonl）定了字的换成码表字，
  没定的（一码多字、待收）仍写 `〓`，原码位记在侧表。
- `▣`（U+25A3）以图代字：源里缅甸字母 U+1001… 占位，本叶 `glyphs` 登记字图，一处一图，没有码位。

两者对对位／放行／组判定的语义**一样**：知道这儿有字、不知道是哪个字，不当证人。要区分时用 `gap_kind`。
设计：ai-team 外的 /mnt/project-files/A23/整理本占位符区分设计-2026-11-16.md；代码侧所有「== 〓」都改走这里。
"""
from __future__ import annotations

GAP_PUA = "〓"      # 〓 私用码（未定字）
GAP_IMAGE = "▣"    # ▣ 以图代字
GAP_CHARS = (GAP_PUA, GAP_IMAGE)
GAP_SET = frozenset(GAP_CHARS)


def is_gap(ch) -> bool:
    """是不是缺字占位（两种都算）。None／空串／多字串都不是。"""
    return ch in GAP_SET


def gap_kind(ch) -> str | None:
    """`pua`（〓）｜`image`（▣）｜None。"""
    if ch == GAP_PUA:
        return "pua"
    if ch == GAP_IMAGE:
        return "image"
    return None
