"""字体域预建件（`clustering/font_pack.py`）：拷进来的行与逐字渲染的逐列相同（时间戳除外），
字体域指纹相同；键随字体、字表、竖排变；`import-font` 有包就不渲染。"""

from pathlib import Path

import pytest

from open_guji_cv.clustering import font_pack as FP
from open_guji_cv.clustering.font_glyphs import FontSpec, import_font
from open_guji_cv.clustering.glyph_db import GlyphDB
from open_guji_cv.clustering.glyph_fp import font_domain_fingerprint

CHARS = ["一", "二", "口", "日", "永", "\U0010FFFD"]      # 末一个字体里没有：两边都记缺字


def _spec() -> FontSpec:
    from open_guji_cv.clustering.font_candidates import _font_files
    return FontSpec(edition_tag="font:t", font_paths=[Path(f) for f in _font_files()[:1]], title="t")


# 时间戳是各自写入时的「现在」，其余列都要相同
_TS = {"created_at", "updated_at", "added_at"}


def _rows(db: GlyphDB) -> dict:
    c = db.conn
    out = {}
    for t, where in (("sources", "kind='font'"), ("instances", "source_id='font:t'"),
                     ("glyphs", "edition_tag='font:t'")):
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})") if r[1] not in _TS | {"glyph_id"}]
        out[t] = sorted(c.execute(f"SELECT {', '.join(cols)} FROM {t} WHERE {where}").fetchall())
    out["exemplars"] = sorted(c.execute(
        "SELECT g.char, e.instance_id, e.role FROM exemplars e JOIN glyphs g ON g.glyph_id=e.glyph_id "
        "WHERE g.edition_tag='font:t'").fetchall())
    out["derived"] = sorted(c.execute(
        "SELECT d.* FROM derived d JOIN instances i ON i.instance_id=d.instance_id "
        "WHERE i.source_id='font:t'").fetchall())
    return out


def test_pack_roundtrip_matches_rendering_row_for_row(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    a = GlyphDB(tmp_path / "a.db")
    import_font(a, _spec(), CHARS)
    pack = FP.save_pack(a, _spec(), CHARS, vertical=False)
    assert pack.parent == tmp_path / "cache" / "fontdb" and pack.exists()

    b = GlyphDB(tmp_path / "b.db")
    b.conn.execute("INSERT INTO glyphs (edition_tag, char, status, n_confirmed, updated_at) "
                   "VALUES ('book', '一', 'sparse', 1, 'x')")     # 目标库已有别的字形：glyph_id 错开
    b.conn.commit()
    r = FP.import_pack(b, pack, "font:t")
    assert r["glyphs"] == 5
    assert _rows(a) == _rows(b)
    assert font_domain_fingerprint(a.db_path) == font_domain_fingerprint(b.db_path) != "none"
    # 重复导入幂等
    FP.import_pack(b, pack, "font:t")
    assert _rows(a) == _rows(b)


def test_key_changes_with_charset_vertical_and_font(tmp_path):
    s = _spec()
    k = FP.pack_key(s, CHARS, False)
    assert k == FP.pack_key(s, list(CHARS), False)
    assert k != FP.pack_key(s, CHARS[:-1], False)
    assert k != FP.pack_key(s, CHARS, True)
    other = tmp_path / "f.ttf"
    other.write_bytes(s.font_paths[0].read_bytes() + b"\0")
    assert k != FP.pack_key(FontSpec(edition_tag="font:t", font_paths=[other]), CHARS, False)


def test_import_fonts_from_manifest_uses_pack_and_skips_rendering(tmp_path, monkeypatch):
    import json

    from open_guji_cv.clustering import font_glyphs as FG
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GUJI_DERIVED_FETCH", "0")
    s = _spec()
    cs = tmp_path / "cs.txt"
    cs.write_text("".join(CHARS), encoding="utf-8")
    man = tmp_path / "m.json"
    man.write_text(json.dumps({"charset": str(cs), "fonts": [
        {"edition_tag": "font:t", "title": "t", "font_paths": [str(p) for p in s.font_paths]}]}), encoding="utf-8")
    a = GlyphDB(tmp_path / "a.db")
    r = FG.import_fonts_from_manifest(a, man)                    # 没包：渲染
    assert "from_pack" not in r["imported"][0]
    FP.save_pack(a, s, CHARS, vertical=False)
    b = GlyphDB(tmp_path / "b.db")
    monkeypatch.setattr(FG, "import_font", lambda *a, **k: pytest.fail("有包就不该渲染"))
    r = FG.import_fonts_from_manifest(b, man)
    assert r["imported"][0]["from_pack"] and r["imported"][0]["glyphs"] == 5
    assert r["imported"][0]["missing"] == 1
    assert _rows(a) == _rows(b)


def test_pack_fetched_from_r2_is_deleted_after_import_local_one_kept(tmp_path, monkeypatch):
    import json
    import shutil

    from open_guji_cv.clustering import font_glyphs as FG
    from open_guji_cv.core import derived as packs
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    s = _spec()
    cs = tmp_path / "cs.txt"
    cs.write_text("".join(CHARS), encoding="utf-8")
    man = tmp_path / "m.json"
    man.write_text(json.dumps({"charset": str(cs), "fonts": [
        {"edition_tag": "font:t", "title": "t", "font_paths": [str(p) for p in s.font_paths]}]}), encoding="utf-8")
    a = GlyphDB(tmp_path / "a.db")
    import_font(a, s, CHARS)
    made = FP.save_pack(a, s, CHARS, vertical=False)
    r2 = tmp_path / "r2"
    r2.mkdir()
    shutil.move(made, r2 / made.name)                              # 本机没有，R2（替身）有
    got = []

    def fake_fetch(kind_dir, name, dest):
        got.append((kind_dir, name))
        shutil.copyfile(r2 / name, dest)
        return True
    monkeypatch.setattr(packs, "fetch_derived", fake_fetch)
    b = GlyphDB(tmp_path / "b.db")
    r = FG.import_fonts_from_manifest(b, man)
    assert got == [("fontdb", made.name)] and r["imported"][0]["from_pack"] == made.name
    assert not made.exists(), "从 R2 取来的包导完要删"
    assert _rows(a) == _rows(b)
