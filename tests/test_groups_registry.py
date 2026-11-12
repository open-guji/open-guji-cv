# -*- coding: utf-8 -*-
"""字组注册表（`open_guji_cv/groups/registry.py`）：成员与现有各处常量一致，判法合法。自造数据，不读真书。"""
from __future__ import annotations


from open_guji_cv.groups import GROUPS, get_group, groups_of
from open_guji_cv.utils import ji_yi_si, ji_yi_si_clf, rr_clf

BACKEND_NAMES = {"rule", "ctx_table", "table", "image"}


def test_members_match_legacy_constants():
    """注册表是单一真源，但现有代码里还有各自的成员常量（在 Step 的 code_deps 里，S0 不动它们）——两边不许漂。"""
    assert GROUPS["jys"].members == ji_yi_si_clf.FAMILY == ji_yi_si.FAMILY
    assert GROUPS["ry"].members == frozenset("日曰")
    assert GROUPS["rr"].members == frozenset(rr_clf.CLASSES)


def test_group_ids_match_dataset_registry():
    """id 与 dataset `char-groups/groups.json` 的 id 一致（jys／ry／rr／yi_560／wxs／wm／ts）；
    另有字组统一流程首批七个异体组（mn／dian／can／chen／li／shen／zhi，2026-10-18；li 2026-10-26 改按刻形判、移到 SHAPE_GROUPS）、第二批四个只看字频的（ji／qing／bian／hui）、
    第三批五个形近不同义的（ly／dt／wj／zh／yh，2026-10-19）、第四批三个（xz／wyu／yt）、日目 rm、第五批（mz／yr／sb／js／em／fc／mb；qg 2026-10-24 并进 zy）、
    第三批只看字频的异体组六个（kan／jiw／qx／dx／zx／qy，2026-10-20）、按字分类 IDS 三组（xu／ce／jiao）、
    整字岭回归 lv 呂吕（2026-10-20；zheng 徵徴 2026-10-27 改成码位组，暂归一到 徴）。"""
    assert set(GROUPS) == {"jys", "ry", "rr", "yi_560", "wxs", "wm", "ts",
                           "dian", "can", "chen", "shen", "zhi", "ji", "qing", "hui", "ly", "dt", "wj", "zh", "yh", "xz", "wyu", "yt", "rm",
                           "mz", "yr", "sb", "js", "em", "fc", "mb",
                           "kan", "jiw", "qx", "dx", "zx", "qy", "xu", "ce", "jiao",
                           "qik", "lih", "jue", "wei", "shuo", "lv", "zy", "sy", "sz", "gm", "xb", "weiw", "shan", "di", "ss"}
    assert all(g.id == k for k, g in GROUPS.items())


def test_backend_names_valid_and_members_nonempty():
    for g in GROUPS.values():
        assert g.members, g.id
        assert set(g.backends) <= BACKEND_NAMES, g.id


def test_yi_560_flow():
    """#560 彝组：字频→IDS 三段（2026-10-20 上线）。"""
    g = get_group("yi_560")
    assert g.backends == () and g.flow is not None and g.flow.solvers == ("freq", "ids")
    assert g.members == frozenset("彝彛彜彞𢑱𢑴")


def test_groups_of_handles_unregistered_and_multi():
    assert sorted(g.id for g in groups_of("日")) == ["rm", "ry"]
    assert [g.id for g in groups_of("𢑴")] == ["yi_560"]
    assert groups_of("天") == []


def test_members_of_different_groups_do_not_overlap():
    """成员不许重叠，除非两个组在 `overlaps` 里互相声明（日曰 ry／日目 rm 共用「日」）。查字组流程可点名的全部组（含码位归一组）。"""
    from open_guji_cv.groups.registry import FLOW_GROUPS
    seen: dict[str, str] = {}
    for g in FLOW_GROUPS.values():
        for ch in g.members:
            if ch in seen:
                other = FLOW_GROUPS[seen[ch]]
                assert g.id in other.overlaps and other.id in g.overlaps, f"{ch} 同属 {seen[ch]} 和 {g.id}"
            seen[ch] = g.id
    for g in FLOW_GROUPS.values():
        for o in g.overlaps:
            assert g.id in FLOW_GROUPS[o].overlaps, f"{g.id} 声明与 {o} 重叠但对方没声明"


def test_old_m7_groups_all_covered_by_group_flow():
    """S6（2026-10-18）：旧 m7 上下文路覆盖的六组都在字组统一流程里有判法；土士、未末加量横。"""
    for gid in ("jys", "ry", "rr", "wxs", "wm", "ts"):
        assert GROUPS[gid].flow is not None and "ctx" in GROUPS[gid].flow.solvers, gid
    assert GROUPS["wm"].flow.solvers == ("ctx", "bars")
    assert GROUPS["ts"].flow.solvers == ("ctx", "bars", "ids")      # 2026-10-22 加字形第二路
    assert GROUPS["jys"].flow.review and GROUPS["jys"].flow.review_fix and GROUPS["jys"].flow.review_abstain


def test_m7_solvers_declared_and_config_dirs_exist():
    """M7：每组声明解法；异体组走 ids，形近不同义组走上下文；config_dir 若已建则必须真存在。"""
    from pathlib import Path
    from open_guji_cv.groups import GROUPS
    root = Path(__file__).resolve().parents[1]
    assert GROUPS["yi_560"].kind == "variant" and GROUPS["yi_560"].solvers == ("ids",)
    for gid in ("jys", "ry", "rr", "wxs", "wm", "ts"):
        assert GROUPS[gid].kind == "near_form" and GROUPS[gid].solvers[:2] == ("ctx_l1", "ctx_l3")
    assert (root / GROUPS["yi_560"].config_dir / "ids_override.tsv").exists()
    for g in GROUPS.values():
        assert set(g.solvers) <= {"ids", "ctx_l1", "ctx_l3", "image"}
