"""5a 规则表（steps.glyph_rules）的守卫：顺序、参数登记、判决层与改前内联逻辑等价。"""

from types import SimpleNamespace

from open_guji_cv.steps.glyph_match import GlyphMatchParams
from open_guji_cv.steps.glyph_rules import (RULE_LABELS, RULES, STEP_RULES, Decision, Rule, Stage, StepState,
                                            Via, decide, decide_variant, rules_markdown)


def _params(**kw):
    return GlyphMatchParams(db_path="x.db", db_fingerprint="fp", **kw)


def _m(verdict="unsure", char=None, matched_id=None, cov=0.995, wmax=3.0, cands=(), guard=None,
       near_shape=None, same_hits=()):
    return SimpleNamespace(verdict=verdict, char=char, matched_id=matched_id, cov=cov, wmax=wmax,
                           candidates=list(cands), guard=guard, near_shape=near_shape, same_hits=same_hits)


def test_ids_unique_and_orders_increasing():
    ids = [r.id for r in RULES]
    assert len(ids) == len(set(ids))
    orders = [r.order for r in RULES]
    assert orders == sorted(orders) and len(set(orders)) == len(orders)
    assert all(r.apply is not None for r in STEP_RULES)
    assert all(r.apply is None for r in RULES if r.stage is Stage.MATCHER)


def test_registered_params_exist():
    fields = set(GlyphMatchParams.model_fields)
    for r in RULES:
        assert set(r.params) <= fields, (r.id, set(r.params) - fields)


def test_markdown_lists_every_rule():
    md = rules_markdown()
    for r in RULES:
        assert f"`{r.id.value}`" in md and r.id.label in md


def test_decide_consensus_then_near_shape():
    st = StepState(params=_params(), confirmed={"甲": 5})
    d = decide(_m(cands=[("甲", 0.995), ("乙", 0.90)]), st)
    assert (d.verdict, d.char, d.via) == ("same", "甲", "consensus:5")
    # 共识不成、近形配置关：不动
    d = decide(_m(cands=[("甲", 0.995), ("乙", 0.99)]), st)
    assert d.verdict == "unsure" and d.via is None
    # 近形开：升，via 记分
    ns = {"winner": "乙", "score": 0.12}
    st2 = StepState(params=_params(), confirmed={}, near_shape_cfg=object())
    d = decide(_m(cands=[("甲", 0.995), ("乙", 0.99)], near_shape=ns), st2)
    assert (d.verdict, d.char, d.via) == ("same", "乙", "near_shape:+0.12")
    # 护栏挡住升档
    d = decide(_m(cands=[("甲", 0.995)], guard="never_match", near_shape=ns), st2)
    assert d.verdict == "unsure"


def test_borrowed_demoted_cell_not_promoted():
    st = StepState(params=_params(), confirmed={"甲": 9}, borrowed=frozenset({"lib:a"}),
                   near_shape_cfg=object())
    m = _m(verdict="same", char="甲", matched_id="lib:a", cands=[("甲", 0.998)],
           same_hits=(("lib:a", 0.998, 3.0),), near_shape={"winner": "甲", "score": 0.3})
    d = decide(m, st)
    assert (d.verdict, d.char, d.matched_id, d.via, d.lent) == ("unsure", None, None, "borrowed:lib:a", "lib:a")
    v = decide_variant(m, st)
    assert (v.verdict, v.char) == ("unsure", None)


def test_same_passthrough():
    st = StepState(params=_params(), confirmed={"甲": 9})
    d = decide(_m(verdict="same", char="甲", matched_id="v2:1:2:3:4", cov=0.998), st)
    assert d == Decision("same", "甲", "v2:1:2:3:4", 0.998, 3.0)


def test_every_rule_enum_registered_once_with_short_label():
    assert sorted(r.id for r in RULES) == sorted(Rule)
    assert set(RULE_LABELS) == set(Rule)
    for rule, label in RULE_LABELS.items():
        assert label and len(label.split()) <= 2, (rule, label)
        assert label.isascii()


def test_via_prefixes_are_frozen_strings():
    # 落盘字符串，改了下游按通道归因就断
    assert [v.value for v in Via] == ["borrowed", "consensus", "near_shape"]
