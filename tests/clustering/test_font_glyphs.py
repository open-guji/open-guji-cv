"""font_glyphs.py 单测：字表解析、渲染几何、来源隔离与检索过滤。

渲染相关用例需要字体文件，环境变量 GUJI_FONT_DIR 未指向可用字体时跳过。
"""

import json
import os
from pathlib import Path

import numpy as np
import pytest

from open_guji_cv.clustering.canonical import CANON_SIZE, is_canonical
from open_guji_cv.clustering.font_glyphs import (FontSpec, import_font,
                                                 load_charset, load_manifest)
from open_guji_cv.clustering.glyph_db import GlyphDB, export_store


def _font_paths() -> list[Path]:
    root = os.environ.get("GUJI_FONT_DIR")
    if not root:
        return []
    return sorted(Path(root).rglob("*.ttf"))[:1]


needs_font = pytest.mark.skipif(not _font_paths(),
                                reason="需要 GUJI_FONT_DIR 指向字体目录")


# ── 字表解析 ──────────────────────────────────────────────

def test_load_charset_plain(tmp_path):
    p = tmp_path / "cs.txt"
    p.write_text("諭論\n# 注释\n千\n諭\n", encoding="utf-8")
    assert load_charset(p) == ["諭", "論", "千"]      # 去重且保序


def test_load_charset_ranges(tmp_path):
    p = tmp_path / "cs.tsv"
    p.write_text("# c\nU+4E00\tU+4E02\tcorpus\nU+4E00\tU+4E00\tocr\n",
                 encoding="utf-8")
    assert load_charset(p) == ["一", "丁", "丂"]


def test_load_charset_bare_hex(tmp_path):
    p = tmp_path / "cs.tsv"
    p.write_text("4E00\t4E01\n", encoding="utf-8")
    assert load_charset(p) == ["一", "丁"]


def test_load_manifest_expands_vars(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_FONT_DIR", "/opt/fonts")
    p = tmp_path / "m.json"
    p.write_text(json.dumps({
        "charset": "cs.txt",
        "fonts": [{"edition_tag": "font:x",
                   "font_paths": ["$MY_FONT_DIR/a.ttf"],
                   "license": "CC0"}]}), encoding="utf-8")
    specs, data = load_manifest(p)
    assert specs[0].font_paths[0] == Path("/opt/fonts/a.ttf")
    assert specs[0].license == "CC0" and data["charset"] == "cs.txt"


# ── 渲染几何 ──────────────────────────────────────────────

@needs_font
def test_render_is_canonical_and_centered():
    from open_guji_cv.clustering.font_glyphs import FontRenderer
    r = FontRenderer(_font_paths())
    img = r.render("國")
    assert is_canonical(img)
    ys, xs = np.nonzero(img < 128)
    # 质心居中受 clamp 约束（墨迹不得出界），极端纵横比的字（「一」「丨」）
    # 会差几个像素；方正的字应当贴合
    assert abs(ys.mean() - CANON_SIZE / 2) <= 2
    assert abs(xs.mean() - CANON_SIZE / 2) <= 2
    # 只缩不放：墨迹不得超出内容区
    assert max(ys.max() - ys.min(), xs.max() - xs.min()) <= 196


@needs_font
def test_render_missing_char_returns_none():
    from open_guji_cv.clustering.font_glyphs import FontRenderer
    r = FontRenderer(_font_paths())
    assert r.render("\U000E0100") is None      # 变体选择符，字体不会有


# ── 入库：来源隔离与检索过滤 ────────────────────────────────

@needs_font
def test_import_font_isolates_source_and_filters(tmp_path):
    db = GlyphDB(tmp_path / "t.sqlite")
    chars = ["一", "二", "三", "口", "日"]
    spec = FontSpec(edition_tag="font:test", font_paths=_font_paths(),
                    title="t", license="CC0")
    res = import_font(db, spec, chars)
    assert res["glyphs"] >= 3

    kind = db.conn.execute(
        "SELECT kind FROM sources WHERE source_id='font:test'").fetchone()[0]
    assert kind == "font"

    from open_guji_cv.clustering.normalize import normalize_patch
    from open_guji_cv.clustering.font_glyphs import FontRenderer
    probe = normalize_patch(FontRenderer(_font_paths()).render("口"))

    hits = db.query(probe, k=3)
    assert hits and all(h.edition_tag == "font:test" for h in hits)
    assert all(h.kind == "font" for h in hits)      # 命中可溯源

    # 白名单：查不存在的 edition 应当空手而归
    assert db.query(probe, editions=["font:nope"], k=3) == []
    # kinds 过滤同理
    assert db.query(probe, kinds=["woodblock"], k=3) == []
    assert db.query(probe, kinds=["font"], k=3)
    db.close()


@needs_font
def test_query_exclude_survives_dedup(tmp_path):
    """exclude 必须在「每字只留最高分」之前生效，否则整字被抹掉。"""
    db = GlyphDB(tmp_path / "t.sqlite")
    spec = FontSpec(edition_tag="font:test", font_paths=_font_paths())
    import_font(db, spec, ["口", "日", "田"])
    from open_guji_cv.clustering.normalize import normalize_patch
    from open_guji_cv.clustering.font_glyphs import FontRenderer
    probe = normalize_patch(FontRenderer(_font_paths()).render("口"))
    self_id = f"font:test:{ord('口'):05X}"
    assert any(h.instance_id == self_id for h in db.query(probe, k=5))
    hits = db.query(probe, k=5, exclude=[self_id])
    assert all(h.instance_id != self_id for h in hits)
    db.close()


@needs_font
def test_font_source_not_exported(tmp_path):
    """字体来源整条链都不进导出目录（可确定性重生成）。"""
    db = GlyphDB(tmp_path / "t.sqlite")
    import_font(db, FontSpec(edition_tag="font:test",
                             font_paths=_font_paths()), ["口", "日"])
    counts = export_store(db, tmp_path / "store")
    assert counts["sources"] == 0 and counts["glyphs"] == 0
    assert counts["exemplars"] == 0 and counts["patches"] == 0
    assert not list((tmp_path / "store" / "patches").glob("*.png"))
    db.close()
