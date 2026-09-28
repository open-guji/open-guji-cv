# -*- coding: utf-8 -*-
"""cards 结果缓存 + 按格 embedding 缓存 + 原型按例增量（overview #166 加急，2026-09-28）。

服务器上全唐文开 CNN 首选后 `/api/review/cards` >180 s、RSS 3.27G：原型缓存键含库内容
指纹，本书库每进一例刻例就整库重跑 CNN；每次请求又给全书待审格重算 embedding。
"""
from __future__ import annotations

import numpy as np
import pytest


def _u(*v) -> np.ndarray:
    a = np.asarray(v, np.float32)
    return a / np.linalg.norm(a)


# ── cards 结果缓存 ──────────────────────────────────────────────────

@pytest.fixture
def cache_env(ws, tmp_path, monkeypatch):
    from open_guji_cv.review import cards as C
    fb = tmp_path / "fb"
    (fb / "events").mkdir(parents=True)
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(fb))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    C.clear_cards_cache()
    yield fb
    C.clear_cards_cache()


def test_cached_cards_hit_and_invalidate_on_event(cache_env, tmp_path):
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.review import cards as C
    st = ProductStore(tmp_path / "products")
    n = {"calls": 0}

    def compute():
        n["calls"] += 1
        return {"book": "keben", "cards": [{"id": "keben:1:1:1", "db": {"c": [("北", .9)]}}]}

    req = {"pages": "1", "group": "char"}
    r1, h1 = C.cached_cards("keben", req, compute, st)
    r2, h2 = C.cached_cards("keben", req, compute, st)
    assert (h1, h2, n["calls"]) == ("miss", "mem", 1)
    assert r1 == r2 and r1["cards"][0]["db"]["c"] == [["北", 0.9]]   # JSON 往返后的形状
    C.clear_cards_cache()
    r3, h3 = C.cached_cards("keben", req, compute, st)
    assert (h3, n["calls"]) == ("disk", 1) and r3 == r1
    # 人裁一写入 → 事件水位变 → 失效
    (cache_env / "events" / "b.jsonl").write_text('{"x":1}\n', encoding="utf-8")
    _, h4 = C.cached_cards("keben", req, compute, st)
    assert (h4, n["calls"]) == ("miss", 2)
    # 参数不同 → 不同键
    _, h5 = C.cached_cards("keben", {**req, "sample_limit": 3}, compute, st)
    assert h5 == "miss"


def test_cached_cards_invalidate_on_product_manifest(cache_env, tmp_path):
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.review import cards as C
    st = ProductStore(tmp_path / "products")
    man = st.root / "keben" / "seed_admit" / "_manifest.jsonl"
    man.parent.mkdir(parents=True)
    man.write_text('{"key":"p0001","fingerprint":"a"}\n', encoding="utf-8")
    calls = []
    C.cached_cards("keben", {}, lambda: calls.append(1) or {"v": 1}, st)
    C.cached_cards("keben", {}, lambda: calls.append(1) or {"v": 1}, st)
    assert len(calls) == 1
    with open(man, "a", encoding="utf-8") as f:
        f.write('{"key":"p0001","fingerprint":"b"}\n')
    C.cached_cards("keben", {}, lambda: calls.append(1) or {"v": 1}, st)
    assert len(calls) == 2


def test_cached_cards_disk_pruned(cache_env, tmp_path, monkeypatch):
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.review import cards as C
    monkeypatch.setattr(C, "_CARDS_DISK_KEEP", 2)
    st = ProductStore(tmp_path / "products")
    for i in range(4):
        C.cached_cards("keben", {"i": i}, lambda: {"v": 1}, st)
    assert len(list(C._cards_cache_dir("keben").glob("*.json"))) == 2


# ── 路由：缓存头、响应体与直接装配逐字节一致 ────────────────────────────────

def test_route_cards_cache_header_and_identical_body(cache_env, monkeypatch):
    import importlib

    from fastapi.testclient import TestClient
    app = importlib.import_module("open_guji_cv.console.app").app
    console_auth = importlib.import_module("open_guji_cv.console.auth")
    Identity = importlib.import_module("open_guji_cv.console.auth.identity").Identity
    app.dependency_overrides[console_auth.get_identity] = lambda: Identity(
        email="r@example.com", role="reviewer", tier="reviewer")
    try:
        c = TestClient(app)
        q = "/api/review/cards?book=keben&pages=1&group=char&gate_cut=false"
        r1, r2 = c.get(q), c.get(q)
        assert r1.status_code == 200, r1.text
        assert r1.headers["X-Cards-Cache"] == "miss" and r2.headers["X-Cards-Cache"] == "mem"
        assert r1.content == r2.content
        r3 = c.get("/api/review/cards?book=keben&pages=1&gate_cut=false")
        assert r3.status_code == 200 and r3.json()["cards"] == []
    finally:
        app.dependency_overrides.clear()


