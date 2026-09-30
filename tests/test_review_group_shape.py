# -*- coding: utf-8 -*-
"""按形聚类分组（任务书-C-批审按形聚类分组，2026-09-27）：分组/聚类全是纯
函数，`get_patch`/`embed` 都用假的注入（不连真图/真 CNN），跟
`test_review_group_char.py` 同一个理由——把领域逻辑单独摆出来测。
"""
from __future__ import annotations

import numpy as np

from open_guji_cv.console.routers.review import (_build_shape_groups,
                                                    _cluster_pool_by_shape,
                                                    _init_shape_centroids,
                                                    _majority, _pool_key_map,
                                                    _shape_candidates,
                                                    _spherical_kmeans,
                                                    cards_by_shape)


def _card(id_="b:1:1:1", page=1, ctx=None, db=None, ocr=None, ref=None) -> dict:
    return {
        "id": id_, "page": page, "col": 1, "slot": 1, "sub": "",
        "patch": f"/api/cache/b/char_patch/{id_}.png",
        "admit": False, "channel": None, "char": None,
        "jys": None, "ref": ref, "form": None, "doubts": [],
        "db": db, "ocr": ocr or [], "ctx": ctx, "groups": None, "ai": None,
    }


# ── _pool_key_map ─────────────────────────────────────────────────────

_PAIRS = {
    "今": [("令", "gw", 0.9, "")],
    "令": [("今", "gw", 0.9, "")],
    "玉": [("王", "gw", 0.9, "")],
    "王": [("玉", "gw", 0.9, "")],
}


def test_pool_key_map_merges_confusable_pair():
    pool_of, members = _pool_key_map({"今", "令", "北"}, pairs=_PAIRS)
    assert pool_of["今"] == pool_of["令"]
    assert pool_of["北"] != pool_of["今"]
    assert members[pool_of["今"]] == {"今", "令"}
    assert members[pool_of["北"]] == {"北"}


def test_pool_key_map_no_pairs_each_char_own_pool():
    pool_of, members = _pool_key_map({"北", "南"}, pairs={})
    assert pool_of["北"] != pool_of["南"]
    assert all(len(v) == 1 for v in members.values())


def test_pool_key_map_oversized_component_dissolves_to_singletons():
    """回归（vol03 真实数据实测）：形近对表连通度很高，链式合并会把一大串
    不相干的字拖进同一个池（真实例：137 字）。超过 `MAX_POOL_LABELS` 就地
    解散回各自单字池，不能真的把它们聚在一起。"""
    import open_guji_cv.console.routers.review as rv
    # 6 个字首尾相连成一条链（A-B-C-D-E-F），链长 6 超过默认上限（6 时不超，
    # 用 7 更保险地触发解散；这里直接把上限调小到测试友好的值）。
    chain = ["甲", "乙", "丙", "丁", "戊", "己", "庚"]
    pairs = {chain[i]: [(chain[i + 1], "visual", 0.99, "")] for i in range(len(chain) - 1)}
    for i in range(1, len(chain)):
        pairs.setdefault(chain[i], []).append((chain[i - 1], "visual", 0.99, ""))

    orig_cap = rv.MAX_POOL_LABELS
    rv.MAX_POOL_LABELS = 4
    try:
        pool_of, members = _pool_key_map(set(chain), pairs=pairs)
    finally:
        rv.MAX_POOL_LABELS = orig_cap

    assert len({pool_of[c] for c in chain}) == len(chain)   # 全部解散成单字池
    for c in chain:
        assert members[pool_of[c]] == {c}


def test_pool_key_map_transitive_chain():
    """A~B、B~C（表里没有直接 A~C）也要落进同一个池（链没超上限时，今/令/
    大/天这类真实小簇需要传递闭包）——并查集处理链式合并。"""
    pairs = {"甲": [("乙", "gw", 0.9, "")], "乙": [("甲", "gw", 0.9, ""), ("丙", "gw", 0.9, "")],
            "丙": [("乙", "gw", 0.9, "")]}
    pool_of, members = _pool_key_map({"甲", "乙", "丙"}, pairs=pairs)
    assert len({pool_of["甲"], pool_of["乙"], pool_of["丙"]}) == 1
    assert members[pool_of["甲"]] == {"甲", "乙", "丙"}


