# -*- coding: utf-8 -*-
"""Elena 208cz 评审三条件的补测（GUJI-208ha）：Literal、别的 lane 不受影响、lib_variant 优先、human/excluded 不加提示、
与 T9 的次序（hint 只给 hint 时刻待审的格）、两开关同开整步。数据全是自造的。"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.clustering.variants import VariantMap
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _oversplit_pairs, _review_lanes_pass
from test_runt_cell_review import SHORT, _run as _runt_run  # noqa: F401
from test_seed_admit_lanes import B, BODY, _ids, _mm, _page, _wit
from test_t11_oversplit import _c, _filler, _hint, _idx, _out, _pair


@pytest.mark.parametrize("bad", ["Hint", "both", "hints", " hint", True])
def test_oversplit_gate_rejects_unknown(bad):
    with pytest.raises(ValidationError):
        SeedAdmitParams(db_path="x", oversplit_gate=bad)


def test_oversplit_gate_accepts_empty_and_hint():
    assert SeedAdmitParams(db_path="x").oversplit_gate == ""
    assert SeedAdmitParams(db_path="x", oversplit_gate="hint").oversplit_gate == "hint"


def test_w3_on_keeps_other_lane_release_even_when_verdict_diff():
    """lane_coord 放行的格即使 verdict=diff，witness3_no_diff 开了也照放（开关只管 witness3）。"""
    chars = BODY[:30]
    wits = [_wit(f"{k}.txt", "前" + chars[:4] + c + chars[5:] + "後") for k, c in zip("dwy", "天夫夫")]
    res = {}
    for on in (False, True):
        out = _page(chars, {5: dict(doubts=["库 unsure(cov=0.95)", "上下文 margin 不足(0.10)"], char="天")})
        mm = {f"{B}:1:5": NS(char=None, candidates=[("天", 0.95)], guard=None, verdict="diff")}
        p = SeedAdmitParams(db_path="x", lane_coord=True, witness3_no_diff=on)
        n = _review_lanes_pass(p, out, mm, {}, _ids({5: "天"}), VariantMap.load(None), lambda: wits)
        res[on] = (n, out[0].chars[4].admit, out[0].chars[4].channel)
    assert res[False] == res[True] and res[True][1] and res[True][2] == "coord_fallback"


def test_w3_lib_variant_takes_precedence_over_diff():
    vm = VariantMap.load(None)
    a, b = next((x, y) for x, y in (("獘", "弊"), ("峯", "峰"), ("羣", "群")) if vm.semantic(x) == vm.semantic(y))
    chars = BODY[:4] + b + BODY[5:30]
    out = _page(chars, {5: dict(doubts=["replace_align"], char=b)})
    wits = [_wit(f"{k}.txt", "前" + chars + "後") for k in "dwy"]
    mm = {f"{B}:1:5": NS(char=None, candidates=[(a, 0.9)], guard=None, verdict="diff")}
    p = SeedAdmitParams(db_path="x", lane_witness3=True, witness3_no_diff=True)
    n = _review_lanes_pass(p, out, mm, _ids({5: (b, "replace")}), _ids({5: b}), vm, lambda: wits)
    r = out[0].chars[4]
    assert n == 0 and not r.admit and r.evidence["lane_skip"]["why"] == "lib_variant"
    assert "witness3_diff" not in r.doubts


def test_hint_skips_human_and_excluded():
    a, b = _pair()
    ci = _idx({1: [a, b], 2: _filler(2)})
    out = _out(["a", "b"], {})
    out[0].chars[0].channel = "human"
    out[0].chars[1].doubts = ["excluded"]
    from open_guji_cv.steps.seed_admit import _oversplit_hint_pass
    assert _oversplit_hint_pass(SeedAdmitParams(db_path="x", oversplit_gate="hint"), out, ci) == 0
    assert all("oversplit_pair" not in r.doubts for r in out[0].chars)
    out = _out(["a", "b"], {})
    out[0].chars[0].provenance = "human"
    assert _oversplit_hint_pass(SeedAdmitParams(db_path="x", oversplit_gate="hint"), out, ci) == 1


def test_pairs_geometry_ignores_admit():
    """纯几何命中集不看 admit：放行与否都在（供 T9 重叠量用）。"""
    a, b = _pair()
    hits = _oversplit_pairs(SeedAdmitParams(db_path="x", oversplit_gate="hint"), _idx({1: [a, b], 2: _filler(2)}))
    assert set(hits) == {"a", "b"} and hits["a"]["partner"] == "b"
    assert _oversplit_pairs(SeedAdmitParams(db_path="x"), None) == {}


def test_hint_before_t9_released_then_demoted_cell_gets_no_pair(tmp_path, monkeypatch):
    """次序：hint 在 T9 前。hint 时刻已放行、之后被 T9 降级的格只有 runt_cell、没有 oversplit_pair（文档已写明不覆盖）。"""
    import open_guji_cv.steps.seed_admit as sa
    ci = NS(columns=[NS(col=1, chars=[_c("tbook:1:1:1", 0, 100), _c("tbook:1:1:2", 1, 55), _c("tbook:1:1:3", 2, 50)]
                        + [_c(f"x{i}", 3 + i, 100) for i in range(22)])])
    real = sa._opt
    monkeypatch.setattr(sa, "_opt", lambda c, k, pg: ci if k == "char_index" else real(c, k, pg))
    rs = _runt_run(tmp_path, monkeypatch, SeedAdmitParams(oversplit_gate="hint", runt_cell_review=True), SHORT)
    assert not rs[3].admit and "runt_cell" in rs[3].doubts       # T9 降级了第 3 格
    for rec in rs.values():
        assert "oversplit_pair" not in rec.doubts                  # 两格在 hint 时刻都已放行 → 无提示


pytestmark = pytest.mark.usefixtures("seed_admit_switches_off")   # 老测试按「放行开关缺省全关」造的数据，见 conftest
