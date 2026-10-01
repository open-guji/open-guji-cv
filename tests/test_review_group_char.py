# -*- coding: utf-8 -*-
"""按字种批审（任务书-C-待审卡按字种批审，2026-09-27）：分组/排序是纯函数，
直接拿 `cards()` 输出形状的字典造，不需要真工作区/ProductStore——与
`test_review_ai_view.py` 同一个理由：把领域逻辑单独摆出来测，不连产物管线。
"""
from __future__ import annotations

from open_guji_cv.console.routers.review import (_build_char_groups,
                                                   _group_key, _tile_rank_score,
                                                   _top_pick, cards_by_char)


def _card(id_="b:1:1:1", page=1, char=None, ai=None, groups=None, ctx=None,
         db=None, ocr=None, ref=None, admit=False) -> dict:
    return {
        "id": id_, "page": page, "col": 1, "slot": 1, "sub": "",
        "patch": f"/api/cache/b/char_patch/{id_}.png",
        "admit": admit, "channel": None, "char": char,
        "jys": None, "ref": ref, "form": None, "doubts": [],
        "db": db, "ocr": ocr or [], "ctx": ctx, "groups": groups, "ai": ai,
    }


# ── _top_pick ───────────────────────────────────────────────────────

def test_top_pick_uses_ai_top_group_single_member():
    c = _card(groups=[{"id": "A", "members": ["北"], "why": ""}],
              ai={"rank": [{"group": "A", "p": 0.9, "why": ""}]})
    assert _top_pick(c) == "北"


def test_top_pick_ai_multi_member_takes_first():
    c = _card(groups=[{"id": "A", "members": ["强", "強"], "why": ""}],
              ai={"rank": [{"group": "A", "p": 0.9, "why": ""}]})
    assert _top_pick(c) == "强"


def test_top_pick_falls_back_to_ctx_when_no_ai():
    c = _card(ctx={"char": "器", "margin": 1.0, "source": "context"})
    assert _top_pick(c) == "器"


def test_top_pick_falls_back_to_db_candidates():
    c = _card(db={"verdict": "unsure", "cov": 0.8, "wmax": 3.0,
                  "candidates": [("旣", 0.8), ("既", 0.5)]})
    assert _top_pick(c) == "旣"


def test_top_pick_falls_back_to_ocr():
    c = _card(ocr=[("卽", 0.7)])
    assert _top_pick(c) == "卽"


def test_top_pick_none_when_no_evidence():
    assert _top_pick(_card()) is None


# ── _group_key ──────────────────────────────────────────────────────

def test_group_key_no_ref_uses_top_only():
    c = _card(ctx={"char": "北"})
    assert _group_key(c) == ("北", None)


def test_group_key_ref_matches_top_stays_together():
    c = _card(ctx={"char": "北"}, ref={"char": "北", "op": "same", "form": None})
    assert _group_key(c) == ("北", None)


def test_group_key_ref_mismatch_splits_out():
    """首选字与整理本对齐字不同 → 单独一组，不混进同字种的组。"""
    c = _card(ctx={"char": "北"}, ref={"char": "比", "op": "diff", "form": None})
    assert _group_key(c) == ("北", "比")


def test_group_key_unresolved_when_no_pick():
    assert _group_key(_card()) == ("__unresolved__", None)


# ── _tile_rank_score ────────────────────────────────────────────────

def test_tile_rank_score_no_db_is_most_suspicious():
    assert _tile_rank_score(_card()) == -1.0


def test_tile_rank_score_uses_cov():
    c = _card(db={"verdict": "unsure", "cov": 0.42, "wmax": 1.0, "candidates": []})
    assert _tile_rank_score(c) == 0.42


# ── _build_char_groups ──────────────────────────────────────────────

