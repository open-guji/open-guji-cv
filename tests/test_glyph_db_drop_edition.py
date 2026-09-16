"""`GlyphDB.drop_edition` 要把 `admissions` 准入台账一起删掉。

台账是 `admit_instance` 的判重依据。台账留着而实例被删掉，重播时整批会被当成
duplicate 跳过——库看着「播过了」，其实是空的，**而且不报错**。
北行日錄 2026-09-16 踩过：1001 个字位重播只进了 114 个字头。
"""
import io

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from open_guji_cv.clustering.glyph_db import GlyphDB


def _png(seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    img = (rng.integers(0, 2, (64, 64), dtype=np.uint8) * 255)
    return cv2.imencode(".png", img)[1].tobytes()


def _seed(db, edition, ids):
    for i, iid in enumerate(ids):
        db.admit_instance(iid, "字", _png(i), provenance="align",
                          edition_tag=edition, page="1", col=1, idx=i + 1)


def _counts(db, edition, prefix):
    q = db.conn.execute
    return {
        "glyphs": q("SELECT COUNT(*) FROM glyphs WHERE edition_tag=?", (edition,)).fetchone()[0],
        "instances": q("SELECT COUNT(*) FROM instances WHERE instance_id LIKE ?",
                       (prefix + "%",)).fetchone()[0],
        "admissions": q("SELECT COUNT(*) FROM admissions WHERE instance_id LIKE ?",
                        (prefix + "%",)).fetchone()[0],
    }


def test_drop_edition_also_clears_the_admission_ledger(tmp_path):
    db = GlyphDB(tmp_path / "glyph.db")
    try:
        ids = [f"bk:1:1:{i}" for i in range(1, 6)]
        _seed(db, "bk", ids)
        before = _counts(db, "bk", "bk:")
        assert before["instances"] == 5 and before["admissions"] == 5

        db.drop_edition("bk")
        after = _counts(db, "bk", "bk:")
        assert after == {"glyphs": 0, "instances": 0, "admissions": 0}, (
            f"台账没清干净：{after}——重播会被判重整批跳过")
    finally:
        db.close()


def test_reseed_after_drop_actually_readmits(tmp_path):
    """这条才是真正要防的回归：drop 之后重播必须**真的进库**，不是报 duplicate。"""
    db = GlyphDB(tmp_path / "glyph.db")
    try:
        ids = [f"bk:1:1:{i}" for i in range(1, 6)]
        _seed(db, "bk", ids)
        db.drop_edition("bk")

        ok = [db.admit_instance(iid, "字", _png(i), provenance="align",
                                edition_tag="bk", page="1", col=1, idx=i + 1)
              for i, iid in enumerate(ids)]
        assert all(ok), f"重播被判重跳过了：{ok}"
        assert _counts(db, "bk", "bk:")["instances"] == 5
    finally:
        db.close()


def test_drop_edition_leaves_other_editions_untouched(tmp_path):
    db = GlyphDB(tmp_path / "glyph.db")
    try:
        _seed(db, "bk", [f"bk:1:1:{i}" for i in range(1, 4)])
        _seed(db, "other", [f"other:1:1:{i}" for i in range(1, 3)])
        db.drop_edition("bk")
        assert _counts(db, "bk", "bk:")["admissions"] == 0
        keep = _counts(db, "other", "other:")
        assert keep["instances"] == 2 and keep["admissions"] == 2
    finally:
        db.close()
