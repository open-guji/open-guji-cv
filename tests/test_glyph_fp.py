"""字形库内容指纹（GUJI-609）：glyph.db 从中心库重建、rowid 重排时不白变；字体域看得见。"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from open_guji_cv.clustering.audit import evict_instance  # noqa: E402
from open_guji_cv.clustering.glyph_db import GlyphDB  # noqa: E402
from open_guji_cv.clustering.glyph_fp import (FONT_TABLE, font_domain_fingerprint,  # noqa: E402
                                              human_shapes_fingerprint)


def _png(seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    return cv2.imencode(".png", rng.integers(0, 2, (64, 64), dtype=np.uint8) * 255)[1].tobytes()


def _db(path: Path, rows) -> GlyphDB:
    d = GlyphDB(path)
    for iid, prov, seed, ch in rows:
        assert d.admit_instance(iid, ch, _png(seed), provenance=prov, edition_tag="bk",
                                page="1", col=1, idx=seed)
    d.conn.commit()
    return d


H1 = ("v2:bk:1:1:2", "human", 2, "字")
H2 = ("v2:bk:1:1:4", "human", 4, "文")
M1 = ("v2:bk:1:1:1", "align", 1, "之")
M2 = ("v2:bk:1:1:3", "align", 3, "也")


def test_insert_order_and_machine_rows_do_not_matter(tmp_path):
    """同样的人裁，换插入顺序、中间多夹机器准入（重建后 rowid 全变）→ 指纹相同。"""
    a = _db(tmp_path / "a.db", [H1, M1, H2])
    b = _db(tmp_path / "b.db", [M2, H2, M1, H1])
    fa = human_shapes_fingerprint(tmp_path / "a.db")
    assert fa.startswith("h1:2:") and fa == human_shapes_fingerprint(tmp_path / "b.db")
    b.conn.execute("VACUUM")
    shutil.copy(tmp_path / "b.db", tmp_path / "c.db")
    assert human_shapes_fingerprint(tmp_path / "c.db") == fa
    a.close(), b.close()


def test_human_changes_are_visible(tmp_path):
    p = tmp_path / "g.db"
    d = _db(p, [H1, H2, M1])
    f0 = human_shapes_fingerprint(p)
    evict_instance(d, H1[0])
    assert d.admit_instance(H1[0], "字", _png(2), provenance="human", edition_tag="bk", page="1", col=1, idx=2)
    d.conn.commit()
    assert human_shapes_fingerprint(p) == f0, "撤了同字重进，人裁通道读到的不变"
    d.conn.execute("UPDATE admissions SET provenance='human_stale_20261019' WHERE instance_id=?", (H2[0],))
    d.conn.commit()
    f1 = human_shapes_fingerprint(p)
    assert f1 != f0 and f1.startswith("h1:1:"), "撤裁"
    gid = d.conn.execute("SELECT glyph_id FROM exemplars WHERE instance_id=?", (H1[0],)).fetchone()[0]
    d.conn.execute("UPDATE glyphs SET char='宇' WHERE glyph_id=?", (gid,))
    d.conn.commit()
    assert human_shapes_fingerprint(p) != f1, "字头改判也算（人裁通道取的是 glyphs 的字头）"
    d.close()


def test_missing_and_unreadable(tmp_path):
    assert human_shapes_fingerprint(tmp_path / "no.db") == "nodb"
    (tmp_path / "junk.db").write_bytes(b"not sqlite")
    assert human_shapes_fingerprint(tmp_path / "junk.db") == "unreadable"
    assert font_domain_fingerprint(tmp_path / "no.db") == "none"


def test_font_domain_is_visible(tmp_path):
    from open_guji_cv.clustering.font_candidates import _font_files
    from open_guji_cv.clustering.font_glyphs import FontSpec, import_font
    fonts = [Path(f) for f in _font_files()[:1]]
    if not fonts:
        pytest.skip("仓内没有字体档")
    p = tmp_path / "g.db"
    d = _db(p, [H1, M1])
    assert font_domain_fingerprint(p) == "none"
    import_font(d, FontSpec(edition_tag="font:test", font_paths=fonts), ["一", "二", "口"])
    f1 = font_domain_fingerprint(p)
    assert f1.startswith("f1:font:test:")
    man = json.loads(d.conn.execute(f"SELECT manifest FROM {FONT_TABLE} WHERE edition_tag='font:test'").fetchone()[0])
    assert man["n_chars"] == 3 and fonts[0].name in man["fonts"]
    from open_guji_cv.clustering.glyph_db import export_store
    export_store(d, tmp_path / "st")
    assert "font_manifest" not in (tmp_path / "st" / "meta.jsonl").read_text(encoding="utf-8"), "清单不进账本"
    import_font(d, FontSpec(edition_tag="font:test", font_paths=fonts), ["一", "二", "口", "日"])
    assert font_domain_fingerprint(p) != f1, "换了字表"
    d.drop_edition("font:test")
    d.conn.commit()
    assert font_domain_fingerprint(p) == "none"
    d.close()


def test_rare_candidates_params_carry_font_domain(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_GLYPH_DB", str(tmp_path / "none.db"))
    from open_guji_cv.steps.rare_candidates import RareCandidatesParams
    assert RareCandidatesParams().db_font_fingerprint == "none"
