"""第三步重构（2026-11-27）：3b `glyph_near`、收尾 `glyph_analyzer`、大步收尾 `finals:`、`StepSpec.enabled_by`。

全部自造数据：小 CNN 用随机权重现造（只测管道通不通、格式对不对，不测准不准）。
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from open_guji_cv.core.pipeline import expand_finals, list_pipelines, load_pipeline
from open_guji_cv.steps.glyph_analyzer import merge_cell
from open_guji_cv.steps.glyph_near import trigger_group

from helpers import make_book, make_ctx, page_chars, page_match, run_steps, write_product

GONG = {"chars": ["宫", "宮", "官"], "fold": {"宮": "宫"}, "trigger": "close", "delta": 0.03}


# ── 触发 ─────────────────────────────────────────────────────────────

def test_trigger_close_needs_rival_in_delta():
    g = {"gong": GONG}
    assert trigger_group([("宫", 0.90), ("官", 0.88)], "宫", g) == ("gong", "close")
    assert trigger_group([("宫", 0.90), ("官", 0.80)], "宫", g) is None          # 分差超 δ
    assert trigger_group([("宫", 0.90), ("宮", 0.895)], "宫", g) is None        # 异体不分，不算对手
    assert trigger_group([("言", 0.90), ("官", 0.895)], "言", g) is None        # 首位不在组里


def test_trigger_member_and_same_verdict_without_candidates():
    g = {"gong": {**GONG, "trigger": "member"}}
    assert trigger_group([("官", 0.9)], "官", g) == ("gong", "member")
    assert trigger_group([], "宮", g) == ("gong", "member")                     # same 档没有候选，看 char
    assert trigger_group([], None, g) is None


# ── 收尾合并 ─────────────────────────────────────────────────────────

class _Cal:
    merge = {"宮": "宫"}

    def calibrate(self, sims):
        return {"宫": 0.9, "官": 0.1}


def _match_rec(**kw):
    return page_match(recs=[{"slot": 1, "verdict": "unsure", **kw}]).columns[0].chars[0]


def _near_rec(sims):
    from open_guji_cv.products.kinds.read import NearMethodOut, NearRec
    return NearRec(id="tbook:1:1:1", slot=1, group="gong", trigger="close",
                   methods=[NearMethodOut(method="cnn_small:gong", sims=sims)])


def test_merge_cell_without_near_keeps_3a_order_p_none():
    r = merge_cell(_match_rec(candidates=[("官", 0.9), ("宫", 0.89), ("言", 0.5)]), None, {}, 2, "elastic")
    assert [c.char for c in r.cands] == ["官", "宫"]
    assert all(c.p is None for c in r.cands) and r.p_src == "" and r.p_map == {}
    assert r.cands[0].evidence == {"a": {"sim": 0.9, "algo": "elastic"}}


def test_merge_cell_with_near_calibrated_p_and_variant():
    rec = merge_cell(_match_rec(candidates=[("官", 0.9), ("宫", 0.89)]),
                     _near_rec({"官": 0.2, "宫": 0.8, "宮": 0.8}), {"cnn_small:gong": _Cal()}, 5, "elastic")
    by = {c.char: c for c in rec.cands}
    assert [c.char for c in rec.cands][:2] == ["宫", "官"]                      # 按 p 降序
    assert by["宫"].p == 0.9 and by["官"].p == 0.1
    assert by["宮"].p is None and by["宮"].evidence["b"]["same_as"] == "宫"     # 异体不另算概率
    assert sum(c.p for c in rec.cands if c.p is not None) == pytest.approx(1.0)
    assert by["宫"].evidence["b"] == {"group": "gong", "cnn_small:gong": 0.8}
    assert rec.p_src == "near:cnn_small:gong"


def test_merge_cell_uncalibrated_method_gives_evidence_only():
    rec = merge_cell(_match_rec(candidates=[("官", 0.9)]), _near_rec({"官": 0.3, "宫": 0.7}), {}, 5, "elastic")
    assert all(c.p is None for c in rec.cands) and rec.p_src == ""
    assert {c.char for c in rec.cands} == {"官", "宫"}


# ── 管线：收尾、缺省关 ────────────────────────────────────────────────

@pytest.mark.parametrize("pid", list_pipelines())
def test_read_final_is_last_of_read_stage(pid):
    pl = load_pipeline(pid)
    if pl.stages["read"]:
        assert pl.final_of("read") == "glyph_analyzer" == pl.stages["read"][-1]
    else:
        assert pl.final_of("read") is None


def test_final_not_last_rejected():
    sk = {"stages": {"read": ["a", "b"]}, "finals": {"read": "a"}}
    with pytest.raises(ValueError, match="最后一步"):
        expand_finals(sk, {"read": ["a", "b"]})


def test_new_steps_off_by_default(tmp_path):
    from open_guji_cv.core.engine import Engine
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore

    pl = load_pipeline("keben_body_v2")

    def enabled(book):
        e = Engine(book, pl, store=ProductStore(tmp_path / "p"), cache=ImageCache(tmp_path / "c"), log=lambda s: None)
        return e._enabled(pl.steps)

    off = enabled(make_book())
    assert "glyph_near" not in off and "glyph_analyzer" not in off and "glyph_match" in off
    on = enabled(make_book(params={"glyph_analyzer": {"enabled": True}}))
    assert "glyph_analyzer" in on and "glyph_near" not in on


# ── 端到端：随机小 CNN ────────────────────────────────────────────────

@pytest.fixture
def tiny_model(tmp_path):
    torch = pytest.importorskip("torch")
    from open_guji_cv.groups.near_methods import _small_net
    d = tmp_path / "glyph_near_gong"
    d.mkdir()
    torch.manual_seed(0)
    for k in range(2):
        torch.save(_small_net()(2).state_dict(), d / f"fold{k}.pt")
    (d / "model.json").write_text(json.dumps({"format": "near-cnn/1", "classes": ["官", "宫"], "merge": {"宮": "宫"},
                                              "folds": ["fold0.pt", "fold1.pt"], "fold_by": "vol_mod"}), encoding="utf-8")
    (d / "calib.json").write_text(json.dumps({"format": "near-calib/1", "knots": {"宫": [[0, 1], [0.1, 0.9]]}}),
                                  encoding="utf-8")
    return d


def test_glyph_near_and_analyzer_end_to_end(tmp_path, tiny_model):
    from open_guji_cv.groups.near_methods import load_method


    groups = {"gong": {**GONG, "methods": {"cnn_small": str(tiny_model)}}}
    book = make_book("vol07", params={"glyph_near": {"groups": groups}, "glyph_analyzer": {"enabled": True}})
    img = np.full((400, 300), 255, np.uint8)
    img[50:120, 200:260] = 0
    ctx = make_ctx(tmp_path, book, raw={1: img})
    write_product(ctx, "glyph_match", 1, glyph_match=page_match(book="vol07", recs=[
        {"slot": 1, "verdict": "unsure", "candidates": [("宫", 0.90), ("官", 0.89)]},
        {"slot": 2, "verdict": "same", "char": "言", "cov": 0.95}]))
    write_product(ctx, "cell_shrink", 1, char_index=page_chars(book="vol07", recs=[
        {"slot": 1, "bbox_page": (30.0, 40.0, 110.0, 130.0)}, {"slot": 2, "bbox_page": (30.0, 140.0, 110.0, 230.0)}]))

    out = run_steps(ctx, 1, ["glyph_near", "glyph_analyzer"])
    near = out["glyph_near"].by_id()
    assert list(near) == ["vol07:1:1:1"]                                        # 只有触发的格
    mo = near["vol07:1:1:1"].methods[0]
    assert mo.method == "cnn_small:gong" and mo.evidence == {"fold": "fold1"}  # 册号 7 % 2 折
    assert mo.sims["宮"] == mo.sims["宫"] and mo.sims["宫"] + mo.sims["官"] == pytest.approx(1, abs=1e-3)
    assert out["glyph_near"].methods_sha.startswith("gong:cnn_small=")

    fin = out["glyph_analyzer"].by_id()
    a, b = fin["vol07:1:1:1"], fin["vol07:1:1:2"]
    assert a.p_src == "near:cnn_small:gong"
    want = load_method("cnn_small", str(tiny_model)).calibrate(mo.sims)
    assert {c.char: c.p for c in a.cands if c.p is not None} == want
    assert b.cands[0].char == "言" and b.cands[0].p is None and b.p_src == ""
