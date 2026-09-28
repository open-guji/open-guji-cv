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


# ── 路由：聚簇参数（缓存本身的测试在 test_review_cards_cache.py）────────────────

def test_route_cluster_param(ws, tmp_path, monkeypatch):
    import importlib

    from fastapi.testclient import TestClient
    from open_guji_cv.review import cards as C
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    C.clear_cards_cache()
    app = importlib.import_module("open_guji_cv.console.app").app
    console_auth = importlib.import_module("open_guji_cv.console.auth")
    Identity = importlib.import_module("open_guji_cv.console.auth.identity").Identity
    app.dependency_overrides[console_auth.get_identity] = lambda: Identity(
        email="r@example.com", role="reviewer", tier="reviewer")
    try:
        c = TestClient(app)
        q = "/api/review/cards?book=keben&pages=1&group=char&gate_cut=false"
        assert "cluster" not in c.get(q).json()               # keben 没设 first_pick：缺省不聚
        assert c.get(q + "&cluster=on").json()["cluster"]["thr"] == CLUSTER_THR
        assert c.get(q + "&cluster=bogus").status_code == 400
    finally:
        app.dependency_overrides.clear()
        C.clear_cards_cache()