# ── 按格 embedding 缓存（`borrow_first.EmbCache`）─────────────────────────

class _ManStore:
    def __init__(self, sha):
        self.sha = sha

    def manifest(self, book, step):
        sha = self.sha

        class _M:
            def get(self, key):
                return type("E", (), {"sha256": sha})()
        return _M()


def test_emb_cache_roundtrip_and_rekey_on_product_change(ws, tmp_path, monkeypatch):
    from open_guji_cv.review.borrow_first import EmbCache
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    card = {"id": "keben:1:1:1", "page": 1}
    ec = EmbCache("keben", _ManStore("aaa"), "fp")
    assert ec.get(card) is None
    ec.put(card, _u(1, 0))
    ec.save()
    got = EmbCache("keben", _ManStore("aaa"), "fp").get(card)
    assert got is not None and np.array_equal(got, _u(1, 0))
    assert EmbCache("keben", _ManStore("bbb"), "fp").get(card) is None   # Step4 重跑 → 换键
    assert EmbCache("keben", _ManStore("aaa"), "fp2").get(card) is None  # 换模型 → 换文件
    assert EmbCache("keben", _ManStore(None), "fp").get(card) is None    # 没产物指纹不缓存


# ── 原型增量重建（#166 加急：库一变不再整库重跑 CNN）───────────────────────

def _mini_db(path, items):
    import sqlite3

    import cv2
    c = sqlite3.connect(path)
    c.executescript("""
      CREATE TABLE glyphs (glyph_id INTEGER PRIMARY KEY, char TEXT, updated_at TEXT);
      CREATE TABLE exemplars (glyph_id INTEGER, instance_id TEXT, role TEXT, added_at TEXT,
                              PRIMARY KEY (glyph_id, instance_id));
      CREATE TABLE admissions (admitted_at TEXT);
      CREATE TABLE derived (instance_id TEXT, kind TEXT, algo_version TEXT, data BLOB,
                            PRIMARY KEY (instance_id, kind, algo_version));""")
    _mini_add(c, items)
    return c


def _mini_add(c, items):
    import cv2
    for ch, iid, v in items:
        gid = c.execute("SELECT glyph_id FROM glyphs WHERE char=?", (ch,)).fetchone()
        if gid is None:
            gid = (c.execute("INSERT INTO glyphs (char, updated_at) VALUES (?, 't')", (ch,)).lastrowid,)
        img = np.full((64, 64), v, np.uint8)
        c.execute("INSERT INTO exemplars VALUES (?,?,'x',?)", (gid[0], iid, iid))
        c.execute("INSERT INTO derived VALUES (?, 'norm', 'v1', ?)",
                  (iid, cv2.imencode(".png", img)[1].tobytes()))
    c.commit()


class _CountingCnn:
    from pathlib import Path as _P
    ckpt = _P("/nonexistent/best.pt")

    def __init__(self):
        self.n = 0

    def embed(self, imgs):
        self.n += len(imgs)
        return np.stack([_u(float(im.mean()) + 1.0, 1.0) for im in imgs])


def test_proto_index_incremental_only_embeds_new_exemplars(tmp_path, monkeypatch):
    from open_guji_cv.review import borrow_first as bf
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(bf.ProtoIndex, "_mem", {})
    db = str(tmp_path / "g.db")
    c = _mini_db(db, [("甲", "i1", 10), ("甲", "i2", 20), ("乙", "i3", 200)])
    cnn = _CountingCnn()
    chars, mat = bf.ProtoIndex.get(db, cnn)
    assert chars == ["乙", "甲"] and cnn.n == 3
    assert np.allclose(np.linalg.norm(mat, axis=1), 1.0)
    bf.ProtoIndex.get(db, cnn)
    assert cnn.n == 3                                     # 库没变：内存命中
    _mini_add(c, [("丙", "i4", 90)])                       # H 道进了一例新刻例
    chars2, _ = bf.ProtoIndex.get(db, cnn)
    assert chars2 == ["丙", "乙", "甲"] and cnn.n == 4     # 只给新那一例过网络
    monkeypatch.setattr(bf.ProtoIndex, "_mem", {})         # 换进程：读盘
    bf.ProtoIndex.get(db, cnn)
    assert cnn.n == 4
    # 与直接整库算的原型一致
    ref_chars, ref = bf.build_protos(bf._load_exemplar_norms(db), cnn.embed)
    got_chars, got = bf.ProtoIndex.get(db, cnn)
    assert ref_chars == got_chars and np.allclose(ref, got, atol=1e-6)
