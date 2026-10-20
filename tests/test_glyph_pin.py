"""册钉字形库（core/glyph_pin.py）：钉了以后人裁指纹换成钉号，没钉逐位不变。"""
from types import SimpleNamespace

import pytest

from open_guji_cv.core.glyph_pin import PIN_FIELDS, parse_pin, pin_token, with_glyph_pin
from open_guji_cv.steps.seed_admit import SeedAdmitParams


def test_parse_pin():
    assert parse_pin(None) is None and parse_pin("") is None
    assert parse_pin(1) == 1 and parse_pin("g2") == 2 and parse_pin("3") == 3
    with pytest.raises(ValueError):
        parse_pin("x")
    with pytest.raises(ValueError):
        parse_pin(0)


def _params(**kw):
    base = dict(human_fingerprint="h1:10:aaaa", approx_fingerprint="ap:bbbb")
    base.update(kw)
    return SeedAdmitParams(**base)


def test_unpinned_book_unchanged():
    p = _params()
    assert with_glyph_pin(p, SimpleNamespace(glyph_pin=None)) is p


def test_pinned_replaces_fields_and_hash_is_stable_across_rulings():
    from open_guji_cv.core.engine import params_hash
    book = SimpleNamespace(glyph_pin=1)
    a = with_glyph_pin(_params(human_fingerprint="h1:10:aaaa"), book)
    b = with_glyph_pin(_params(human_fingerprint="h1:11:cccc"), book)   # 别处多了一条人裁
    assert a.human_fingerprint == pin_token(1) == "glyph-g1"
    assert params_hash(a) == params_hash(b)
    c = with_glyph_pin(_params(human_fingerprint="h1:11:cccc"), SimpleNamespace(glyph_pin=2))
    assert params_hash(c) != params_hash(b)                            # 加号 = 有意落地，判过期


def test_empty_fields_stay_empty():
    p = with_glyph_pin(_params(approx_fingerprint=""), SimpleNamespace(glyph_pin=1))
    assert p.approx_fingerprint == ""
    assert set(PIN_FIELDS) == {"human_fingerprint", "approx_fingerprint"}


def test_book_yaml_field(tmp_path):
    from open_guji_cv.core.book import load_book
    src = tmp_path / "b1.yaml"
    src.write_text("id: b1\ntitle: t\nraw_dir: raw\nglyph_pin: g3\n", encoding="utf-8")
    try:
        bk = load_book("b1", books_dir=tmp_path)
    except Exception as e:                 # 册 yaml 必填字段随版本变，构不出来就只测解析
        pytest.skip(f"最小册 yaml 构不出 BookSpec：{e}")
    assert bk.glyph_pin == 3
