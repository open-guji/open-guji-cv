"""参校本四维是唯一入口（CV0 2026-11-27／28，Sheldon 定）：册配置键校验、段上压低、seed_admit 信任字段由准确度推出，
册里写的旧开关不采用；证人排序看 accuracy。"""
import types
import warnings

import pytest

from open_guji_cv.core.ref_profile import check_reference_dims, load_reference_profile
from open_guji_cv.report.witness import ACCURACY_ORDER
from open_guji_cv.steps.seed_admit import (SeedAdmitParams, accuracy_page_params, book_trust_params,
                                           derive_trust, ref_accuracy_summary)


def _book(refs, profile=None, id="b"):
    return types.SimpleNamespace(id=id, references=refs, reference_profile=load_reference_profile(profile, refs))


def test_dims_validate():
    check_reference_dims([{"file": "a", "form": "column", "punct": "none", "script": "faithful",
                           "accuracy": "high", "accuracy_evidence": "全唐文 4 册 11 万格 99.95%"}])
    with pytest.raises(ValueError, match="accuracy"):
        check_reference_dims([{"file": "a", "accuracy": "best"}])
    with pytest.raises(ValueError, match="script"):
        check_reference_dims([{"file": "a", "script": "繁体"}])
    check_reference_dims([{"file": "a", "quality": "best", "line_is_column": True}])   # 旧键迁移期并存不报


def test_segment_accuracy_only_lowers():
    refs = [{"file": "a", "accuracy": "high"}]
    prof = load_reference_profile({"segments": [{"pages": ["1-3"], "kind": "text", "accuracy": "mid"}]}, refs)
    assert prof.accuracy_of(2, refs) == "mid" and prof.accuracy_of(9, refs) == "high"
    with pytest.raises(ValueError, match="只许压低"):
        load_reference_profile({"segments": [{"pages": [1], "kind": "text", "accuracy": "very_high"}]}, refs)
    with pytest.raises(ValueError, match="只许压低"):     # 未标按 low
        load_reference_profile({"segments": [{"pages": [1], "kind": "text", "accuracy": "mid"}]}, [{"file": "a"}])


def test_derive_trust_tiers():
    assert derive_trust("very_high", "faithful", "column") == {
        "reference_trust": "very_high", "ref_lib_coord": False, "follow_ref_variants": True, "ref_topk_follow": True}
    assert derive_trust("high", "trad", "column") == {
        "reference_trust": "high", "ref_lib_coord": False, "follow_ref_variants": False, "ref_topk_follow": False}
    assert derive_trust("high", "faithful", "column", by_carving=True)["follow_ref_variants"] is False   # 殿本按刻形
    assert derive_trust("mid", "", "column")["ref_lib_coord"] is True
    assert derive_trust("mid", "", "text")["ref_lib_coord"] is False   # 不分行用不上坐标对位
    assert derive_trust("low") == derive_trust("") == {
        "reference_trust": "none", "ref_lib_coord": False, "follow_ref_variants": False, "ref_topk_follow": False}


def test_book_params_override_legacy_keys_and_keep_shiji_dump():
    """史記：册里旧写 reference_trust very_high＋follow_ref_variants＋ref_topk_follow，标 very_high＋faithful 后推出同样的值 →
    参数 dump 逐位相同（指纹不变），也不提示。"""
    old = SeedAdmitParams(reference_trust="very_high", follow_ref_variants=True, ref_topk_follow=True)
    book = _book([{"file": "a", "form": "column", "script": "faithful", "accuracy": "very_high"}])
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        new = book_trust_params(old, book)
    assert new.model_dump(context={"hash": True}) == old.model_dump(context={"hash": True})


def test_book_params_replace_ref_lib_coord_and_warn():
    old = SeedAdmitParams(ref_lib_coord=True)
    book = _book([{"file": "a", "form": "column", "script": "trad", "accuracy": "high"}])
    with pytest.warns(FutureWarning, match="ref_lib_coord"):
        new = book_trust_params(old, book)
    assert (new.reference_trust, new.ref_lib_coord, new._follow_variants()) == ("high", False, False)
    # 没标准确度＝low：旧开关一律不采用
    with pytest.warns(FutureWarning):
        assert book_trust_params(SeedAdmitParams(reference_trust="high"), _book([{"file": "a"}])).reference_trust == "none"
    # 没配参校本：全关
    assert book_trust_params(SeedAdmitParams(), _book([])).reference_trust == "none"


def test_page_lowered_and_none_pages():
    refs = [{"file": "a", "form": "column", "script": "faithful", "accuracy": "very_high"}]
    book = _book(refs, {"segments": [{"pages": [3], "kind": "column", "accuracy": "mid"},
                                     {"pages": [5], "kind": "none"}]})
    p = book_trust_params(SeedAdmitParams(), book)
    assert p.reference_trust == "very_high" and p.ref_accuracy == "3:mid"
    q = accuracy_page_params(p, 3, book)
    assert (q.reference_trust, q.ref_lib_coord, q.ref_topk_follow) == ("none", True, False)
    assert accuracy_page_params(p, 4, book) is p and accuracy_page_params(p, 5, book) is p


def test_script_trad_edge_pair_ref_back_to_freq():
    p = SeedAdmitParams(edge_pair_to="ref")
    q = book_trust_params(p, _book([{"file": "a", "script": "trad", "accuracy": "high"}]))
    assert q.edge_pair_to == "freq" and not q._follow_variants()


def test_summary_and_dump():
    b = _book([{"file": "a", "accuracy": "high"}], {"segments": [{"pages": ["1-3"], "kind": "text", "accuracy": "mid"}]})
    assert ref_accuracy_summary(b) == "1-3:mid"
    d = SeedAdmitParams().model_dump()
    assert not {"trust_from_accuracy", "ref_accuracy", "ref_variants_off"} & set(d)
    assert SeedAdmitParams.model_validate({"trust_from_accuracy": True}).model_dump() == d   # 过渡开关写了也丢


def test_witness_order_by_accuracy():
    assert ACCURACY_ORDER["very_high"] > ACCURACY_ORDER["high"] > ACCURACY_ORDER["mid"] > ACCURACY_ORDER["low"]


def test_book_params_hook():
    from open_guji_cv.steps.seed_admit import SeedAdmitStep
    ctx = types.SimpleNamespace(book=_book([{"file": "a", "accuracy": "high"}]))
    assert SeedAdmitStep().book_params(SeedAdmitParams(), ctx).reference_trust == "high"
