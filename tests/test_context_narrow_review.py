"""N1/N2：context 通道收紧开关（默认关）的纯函数与默认值。"""
import pytest

from open_guji_cv.products.kinds.chars import CharRec
from open_guji_cv.steps.seed_admit import (
    SeedAdmitParams, _SINGLE_STROKES, _narrow_slice, _page_med_wh)


def _rec(i, w, h, sub=None, kind="char"):
    return CharRec(id=f"b:1:1:{i}", slot=i, pos=i, idx=i - 1, sub=sub, cell_type="char",
                   step3_kind=kind, bbox_col=(0, 0, w, h), width=w, height=h)


def test_defaults_off():
    p = SeedAdmitParams()
    assert p.context_single_stroke_review is False
    assert p.context_narrow_review is False
    assert p.context_narrow_ratio == 0.5


def test_single_stroke_set():
    assert set("一丨亅丶丿乀乁乚乛") == set(_SINGLE_STROKES)
    assert "二" not in _SINGLE_STROKES


def test_page_median_ignores_sub_and_jiazhu():
    imap = {r.id: r for r in [_rec(1, 100, 100), _rec(2, 120, 110), _rec(3, 110, 120),
                              _rec(4, 20, 20, sub="a"), _rec(5, 10, 10, kind="jiazhu")]}
    assert _page_med_wh(imap) == (110, 110)


def test_narrow_slice():
    med = (110.0, 110.0)
    assert _narrow_slice(_rec(1, 50, 110), med, 0.5)
    assert _narrow_slice(_rec(1, 110, 54), med, 0.5)
    assert not _narrow_slice(_rec(1, 56, 56), med, 0.5)
    assert not _narrow_slice(None, med, 0.5)
    assert not _narrow_slice(_rec(1, 1, 1), (0.0, 0.0), 0.5)


def test_narrow_col():
    from types import SimpleNamespace as N
    from open_guji_cv.steps.seed_admit import _gate_band_widths, _narrow_col
    gm = N(columns=[N(col=1, band_width=100.0), N(col=2, band_width=110.0),
                    N(col=3, band_width=60.0), N(col=4, band_width=105.0)])
    g = _gate_band_widths(gm)
    assert _narrow_col(g, "b:1:3:5", 0.75)
    assert not _narrow_col(g, "b:1:1:5", 0.75)
    assert not _narrow_col({}, "b:1:3:5", 0.75)
    assert _gate_band_widths(None) == {}
    assert SeedAdmitParams().context_narrow_col_review is False


# ── 关时不进 dump（GUJI-208de）────────────────────────────────────────
from open_guji_cv.steps.seed_admit import _N_KEYS  # noqa: E402


def test_n_keys_default_not_in_dump():
    d = SeedAdmitParams().model_dump()
    assert not [k for k in _N_KEYS if k in d]


@pytest.mark.parametrize("k,v", [("context_single_stroke_review", True), ("context_narrow_review", True),
                                 ("context_narrow_ratio", 0.45), ("context_narrow_ref", (30.0, 40.0)),
                                 ("context_narrow_col_review", True), ("context_narrow_col_ratio", 0.6)])
def test_n_key_non_default_in_dump_and_changes_hash(k, v):
    base = SeedAdmitParams().model_dump()
    d = SeedAdmitParams(**{k: v}).model_dump()
    assert d[k] == v and not [x for x in _N_KEYS if x != k and x in d]
    assert {x: y for x, y in d.items() if x != k} == base


def test_n_keys_off_equals_explicit_default():
    assert SeedAdmitParams().model_dump() == SeedAdmitParams(
        context_narrow_ratio=0.5, context_narrow_review=False, context_narrow_ref=None).model_dump()
