"""M7 上下文路接进 `seed_admit` 的一遍（GUJI-563）：L1 规则先行，弃权再查 v3 答案表（L2），
按注册表声明的策略交 `apply_group_verdicts` 执行升降。

只被 `seed_admit` 在书级开关 `m7_groups` 非空时调用；缺省关，关着时本模块不执行。窗口由调用方的 `ctx_fn`
给（`seed_admit._clf_ctx`，邻格取已放行字→整理本字→□，宽 `context.WIDTH`），同一份窗口既用于 L1 也用于 L2 表的键，
所以建表（`research/m7/ctx/l2_make_book.py`）与运行时必须用同一个窗口函数。

判格在前、改格在后：先对本页所有候选格算好 verdict（窗口来自遍前状态），再逐组执行，避免前一格被改字后
污染后一格的窗口。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

from .apply import ApplyResult, apply_group_verdicts
from .ctx_l1 import CtxL1Backend
from .ctx_l2 import CtxL2Backend
from .context import WIDTH
from .protocol import GroupVerdict, JudgeInput, window_from_text
from .registry import GROUPS

_REPO = Path(__file__).resolve().parents[2]
_L1: dict[str, CtxL1Backend] = {}
_L2: dict[str, CtxL2Backend] = {}


def rules_path(group: str) -> Path:
    return _REPO / GROUPS[group].config_dir / "rules.yaml"


def fingerprint(groups, tables: dict[str, str]) -> str:
    """规则文件与答案表的内容哈希；换了任何一个，seed_admit 产物判过期。"""
    h = hashlib.sha256()
    for g in sorted(groups):
        p = rules_path(g)
        h.update(g.encode())
        h.update(hashlib.sha256(p.read_bytes()).digest() if p.exists() else b"missing")
        t = tables.get(g)
        h.update(hashlib.sha256(Path(t).read_bytes()).digest() if t and Path(t).exists() else b"-")
    return h.hexdigest()[:16]


def _l1(g: str) -> CtxL1Backend:
    if g not in _L1:
        _L1[g] = CtxL1Backend(rules_path(g), GROUPS[g].members)
    return _L1[g]


def _l2(path: str) -> CtxL2Backend:
    if path not in _L2:
        _L2[path] = CtxL2Backend(path)
    return _L2[path]


def judge(g: str, cid: str, ref, left: str, right: str, table: str | None) -> GroupVerdict:
    spec = GROUPS[g]
    cell = JudgeInput(id=cid, ref=ref, window=window_from_text(left, right))
    v = _l1(g).judge(spec, cell)
    if v.char is not None:
        return v
    if table:
        v2 = _l2(table).judge(spec, cell)
        v2.extra = {**v2.extra, "l1_why": v.why}
        return v2
    return v


def m7_pass(seq: list, amap: dict, groups: tuple, tables: dict[str, str],
            ctx_fn: Callable[[list, int, int], str]) -> dict[str, ApplyResult]:
    """`seq`：本页读序展平后的格记录（已剔除排除名单格）；`amap`：{id: (整理本字, op)}。→ 逐组执行结果。"""
    verdicts: dict[str, dict[str, GroupVerdict]] = {g: {} for g in groups}
    refs: dict[str, str | None] = {}
    for i, r in enumerate(seq):
        ref = (amap.get(r.id) or (None, None))[0]
        refs[r.id] = ref
        left = right = None
        for g in groups:
            mem = GROUPS[g].members
            if ref not in mem and r.char not in mem:
                continue
            if left is None:
                left, right = ctx_fn(seq, i, -1), ctx_fn(seq, i, 1)
            verdicts[g][r.id] = judge(g, r.id, ref, left, right, tables.get(g))
    res: dict[str, ApplyResult] = {}
    for g in groups:
        res[g] = apply_group_verdicts(seq, verdicts[g], GROUPS[g], refs)
    by_id = {r.id: r for r in seq}
    for g in groups:
        for cid, v in verdicts[g].items():
            if v.char is None:
                continue
            r = by_id[cid]
            ev = {**(r.evidence or {}).get("m7_group", {}), g: {"char": v.char, "via": v.via, "why": v.why,
                                                              "rules": v.extra.get("rules")}}
            r.evidence = {**(r.evidence or {}), "m7_group": ev}
    return res
