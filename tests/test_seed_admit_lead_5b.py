"""seed_admit 字组／形近白名单（`solo_cal_allow`）与库与 5-b 不一致时听 5-b（`lead_5b`），都缺省关。"""
from __future__ import annotations

import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.steps.seed_admit import (SeedAdmitParams, _parse_cal_tiers, lead_5b_decide,
                                           solo_cal_decide)
from open_guji_cv.variants import are_variants

TIERS = _parse_cal_tiers("0.98:0.03,0.95:0.05")
SKIP = "己已巳于干曰日代伐遣遺"
CAL = dict(guard=None, tiers=TIERS, skip=SKIP, group_chars=frozenset("王玉卿鄉于干"),
           near_form_chars=frozenset("七匕士土侯"), cov_5b=0.95)
OK = ["库 unsure(cov=0.97)", "上下文 margin 不足(0.02)"]


def test_allow_needs_5b_agree():
    cands = [("卿", 0.97), ("鄉", 0.90)]
    assert solo_cal_decide(cands=cands, doubts=OK + ["group_flow_abstain"], rare_top="卿", **CAL) is None
    got = solo_cal_decide(cands=cands, doubts=OK + ["group_flow_abstain"], rare_top="卿", allow="卿", **CAL)
    assert got == ("卿", 0.97, 0.07, "allow")
    assert solo_cal_decide(cands=cands, doubts=OK, rare_top="鄉", allow="卿", **CAL) is None
    assert solo_cal_decide(cands=[("卿", 0.94), ("鄉", 0.90)], doubts=OK, rare_top="卿", allow="卿", **CAL) is None


def test_allow_skip_and_near_form():
    # 于 在 skip 里也可放（只要 5-b 同意）；near_form 疑问只对白名单字认
    assert solo_cal_decide(cands=[("于", 0.999), ("子", 0.9)], doubts=OK, rare_top="于", allow="于", **CAL)[3] == "allow"
    assert solo_cal_decide(cands=[("于", 0.999), ("千", 0.99)], doubts=OK, rare_top="干", allow="于", **CAL) is None
    assert solo_cal_decide(cands=[("侯", 0.99), ("𠋫", 0.95)], doubts=OK + ["near_form"], rare_top="侯",
                           allow="侯", **CAL)[0] == "侯"
    assert solo_cal_decide(cands=[("侯", 0.99), ("𠋫", 0.95)], doubts=OK + ["occluded"], rare_top="侯",
                           allow="侯", **CAL) is None
    # 不在白名单的普通字：照旧不认 near_form
    assert solo_cal_decide(cands=[("張", 0.99), ("振", 0.90)], doubts=OK + ["near_form"], rare_top="張",
                           allow="侯", **CAL) is None


L5 = dict(guard=None, doubts=OK, skip=SKIP, are_variants=are_variants, gap_out=0.023, gap_in=0.015, lib_min=0.935)


def test_lead_out_of_lib():
    got = lead_5b_decide(cands=[("鈎", 0.90), ("鎬", 0.89)], rare=[("筠", 0.96), ("鈎", 0.93)], cell_id="001:1:2:3", **L5)
    assert got == ("筠", 0.03, "out")
    assert lead_5b_decide(cands=[("鈎", 0.90)], rare=[("筠", 0.95), ("鈎", 0.94)], cell_id="001:1:2:3", **L5) is None


def test_lead_lib_second():
    cands = [("李", 0.983), ("季", 0.979)]
    assert lead_5b_decide(cands=cands, rare=[("季", 0.97), ("䄹", 0.944)], cell_id="001:1:2:3", **L5) == ("季", 0.026, "in")
    assert lead_5b_decide(cands=cands, rare=[("季", 0.97), ("䄹", 0.96)], cell_id="001:1:2:3", **L5) is None
    # 库给 5-b 首位的分太低（俄→我、真字是 義）
    assert lead_5b_decide(cands=[("俄", 0.939), ("我", 0.9296)], rare=[("我", 0.9388), ("找", 0.9048)],
                          cell_id="001:1:2:3", **L5) is None
    # 5-b 首位是库第三名：不放
    assert lead_5b_decide(cands=[("李", 0.98), ("季", 0.97), ("秀", 0.96)], rare=[("秀", 0.99), ("x", 0.9)],
                          cell_id="001:1:2:3", **L5) is None


@pytest.mark.parametrize("cands,rare,cid,over", [
    ([("才", 0.926)], [("彳", 0.9578), ("犭", 0.9264)], "001:162:2:17b", {}),     # 拆分子格的半字
    ([("鎭", 0.958), ("鎮", 0.93)], [("鎮", 0.99), ("鏌", 0.94)], "001:1:2:3", {}),  # 异体交码位
    ([("于", 0.99)], [("干", 0.99), ("千", 0.90)], "001:1:2:3", {}),                 # skip 里的字
    ([("鈎", 0.90)], [("筠", 0.96), ("x", 0.90)], "001:1:2:3", {"guard": "never_match"}),
    ([("鈎", 0.90)], [("筠", 0.96), ("x", 0.90)], "001:1:2:3", {"doubts": OK + ["group_flow_abstain"]}),
    ([("鈎", 0.90)], [("〓", 0.96), ("x", 0.90)], "001:1:2:3", {}),
])
def test_lead_rejects(cands, rare, cid, over):
    kw = {**L5, **over}
    assert lead_5b_decide(cands=cands, rare=rare, cell_id=cid, **kw) is None


def test_dump_off_by_default():
    d = SeedAdmitParams().model_dump()
    assert not any(k.startswith("lead_5b") for k in d)
    assert "solo_cal_allow" not in d
    d2 = SeedAdmitParams(solo_cal=True, solo_cal_allow="卿", lead_5b=True).model_dump()
    assert d2["solo_cal_allow"] == "卿" and d2["lead_5b"] is True and d2["lead_5b_gap_out"] == 0.023


def test_allow_plain_char_keeps_normal_tiers():
    # 白名单里不在字组／形近表／skip 的字（如 文）照常走 cov／gap 档，不因进白名单而只剩 5-b 档
    got = solo_cal_decide(cands=[("文", 0.99), ("丈", 0.95)], doubts=OK, rare_top="丈", allow="文", **CAL)
    assert got == ("文", 0.99, 0.04, "tier")