# ── _majority ───────────────────────────────────────────────────────

def test_majority_basic():
    assert _majority(["今", "今", "令"]) == ("今", 2)


def test_majority_ignores_none():
    assert _majority([None, None, "今"]) == ("今", 1)


def test_majority_all_none():
    assert _majority([None, None]) == (None, 0)


# ── _shape_candidates ───────────────────────────────────────────────

def test_shape_candidates_suggest_first_then_by_votes():
    tiles = [_card(ref={"char": "今"}), _card(ref={"char": "今"}), _card(ref={"char": "令"})]
    out = _shape_candidates(tiles, "今")
    assert out[0] == "今"
    assert "令" in out


def test_shape_candidates_cap_and_dedup():
    tiles = [_card(ctx={"char": "甲"}), _card(ctx={"char": "乙"}),
             _card(ctx={"char": "丙"}), _card(ctx={"char": "丁"})]
    out = _shape_candidates(tiles, "甲", cap=3)
    assert len(out) == 3
    assert out[0] == "甲"
    assert len(set(out)) == len(out)


# ── _init_shape_centroids / _spherical_kmeans ───────────────────────

def _emb2(x: float, y: float) -> np.ndarray:
    v = np.array([x, y], dtype=np.float32)
    return v / np.linalg.norm(v)


def test_init_shape_centroids_prefers_trustworthy_exemplar():
    tiles = [
        _card("t1", ctx={"char": "今"}),                                  # AI=今，无 ref
        _card("t2", ctx={"char": "今"}, ref={"char": "今"}),               # AI=令 ref=今：可信锚点
        _card("t3", ctx={"char": "令"}, ref={"char": "令"}),               # 可信锚点
    ]
    emb = np.stack([_emb2(1, 0.1), _emb2(1, 0.2), _emb2(-1, 0.2)])
    seeded = _init_shape_centroids(tiles, emb, {"今", "令"}, 2)
    assert seeded is not None
    c, used = seeded
    assert c.shape == (2, 2) and used == ["今", "令"]
    # 今簇种子应该是 t2（可信锚点），不是 t1
    assert np.allclose(c[0], emb[1])


def test_init_shape_centroids_not_enough_seeds_returns_none():
    tiles = [_card("t1", ctx={"char": "今"})]
    emb = np.stack([_emb2(1, 0)])
    assert _init_shape_centroids(tiles, emb, {"今", "令"}, 2) is None


def test_spherical_kmeans_separates_two_clear_blobs():
    emb = np.stack([_emb2(1, 0.05), _emb2(1, -0.05), _emb2(1, 0.02),
                    _emb2(-1, 0.05), _emb2(-1, -0.02)])
    centroids = np.stack([_emb2(1, 0), _emb2(-1, 0)])
    assign = _spherical_kmeans(emb, centroids)
    assert list(assign[:3]) == [0, 0, 0]
    assert list(assign[3:]) == [1, 1]


# ── _cluster_pool_by_shape ───────────────────────────────────────────

def _fake_embed_2d(patches):
    return np.stack(patches).astype(np.float32)


def test_cluster_pool_by_shape_no_confusable_merge_is_unclustered():
    tiles = [_card(f"t{i}", ctx={"char": "北"}) for i in range(3)]
    out = _cluster_pool_by_shape(tiles, {"北"}, get_patch=lambda t: _emb2(1, 0), embed=_fake_embed_2d)
    assert len(out) == 1 and out[0]["clustered"] is False
    assert out[0]["tiles"] == tiles


