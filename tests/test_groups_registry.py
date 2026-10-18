# -*- coding: utf-8 -*-
"""字组注册表（`open_guji_cv/groups/registry.py`，S0）：成员与现有各处常量一致，策略合法。自造数据，不读真书。"""
from __future__ import annotations

import pytest

from open_guji_cv.groups import GROUPS, GroupPolicy, get_group, groups_of
from open_guji_cv.utils import ji_yi_si, ji_yi_si_clf, ry_group, rr_clf

BACKEND_NAMES = {"rule", "ctx_table", "table", "image"}


def test_members_match_legacy_constants():
    """注册表是单一真源，但现有代码里还有各自的成员常量（在 Step 的 code_deps 里，S0 不动它们）——两边不许漂。"""
    assert GROUPS["jys"].members == ji_yi_si_clf.FAMILY == ji_yi_si.FAMILY
    assert GROUPS["ry"].members == ry_group.FAMILY
    assert GROUPS["rr"].members == frozenset(rr_clf.CLASSES)


def test_group_ids_match_dataset_registry():
    """id 与 dataset `char-groups/groups.json` 的 id 一致（jys／ry／rr／yi_560／wxs／wm／ts）；
    另有字组统一流程首批七个异体组（mn／dian／can／chen／li／shen／zhi，2026-10-18）。"""
    assert set(GROUPS) == {"jys", "ry", "rr", "yi_560", "wxs", "wm", "ts",
                           "mn", "dian", "can", "chen", "li", "shen", "zhi"}
    assert all(g.id == k for k, g in GROUPS.items())


def test_backend_names_valid_and_members_nonempty():
    for g in GROUPS.values():
        assert g.members, g.id
        assert set(g.backends) <= BACKEND_NAMES, g.id


def test_yi_560_is_inert():
    """#560 异体组只登记成员：没有判别器，不抬不降，走人裁数据路。"""
    g = get_group("yi_560")
    assert g.backends == ()
    assert not g.policy.lift and not g.policy.demote
    assert g.members == frozenset("彝彛彜彞𢑱𢑴")


def test_groups_of_handles_unregistered_and_multi():
    assert [g.id for g in groups_of("日")] == ["ry"]
    assert [g.id for g in groups_of("𢑴")] == ["yi_560"]
    assert groups_of("天") == []


def test_members_of_different_groups_do_not_overlap():
    seen: dict[str, str] = {}
    for g in GROUPS.values():
        for ch in g.members:
            assert ch not in seen, f"{ch} 同属 {seen[ch]} 和 {g.id}"
            seen[ch] = g.id


@pytest.mark.parametrize("gid", ["jys", "ry", "rr"])
def test_policy_is_consistent(gid):
    p = GROUPS[gid].policy
    assert p.target in {"pending", "admitted", "any"}
    assert p.membership in {"ref", "char"}
    if p.lift:
        assert p.lift_channel                      # 抬升必须有通道名
    if p.lift_needs_ref_agree or p.demote:
        assert p.disagree_doubt                    # 有「不一致」分支就要有疑问码
    if p.demote:
        assert p.demote_by
    if p.strong_channels:
        assert p.conflict_doubt
    if p.abstain_demote_channels:
        assert p.abstain_doubt
    assert "human" in p.skip_channels               # 人裁位任何遍都不动


def test_policy_defaults_are_inert():
    p = GroupPolicy()
    assert not p.lift and not p.demote and not p.strong_channels and p.evidence == ()


def test_m7_solvers_declared_and_config_dirs_exist():
    """M7：每组声明解法；异体组走 ids，形近不同义组走上下文；config_dir 若已建则必须真存在。"""
    from pathlib import Path
    from open_guji_cv.groups import GROUPS
    root = Path(__file__).resolve().parents[1]
    assert GROUPS["yi_560"].kind == "variant" and GROUPS["yi_560"].solvers == ("ids",)
    for gid in ("jys", "ry", "rr", "wxs", "wm", "ts"):
        assert GROUPS[gid].kind == "near_form" and GROUPS[gid].solvers[:2] == ("ctx_l1", "ctx_l2")
    assert (root / GROUPS["yi_560"].config_dir / "ids_override.tsv").exists()
    for g in GROUPS.values():
        assert set(g.solvers) <= {"ids", "ctx_l1", "ctx_l2", "image"}
