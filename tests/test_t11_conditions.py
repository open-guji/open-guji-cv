# -*- coding: utf-8 -*-
"""Elena 208cz 评审条件的补测（GUJI-208ha）：lib_variant 优先（witness3_no_diff 无书开，2026-11-23 删）。数据全是自造的。
（过切提示与矮格转人审的几条已随两开关于 2026-10-23 删除。）"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.clustering.variants import VariantMap
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _review_lanes_pass
from test_seed_admit_lanes import B, BODY, _ids, _mm, _page, _wit


def test_w3_lib_variant_takes_precedence_over_diff():
    vm = VariantMap.load(None)
    a, b = next((x, y) for x, y in (("獘", "弊"), ("峯", "峰"), ("羣", "群")) if vm.semantic(x) == vm.semantic(y))
    chars = BODY[:4] + b + BODY[5:30]
    out = _page(chars, {5: dict(doubts=["replace_align"], char=b)})
    wits = [_wit(f"{k}.txt", "前" + chars + "後") for k in "dwy"]
    mm = {f"{B}:1:5": NS(char=None, candidates=[(a, 0.9)], guard=None, verdict="diff")}
    p = SeedAdmitParams(db_path="x", lane_witness3=True)
    n = _review_lanes_pass(p, out, mm, _ids({5: (b, "replace")}), _ids({5: b}), vm, lambda: wits)
    r = out[0].chars[4]
    assert n == 0 and not r.admit and r.evidence["lane_skip"]["why"] == "lib_variant"
    assert "witness3_diff" not in r.doubts


pytestmark = pytest.mark.usefixtures("seed_admit_switches_off")   # 老测试按「放行开关缺省全关」造的数据，见 conftest
