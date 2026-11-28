"""参校本四维＋准确度分档（CV0 2026-11-27）：册配置键校验、段上压低、seed_admit `trust_from_accuracy` 逐页推信任档。
缺省关时参数 dump 不变、逐页原样返回同一对象。"""
import types

import pytest

from open_guji_cv.core.ref_profile import check_reference_dims, load_reference_profile
from open_guji_cv.steps.seed_admit import (SeedAdmitParams, accuracy_page_params,
                                           ref_accuracy_summary)


def _book(refs, profile=None):
    return types.SimpleNamespace(references=refs, reference_profile=load_reference_profile(profile, refs))


def test_dims_validate():
    check_reference_dims([{"file": "a", "form": "column", "punct": "none", "script": "faithful",
                           "accuracy": "high", "accuracy_evidence": "全唐文 4 册 11 万格 99.95%"}])
    with pytest.raises(ValueError, match="accuracy"):
        check_reference_dims([{"file": "a", "accuracy": "best"}])
    with pytest.raises(ValueError, match="script"):
        check_reference_dims([{"file": "a", "script": "繁体"}])
    with pytest.raises(ValueError, match="自相矛盾"):
        check_reference_dims([{"file": "a", "form": "column", "line_is_column": False}])


def test_segment_accuracy_only_lowers():
    refs = [{"file": "a", "accuracy": "high"}]
    prof = load_reference_profile({"segments": [{"pages": ["1-3"], "kind": "text", "accuracy": "mid"}]}, refs)
    assert prof.accuracy_of(2, refs) == "mid" and prof.accuracy_of(9, refs) == "high"
    with pytest.raises(ValueError, match="只许压低"):
        load_reference_profile({"segments": [{"pages": [1], "kind": "text", "accuracy": "very_high"}]}, refs)
    with pytest.raises(ValueError, match="none"):
        load_reference_profile({"segments": [{"pages": [1], "kind": "none", "accuracy": "low"}]}, refs)


def test_switch_off_unchanged():
    p = SeedAdmitParams()
    book = _book([{"file": "a", "accuracy": "very_high", "script": "trad"}])
    assert accuracy_page_params(p, 1, book) is p
    d = p.model_dump()
    assert not {"trust_from_accuracy", "ref_accuracy", "ref_variants_off"} & set(d)


def test_switch_on_maps_tiers():
    on = SeedAdmitParams(trust_from_accuracy=True)
    for acc, trust, coord in (("very_high", "very_high", False), ("high", "high", False),
                              ("mid", "none", True), ("low", "none", False), (None, "none", False)):
        q = accuracy_page_params(on, 1, _book([{"file": "a", "accuracy": acc}]))
        assert (q.reference_trust, q.ref_lib_coord) == (trust, coord), acc
    # 只往上推：册里已写 very_high，参校本标 high 也不降
    hi = SeedAdmitParams(trust_from_accuracy=True, reference_trust="very_high")
    assert accuracy_page_params(hi, 1, _book([{"file": "a", "accuracy": "high"}])) is hi
    # 无参照页不动
    b = _book([{"file": "a", "accuracy": "high"}], {"segments": [{"pages": [3], "kind": "none"}]})
    assert accuracy_page_params(on, 3, b) is on
    assert accuracy_page_params(on, 4, b).reference_trust == "high"


def test_script_normalized_turns_off_variants():
    on = SeedAdmitParams(trust_from_accuracy=True, edge_pair_to="ref")
    q = accuracy_page_params(on, 1, _book([{"file": "a", "accuracy": "high", "script": "trad"}]))
    assert q.reference_trust == "high" and q.ref_variants_off and not q._follow_variants() and q.edge_pair_to == "freq"
    f = accuracy_page_params(on, 1, _book([{"file": "a", "accuracy": "high", "script": "faithful"}]))
    assert f._follow_variants() and f.edge_pair_to == "ref"


def test_summary_into_fingerprint():
    b = _book([{"file": "a", "accuracy": "high", "script": "faithful"}, {"file": "b"}],
              {"segments": [{"pages": ["1-3"], "kind": "text", "accuracy": "mid"}]})
    s = ref_accuracy_summary(b)
    assert s == "refs=high/faithful;/|segs=1-3:mid"
    p = SeedAdmitParams(trust_from_accuracy=True, ref_accuracy=s)
    d = p.model_dump()
    assert d["trust_from_accuracy"] is True and d["ref_accuracy"] == s


def test_book_params_hook_fills_summary_only_when_on():
    from open_guji_cv.steps.seed_admit import SeedAdmitStep
    refs = [{"file": "a", "accuracy": "high"}]
    ctx = types.SimpleNamespace(book=_book(refs))
    step = SeedAdmitStep()
    assert step.book_params(SeedAdmitParams(trust_from_accuracy=True), ctx).ref_accuracy == "refs=high/"
    p = SeedAdmitParams()
    assert step.book_params(p, ctx) is p
