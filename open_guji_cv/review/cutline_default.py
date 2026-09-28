# -*- coding: utf-8 -*-
"""Step7「切分裁决」卡片的默认选中项（overview#188，2026-09-28）。

用户：「step 7 切分裁决应该默认选择 u-net，方便快速确认」。卡里有 U-Net 候选
（`unet_seam`，L3 扩池补的）就默认选它，没有才退回引擎 `chosen`。qtw-draft v006
实测 250 卡里 110 卡带 `unet_seam`，且没有一张被引擎选为 `chosen`。

书级开关 `params.review.cutline_default: unet | chosen`（书 yaml，缺省 `unet`），
哪本书要退回「默认选引擎」就改它。

verdict 口径随之改成**跟卡片的默认选中项比**（C 道定，overview#188 评论）：
`moved` = 用户动手改了（改选别的候选或自己画），直接确认默认项记 `ok`。
「用户认可的是 U-Net 还是引擎」另记在事件的 `picked_source`／`default_pick` 里，
下游要「引擎错没错」看 `picked_source != "engine"`，**不要**再拿 `moved` 当这个信号。
事件怎么写在前端 `components/cutline/cutlineVerdict.ts`。
"""
from __future__ import annotations

UNET_KIND = "unet_seam"
MODES = ("unet", "chosen")
DEFAULT_MODE = "unet"


def cutline_default_mode(book_spec) -> str:
    """书 yaml `params.review.cutline_default` → `"unet"` / `"chosen"`，没配为 `"unet"`。

    写错了直接报错（同 `borrow_first.first_pick_mode`）：开关写错却以为退回了引擎，
    用户一路 Enter 确认的就不是自己以为的那条线。
    """
    cfg = ((getattr(book_spec, "params", None) or {}).get("review") or {})
    v = cfg.get("cutline_default")
    if v in (None, ""):
        return DEFAULT_MODE
    if v not in MODES:
        raise ValueError(f"书 yaml params.review.cutline_default 只认 {MODES}，得到 {v!r}")
    return v


def default_pick(candidates: list[dict], chosen: int | None, mode: str) -> tuple[int | None, str]:
    """一张卡的默认选中项 → `(候选下标 或 None, "unet" | "chosen")`。

    第二个值是**这张卡实际默认成了什么**，不是开关值：开关是 `unet` 但卡里没有
    U-Net 候选时退回 `chosen`，记 `"chosen"`。
    """
    if mode == "unet":
        for i, c in enumerate(candidates or []):
            if c.get("kind") == UNET_KIND:
                return i, "unet"
    return chosen, "chosen"


def attach_default_pick(cases: list[dict], mode: str) -> None:
    """给每个用例挂 `default_idx`／`default_pick`（就地改）。候选要先由 `_attach_candidates` 挂好。"""
    for c in cases:
        c["default_idx"], c["default_pick"] = default_pick(c.get("candidates") or [], c.get("chosen"), mode)
