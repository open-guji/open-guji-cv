"""于千子干等形近不同义组（2026-10-24，A24「强化于千子干等形近判别」）：千干 qg 并进 zy、新建 予子 yz、官宫宮 guan、侯候𠉀俟 hou、兩雨 liang。"""
from types import SimpleNamespace

from open_guji_cv.groups.flow import FlowConfig, check_groups, decide, entry
from open_guji_cv.groups.methods import Only
from open_guji_cv.groups.protocol import GroupVerdict
from open_guji_cv.groups.registry import FLOW_GROUPS, GROUPS, RENAMED, SHAPE_GROUPS, flow_names

NEW = ("zy", "yz", "guan", "hou", "liang")


def _cell(admit=False, char=None):
    return SimpleNamespace(id="vol12:1:1:1", char=char, admit=admit, channel=None, provenance="", doubts=[], evidence={})


def test_registered_and_checked():
    check_groups(NEW)
    assert GROUPS["zy"].members == frozenset("于千子干") and "qg" not in FLOW_GROUPS
    assert {"yz", "guan", "hou", "liang"} <= set(SHAPE_GROUPS) and not {"yz", "guan", "hou", "liang"} & set(GROUPS)
    # GROUPS 的成员全集不变（并组前 zy 子于 ＋ qg 千干），glyph_match 弱命中与 rare_ref_coord 的行为不变
    assert set(GROUPS["zy"].members) == set("子于") | set("千干")


def test_renamed_qg_reads_as_zy():
    assert RENAMED["qg"] == "zy"
    assert flow_names(["jys", "qg", "sb", "zy"]) == ("jys", "zy", "sb")


def test_seed_admit_param_renames(tmp_path):
    from open_guji_cv.steps.seed_admit import SeedAdmitParams
    p = SeedAdmitParams(group_flow=["qg", "zy", "jys"], db_path=str(tmp_path / "none.db"))
    assert p.group_flow == ("zy", "jys")


def test_entry_four_way_tie_goes_to_zy_and_yu_tie_to_yz():
    cfg = FlowConfig(groups=NEW)
    # 「禘【于】太廟」库排 子于干千、分差 0.002 内：并组前哪组都装不下
    assert entry(_cell(), [("子", 0.996), ("于", 0.996), ("干", 0.995), ("千", 0.994)], None, cfg) == ("zy", "lift")
    # 予子紧咬归 yz（zy 装不下 予）
    assert entry(_cell(), [("子", 0.998), ("予", 0.995)], None, cfg) == ("yz", "lift")
    assert entry(_cell(), [("宫", 0.998), ("官", 0.998), ("宮", 0.994)], None, cfg) == ("guan", "lift")
    assert entry(_cell(), [("𠉀", 0.976), ("候", 0.969), ("侯", 0.966)], None, cfg) == ("hou", "lift")


def test_l1_rules_decide_and_family_form():
    cfg = FlowConfig(groups=NEW)
    r = _cell()
    ch, why, _ = decide("guan", r, [("宫", 0.999), ("官", 0.997)], None, cfg, left="乾隆壬戌進士", right="宜君縣知縣")
    assert (ch, why) == ("官", "agree")
    # 宫族：库形最近领先族内另一形不到 form_margin → 待定
    ch, why, trail = decide("guan", r, [("官", 0.997), ("宫", 0.996), ("宮", 0.995)], None, cfg, left="不出朱子之一證矣古者", right="室皆有定制")
    assert ch is None and trail[-1]["why"] == "abstain:form_close"
    ch, _, _ = decide("hou", r, [("候", 0.969), ("侯", 0.958)], None, cfg, left="所爲阮諶夏", right="伏")
    assert ch == "侯"
    ch, _, _ = decide("zy", r, [("干", 0.999), ("千", 0.999)], None, cfg, left="詞嚴義正足以爲", right="古之大防矣")
    assert ch == "千"


def test_only_gate():
    class Inner:
        name = "ids"; needs_patch = False
        def run(self, inp):
            return GroupVerdict(inp.cfg.answer, why="agree", via="ids")
    g = Only("ids", inner=Inner(), chars=frozenset("子于干"), give=frozenset("子于"))
    mk = lambda cands, ref=None, ans="于": SimpleNamespace(cands=cands, ref=ref, cfg=SimpleNamespace(delta=0.03, answer=ans))
    assert g.run(mk([("子", 0.99), ("于", 0.98)])).char == "于"
    assert g.run(mk([("子", 0.99), ("千", 0.98)])).why == "abstain:gate"           # 千 紧咬：HOG 没见过，不跑
    assert g.run(mk([("子", 0.99), ("于", 0.98)], ref="千")).why == "abstain:gate"  # 整理本是 千
    assert g.run(mk([("子", 0.99), ("于", 0.98)], ans="干")).why == "abstain:gate_give"
