"""管线**回流**读裁决表：给 Step 用的只读查询，数据源是 workspace 的
`feedback/verdicts/`（`consumers.verdict_store()`），**不是** open-guji-dataset。

三仓边界（2026-09-13）：生产管线运行时只读写 workspace。第一版人裁回流从测试集
仓取金标（cv `78319605cf`，已撤），这里是改到裁决表之后的版本。
"""

from __future__ import annotations

TOUCHING_CUTS_SHARD = "char-segmentation/touching-cuts"
CUT_KINDS = ("straight", "seam_narrow", "seam_wide")


def resolved_cuts(book: str) -> dict[tuple[int, int, int], str]:
    """已裁决、可直接收敛的切点：`(page, col, slot_above) → 候选 kind`。

    收「人从候选池里选中了哪一条」：`cand` 落在 `CUT_KINDS` 内、`status` 为 active、
    `verdict` 不是 overlap / idk。Step7 裁决台发的 verdict 是 `confirmed`，Step3 切线
    卡发的是 `ok` / `moved`，都认——判据是 cand，不是 verdict 的具体词。
    `overlap`（切哪都伤字）、`idk`（拿不准）不收，那两类是真难例仍要留给人，见
    `.claude/doc/row_boundaries_design.md`「5 条都不对」节。人自己画的折线（`polyline`）
    不在候选池里，收不了——候选池只有算法算出来的那几条。

    生效时机：`segment_column` 在**该页下次重跑**时按这张表收敛候选；裁决本身不改
    产物指纹（指纹是步骤级参数，塞进去会让全书 Step3 及下游一起过期）。Step7 顺序闸
    另按事件日志即时放行（`review/cards.py`），人不会因此被挡。
    """
    from .consumers import verdict_store
    out: dict[tuple[int, int, int], str] = {}
    try:
        items = verdict_store().list(TOUCHING_CUTS_SHARD, legacy=False)
    except Exception:
        return out
    for it in items:
        if it.status != "active" or str(it.anchor.book) != book:
            continue
        cand = it.expected.get("cand")
        if cand not in CUT_KINDS or it.expected.get("verdict") in ("overlap", "idk"):
            continue
        page, col, slot = it.anchor.page, it.anchor.col, it.anchor.slot
        if page is None or col is None or slot is None:
            continue
        out[(page, col, slot)] = cand
    return out
