"""待审原因 PendingReason 的守卫：enum 与 yaml 一致、码与优先级不重复、旧码都有去处、不确定的给 unknown。"""
import json

import pytest

from open_guji_cv.review import pending_reason as pr
from open_guji_cv.review.causes import CAUSES
from open_guji_cv.review.cards import CLASS_KEYS
from open_guji_cv.review.pending_reason import PendingReason, Route


def test_yaml_matches_enum():
    s = pr.specs()
    assert set(s) == set(PendingReason)
    for r in PendingReason:
        assert r.value == r.name.lower()


def test_codes_and_priorities_unique():
    s = pr.specs().values()
    codes = [x.code for x in s]
    prios = [x.priority for x in s]
    assert len(codes) == len(set(codes))
    assert len(prios) == len(set(prios))
    for x in s:
        assert x.code[0] == pr._load()["categories"][x.category.value]["code"], x


def test_unknown_is_last_and_human():
    u = PendingReason.UNKNOWN.spec
    assert u.priority == max(x.priority for x in pr.specs().values())
    assert u.route is Route.HUMAN


@pytest.mark.parametrize("v", [None, "", "  ", "no_such_reason", "A2", 3])
def test_parse_uncertain_is_unknown(v):
    assert pr.parse(v) is PendingReason.UNKNOWN


def test_parse_known():
    assert pr.parse("group_abstain") is PendingReason.GROUP_ABSTAIN
    assert pr.parse(PendingReason.HARD_PAIR) is PendingReason.HARD_PAIR
    assert str(PendingReason.HARD_PAIR) == "hard_pair"
    assert json.dumps({"pending_reason": PendingReason.HARD_PAIR}) == '{"pending_reason": "hard_pair"}'


def test_every_legacy_cause_and_cls_has_a_home():
    """旧成因码、旧卡片类别都至少对应一个新原因（迁移旧数据时推得出；推不出才落 unknown）。"""
    for c in CAUSES:
        assert pr.legacy_candidates(cause=c), c
    for k in CLASS_KEYS:
        assert pr.legacy_candidates(cls=k), k


def test_by_code_and_export():
    assert pr.by_code("Z01") is PendingReason.GROUP_ABSTAIN
    assert pr.by_code("Q99") is PendingReason.UNKNOWN
    e = pr.export()
    assert e["field"] == "pending_reason"
    assert set(e["reasons"]) == {r.value for r in PendingReason}
    json.dumps(e, ensure_ascii=False)
