"""`apply_group_verdicts`：唯一的升降执行函数（在 `seed_admit` 阶段调用，拿 pick 与放行状态比）。

语义**逐条对齐**现有三处实现，旧证据键／疑问码／通道名原样保留：

- 抬待审、不改字、不降：`seed_admit._ry_group_pass`（`policy.target="pending"`＋`lift_needs_ref_agree`）；
- 只降级、不改字、不放行：`seed_admit._rr_clf_pass`（`target="admitted"`＋`demote`）；
- 升降混合、强通道冲突两边都不信：`seed_admit._ji_yi_si_clf_cell` 的规则路（`strong_channels`＋`lift_overwrites_admitted`）。

对拍见 `tests/test_groups_apply_parity.py`（在同一批合成记录上分别跑旧函数与本函数，逐字段比）。
记录是**鸭子类型**：只读写 `id`／`admit`／`char`／`channel`／`provenance`／`doubts`／`evidence`，
所以 `seed_admit` 的 `CharAdmit` 和测试里的 `SimpleNamespace` 都能用。

不覆盖（见设计档第七节）：jys 的表路建议字（`ji_yi_si_clf_table`）与 llm 路、`ji_yi_si_ctx_rule`、`ji_yi_si_review` 三方一致闸。
"""
from __future__ import annotations

from dataclasses import dataclass

from .protocol import GroupVerdict
from .registry import GroupSpec


@dataclass
class ApplyResult:
    lifted: int = 0       # 新放行的格数（原先未放行）
    demoted: int = 0      # 新退回待审的格数（原先已放行）
    touched: int = 0      # 被本遍改动过（含只加疑问码）的格数


def _append(doubts, code: str) -> list:
    return list(dict.fromkeys(list(doubts or []) + [code]))


def _mark_demoted_from(rec, by: str) -> None:
    """同 `seed_admit._demote`：只在已放行时记 `evidence.demoted_from`，必须在清空 channel 之前调用。"""
    if rec.admit:
        rec.evidence = {**(rec.evidence or {}), "demoted_from": {"channel": rec.channel, "by": by}}


def _selected(rec, ref, spec: GroupSpec) -> bool:
    p = spec.policy
    if rec.channel in p.skip_channels or getattr(rec, "provenance", None) == "human":
        return False
    if p.target == "pending" and rec.admit:
        return False
    if p.target == "admitted" and not rec.admit:
        return False
    subject = ref if p.membership == "ref" else rec.char
    if not subject or subject not in spec.members:
        return False
    ds = rec.doubts or []
    if any(d in p.skip_doubts for d in ds):
        return False
    if p.skip_doubt_substr and any(s in d for d in ds for s in p.skip_doubt_substr):
        return False
    return True


def apply_group_verdicts(records, verdicts: dict, spec: GroupSpec, refs: dict | None = None) -> ApplyResult:
    """按 `spec.policy` 把各格的 `GroupVerdict` 落到记录上。

    `records`：可迭代的格记录（顺序无关）；`verdicts`：`{id: GroupVerdict | None}`，缺项＝本格没判（不动）；
    `refs`：`{id: 整理本对位字}`，`membership="ref"` 的组需要。弃权（`verdict.char is None`）对大多数组完全不动。
    """
    p, res = spec.policy, ApplyResult()
    refs = refs or {}
    for rec in records:
        v: GroupVerdict | None = verdicts.get(rec.id)
        ref = refs.get(rec.id)
        if v is None or not _selected(rec, ref, spec):
            continue
        for key, field in p.evidence:                # 证据：判了就写，弃权也写（与现行各遍一致）
            if v.extra.get(field) is not None:
                rec.evidence = {**(rec.evidence or {}), key: v.extra[field]}
        pick = v.char
        was_admit = bool(rec.admit)

        if pick is None:                             # 弃权：多数组完全不动；jys 有一条退役通道要退回
            if p.abstain_demote_channels and rec.admit and rec.channel in p.abstain_demote_channels:
                _mark_demoted_from(rec, p.abstain_doubt)
                rec.char, rec.admit, rec.channel, rec.provenance = None, False, None, ""
                rec.doubts = _append(rec.doubts, p.abstain_doubt)
                res.demoted += 1; res.touched += 1
            continue

        if p.strong_channels and rec.admit and rec.channel in p.strong_channels and rec.char in spec.members:
            if rec.char == pick:                     # 强通道与 pick 一致：不动
                continue
            _mark_demoted_from(rec, p.conflict_doubt)     # 冲突：两边都不信，送审
            rec.char, rec.admit, rec.channel, rec.provenance = None, False, None, ""
            rec.doubts = _append(rec.doubts, p.conflict_doubt)
            res.demoted += 1; res.touched += 1
            continue

        if p.lift and (not rec.admit or p.lift_overwrites_admitted):
            if p.lift_needs_ref_agree and pick != ref:
                rec.doubts = _append(rec.doubts, p.disagree_doubt)     # 不同字：仍待审，记疑问
                res.touched += 1
                continue
            rec.char, rec.admit, rec.channel, rec.provenance = pick, True, p.lift_channel, p.lift_provenance
            rec.doubts = [d for d in (rec.doubts or []) if d not in p.lift_clear_doubts]
            if not was_admit:
                res.lifted += 1
            res.touched += 1
            continue

        if p.demote and rec.admit and pick != rec.char:
            _mark_demoted_from(rec, p.demote_by)
            if p.demote_clears_char:
                rec.char = None
            rec.admit, rec.channel, rec.provenance = False, None, ""
            rec.doubts = _append(rec.doubts, p.disagree_doubt)
            res.demoted += 1; res.touched += 1
    return res
