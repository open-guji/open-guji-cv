"""N1：context 通道收紧开关（默认关）的纯函数与默认值。"""
import pytest

from open_guji_cv.steps.seed_admit import (
    SeedAdmitParams, _SINGLE_STROKES)


def test_defaults_off():
    p = SeedAdmitParams()
    assert p.context_single_stroke_review is False


def test_single_stroke_set():
    assert set("一丨亅丶丿乀乁乚乛") == set(_SINGLE_STROKES)
    assert "二" not in _SINGLE_STROKES


# ── 关时不进 dump（GUJI-208de）────────────────────────────────────────
from open_guji_cv.steps.seed_admit import _N_KEYS  # noqa: E402


def test_n_keys_default_not_in_dump():
    d = SeedAdmitParams().model_dump()
    assert not [k for k in _N_KEYS if k in d]


@pytest.mark.parametrize("k,v", [("context_single_stroke_review", True)])
def test_n_key_non_default_in_dump_and_changes_hash(k, v):
    base = SeedAdmitParams().model_dump()
    d = SeedAdmitParams(**{k: v}).model_dump()
    assert d[k] == v and not [x for x in _N_KEYS if x != k and x in d]
    assert {x: y for x, y in d.items() if x != k} == base
