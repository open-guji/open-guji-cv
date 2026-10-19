# -*- coding: utf-8 -*-
"""近似字侧表（overview#276）的 store 导出与重建。

（原在 `test_approx_store_sync.py`；服务器 git 三方同步随 `scripts/glyph_store_sync.py` 退役，
中心库之间的合并见 `tests/datastore/test_datastore_workcopy.py`。）
"""
from __future__ import annotations

import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402

from open_guji_cv.clustering.glyph_db import GlyphDB, export_store, rebuild_from_store  # noqa: E402


def _png(k: int) -> bytes:
    img = np.full((80, 80), 255, np.uint8)
    cv2.rectangle(img, (6 + k % 20, 10), (70, 70 - k % 15), 0, 4)
    cv2.line(img, (10, 10 + k % 30), (70, 40), 0, 3)
    return cv2.imencode(".png", img)[1].tobytes()


def _admit(db: GlyphDB, slot: int, ch: str) -> str:
    iid = f"v2:v006:1:1:{slot}"
    assert db.admit_instance(iid, ch, _png(slot), provenance="human", page="1", col=1, idx=slot)
    db.conn.commit()
    return iid


def test_export_rebuild_roundtrip(tmp_path):
    p = tmp_path / "a.db"
    g = GlyphDB(p)
    iid = _admit(g, 2, "以")
    g.set_approx(iid, "以", ids="⿰𠄌人", note="n", reviewer="r", at="2026-09-29T01:00:00+00:00")
    g.clear_approx(iid, at="2026-09-29T02:00:00+00:00")
    g.set_approx(iid, "以", ids="⿰𠄌人", at="2026-09-29T03:00:00+00:00")
    counts = export_store(g, tmp_path / "st")
    g.close()
    assert counts["approx_labels"] == 1 and counts["approx_clears"] == 1
    rebuild_from_store(tmp_path / "st", tmp_path / "b.db")
    g = GlyphDB(tmp_path / "b.db")
    assert g.approx_of(iid) == {"instance_id": iid, "label": "以", "ids": "⿰𠄌人", "note": None,
                                "reviewer": None, "created_at": "2026-09-29T03:00:00+00:00"}
    assert g.conn.execute("SELECT count(*) FROM approx_clears").fetchone()[0] == 1
    g.close()


def test_empty_side_table_exports_empty_files(tmp_path):
    """没有近似例的库：多出两个空文件，其余导出不变（store 里原有文件一个字节都不动）。"""
    p = tmp_path / "a.db"
    g = GlyphDB(p)
    _admit(g, 1, "之")
    export_store(g, tmp_path / "st")
    g.close()
    assert (tmp_path / "st" / "approx_labels.jsonl").read_text(encoding="utf-8") == ""
    assert (tmp_path / "st" / "approx_clears.jsonl").read_text(encoding="utf-8") == ""


