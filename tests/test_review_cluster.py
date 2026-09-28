# -*- coding: utf-8 -*-
"""批审组内按形聚簇 + cards 结果缓存（overview #166，2026-09-28）。

聚类是纯函数，拿手造的单位向量测；装配（`_build_char_groups` + clusterer）拿
`cards()` 输出形状的字典造；缓存与路由用 fixture 工作区（`ws`，册 keben）。
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from open_guji_cv.console.routers.review import (_build_char_groups, _build_shape_groups,
                                                   _make_clusterer, cards_by_char,
                                                   cards_by_shape)
from open_guji_cv.console.routers.review_cluster import (CLUSTER_THR, calibrate,
                                                           cluster_tiles, leader_cluster)


def _u(*v) -> np.ndarray:
    a = np.asarray(v, np.float32)
    return a / np.linalg.norm(a)


def _card(id_, char="北", page=1, ref=None) -> dict:
    return {"id": id_, "page": page, "col": 1, "slot": 1, "sub": "",
            "patch": f"/api/cache/b/char_patch/{id_}.png", "admit": False,
            "channel": None, "char": None, "jys": None, "ref": ref, "form": None,
            "doubts": [], "db": None, "ocr": [], "ctx": {"char": char, "margin": 1.0,
                                                          "source": "context"},
            "groups": None, "ai": None}


# ── leader_cluster ──────────────────────────────────────────────────

def test_leader_cluster_merges_close_and_splits_far():
    E = np.stack([_u(1, 0, 0), _u(1, .05, 0), _u(1, 0, .05), _u(0, 1, 0), _u(0, 1, .05)])
    cls = leader_cluster(E, ["x"] * 5, thr=0.95)
    assert sorted(map(sorted, cls)) == [[0, 1, 2], [3, 4]]
    assert [len(c) for c in cls] == [3, 2]          # 大簇在前


def test_leader_cluster_key_mismatch_never_merges():
    """首选字不同的两格即使图一模一样也不同簇（#166「与代表图不一致的不合进该簇」）。"""
    E = np.stack([_u(1, 0), _u(1, 0), _u(1, 0)])
    cls = leader_cluster(E, ["今", "今", "令"], thr=0.5)
    assert sorted(map(sorted, cls)) == [[0, 1], [2]]


def test_leader_cluster_invalid_rows_are_singletons():
    E = np.stack([_u(1, 0), _u(1, 0), _u(1, 0)])
    cls = leader_cluster(E, ["x"] * 3, thr=0.5, valid=[True, False, True])
    assert sorted(map(sorted, cls)) == [[0, 2], [1]]
    assert leader_cluster(None, ["x", "x"]) == [[0], [1]]


def test_leader_cluster_rep_is_nearest_to_centroid():
    E = np.stack([_u(1, .3), _u(1, 0), _u(1, -.3)])
    cls = leader_cluster(E, ["x"] * 3, thr=0.9)
    assert len(cls) == 1 and cls[0][0] == 1          # 居中那张当代表


def test_leader_cluster_deterministic_and_empty():
    E = np.stack([_u(1, i * .01) for i in range(6)])
    assert leader_cluster(E, ["x"] * 6, .99) == leader_cluster(E, ["x"] * 6, .99)
    assert leader_cluster(np.zeros((0, 2)), []) == []


def test_calibrate_counts_wrong_merges():
    E = np.stack([_u(1, 0), _u(1, .01), _u(1, .02), _u(0, 1)])
    human = ["今", "今", "令", "今"]                  # 第 3 格人裁是「令」却长得像「今」
    first = ["今"] * 4
    lo, hi = calibrate(E, human, first, [0.9, 0.99999])
    assert lo["n_shown"] == 2 and lo["n_via_rep"] == 2 and lo["n_bad"] == 1
    assert lo["bad_rate"] == 0.5
    assert hi["n_bad"] == 0 and hi["n_shown"] == 4


# ── cluster_tiles / 装配 ─────────────────────────────────────────────

def test_cluster_tiles_shape_and_members():
    tiles = [_card(f"b:1:1:{i}") for i in range(4)]
    emb = {"b:1:1:0": _u(1, 0), "b:1:1:1": _u(1, .01), "b:1:1:2": _u(0, 1)}   # 第 4 格缺向量
    cls = cluster_tiles(tiles, lambda t: emb.get(t["id"]), lambda t: "北", thr=0.9)
    assert [c["n"] for c in cls] == [2, 1, 1]
    top = cls[0]
    assert top["id"] == top["rep"]["id"] == top["members"][0]["id"]
    assert top["members"][0]["sim"] == 1.0
    assert {m["id"] for m in top["members"]} == {"b:1:1:0", "b:1:1:1"}
    missing = next(c for c in cls if c["id"] == "b:1:1:3")
    assert missing["members"][0]["sim"] is None
    assert sum(c["n"] for c in cls) == 4


