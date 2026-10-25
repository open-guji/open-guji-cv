# -*- coding: utf-8 -*-
"""字形库按版本钉（GUJI-727）：快照 g<N>、按版本建库、参数三态、起跑前核库、push 守卫。

自造字形库，不碰真书数据、不连网（R2 用桩）。
"""
from __future__ import annotations

import json
import random
import sqlite3
from types import SimpleNamespace

import cv2
import pytest

from open_guji_cv.clustering.synth import degrade, synthetic_glyph


def _png(seed: int) -> bytes:
    g = degrade(synthetic_glyph(random.Random(300 + seed)), random.Random(seed), wear=0.3)
    ok, buf = cv2.imencode(".png", 255 - (g * 255).astype("uint8"))
    assert ok
    return buf.tobytes()


def _admit(db_path, cells):
    from open_guji_cv.clustering.glyph_db import GlyphDB
    db = GlyphDB(db_path)
    try:
        for ch, prov, i in cells:
            assert db.admit_instance(f"v2:vol01:1:{i}:1", ch, _png(i), provenance=prov, edition_tag="ted",
                                     page="1", col=i, idx=1)
        db.conn.commit()
    finally:
        db.close()


def _export(db_path, store):
    from open_guji_cv.clustering.glyph_db import GlyphDB, export_store
    db = GlyphDB(db_path)
    try:
        export_store(db, store)
    finally:
        db.close()


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    """没迁中心库的工作区：字形库真源 + 当前 glyph.db（甲乙两例人裁、丙一例机器）。"""
    for k in ("GUJI_GLYPH_DB", "GUJI_GLYPH_STORE", "GUJI_PRODUCTS_DIR", "GUJI_DATA_BRANCH"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GUJI_DATA_CACHE", str(tmp_path / "blobcache"))
    w = tmp_path / "ws"
    (w / "output").mkdir(parents=True)
    (w / "workspace.yaml").write_text("id: tws\n", encoding="utf-8")
    monkeypatch.setenv("GUJI_WORKSPACE", str(w))
    live = w / "output" / "glyph.db"
    _admit(live, [("甲", "human", 1), ("乙", "human", 2), ("丙", "align", 3)])
    _export(live, w / "output" / "glyph_store")
    return w


def _rows(db):
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
        return {q: sorted(c.execute(q).fetchall()) for q in (
            "SELECT e.instance_id, g.edition_tag, g.char FROM exemplars e JOIN glyphs g USING(glyph_id)",
            "SELECT instance_id, char, provenance, admitted_at FROM admissions",
            "SELECT instance_id, label, label_status, patch_png FROM instances",
            "SELECT instance_id, kind, algo_version, data FROM derived")}


def test_snapshot_writes_manifest_and_builds_identical_db(ws):
    from open_guji_cv.core.glyph_pin import items_digest, load_manifest, pinned_db_meta, pinned_db_path
    from open_guji_cv.ops.glyph_snapshot import collect, snapshot
    out = snapshot(ws, note="首版")
    assert out["pin"] == 1 and out["png"] == 3 and out["borrow"] == []
    man = load_manifest(ws, 1)
    assert man["digest"] == items_digest(collect(ws)[0]) == out["digest"]
    assert man["note"] == "首版" and man["fingerprints"]["n_human"] == 2
    assert (ws / "config" / "glyph-pack" / "g1" / "manifest.json").exists()
    db = pinned_db_path(1)
    assert db == ws / "output" / "glyph-g1.db"
    assert pinned_db_meta(db)["digest"] == man["digest"]
    assert _rows(db) == _rows(ws / "output" / "glyph.db")       # 快照即当前：建出的库与当前库逐行相同
    with pytest.raises(SystemExit, match="不空升"):
        snapshot(ws)


def test_new_rulings_go_to_live_library_not_old_snapshot(ws):
    from open_guji_cv.core.glyph_pin import load_manifest, pinned_db_path
    from open_guji_cv.ops.glyph_snapshot import build_pinned_db, snapshot
    snapshot(ws)
    g1_rows = _rows(pinned_db_path(1))
    live = ws / "output" / "glyph.db"
    _admit(live, [("丁", "human", 4)])                        # 别处又审进一条人裁
    _export(live, ws / "output" / "glyph_store")
    assert _rows(pinned_db_path(1)) == g1_rows
    assert build_pinned_db(ws, 1)["reused"] is True
    r = build_pinned_db(ws, 1, force=True)                     # 当前库变了，按 g1 清单重建出的仍是 g1
    assert r["reused"] is False and _rows(pinned_db_path(1)) == g1_rows
    out = snapshot(ws)
    assert out["pin"] == 2 and out["digest"] != load_manifest(ws, 1)["digest"]
    assert _rows(pinned_db_path(2)) == _rows(live)


def _book(pin):
    return SimpleNamespace(glyph_pin=pin, id="vol01")


def test_unpinned_and_legacy_params_unchanged(ws):
    from open_guji_cv.core.engine import params_hash
    from open_guji_cv.core.glyph_pin import with_glyph_pin
    from open_guji_cv.steps.glyph_match import GlyphMatchParams
    from open_guji_cv.steps.seed_admit import SeedAdmitParams
    for P in (GlyphMatchParams, SeedAdmitParams):
        p = P()
        assert with_glyph_pin(p, _book(None)) is p
    s = SeedAdmitParams()
    legacy = with_glyph_pin(s, _book(3))                       # 钉了号、没有快照：旧做法，只换指纹
    assert legacy.human_fingerprint == "glyph-g3" and legacy.db_path == s.db_path
    g = GlyphMatchParams()
    assert with_glyph_pin(g, _book(3)).model_dump() == g.model_dump()


def test_snapshot_pin_reads_pinned_db_and_hash_ignores_live_library(ws):
    from open_guji_cv.core.engine import params_hash
    from open_guji_cv.core.glyph_pin import load_manifest, pinned_db_path, with_glyph_pin
    from open_guji_cv.core.step import STEPS
    from open_guji_cv.ops.glyph_snapshot import snapshot
    from open_guji_cv.steps.glyph_match import GlyphMatchParams
    from open_guji_cv.steps.row_segment import RowSegmentParams
    from open_guji_cv.steps.seed_admit import SeedAdmitParams
    snapshot(ws)
    dg, db = load_manifest(ws, 1)["digest"], str(pinned_db_path(1))
    g = with_glyph_pin(GlyphMatchParams(), _book(1))
    assert g.db_path == db and g.db_fingerprint == dg and g.borrow_fingerprint == ""
    s = with_glyph_pin(SeedAdmitParams(), _book(1))
    assert s.db_path == db and s.human_fingerprint == dg and s.approx_fingerprint == ""
    r = with_glyph_pin(RowSegmentParams(roster_glyph_refine=True), _book(1))
    assert r.roster_glyph_db == db and r.roster_glyph_fingerprint == dg
    plain_rs = RowSegmentParams()
    assert with_glyph_pin(plain_rs, _book(1)) is plain_rs     # 开关没开的 row_segment 不碰
    h0 = params_hash(s, STEPS["seed_admit"].spec.soft_params)
    live = ws / "output" / "glyph.db"
    _admit(live, [("丁", "human", 4)])                        # 当前库多了人裁：钉 g1 的册参数不变
    s2 = with_glyph_pin(SeedAdmitParams(), _book(1))
    assert params_hash(s2, STEPS["seed_admit"].spec.soft_params) == h0
    assert SeedAdmitParams().human_fingerprint != SeedAdmitParams(db_path=db).human_fingerprint
    explicit = SeedAdmitParams(db_path=str(ws / "other.db"))  # 显式指了别的库：只钉指纹，不换库
    e = with_glyph_pin(explicit, _book(1))
    assert e.db_path == explicit.db_path and e.human_fingerprint == "glyph-g1"


def test_require_pinned_db_and_ensure(ws):
    from open_guji_cv.core.glyph_pin import GlyphPinMissing, pinned_db_path, require_pinned_db
    from open_guji_cv.ops.glyph_snapshot import ensure_pins, snapshot
    require_pinned_db(ws, 7)                                   # 没快照的号：不查
    snapshot(ws)
    require_pinned_db(ws, 1)
    pinned_db_path(1).unlink()
    with pytest.raises(GlyphPinMissing, match="pin-build"):
        require_pinned_db(ws, 1)
    assert [r["pin"] for r in ensure_pins(ws, [1, 7], log=lambda s: None)] == [1]
    require_pinned_db(ws, 1)


class _FakeR2:
    """桩：按 sha 给 blob。"""

    def __init__(self, blobs):
        self.blobs = blobs

    def fetch_blobs(self, shas, bucket="main", ext="png", skip_missing=False):
        for s in shas:
            yield s, self.blobs.get(s)


def test_build_from_r2_when_local_files_are_gone(ws, tmp_path):
    import shutil
    from open_guji_cv.core.glyph_pin import load_manifest, pinned_db_path
    from open_guji_cv.ops.glyph_snapshot import _store_dir, build_pinned_db, snapshot, verify_remote
    snapshot(ws)
    want = _rows(pinned_db_path(1))
    man = load_manifest(ws, 1)
    store = _store_dir(ws)
    blobs = {it["sha256"]: (store / it["path"]).read_bytes() for it in man["items"]}
    assert verify_remote(ws, 1, src=_FakeR2(blobs))["ok"]
    shutil.rmtree(store)                                       # 新机器：本机没有那一版的文件，缓存也是空的
    shutil.rmtree(tmp_path / "blobcache")
    pinned_db_path(1).unlink()
    r = build_pinned_db(ws, 1, src=_FakeR2(blobs))
    assert r["fetched"] == len(man["items"]) and r["local"] == 0
    assert _rows(pinned_db_path(1)) == want
    lost = dict(blobs)
    lost.pop(man["items"][0]["sha256"])
    with pytest.raises(SystemExit, match="R2 也取不到"):
        verify_remote(ws, 1, src=_FakeR2(lost))


def test_upload_plan_dry_run(ws):
    from open_guji_cv.ops.glyph_snapshot import snapshot, upload_blobs
    out = snapshot(ws)
    plan = upload_blobs(ws, 1)
    assert plan["executed"] is False and plan["png"] == out["png"] and plan["n_not_local"] == 0
    assert plan["txt"] >= 1


def test_built_db_meta_carries_fingerprints_for_manifest_without_them(ws):
    """清单没记 fingerprints（--no-build 出的 g4）时，钉号读建库时写进库 meta 的那份。"""
    from open_guji_cv.core.glyph_pin import pinned_db_meta, pinned_db_path
    from open_guji_cv.ops.glyph_snapshot import build_pinned_db, snapshot
    snapshot(ws, build=False)
    build_pinned_db(ws, 1)
    fp = pinned_db_meta(pinned_db_path(1))["fingerprints"]
    assert fp["n_human"] == 2 and "approx" in fp and "borrow_fingerprint" in fp


def test_upload_and_verify_only_new_items_since_previous(ws):
    """出 g2 时只传、只核相对 g1 新增或改动的条目；``full`` 才全量。"""
    from open_guji_cv.core.glyph_pin import load_manifest
    from open_guji_cv.ops.glyph_snapshot import _store_dir, snapshot, upload_blobs, verify_remote
    snapshot(ws)
    live = ws / "output" / "glyph.db"
    _admit(live, [("丁", "human", 4)])
    _export(live, ws / "output" / "glyph_store")
    snapshot(ws)
    g1, g2 = load_manifest(ws, 1), load_manifest(ws, 2)
    old = {(it["root"], it["path"], it["sha256"]) for it in g1["items"]}
    new = [it for it in g2["items"] if (it["root"], it["path"], it["sha256"]) not in old]
    assert 0 < len(new) < len(g2["items"])
    plan = upload_blobs(ws, 2)
    assert plan["png"] + plan["txt"] == len(new)
    assert plan["skipped_same_as_previous"] == len(g2["items"]) - len(new)
    assert upload_blobs(ws, 2, full=True)["skipped_same_as_previous"] == 0
    store = _store_dir(ws)
    blobs = {it["sha256"]: (store / it["path"]).read_bytes() for it in g2["items"]}
    only_new = {it["sha256"]: blobs[it["sha256"]] for it in new}
    r = verify_remote(ws, 2, src=_FakeR2(only_new))           # R2 只有新条目也能核过：旧条目上一版核过
    assert r["ok"] and r["checked"] == len(new) and r["items"] == len(g2["items"])
    with pytest.raises(SystemExit, match="R2 也取不到"):
        verify_remote(ws, 2, src=_FakeR2(only_new), full=True)


def test_push_collects_new_pack_text_and_refuses_changed(ws):
    from open_guji_cv.core.glyph_pin import load_manifest
    from open_guji_cv.datastore.workcopy import glyph_pack_blobs
    from open_guji_cv.ops.glyph_snapshot import snapshot
    snapshot(ws)
    rel = "config/glyph-pack/g1/manifest.json"
    rows = [SimpleNamespace(tbl="files", src_path=rel)]
    got = glyph_pack_blobs(ws, ws, {}, rows)
    man = load_manifest(ws, 1)
    assert set(got) == {it["sha256"] for it in man["items"] if it["type"] == "txt"}
    assert glyph_pack_blobs(ws, ws, {rel: "x"}, rows) == {}   # 基准里已有（推过）：不再传
    st = ws / "output" / "glyph_store" / "exemplars.jsonl"
    st.write_text(st.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="重出"):
        glyph_pack_blobs(ws, ws, {}, rows)


def test_manifest_json_is_stable(ws):
    """清单条目按 (root, path) 排序、带类型；digest 只看 (root, path, sha)。"""
    from open_guji_cv.core.glyph_pin import items_digest
    from open_guji_cv.ops.glyph_snapshot import collect
    items, _ = collect(ws)
    assert items == sorted(items, key=lambda i: (i["root"], i["path"]))
    assert {i["type"] for i in items} == {"txt", "png"}
    shuffled = list(reversed([{**i, "size": 0} for i in items]))
    assert items_digest(shuffled) == items_digest(items)
    assert json.loads(json.dumps(items)) == items


def test_font_domain_copied_from_live_db(ws):
    """字体域不在真源里：建钉版库时从当前库原样拷，字体域指纹相同（Step5-b 不因换库而变）。"""
    from pathlib import Path
    from open_guji_cv.clustering.font_candidates import _font_files
    from open_guji_cv.clustering.font_glyphs import FontSpec, import_font
    from open_guji_cv.clustering.glyph_db import GlyphDB
    from open_guji_cv.clustering.glyph_fp import font_domain_fingerprint
    from open_guji_cv.core.glyph_pin import pinned_db_path
    from open_guji_cv.ops.glyph_snapshot import snapshot
    files = _font_files()[:1]
    if not files:
        pytest.skip("本机没有字体文件")
    from open_guji_cv.ops.glyph_snapshot import build_pinned_db
    live = ws / "output" / "glyph.db"
    out = snapshot(ws)                                             # 先出快照、后导字体（新机器常这样）
    assert out["db"]["fonts"] == []
    db = GlyphDB(live)
    try:
        import_font(db, FontSpec(edition_tag="font:t", font_paths=[Path(f) for f in files], title="t"), ["一", "口"])
    finally:
        db.close()
    r = build_pinned_db(ws, 1)                                     # 字体域变了：不复用，重建带上字体
    assert r["reused"] is False and r["fonts"][0]["edition"] == "font:t"
    assert font_domain_fingerprint(pinned_db_path(1)) == font_domain_fingerprint(live)
    assert build_pinned_db(ws, 1)["reused"] is True
    assert out["fingerprints"]["n_instances"] == 3                # 字体域不算本书实例


def test_manifest_dump_roundtrips():
    from open_guji_cv.ops.glyph_snapshot import _dump
    man = {"n": 1, "digest": "glyph-x", "fingerprints": {"approx": False},
           "items": [{"root": "gs", "path": "a.jsonl", "sha256": "0" * 64, "size": 1, "type": "txt"},
                     {"root": "gs", "path": "p/b.png", "sha256": "1" * 64, "size": 2, "type": "png"}]}
    text = _dump(man)
    assert json.loads(text) == man
    assert sum(1 for ln in text.splitlines() if "sha256" in ln) == len(man["items"])   # 一行一条
