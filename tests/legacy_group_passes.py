# -*- coding: utf-8 -*-
"""**冻结的旧实现**：S2a 之前 `seed_admit._ry_group_pass`／`_rr_clf_pass` 的原样副本（取自 main 22c24d9b）。

S2a 把这两个遍改成「后端 judge → `apply_group_verdicts`」之后，`seed_admit` 里已经没有旧实现了；
对拍测试（`test_groups_apply_parity.py`）需要一份**不会随生产代码变**的参考实现，才不会变成自己对自己。
所以把旧逻辑原样冻在这里。**不要改它**——它是「等价」的定义；要改生产行为请先改这里并说明为什么。
依赖 `seed_admit` 里没动的 `_clf_ctx`／`_page_patch`／`_demote`／`PatchUnavailable`。
"""
from __future__ import annotations

import open_guji_cv.steps.seed_admit as sa
from open_guji_cv.core.step import RunContext


def ry_group_pass_legacy(out: list, amap: dict, cache: str) -> int:
    """日／曰 v2 答案表只读证据（overview#441）→ 新增放行数。只抬待审的日曰格，不改字、不降放行格。"""
    from open_guji_cv.utils.ry_group import FAMILY, decide
    seq = [r for c in sorted(out, key=lambda c: c.col) for r in c.chars
           if not (r.doubts and "excluded" in r.doubts)]
    n = 0
    for i, r in enumerate(seq):
        ref = (amap.get(r.id) or (None, None))[0]
        if (r.admit or r.channel == "human" or ref not in FAMILY
                or any(d in ("occluded", "glyph_timeout") or "seal" in d for d in (r.doubts or []))):
            continue
        res = decide(cache, r.id, sa._clf_ctx(seq, amap, i, -1), sa._clf_ctx(seq, amap, i, 1))
        if not res:
            continue
        r.evidence = {**(r.evidence or {}), "ry_group": res}
        ch = res.get("char")
        if not ch:
            continue
        if ch != ref:
            r.doubts = list(dict.fromkeys((r.doubts or []) + ["ry_disagree"]))
            continue
        r.char, r.admit, r.channel, r.provenance = ch, True, "ry_group", "context"
        r.doubts = [d for d in (r.doubts or []) if d != "always_review"]
        n += 1
    return n


def rr_clf_pass_legacy(ctx: RunContext, page: int, p: object, out: list, patch_missing: dict) -> int:
    """入人八字形分类器的「分歧→送审」（只降级，放在所有通道与各遍之后）。→ 降级格数。见 `SeedAdmitParams.rr_clf`。"""
    from open_guji_cv.utils import rr_clf
    model = p.rr_clf_model or None
    n = 0
    for col in out:
        for rec in col.chars or []:
            if (not rec.admit or rec.provenance == "human" or rec.channel == "human"
                    or not rec.char or rec.char not in rr_clf.CLASSES):
                continue
            try:
                patch = sa._page_patch(ctx, page, col.col, rec.slot, rec.sub)
            except sa.PatchUnavailable:
                if p.patch_missing != "skip":
                    raise
                patch_missing.setdefault(rec.id, []).append("rr_clf")
                rec.evidence = {**(rec.evidence or {}), "patch_missing": list(patch_missing[rec.id])}
                continue
            c = rr_clf.classify(patch, model, p.rr_clf_p)
            rec.evidence = {**(rec.evidence or {}), "rr_clf": c}
            if c["pick"] and c["pick"] != rec.char:
                sa._demote(rec, "rr_clf")
                rec.admit, rec.channel, rec.provenance = False, None, ""
                rec.doubts = list(dict.fromkeys(list(rec.doubts or []) + ["rr_clf_disagree"]))
                n += 1
    return n

