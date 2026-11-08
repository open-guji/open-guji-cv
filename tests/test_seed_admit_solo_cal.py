"""seed_admit 无参照格 5a 校准直放（`SeedAdmitParams.solo_cal`，缺省关）。"""
from __future__ import annotations

import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _parse_cal_tiers, solo_cal_decide

TIERS = _parse_cal_tiers("0.98:0.03,0.95:0.05")
SKIP = "己已巳于干曰日代伐遣遺"
KW = dict(guard=None, doubts=["库 unsure(cov=0.97)", "上下文 margin 不足(0.02)"], tiers=TIERS, skip=SKIP,
          group_chars=frozenset("王玉"))


def test_tiers():
    assert TIERS == [(0.98, 0.03), (0.95, 0.05)]
    assert solo_cal_decide(cands=[("張", 0.985), ("振", 0.95)], **KW) == ("張", 0.985, 0.035)
    assert solo_cal_decide(cands=[("張", 0.96), ("振", 0.905)], **KW) == ("張", 0.96, 0.055)
    assert solo_cal_decide(cands=[("張", 0.96)], **KW) == ("張", 0.96, 0.96)       # 没有异字：gap＝cov
    assert solo_cal_decide(cands=[("張", 0.985), ("張", 0.97), ("振", 0.95)], **KW) == ("張", 0.985, 0.035)


@pytest.mark.parametrize("cands,over", [
    ([("張", 0.985), ("振", 0.96)], {}),                           # 0.98 档 gap 不够
    ([("張", 0.97), ("振", 0.93)], {}),                            # 0.95 档 gap 不够
    ([("張", 0.94), ("振", 0.80)], {}),                            # cov 太低
    ([("代", 0.99), ("張", 0.90)], {}),                            # 首位在排除对
    ([("張", 0.99), ("遣", 0.90)], {}),                            # 第一个异字在排除对
    ([("王", 0.99), ("張", 0.90)], {}),                            # 首位在字组
    ([("張", 0.99), ("振", 0.90)], {"guard": "conflict"}),
    ([("張", 0.99), ("振", 0.90)], {"doubts": ["occluded"]}),
    ([("張", 0.99), ("振", 0.90)], {"doubts": ["库里没有这个字"]}),
])
def test_blocks(cands, over):
    assert solo_cal_decide(cands=cands, **{**KW, **over}) is None


def test_ok_doubts():
    for d in ("near_form", "护栏:never_match", "group_flow_abstain"):
        assert solo_cal_decide(cands=[("七", 0.99), ("匕", 0.90)], **{**KW, "doubts": [d]}) is not None
    assert solo_cal_decide(cands=[("七", 0.99), ("匕", 0.90)], **{**KW, "guard": "never_match"}) is not None


def test_params_invisible_when_off():
    d = SeedAdmitParams().model_dump()
    assert not [k for k in d if k.startswith("solo_cal")]
    d = SeedAdmitParams(solo_cal=True).model_dump()
    assert d["solo_cal"] and d["solo_cal_tiers"] == "0.98:0.03,0.95:0.05"