def test_build_char_groups_sum_equals_total():
    """验收标准：按字种分组的数量、组内格数之和等于待审总数。"""
    cs = [
        _card("b:1:1:1", page=1, ctx={"char": "北"}),
        _card("b:1:1:2", page=1, ctx={"char": "北"}),
        _card("b:2:1:1", page=2, ctx={"char": "南"}),
        _card("b:2:1:2", page=2),   # 无证据 → unresolved
    ]
    groups = _build_char_groups(cs, sample_limit=60)
    assert sum(g["n"] for g in groups) == len(cs)
    assert {g["char"] for g in groups} == {"北", "南", None}


def test_build_char_groups_mismatch_group_isolated():
    cs = [
        _card("b:1:1:1", ctx={"char": "北"}),                                    # 组 (北, None)
        _card("b:1:1:2", ctx={"char": "北"}, ref={"char": "比", "op": "diff"}),   # 组 (北, 比)
    ]
    groups = _build_char_groups(cs, sample_limit=60)
    keys = {(g["char"], g["ref_char"]) for g in groups}
    assert keys == {("北", None), ("北", "比")}
    for g in groups:
        assert g["n"] == 1   # 两组各一格，没有混在一起


def test_build_char_groups_sorted_by_size_desc():
    cs = ([_card(f"b:1:1:{i}", ctx={"char": "北"}) for i in range(3)]
          + [_card("b:1:2:1", ctx={"char": "南"})])
    groups = _build_char_groups(cs, sample_limit=60)
    assert [g["char"] for g in groups] == ["北", "南"]
    assert groups[0]["n"] == 3 and groups[1]["n"] == 1


def test_build_char_groups_sample_limit_truncates_but_n_keeps_true_count():
    cs = [_card(f"b:1:1:{i}", ctx={"char": "北"}) for i in range(5)]
    groups = _build_char_groups(cs, sample_limit=2)
    assert groups[0]["n"] == 5
    assert len(groups[0]["tiles"]) == 2
    assert groups[0]["truncated"] is True


def test_build_char_groups_pages_distribution():
    cs = [_card("b:1:1:1", page=1, ctx={"char": "北"}),
          _card("b:2:1:1", page=2, ctx={"char": "北"}),
          _card("b:2:1:2", page=2, ctx={"char": "北"})]
    groups = _build_char_groups(cs, sample_limit=60)
    assert groups[0]["pages"] == [{"page": 1, "n": 1}, {"page": 2, "n": 2}]


def test_build_char_groups_rank_least_similar_first():
    cs = [_card("b:1:1:1", ctx={"char": "北"},
                db={"verdict": "same", "cov": 0.99, "wmax": 1.0, "candidates": []}),
          _card("b:1:1:2", ctx={"char": "北"}, db=None),   # 没库命中 → 最可疑，排最前
          _card("b:1:1:3", ctx={"char": "北"},
                db={"verdict": "unsure", "cov": 0.3, "wmax": 1.0, "candidates": []})]
    groups = _build_char_groups(cs, sample_limit=60)
    ordered_ids = [t["id"] for t in groups[0]["tiles"]]
    assert ordered_ids == ["b:1:1:2", "b:1:1:3", "b:1:1:1"]


# ── cards_by_char（薄装配层）──────────────────────────────────────────

class FakeStore:
    """只需要 `cards()` 内部会调的 `.read()` 不炸；这里没有任何真产物，
    `cards()` 对每页都会因 `a is None` 直接跳过，返回空卡片列表——够测
    `cards_by_char` 的装配形状（book/mode/n_total 等字段），不测真数据。"""

    def read(self, book, step_id, key, kind_id):
        return None


def test_cards_by_char_empty_book_shape(keben_book):
    """`cards()` 本身要 `load_book()` 过（书要存在），fixture 册 `keben` 够用——
    这里只测空产物时的装配形状，不测真数据（真数据的分组行为已经在上面
    纯函数那批测过了）。"""
    out = cards_by_char("keben", "1", "review", FakeStore(),
                        gate_cut=False, skip_decided=False, sample_limit=60)
    assert out["book"] == "keben"
    assert out["mode"] == "char"
    assert out["n_total"] == 0
    assert out["groups"] == []