def test_cluster_pool_by_shape_no_embed_fn_falls_back_to_label_split():
    """CNN 不可用时退到「按首选字拆」——不能比 group=char 更差（两字糊成一组）。"""
    tiles = [_card("t1", ctx={"char": "今"}), _card("t2", ctx={"char": "令"})]
    out = _cluster_pool_by_shape(tiles, {"今", "令"}, get_patch=lambda t: _emb2(1, 0), embed=None)
    assert len(out) == 2
    assert all(cl["clustered"] is False for cl in out)
    assert sum(len(cl["tiles"]) for cl in out) == len(tiles)


def test_cluster_pool_by_shape_splits_two_shapes():
    jin = [_card(f"jin{i}", ctx={"char": "今"}, ref={"char": "今"}) for i in range(4)]
    ling = [_card(f"ling{i}", ctx={"char": "令"}, ref={"char": "令"}) for i in range(2)]
    tiles = jin + ling

    def get_patch(t):
        return _emb2(1, 0.05) if t["id"].startswith("jin") else _emb2(-1, 0.05)

    out = _cluster_pool_by_shape(tiles, {"今", "令"}, get_patch=get_patch, embed=_fake_embed_2d)
    assert sum(cl["clustered"] for cl in out) == len(out)   # 全部真聚类出来的
    assert sum(len(cl["tiles"]) for cl in out) == len(tiles)   # 格数不丢
    sizes = sorted(len(cl["tiles"]) for cl in out)
    assert sizes == [2, 4]


def test_cluster_pool_by_shape_missing_image_not_dropped():
    """算不出图的格塞进最大簇，不能凭空消失（验收标准：组内格数之和＝待审总数）。"""
    tiles = [_card("jin1", ctx={"char": "今"}, ref={"char": "今"}),
            _card("jin2", ctx={"char": "今"}, ref={"char": "今"}),
            _card("ling1", ctx={"char": "令"}, ref={"char": "令"}),
            _card("nogfx", ctx={"char": "今"})]   # 这格没图

    def get_patch(t):
        if t["id"] == "nogfx":
            return None
        return _emb2(1, 0.05) if t["id"].startswith("jin") else _emb2(-1, 0.05)

    out = _cluster_pool_by_shape(tiles, {"今", "令"}, get_patch=get_patch, embed=_fake_embed_2d)
    assert sum(len(cl["tiles"]) for cl in out) == len(tiles)
    all_ids = {t["id"] for cl in out for t in cl["tiles"]}
    assert all_ids == {t["id"] for t in tiles}


def test_cluster_pool_by_shape_over_embed_cap_falls_back_to_label_split():
    tiles = [_card(f"t{i}", ctx={"char": "今" if i % 2 else "令"}) for i in range(5)]
    out = _cluster_pool_by_shape(tiles, {"今", "令"}, get_patch=lambda t: _emb2(1, 0),
                                 embed=_fake_embed_2d, max_embed=3)
    assert all(cl["clustered"] is False for cl in out)
    assert sum(len(cl["tiles"]) for cl in out) == len(tiles)


def test_cluster_pool_by_shape_missing_image_goes_to_its_own_label_cluster():
    """缺图格塞进**它自己首选字**对应的簇，不是随便塞最大簇——否则会把
    「令」的缺图格污染进「今」簇的多数票统计。"""
    tiles = [_card("jin1", ctx={"char": "今"}, ref={"char": "今"}),
            _card("jin2", ctx={"char": "今"}, ref={"char": "今"}),
            _card("jin3", ctx={"char": "今"}, ref={"char": "今"}),
            _card("ling1", ctx={"char": "令"}, ref={"char": "令"}),
            _card("lingx", ctx={"char": "令"})]   # 令，缺图

    def get_patch(t):
        if t["id"] == "lingx":
            return None
        return _emb2(1, 0.05) if t["id"].startswith("jin") else _emb2(-1, 0.05)

    out = _cluster_pool_by_shape(tiles, {"今", "令"}, get_patch=get_patch, embed=_fake_embed_2d)
    ling_cluster = next(cl for cl in out if any(t["id"] == "ling1" for t in cl["tiles"]))
    assert any(t["id"] == "lingx" for t in ling_cluster["tiles"])


