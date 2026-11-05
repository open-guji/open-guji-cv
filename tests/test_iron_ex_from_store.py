"""`seed_admit.iron_ex_from_store`（2026-11-05）：铁证判别器的人裁刻例图从字形库取，不看缓存。"""
from pathlib import Path

import cv2
import numpy as np

from open_guji_cv.clustering.glyph_db import GlyphDB
from open_guji_cv.steps import seed_admit as SA


def _raw() -> np.ndarray:
    img = np.full((90, 70), 250, np.uint8)            # 字块：浅灰底、带留白
    cv2.rectangle(img, (20, 15), (49, 74), 0, 3)
    cv2.line(img, (20, 45), (49, 45), 0, 3)
    return img


def test_store_raw_keeps_ink_size_and_ignores_cache(tmp_path: Path, monkeypatch):
    db = tmp_path / "g.db"
    d = GlyphDB(db)
    assert d.admit_instance("v2:vol01:3:2:7", "日", cv2.imencode(".png", _raw())[1].tobytes(),
                            provenance="human", edition_tag="bk", page="3", col=2, idx=7)
    d.conn.commit()
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "empty-cache"))   # 缓存是空的
    x = SA._store_ex_raw(str(db), "vol01:3:2:7")
    assert x is not None
    def ink(a):
        ys, xs = np.nonzero(a < 128)
        return ys.max() - ys.min() + 1, xs.max() - xs.min() + 1
    # canonical 只平移不放大：墨迹框尺寸与原字块一致
    assert ink(x) == ink(_raw())
    assert SA._store_ex_raw(str(db), "vol01:9:9:9") is None


def test_switch_off_keeps_params_dump():
    p = SA.SeedAdmitParams()
    assert "iron_ex_from_store" not in p.model_dump()
    assert SA.SeedAdmitParams(iron_ex_from_store=True).model_dump()["iron_ex_from_store"] is True
