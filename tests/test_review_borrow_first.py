# -*- coding: utf-8 -*-
"""借库书人审卡「AI 首选」改 CNN 原型（任务书-C-借库书人审首选改CNN原型，2026-09-27）。

`review/borrow_first.py` 的融合/标注/排序都是纯函数，直接喂数测；接线处
（`cards._finish`、路由 `_top_pick`、按字种组内排序）用假书配置与卡片字典测，
不连真工作区。**开关缺省关**这一条是验收要点：没写 `params.review` 的书，
`_finish` 必须原样返回同一个对象、不多任何键。
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from open_guji_cv.console.routers.review import (_build_char_groups,
                                                   _top_pick)
from open_guji_cv.review import borrow_first as bf
from open_guji_cv.review import cards as cards_mod


def _bk(params=None):
    return SimpleNamespace(params=params or {})


# ── 开关 ───────────────────────────────────────────────────────────

def test_mode_default_off():
    assert bf.first_pick_mode(_bk()) is None
    assert bf.first_pick_mode(_bk({"glyph_match": {"x": 1}})) is None
    assert bf.first_pick_mode(_bk({"review": {"first_pick": "off"}})) is None
    assert bf.first_pick_mode(SimpleNamespace()) is None     # 老 BookSpec 没 params 属性


@pytest.mark.parametrize("m", ["cnn", "rrf"])
def test_mode_on(m):
    assert bf.first_pick_mode(_bk({"review": {"first_pick": m}})) == m


def test_mode_typo_raises():
    """写错了不能静默当关——以为开着、审卡照旧给像素首选，正是要修的错。"""
    with pytest.raises(ValueError):
        bf.first_pick_mode(_bk({"review": {"first_pick": "CNN原型"}}))


def test_review_db_path_prefers_book_glyph_match(monkeypatch):
    assert bf.review_db_path(_bk({"glyph_match": {"db_path": "/x/siku.db"}})) == "/x/siku.db"
    monkeypatch.setenv("GUJI_GLYPH_DB", "/y/env.db")
    assert bf.review_db_path(_bk()) == "/y/env.db"


# ── 融合与首选 ─────────────────────────────────────────────────────

def test_rrf_both_lists_agree():
    assert bf.rrf_fuse([("以", .9), ("取", .8)], [("以", .7), ("取", .6)])[0][0] == "以"


def test_rrf_tie_goes_to_cnn():
    """两路首位不同、互不出现在对方列表：分数相同，CNN 名次靠前的赢。"""
    fused = bf.rrf_fuse([("取", .95)], [("以", .8)])
    assert fused[0][0] == "以"
    assert fused[0][1] == fused[1][1]


def test_rrf_pixel_wins_when_cnn_second_agrees():
    """像素首位 = CNN 次位，CNN 首位像素没列：像素首位两路都有分，胜出。"""
    fused = bf.rrf_fuse([("令", .9)], [("今", .8), ("令", .7)])
    assert fused[0][0] == "令"


def test_rrf_duplicate_char_takes_best_rank():
    fused = dict(bf.rrf_fuse([("之", .9), ("之", .8), ("乏", .7)], []))
    assert fused["之"] == pytest.approx(1 / 61, abs=1e-6)
    assert fused["乏"] == pytest.approx(1 / 63, abs=1e-6)


def test_pick_first_cnn_falls_back_to_pixel():
    assert bf.pick_first([("取", .9)], [("以", .8)], "cnn") == "以"
    assert bf.pick_first([("取", .9)], [], "cnn") == "取"
    assert bf.pick_first([], [], "cnn") is None
    assert bf.pick_first([], [], "rrf") is None
    with pytest.raises(ValueError):
        bf.pick_first([], [], "vote")


def test_first_view_agree_flags():
    v = bf.first_view([("以", .9)], [("以", .8), ("取", .1)], "rrf")
    assert v == {"char": "以", "mode": "rrf", "pixel": "以", "cnn": "以", "agree": True,
                 "cnn_candidates": [["以", 0.8], ["取", 0.1]], "proto_src": None}
    assert bf.first_view([("取", .9)], [("以", .8)], "cnn")["agree"] is False
    assert bf.first_view([], [("以", .8)], "cnn")["agree"] is None
    assert bf.first_view([("以", .9)], [], "cnn")["agree"] is None


def test_sort_disagree_first_stable():
    cs = [{"id": "a", "first": {"agree": True}}, {"id": "b", "first": {"agree": False}},
          {"id": "c", "first": {"agree": None}}, {"id": "d", "first": {"agree": True}},
          {"id": "e", "first": {"agree": False}}]
    assert [c["id"] for c in bf.sort_disagree_first(cs)] == ["b", "c", "e", "a", "d"]


# ── 原型索引 ─────────────────────────────────────────────────────────

def test_build_protos_mean_then_unit():
    """均值原型＝各例 embedding 求均值再单位化（与 R 的 a5_cnn.py 同口径），分块不改结果。"""
    vec = {1: np.array([1.0, 0.0]), 2: np.array([0.0, 1.0]), 3: np.array([3.0, 4.0])}

    def fake_embed(imgs):
        return np.stack([vec[int(im[0, 0])] for im in imgs])

    im = lambda v: np.full((64, 64), v, np.uint8)   # noqa: E731
    chars, mat = bf.build_protos({"甲": [im(1), im(2)], "乙": [im(3)], "丙": []},
                                 fake_embed, chunk=1)
    assert chars == ["乙", "甲"]           # 空字丢掉、字表排序
    assert np.allclose(mat[1], [np.sqrt(.5), np.sqrt(.5)], atol=1e-6)
    assert np.allclose(mat[0], [.6, .8], atol=1e-6)


def test_rank_protos_topk_order():
    P = np.array([[1, 0], [0, 1], [.6, .8]], np.float32)
    got = bf.rank_protos(np.array([[0, 1], [1, 0]], np.float32), ["甲", "乙", "丙"], P, k=2)
    assert [c for c, _ in got[0]] == ["乙", "丙"]
    assert [c for c, _ in got[1]] == ["甲", "丙"]
    assert bf.rank_protos(np.zeros((1, 2), np.float32), [], np.zeros((0, 2)), k=2) == [[]]


def test_cnn_ranks_missing_patch_gives_empty(monkeypatch):
    """缺图（None）的卡给空 CNN 候选；CNN 不可用时全空，不报错。"""
    class Off:
        available = False
    assert bf.cnn_ranks_for_patches([None, np.zeros((64, 64), np.uint8)], "x.db", Off()) == [[], []]

    class On:
        available = True
        ckpt = "ck"

        def embed(self, imgs):
            return np.tile(np.array([[1.0, 0.0]], np.float32), (len(imgs), 1))
    monkeypatch.setattr(bf.ProtoIndex, "get",
                        classmethod(lambda cls, db, cnn: (["甲", "乙"], np.eye(2, dtype=np.float32))))
    got = bf.cnn_ranks_for_patches([None, np.zeros((64, 64), np.uint8)], "x.db", On(), k=1)
    assert got[0] == [] and got[1][0][0] == "甲"


# ── 接线：cards._finish ────────────────────────────────────────────

def _res():
    return {"book": "b", "cards": [
        {"id": "b:1:1:1", "db": {"candidates": [["以", .9]]}},
        {"id": "b:1:1:2", "db": {"candidates": [["取", .9]]}},
    ], "truncated": False, "blocked": [], "n_decided": 0}


def test_finish_off_is_identity(monkeypatch):
    """开关关（四庫、北行）：原样返回同一个对象，不挂 first、不排序、不碰 CNN。"""
    def boom(*a, **k):
        raise AssertionError("开关关时不许调 annotate")
    monkeypatch.setattr(cards_mod, "annotate", boom)
    r = _res()
    snap = repr(r)
    out = cards_mod._finish("b", _bk(), None, r)
    assert out is r and repr(out) == snap


def test_finish_on_annotates_and_sorts(monkeypatch):
    def fake_annotate(book, cs, st, mode, bk=None):
        for c, cnn in zip(cs, (["以"], ["以"])):
            c["first"] = bf.first_view([tuple(x) for x in c["db"]["candidates"]],
                                       [(ch, .8) for ch in cnn], mode)
        return {"mode": mode, "n": len(cs)}
    monkeypatch.setattr(cards_mod, "annotate", fake_annotate)
    out = cards_mod._finish("b", _bk({"review": {"first_pick": "cnn"}}), None, _res())
    assert out["first_pick"]["mode"] == "cnn"
    assert [c["id"] for c in out["cards"]] == ["b:1:1:2", "b:1:1:1"]   # 不一致的排前
    assert out["cards"][0]["first"]["char"] == "以"


# ── 接线：按字种批审 ────────────────────────────────────────────────

def _card(id_, first=None, ctx=None, cov=0.5):
    c = {"id": id_, "page": 1, "col": 1, "slot": 1, "sub": "", "ref": None,
         "db": {"verdict": "unsure", "cov": cov, "candidates": [["取", cov]]},
         "ocr": [], "ctx": ctx, "groups": None, "ai": None}
    if first is not None:
        c["first"] = first
    return c


def test_top_pick_uses_first_before_ctx():
    c = _card("a", first={"char": "以", "agree": False}, ctx={"char": "取"})
    assert _top_pick(c) == "以"
    assert _top_pick(_card("b", ctx={"char": "取"})) == "取"       # 没开关：原链


def test_top_pick_ai_still_wins_over_first():
    c = _card("a", first={"char": "以", "agree": False})
    c["groups"] = [{"id": "A", "members": ["北"], "why": ""}]
    c["ai"] = {"rank": [{"group": "A", "p": .9, "why": ""}]}
    assert _top_pick(c) == "北"


def test_char_groups_disagree_tiles_first():
    cs = [_card("a", {"char": "以", "agree": True}, cov=.1),
          _card("b", {"char": "以", "agree": False}, cov=.9),
          _card("c", {"char": "以", "agree": True}, cov=.05)]
    g = _build_char_groups(cs, 60)
    assert len(g) == 1 and g[0]["char"] == "以"
    assert [t["id"] for t in g[0]["tiles"]] == ["b", "c", "a"]


def test_char_groups_without_first_unchanged_order():
    cs = [_card("a", cov=.3), _card("b", cov=.1), _card("c", cov=.2)]
    assert [t["id"] for t in _build_char_groups(cs, 60)[0]["tiles"]] == ["b", "c", "a"]


# ── 原型来源可切换（用户 09-27 22:20Z：借库只作冷启动）──────────────────

def _ix(chars, vecs):
    return list(chars), np.array(vecs, np.float32)


def test_sources_default_borrow_only():
    assert bf.proto_sources(_bk({"review": {"first_pick": "cnn"}})) == (None, True)


def test_sources_own_relative_to_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path))
    own, fb = bf.proto_sources(_bk({"review": {"own_db": "output/own.db", "borrow_fallback": False}}))
    assert own == str(tmp_path / "output/own.db") and fb is False


def test_sources_bad_config_raises():
    with pytest.raises(ValueError):
        bf.proto_sources(_bk({"review": {"borrow_fallback": False}}))     # 一个原型都没有
    with pytest.raises(ValueError):
        bf.proto_sources(_bk({"review": {"own_db": "x", "borrow_fallback": "no"}}))


def test_merge_own_first_then_fallback():
    own = _ix(["以", "令"], [[1, 0], [0, 1]])
    bor = _ix(["以", "取", "今"], [[0, 1], [1, 1], [1, -1]])
    chars, mat, src = bf.merge_protos(own, bor, True)
    assert chars == ["以", "令", "取", "今"]
    assert src == ["own", "own", "borrow", "borrow"]
    assert np.allclose(mat[0], [1, 0])          # 「以」用本书刻例，不是借库那条


def test_merge_no_fallback_drops_missing():
    chars, _, src = bf.merge_protos(_ix(["以"], [[1, 0]]), _ix(["取"], [[0, 1]]), False)
    assert chars == ["以"] and src == ["own"]


def test_merge_no_own_is_borrow():
    chars, _, src = bf.merge_protos(None, _ix(["取"], [[0, 1]]), True)
    assert chars == ["取"] and src == ["borrow"]
    chars, mat, _ = bf.merge_protos(None, None, True)
    assert chars == [] and mat.shape[0] == 0


def test_load_index_missing_own_file_falls_back(monkeypatch, tmp_path):
    """本书库文件还不存在（H 没建）：当空库，全走借库，不报错。"""
    monkeypatch.setattr(bf.ProtoIndex, "get",
                        classmethod(lambda cls, db, cnn: _ix(["取"], [[0, 1]])))
    chars, _, src = bf.load_index("borrow.db", object(), str(tmp_path / "nope.db"), True)
    assert chars == ["取"] and src == {"取": "borrow"}


def test_first_view_proto_src():
    assert bf.first_view([], [("以", .9)], "cnn", "own")["proto_src"] == "own"
    assert bf.first_view([("以", .9)], [], "cnn", "own")["proto_src"] is None
