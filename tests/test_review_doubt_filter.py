# -*- coding: utf-8 -*-
"""待审卡按 doubt 码筛选（overview#215）：`cards(doubt=…)` 与 `/api/review/cards?doubt=…`。

产物自己造（`PageAdmit` 直接构造），不扫真书。三条要守的：
不传 `doubt` 时响应与改前逐字节一致；计数不受 `limit` 截断；缓存键带上新参数。
"""
from __future__ import annotations


import pytest

import open_guji_cv.steps  # noqa: F401  注册产物种类


def _rec(cid, slot, doubts, *, admit=False, char="之", evidence=None):
    from open_guji_cv.products.kinds.recog import AdmitRec
    return AdmitRec(id=cid, slot=slot, admit=admit, char=char, doubts=doubts,
                    evidence=evidence or {})


@pytest.fixture
def env(ws, tmp_path, monkeypatch):
    """keben 两页待审卡：各种 doubt 码组合 + 一张自动档 + 一张排除名单。"""
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.products.kinds.recog import ColumnAdmit, PageAdmit
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.review import cards as C
    fb = tmp_path / "fb"
    (fb / "events").mkdir(parents=True)
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(fb))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(tmp_path / "products"))
    st = ProductStore(tmp_path / "products")
    occ = {"occluded": {"via": "coord", "ref_blank": False}}
    p1 = [
        _rec("keben:1:1:1", 1, ["occluded"], char="天", evidence=occ),
        _rec("keben:1:1:2", 2, ["channel_off", "库里没有这个字"]),
        _rec("keben:1:1:3", 3, ["replace_form"]),
        _rec("keben:1:1:4", 4, ["库 unsure(cov=0.123)"]),        # 只有中文说明 → _none
        _rec("keben:1:1:5", 5, [], admit=True),                   # 自动档，only=review 不出
        _rec("keben:1:1:6", 6, ["excluded"]),                     # 排除名单，不出也不计
    ]
    p2 = [
        _rec("keben:2:1:1", 1, ["channel_off", "variant_indirect"]),
        _rec("keben:2:1:2", 2, ["occluded"], char=None,
             evidence={"occluded": {"via": "coord", "ref_blank": True}}),
        _rec("keben:2:1:3", 3, ["solo_confusable"]),
    ]
    for pg, recs in ((1, p1), (2, p2)):
        st.write("keben", "seed_admit", page_key(pg),
                 {"seed_admit": PageAdmit(page=pg, columns=[ColumnAdmit(col=1, chars=recs)])})
    C.clear_cards_cache()
    yield st
    C.clear_cards_cache()


def _ids(res):
    return [c["id"] for c in res["cards"]]


# ── 语法 ────────────────────────────────────────────────────────────

def test_parse_doubt_filter():
    from open_guji_cv.review.cards import parse_doubt_filter
    assert parse_doubt_filter("") is None and parse_doubt_filter("  ") is None
    assert parse_doubt_filter("*") == frozenset() == parse_doubt_filter("all")
    assert parse_doubt_filter("occluded, channel_off") == {"occluded", "channel_off"}
    assert parse_doubt_filter("occluded，_none") == {"occluded", "_none"}
    with pytest.raises(ValueError):
        parse_doubt_filter("库里没有这个字")


def test_doubt_codes_skips_prose():
    from open_guji_cv.review.cards import doubt_codes
    assert doubt_codes(["channel_off", "库 unsure(cov=0.1)", "护栏:x", "occluded"]) == \
        ["channel_off", "occluded"]
    assert doubt_codes(None) == []


# ── cards() ─────────────────────────────────────────────────────────

def test_no_doubt_param_unchanged(env):
    """不传 doubt：没有计数字段，出卡与原先一致（遮挡卡排最前）。"""
    from open_guji_cv.review.cards import cards
    res = cards("keben", "1-2", 400, "review", env, gate_cut=False, skip_decided=False)
    assert "doubt_counts" not in res and "doubt_total" not in res
    assert _ids(res) == ["keben:1:1:1", "keben:2:1:2", "keben:1:1:2", "keben:1:1:3",
                         "keben:1:1:4", "keben:2:1:1", "keben:2:1:3"]


def test_counts_and_filter(env):
    from open_guji_cv.review.cards import cards
    allr = cards("keben", "1-2", 400, "review", env, gate_cut=False, skip_decided=False,
                 doubt="*")
    base = cards("keben", "1-2", 400, "review", env, gate_cut=False, skip_decided=False)
    assert allr["cards"] == base["cards"]                   # `*` 不筛
    assert allr["doubt_total"] == 7
    assert allr["doubt_counts"] == {"channel_off": 2, "occluded": 2, "_none": 1,
                                    "replace_form": 1, "solo_confusable": 1,
                                    "variant_indirect": 1}
    occ = cards("keben", "1-2", 400, "review", env, gate_cut=False, skip_decided=False,
                doubt="occluded")
    assert _ids(occ) == ["keben:1:1:1", "keben:2:1:2"]
    assert occ["doubt_counts"] == allr["doubt_counts"]      # 计数是筛之前的
    assert occ["cards"][0]["occluded"] == {"char": "天", "via": "coord", "ref_blank": False}
    two = cards("keben", "1-2", 400, "review", env, gate_cut=False, skip_decided=False,
                doubt="replace_form,_none")
    assert _ids(two) == ["keben:1:1:3", "keben:1:1:4"]


def test_counts_not_truncated_by_limit(env):
    """limit=1：卡只出 1 张，但计数数到页范围末尾。"""
    from open_guji_cv.review.cards import cards
    res = cards("keben", "1-2", 1, "review", env, gate_cut=False, skip_decided=False,
                doubt="channel_off")
    assert _ids(res) == ["keben:1:1:2"] and res["truncated"] is True
    assert res["doubt_counts"]["channel_off"] == 2 and res["doubt_total"] == 7
    # 不计数时 limit 行为照旧：提前返回
    old = cards("keben", "1-2", 1, "review", env, gate_cut=False, skip_decided=False)
    assert old["truncated"] is True and len(old["cards"]) == 1


# ── 路由 ────────────────────────────────────────────────────────────


