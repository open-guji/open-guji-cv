# -*- coding: utf-8 -*-
"""体检结果带库指纹，过期不出卡（GUJI-710）。

起因（GUJI-623）：findings.jsonl 是 09-26 的库算的，09-27 刻例重排编号后没重跑，控制台照样出卡，
实例 id 已指向别的图，9 张卡错位。这里自造一个小库，不跑真体检（HOG＋弹性验证太慢），
直接造 `run_selfcheck` 形状的结果走 `save` → `freshness` → 控制台路由。"""

from __future__ import annotations

import shutil
import sqlite3

import cv2
import numpy as np
import pytest

from open_guji_cv.clustering import glyph_selfcheck as G
from open_guji_cv.clustering.glyph_db import GlyphDB


def _png(k):
    img = np.full((64, 64), 255, np.uint8)
    cv2.rectangle(img, (10 + k, 10), (50, 50 - k), 0, 3)
    return cv2.imencode(".png", img)[1].tobytes()


@pytest.fixture()
def lib(tmp_path):
    p = tmp_path / "output" / "glyph.db"
    p.parent.mkdir()
    g = GlyphDB(p)
    g.admit_instance("bk:1:1:1", "王", _png(0), provenance="align", page="1", col=1, idx=1)
    g.admit_instance("bk:1:1:2", "王", _png(1), provenance="align", page="1", col=1, idx=2)
    g.admit_instance("bk:1:1:3", "干", _png(2), provenance="human", page="1", col=1, idx=3)
    g.admit_instance("bk:1:1:4", "土", _png(3), provenance="align", page="1", col=1, idx=4)
    g.close()
    return p


def _result(db):
    """`run_selfcheck` 形状的结果：两张卡（1 形似 3「干」；4 同字离群、参照 2）。"""
    rows = G.library_rows(db)
    f1 = G.Finding("bk:1:1:1", "王", "align", flags=["rival"], rival=0.95, rival_char="干",
                   rival_peer="bk:1:1:3", rival_prov="human", same_peer="bk:1:1:2")
    f2 = G.Finding("bk:1:1:4", "土", "align", flags=["outlier"], n_same_self=1,
                   best_same_self=0.5, same_peer="bk:1:1:2")
    refs = {i for f in (f1, f2) for i in G._card_refs(G.asdict(f))}
    return {"db": str(db), "db_fp": G._fingerprint(rows),
            "inst_sha": {i: rows[i][1] for i in refs}, "n_checked": 4, "n_flagged": 2,
            "findings": [f1, f2], "all": [f1, f2]}


def _swap_image(db, iid, k):
    c = sqlite3.connect(db)
    c.execute("UPDATE instances SET patch_png=? WHERE instance_id=?", (_png(k), iid))
    c.commit()
    c.close()


def test_fingerprint_content_only(lib, tmp_path):
    fp = G.library_fingerprint(lib)
    assert fp.startswith("k1:4:")
    cp = tmp_path / "copy.db"
    shutil.copy(lib, cp)
    assert G.library_fingerprint(cp) == fp                 # 复制不变
    _swap_image(cp, "bk:1:1:2", 9)
    assert G.library_fingerprint(cp) != fp                 # id 换了图就变
    g = GlyphDB(lib)
    g.admit_instance("bk:1:1:5", "王", _png(5), provenance="align")
    g.close()
    assert G.library_fingerprint(lib).startswith("k1:5:")  # 进库就变


def test_save_records_fp_and_card_shas(lib):
    out = G.save(_result(lib), lib.parent / "glyph_selfcheck")
    meta, rows = G.load_findings(out)
    assert meta["db_fp"] == G.library_fingerprint(lib)
    assert "inst_sha" not in meta                          # 只进卡，不进 summary（控制台要回传 meta）
    r1 = next(r for r in rows if r["instance_id"] == "bk:1:1:1")
    shas = G.library_rows(lib)
    assert r1["sha"] == shas["bk:1:1:1"][1]
    assert r1["peer_sha"] == {"bk:1:1:3": shas["bk:1:1:3"][1], "bk:1:1:2": shas["bk:1:1:2"][1]}


def test_freshness(lib):
    out = G.save(_result(lib), lib.parent / "glyph_selfcheck")
    meta, rows = G.load_findings(out)
    assert G.freshness(meta, rows, lib)["fresh"]
    assert G.freshness({}, [], lib)["fresh"]                # 没跑过体检不算过期

    old = {k: v for k, v in meta.items() if k != "db_fp"}  # 旧版 selfcheck 算的：没有指纹
    fr = G.freshness(old, rows, lib)
    assert not fr["fresh"] and "没有库指纹" in fr["reason"]

    # 体检页上撤了对手「干」：库指纹变了，但只有那张卡不出，另一张照出
    from open_guji_cv.clustering.audit import evict_instance
    g = GlyphDB(lib)
    evict_instance(g, "bk:1:1:3")
    g.close()
    fr = G.freshness(meta, rows, lib)
    assert fr["fresh"] and fr["db_fp"] != meta["db_fp"]
    assert fr["drop"] == {next(r["key"] for r in rows if r["instance_id"] == "bk:1:1:1")}

    # 刻例重排编号：参照 id 指向了别的图 → 整份过期
    _swap_image(lib, "bk:1:1:2", 7)
    fr = G.freshness(meta, rows, lib)
    assert not fr["fresh"] and "bk:1:1:2" in fr["reason"]


def test_freshness_relabel_drops_card(lib):
    out = G.save(_result(lib), lib.parent / "glyph_selfcheck")
    meta, rows = G.load_findings(out)
    c = sqlite3.connect(lib)
    gid = c.execute("SELECT glyph_id FROM glyphs WHERE char='土'").fetchone()[0]
    c.execute("UPDATE glyphs SET char='士' WHERE glyph_id=?", (gid,))
    c.commit()
    c.close()
    fr = G.freshness(meta, rows, lib)
    assert fr["fresh"]
    assert fr["drop"] == {next(r["key"] for r in rows if r["instance_id"] == "bk:1:1:4")}


