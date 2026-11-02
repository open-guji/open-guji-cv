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
