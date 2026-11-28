"""默认链（2026-11-28 三链合一）：旧链 id 当别名、版式推导、合并前后步骤与参数逐项相同。

设计：https://claude.ai/artifact/99ihHT9o84MSKtB59YDWMp 。合并只换了「怎么选链」，步骤 id、产物、参数层都不动，
所以每个旧 id 加载出来必须与 `guji_default@<版式>` 完全相同，各书指纹才逐位不变（L0）。"""

import pytest

from helpers import make_book
from open_guji_cv.core import seg_set as S
from open_guji_cv.core.engine import _self_payload, params_hash
from open_guji_cv.core.pipeline import default_pipeline_id, load_pipeline, pipeline_for, resolve_params
from open_guji_cv.core.step import STEPS


@pytest.mark.parametrize("old,lay", sorted(S.LEGACY_PIPELINES.items()))
def test_legacy_id_is_alias(old, lay):
    a, b = load_pipeline(old), load_pipeline(f"guji_default@{lay}")
    assert a.id == b.id == "guji_default" and a.layout == b.layout == lay
    assert a.steps == b.steps and a.stages == b.stages and a.finals == b.finals
    assert a.ref == f"guji_default@{lay}"


def test_bare_id_follows_book():
    assert load_pipeline("guji_default").layout == "grid"
    assert load_pipeline("guji_default", book=make_book(edition="modern")).layout == "print"
    assert load_pipeline("guji_default", book=make_book(layout="free")).layout == "free"
    # 引用里写死的版式压过册
    assert load_pipeline("keben_free", book=make_book(edition="modern")).layout == "free"
    assert pipeline_for(make_book(seg_set="beixing")).layout == "print"


def test_layout_validation():
    with pytest.raises(ValueError):
        S.validate_layout("keben")
    with pytest.raises(ValueError):
        load_pipeline("guji_default@nope")


def _payloads(pl, book):
    ps = resolve_params(pl, book)
    out = {}
    for sid in pl.steps:
        st = STEPS[sid]
        p = ps.get(sid) or (st.spec.params() if st.spec.params else None)
        out[sid] = _self_payload(st, book, params_hash(p, st.spec.soft_params, st.spec.path_params))
    return out


@pytest.mark.parametrize("kw", [{}, {"edition": "modern"}, {"seg_set": "beixing"}, {"seg_set": "zengguang_youxue"},
                                {"pipeline": "keben_free"}, {"pipeline": "modern_body"}])
def test_fingerprint_payload_same_for_old_and_new_ref(kw):
    """同一册：按旧链 id 加载与按册推出的 `guji_default@版式` 加载，每步指纹里不含上游的部分逐位相同。"""
    book = make_book(**kw)
    new = load_pipeline(default_pipeline_id(book))
    old = load_pipeline({v: k for k, v in S.LEGACY_PIPELINES.items()}[new.layout])
    assert new.steps == old.steps
    assert _payloads(new, book) == _payloads(old, book)


def test_seg_set_for_run_by_layout():
    assert S.seg_set_for_run(make_book(), "guji_default@print") == "beixing"
    assert S.seg_set_for_run(make_book(), "guji_default", "free") == "zengguang_youxue"
    assert S.seg_set_for_run(make_book(), "guji_default") == "siku_zongmu"