# ── _build_shape_groups（端到端装配，仍是纯函数）─────────────────────

def test_build_shape_groups_sum_equals_total():
    cs = [_card("b:1:1:1", ctx={"char": "北"}),
          _card("b:1:1:2", ctx={"char": "南"}),
          _card("b:1:1:3")]   # 无证据 → unresolved
    groups = _build_shape_groups(cs, 60, get_patch=lambda t: None, embed=None)
    assert sum(g["n"] for g in groups) == len(cs)


def test_build_shape_groups_merges_and_splits_pool():
    jin = [_card(f"jin{i}", ctx={"char": "今"}, ref={"char": "今"}) for i in range(4)]
    ling = [_card(f"ling{i}", ctx={"char": "令"}, ref={"char": "令"}) for i in range(2)]
    cs = jin + ling

    def get_patch(t):
        return _emb2(1, 0.05) if t["id"].startswith("jin") else _emb2(-1, 0.05)

    import open_guji_cv.console.routers.review as rv
    orig = rv.load_pairs
    rv.load_pairs = lambda: _PAIRS
    try:
        groups = _build_shape_groups(cs, 60, get_patch=get_patch, embed=_fake_embed_2d)
    finally:
        rv.load_pairs = orig

    assert sum(g["n"] for g in groups) == len(cs)
    assert {g["pool"] for g in groups} == {"今+令"}
    chars = set(g["char"] for g in groups)
    assert chars == {"令", "今"}
    for g in groups:
        assert g["clustered"] is True
        assert g["purity"] == 1.0
        assert g["char"] in g["candidates"]


def test_build_shape_groups_no_cnn_still_splits_confusable_pool():
    """回归：CNN 不可用时，形近对合并的池必须仍然拆成各字一组——早先一版实现
    在这种情况下把 今/令 糊成一组，比 group=char（本就分开两组）还倒退。"""
    cs = [_card(f"jin{i}", ctx={"char": "今"}) for i in range(3)]
    cs += [_card(f"ling{i}", ctx={"char": "令"}) for i in range(2)]

    import open_guji_cv.console.routers.review as rv
    orig = rv.load_pairs
    rv.load_pairs = lambda: _PAIRS
    try:
        groups = _build_shape_groups(cs, 60, get_patch=lambda t: None, embed=None)
    finally:
        rv.load_pairs = orig

    assert sum(g["n"] for g in groups) == len(cs)
    assert {g["char"] for g in groups} == {"今", "令"}
    assert all(g["clustered"] is False for g in groups)


def test_build_shape_groups_ai_and_ref_majority_reported():
    tiles = [_card(f"t{i}", ctx={"char": "今"}, ref={"char": "令"}) for i in range(3)]
    tiles += [_card("t4", ctx={"char": "今"}, ref={"char": "今"})]
    groups = _build_shape_groups(tiles, 60, get_patch=lambda t: None, embed=None)
    assert len(groups) == 1
    g = groups[0]
    assert g["ai_majority"] == {"char": "今", "n": 4}
    assert g["ref_majority"] == {"char": "令", "n": 3}
    assert g["char"] == "令"        # 取整理本对齐字多数票，不取 AI 首选
    assert g["purity"] == 0.75


# ── cards_by_shape（薄装配层）────────────────────────────────────────

class FakeStore:
    def read(self, book, step_id, key, kind_id):
        return None


def test_cards_by_shape_empty_book_shape(keben_book):
    out = cards_by_shape("keben", "1", "review", FakeStore(),
                         gate_cut=False, skip_decided=False, sample_limit=60)
    assert out["book"] == "keben"
    assert out["mode"] == "shape"
    assert out["n_total"] == 0
    assert out["groups"] == []
    assert "cluster_ready" in out
