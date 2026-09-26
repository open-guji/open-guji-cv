# -*- coding: utf-8 -*-
"""体检的 Unihan 异体豁免：只认指定属性的边，形近字（无边 / kSpoofingVariant）照旧互判。"""

from open_guji_cv.clustering.glyph_selfcheck import UNIHAN_SAME_WIDE, _unihan_same


def test_unihan_same_default_and_wide():
    uv = _unihan_same()
    assert uv("強", "强") and uv("戸", "戶") and uv("卽", "即")
    assert not uv("內", "内")            # 只有简繁边，缺省不认
    assert not uv("千", "干") and not uv("強", "強")
    wide = _unihan_same(UNIHAN_SAME_WIDE)
    assert wide("內", "内") and wide("別", "别")
    assert not wide("千", "干")


def test_near_forms_sync(tmp_path):
    """体检「形近·异体」人裁 → 形近人裁表：新对加进来，已有对只记事件，重复跑不变。"""
    import importlib.util
    import json
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "nfs", Path(__file__).resolve().parents[2] / "scripts" / "glyph_near_forms_sync.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    ws = tmp_path / "ws"
    (ws / "output" / "glyph_selfcheck").mkdir(parents=True)
    (ws / "output" / "glyph_selfcheck" / "near_forms.jsonl").write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in [
            {"pair": ["強", "强"], "event": "e1"}, {"pair": ["入", "人"], "event": "e2"},
            {"pair": ["強", "强"], "event": "e3"}, {"pair": ["", "强"], "event": "e4"}]), encoding="utf-8")
    table = {"pairs": {"人入": 1.0}}
    found = m.collect([ws])
    assert m.merge(table, found) == ["強强"]           # 按码点排：強 U+5F37 < 强 U+5F3A
    assert table["sources"]["人入"] == ["e2"] and table["sources"]["強强"] == ["e1", "e3"]
    assert m.merge(table, m.collect([ws])) == [] and table["n_pairs"] == 2