def _fake_emb(cards_, blobs):
    return {c["id"]: _u(*blobs[i % len(blobs)]) for i, c in enumerate(cards_)}


def test_build_char_groups_with_clusterer_reps_and_counts():
    cs = [_card(f"b:1:1:{i}", "北") for i in range(10)] + [_card(f"b:2:1:{i}", "南", page=2)
                                                             for i in range(3)]
    emb = _fake_emb(cs, [(1, 0, 0), (0, 1, 0)])          # 每个字种两种形
    cl = _make_clusterer("b", None, cs, emb, None)
    gs = _build_char_groups(cs, 60, cl)
    g = gs[0]
    assert g["char"] == "北" and g["n"] == 10
    assert g["n_clusters"] == 2 and len(g["tiles"]) == len(g["clusters"]) == 2
    assert [t["id"] for t in g["tiles"]] == [c["id"] for c in g["clusters"]]
    assert sum(c["n"] for c in g["clusters"]) == 10
    # 全书待审格数守恒：每格恰在一簇
    ids = [m["id"] for g in gs for c in g["clusters"] for m in c["members"]]
    assert sorted(ids) == sorted(c["id"] for c in cs)


def test_build_char_groups_cluster_sample_limit_truncates_clusters():
    cs = [_card(f"b:1:1:{i}") for i in range(5)]
    emb = {c["id"]: _u(*np.eye(5)[i]) for i, c in enumerate(cs)}   # 两两正交，各自成簇
    g = _build_char_groups(cs, 3, _make_clusterer("b", None, cs, emb, None))[0]
    assert g["n_clusters"] == 5 and len(g["clusters"]) == 3 and g["truncated"] is True


def test_build_char_groups_without_clusterer_unchanged():
    cs = [_card(f"b:1:1:{i}") for i in range(3)]
    g = _build_char_groups(cs, 60)[0]
    assert "clusters" not in g and "n_clusters" not in g and len(g["tiles"]) == 3


def test_shape_groups_clusterer_respects_first_pick_key():
    """按形分组里同一组可以有几个首选字（形近池），聚簇时首选字不同的格不合簇。"""
    cs = [_card("b:1:1:1", "今"), _card("b:1:1:2", "今"), _card("b:1:1:3", "令")]
    emb = {c["id"]: _u(1, 0) for c in cs}                  # 三张图一模一样
    cl = _make_clusterer("b", None, cs, emb, None)
    out = cl(cs, 60)
    assert sorted(c["n"] for c in out["clusters"]) == [1, 2]


def test_shape_groups_accept_clusterer():
    cs = [_card(f"b:1:1:{i}", "北") for i in range(4)]
    emb = {c["id"]: _u(1, 0) for c in cs}
    gs = _build_shape_groups(cs, 60, get_patch=lambda t: None, embed=None,
                             clusterer=_make_clusterer("b", None, cs, emb, None))
    assert gs[0]["n_clusters"] == 1 and gs[0]["clusters"][0]["n"] == 4


def test_default_threshold_is_a_cosine():
    assert 0.5 < CLUSTER_THR < 1.0


# ── 开关：没设 first_pick 的书缺省不聚、输出与改前逐字节一样 ─────────────────

class _EmptyStore:
    root = None

    def read(self, *a, **k):
        return None


def test_auto_cluster_off_for_book_without_first_pick(keben_book):
    kw = dict(gate_cut=False, skip_decided=False, sample_limit=60)
    base = cards_by_char("keben", "1", "review", _EmptyStore(), **kw)
    auto = cards_by_char("keben", "1", "review", _EmptyStore(), cluster="auto", **kw)
    assert json.dumps(base, ensure_ascii=False) == json.dumps(auto, ensure_ascii=False)
    assert "cluster" not in auto
    shp = cards_by_shape("keben", "1", "review", _EmptyStore(), cluster="auto", **kw)
    assert "cluster" not in shp


def test_forced_cluster_on_adds_summary(keben_book):
    out = cards_by_char("keben", "1", "review", _EmptyStore(), gate_cut=False,
                        skip_decided=False, sample_limit=60, cluster="on")
    assert out["cluster"]["n_cells"] == 0 and out["cluster"]["thr"] == CLUSTER_THR


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
        assert "cluster" not in r1.json()                     # keben 没设 first_pick
        assert c.get(q + "&cluster=bogus").status_code == 400
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
