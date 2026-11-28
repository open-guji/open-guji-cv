"""follow_ref_seen：看图核实过的字对（A24 2026-11-02，全唐文）。"""
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _parse_follow_ref_seen, seen_pair_decide

R = _parse_follow_ref_seen("天=大,天=又,永=氷")


def _d(**kw):
    base = dict(admit=False, channel=None, char="大", doubts=["near_form", "group_flow_abstain", "上下文 margin 不足(0.2)"],
                ref="天", cands=[("大", 0.95), ("天", 0.92), ("又", 0.88)], verdict="unsure", guard=None, rules=R,
                cov_min=0.92, gap_min=0.005)
    base.update(kw)
    return seen_pair_decide(**base)


def test_parse_multi():
    assert R["天"] == frozenset({"大", "又"}) and R["永"] == frozenset({"氷"})


def test_admit_despite_near_form_and_abstain():
    assert _d() == "admit"


def test_hard_doubts_block():
    for dd in ("occluded", "group_flow_disagree", "ctx_garble_run", "护栏:x"):
        assert _d(doubts=[dd]) is None


def test_not_in_table_or_low_cov_or_rival():
    assert _d(ref="王") is None
    assert _d(cands=[("大", 0.90)]) is None
    assert _d(cands=[("大", 0.95), ("犬", 0.948)]) is None
    assert _d(cands=[("犬", 0.97), ("大", 0.95)]) is None
    assert _d(admit=True) is None and _d(channel="human") is None and _d(verdict="diff") is None


def test_default_params_dump_unchanged():
    d = SeedAdmitParams().model_dump()
    assert "follow_ref_seen" not in d
    assert "follow_ref_seen" in SeedAdmitParams(follow_ref_seen="天=大").model_dump()


def test_conflict_pair_follows_ref_when_enabled():
    # N01 第 7 轮复查：七／𠤎 字形相同，库里两个都判 same（护栏 conflict）；开 allow_conflict 且候选前两名恰是这一对 → 放整理本形
    rules = _parse_follow_ref_seen("七=𠤎,𠤎=七")
    kw = dict(char="𠤎", doubts=["护栏:conflict", "库 unsure(cov=0.999)", "iron_ex_missing"], ref="七",
              cands=[("𠤎", 0.999), ("七", 0.999), ("名", 0.88)], verdict="unsure", guard="conflict", rules=rules)
    assert _d(**kw) is None                              # 缺省关：照旧拦
    assert _d(**kw, allow_conflict=True) == "admit"
    assert _d(**{**kw, "ref": "𠤎", "char": "七", "cands": [("七", 0.999), ("𠤎", 0.999)]}, allow_conflict=True) == "admit"


def test_conflict_pair_guards_stay():
    rules = _parse_follow_ref_seen("七=𠤎,𠤎=七")
    kw = dict(char="𠤎", doubts=["护栏:conflict"], ref="七", verdict="unsure", guard="conflict", rules=rules, allow_conflict=True)
    assert _d(**kw, cands=[("𠤎", 0.999), ("匕", 0.999), ("七", 0.998)]) is None      # 前两名混进组外字
    assert _d(**{**kw, "ref": "匕"}, cands=[("𠤎", 0.999), ("七", 0.999)]) is None          # 整理本是第三个字
    assert _d(**{**kw, "guard": "never_match", "doubts": ["护栏:never_match"]}, cands=[("𠤎", 0.999), ("七", 0.999)]) is None
    assert _d(**{**kw, "doubts": ["护栏:conflict", "occluded"]}, cands=[("𠤎", 0.999), ("七", 0.999)]) is None


def test_conflict_param_default_not_in_dump():
    assert "follow_ref_seen_conflict" not in SeedAdmitParams(follow_ref_seen="七=𠤎").model_dump()
    assert "follow_ref_seen_conflict" not in SeedAdmitParams(follow_ref_seen_conflict=True).model_dump()
    assert SeedAdmitParams(follow_ref_seen="七=𠤎", follow_ref_seen_conflict=True).model_dump()["follow_ref_seen_conflict"] is True
