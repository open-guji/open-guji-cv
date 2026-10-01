# -*- coding: utf-8 -*-
"""L3 补标签两批（review/label_batches.py）：抽样、批次落盘、收割、旧卡迁移。全部自造数据。"""
from __future__ import annotations

import json

import numpy as np
import pytest

from open_guji_cv.errors import ProductMissing
from open_guji_cv.feedback.events import EventTarget, make_event
from open_guji_cv.gold.store import GoldStore
from open_guji_cv.products.kinds.cells import CellRec, ColumnCells, CutPointCandidates, PageCells, SeamCandidate
from open_guji_cv.products.kinds.columns import BorderTrim, ColumnTriage, ColumnWindowRec, PageWindows
from open_guji_cv.review import label_batches as LB


# ── 抽样 ─────────────────────────────────────────────────────────────

def test_allocate_floor_total_and_small_strata():
    pops = {"a": 1000, "b": 100, "c": 3}
    out = LB.allocate(pops, 60, floor=6)
    assert out["c"] == 3                       # 小层全取
    assert out["b"] >= 6 and out["a"] >= 6
    assert sum(out.values()) == 60


def test_allocate_tier_shortfall_backfill_stays_within_population():
    # 一档的总体撑不满配额 → 缺口全局回填，任何层的 n_h 都不许超过 N_h（真产物冒烟时踩到的）
    pops = {"a|hard": 2, "b|mid": 3, "c|easy": 40}
    out = LB.allocate(pops, 30, floor=6, tier_of={"a|hard": "hard", "b|mid": "mid", "c|easy": "easy"},
                      tier_share={"hard": 0.5, "mid": 0.3, "easy": 0.2})
    assert all(out[k] <= pops[k] for k in out) and sum(out.values()) == 30


def test_allocate_never_exceeds_population():
    assert sum(LB.allocate({"a": 5, "b": 4}, 200).values()) == 9


def test_allocate_tiers_oversample_hard():
    pops = {"x|hard": 50, "y|easy": 5000}
    out = LB.allocate(pops, 100, floor=4, tier_of={"x|hard": "hard", "y|easy": "easy"},
                      tier_share={"hard": 0.4, "easy": 0.6})
    assert out["x|hard"] == 40 and out["y|easy"] == 60


def test_stratified_sample_weights_unbiased_and_deterministic():
    pool = {"s1": [{"i": i} for i in range(100)], "s2": [{"i": 1000 + i} for i in range(10)]}
    a, table = LB.stratified_sample(pool, 30, seed=7, floor=5)
    b, _ = LB.stratified_sample(pool, 30, seed=7, floor=5)
    assert a == b                              # 同 seed 同结果
    # Horvitz–Thompson：Σ 权重 = 总体数
    assert sum(w for _s, _x, w in a) == pytest.approx(110, rel=1e-3)
    assert all(table[k]["weight"] == pytest.approx(table[k]["N"] / table[k]["n"], rel=1e-3) for k in table)


# ── 列端类别映射 ─────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,new,legacy", [
    ("clean", "trim", "clean"), ("glued", "glued", None), ("none", "none", None),
    ("idk", "idk", None), ("trim", "trim", None), ("double", "double", None), ("???", None, "???")])
def test_map_end_class(raw, new, legacy):
    assert LB.map_end_class(raw) == (new, legacy)


def test_end_difficulty_and_fingerprint():
    assert LB.end_difficulty("b", "glued") == "hard"
    assert LB.end_difficulty("a2", "none") == "hard"          # 多层
    assert LB.end_difficulty("a", "none") == "easy"
    img = np.zeros((220, 40), np.uint8)
    img[:5] = 255
    fp = LB.end_fingerprint(img)
    assert fp == LB.end_fingerprint(img.copy()) and fp != LB.end_fingerprint(np.zeros_like(img))


# ── 没有产物要清楚报错 ───────────────────────────────────────────────

class _Store:
    """只会 read 的假产物库：{(step, page_key, kind): obj}。"""
    def __init__(self, data=None):
        self.data = data or {}

    def read(self, book, step, pk, kind):
        return self.data.get((step, pk, kind))

    def manifest(self, book, step):
        return None


def test_need_products_raises_clear_error():
    with pytest.raises(ProductMissing) as ei:
        LB._need_products(_Store(), "tbook", "row_segment", "cells", [1, 2])
    assert "现行" in str(ei.value) and "row_segment" in str(ei.value)


# ── 总体构造 ─────────────────────────────────────────────────────────

def _cell(slot, kind="char", y0=0.0):
    return CellRec(slot=slot, pos=slot, y0=y0, y1=y0 + 10, x0=0, x1=10, kind=kind, order=slot)


def test_cutline_population_strata_and_exclusion():
    cells = [_cell(i, y0=i * 10.0) for i in range(1, 6)]
    cells[2] = _cell(3, kind="blank", y0=20.0)
    cp_hard = CutPointCandidates(k=1, y=10, slot_above=1, slot_below=2, chosen=0, escalate=True,
                                 candidates=[SeamCandidate(kind="straight", dis_unet=150, agree=0.3)])
    cp_mid = CutPointCandidates(k=4, y=40, slot_above=4, slot_below=5, chosen=0,
                                candidates=[SeamCandidate(kind="straight"), SeamCandidate(kind="unet_seam")])
    col = ColumnCells(col=1, ok=True, n_body_slots=5, cells=cells, cut_candidates=[cp_hard, cp_mid])
    store = _Store({("row_segment", "p0001", "cells"): PageCells(page=1, period=10, ref_w=10, columns=[col])})
    pool, meta = LB.cutline_population(store, "tbook", [1], exclude_ids={"tbook:1:1:4"})
    ids = {it["id"]: k for k, v in pool.items() for it in v}
    # slot2→3 / 3→4 含 blank 不出；4→5 已在金标被排除；只剩 1→2
    assert ids == {"tbook:1:1:1": "tail|hard"} or ids == {"tbook:1:1:1": "body|hard"}
    assert meta["skipped"]["already_gold"] == 1 and meta["skipped"]["blank"] == 2


def test_column_end_population_strata():
    mk = lambda c, tcls, bcls, tcase, bcase: ColumnWindowRec.model_construct(
        col=c, raised=False, trim_top=BorderTrim(px=3, case=tcase), trim_bottom=BorderTrim(px=0, case=bcase),
        triage=ColumnTriage(side_class="clean", top_class=tcls, bot_class=bcls))
    wins = PageWindows.model_construct(page=1, page_size=(1000, 1500), columns=[
        mk(1, "none", "glued", "a", "b"), mk(2, "clean", "idk", "d2", "e")])
    pool, meta = LB.column_end_population(_Store({("column_warp", "p0001", "column_windows"): wins}), "tbook", [1])
    assert meta["n_population"] == 4
    assert set(pool) == {"a|none", "b|glued", "d2|clean", "e|idk"}
    assert pool["b|glued"][0]["id"] == "colborder:tbook:1:1:bot"


# ── 收割 ─────────────────────────────────────────────────────────────

def _ev(batch, seq, kind, key, payload, fp="fp-click"):
    t = EventTarget(step="row_segment", unit="cell", key=key,
                    anchor={"product_key": {"step": "row_segment", "key": "p0001", "fingerprint": fp}})
    return make_event(batch, seq, kind, t, payload)


def _cut_card(cid="tbook:1:1:4", **kw):
    return {"id": cid, "book": "tbook", "page": 1, "col": 1, "slot_above": 4, "slot_below": 5,
            "ctx": "body", "diff": "hard", "n_cand": 2, "dis_unet": 99, "agree": 0.4,
            "chosen_kind": "straight", "stratum": "body|hard", "stratum_weight": 3.5, "page_w": 1000,
            "geom_sig": "g0", "bbox": [10, 20, 30, 40], "y_engine": 41.0,
            "product_key": {"step": "row_segment", "key": "p0001", "fingerprint": "fp-gen"}, **kw}


def test_harvest_cutline_page_coords_weights_and_no_overwrite(tmp_path):
    ds = GoldStore(tmp_path / "ds")
    cards = [_cut_card(), _cut_card("tbook:1:1:9"), _cut_card("tbook:1:1:11")]
    evs = [
        _ev("b", 1, "cutline", "tbook:1:1:4", {"verdict": "moved", "y": 40, "y_old": 41, "col_h": 1400,
                                                "page_x": 100.0, "page_y": 500.5, "geom_sig": "g0",
                                                "picked_source": "unet"}),
        _ev("b", 2, "cutline", "tbook:1:1:9", {"verdict": "idk", "y": 10}),
        _ev("b", 3, "cutline", "tbook:1:1:11", {"verdict": "ok", "y": 10}),        # 没页面坐标
        _ev("b", 4, "cutline", "tbook:9:9:9", {"verdict": "ok", "y": 10}),         # 不在批里
    ]
    out = LB.harvest_cutline("b", evs, cards, dataset=ds)
    assert out["n_added"] == 3 and out["skipped"] == {"not_in_batch": 1, "no_page_coords": 1}
    it = ds.get(LB.CUTLINE_SHARD, "tbook:1:1:4")
    assert it.expected["page_x_tr"] == 1000 - 1 - 100.0 and it.expected["page_y"] == 500.5   # 左上 → 右上原点
    assert it.anchor.space == LB.SPACE_TR and it.anchor.bbox == (10, 20, 30, 40)
    assert it.stratum_weight == 3.5 and it.input["source"] == "L3-batch" and it.input["fp_match"] is False
    assert it.status == "active" and ds.get(LB.CUTLINE_SHARD, "tbook:1:1:9").status == "uncertain"
    assert ds.get(LB.CUTLINE_SHARD, "tbook:1:1:11").status == "stale"            # 无页面锚的不进评测
    # 二次收割：旧条目不动
    again = LB.harvest_cutline("b", evs, cards, dataset=ds)
    assert again["n_added"] == 0 and len(again["skipped_ids"]["id_exists_kept_old"]) == 3


def _end_card(end="top", **kw):
    return {"id": f"colborder:tbook:1:2:{end}", "book": "tbook", "page": 1, "col": 2, "end": end,
            "trim_case": "b", "trim_px": 3, "end_class": "glued", "stratum": "b|glued", "stratum_weight": 2.0,
            "end_fingerprint": "AAAA", "bbox": [1, 2, 3, 4], "geom_sig": "g",
            "product_key": {"step": "column_warp", "key": "p0001", "fingerprint": "fp"}, **kw}


def test_harvest_column_end_maps_legacy_clean(tmp_path):
    ds = GoldStore(tmp_path / "ds")
    evs = [_ev("b", 1, "border_class", "colborder:tbook:1:2:top", {"border_class": "clean"}, fp="fp"),
           _ev("b", 2, "border_class", "colborder:tbook:1:2:bot", {"border_class": "double"}, fp="fp"),
           _ev("b", 3, "border_class", "colborder:tbook:1:2:top", {"border_class": "glued"}, fp="fp")]  # 后到覆盖
    out = LB.harvest_column_end("b", evs, [_end_card("top"), _end_card("bot")], dataset=ds)
    assert out["n_added"] == 2
    assert ds.get(LB.COLEND_SHARD, "tbook:1:2:top").expected["class"] == "glued"
    d = ds.get(LB.COLEND_SHARD, "tbook:1:2:bot")
    assert d.expected["class"] == "double" and d.input["end_fingerprint"] == "AAAA" and d.input["fp_match"] is True


def test_harvest_column_end_legacy_value_recorded(tmp_path):
    ds = GoldStore(tmp_path / "ds")
    evs = [_ev("b", 1, "border_class", "colborder:tbook:1:2:top", {"border_class": "clean"})]
    LB.harvest_column_end("b", evs, [_end_card("top")], dataset=ds)
    e = ds.get(LB.COLEND_SHARD, "tbook:1:2:top").expected
    assert e["class"] == "trim" and e["legacy_class"] == "clean"


# ── 旧 overview 列端卡 ───────────────────────────────────────────────

def test_migrate_legacy_overview(tmp_path):
    f = tmp_path / "v.jsonl"
    f.write_text("\n".join(json.dumps(d) for d in [
        {"id": "t000_p21c5", "verdict": "clean", "t": 1}, {"id": "h049_p138c6", "verdict": "residual", "t": 2},
        {"id": "t008_p33c2", "verdict": "cut1", "t": 3}, {"id": "l074_p29c2", "verdict": "bar_ok_char", "t": 4},
        {"id": "weird", "verdict": "clean"}]), encoding="utf-8")
    ds = GoldStore(tmp_path / "ds")
    out = LB.migrate_legacy_overview(f, "vol02", dataset=ds)
    assert out["n_added"] == 3 and out["skipped"] == {"char_block_card_not_end": 1, "bad_id": 1}
    it = ds.get(LB.COLEND_SHARD, "vol02:21:5:bot")                     # t = 列尾 = 下端
    assert it.expected["class"] == "idk" and it.expected["legacy_verdict"] == "clean"
    assert it.input["source"] == "legacy-overview" and it.status == "uncertain"
    assert ds.get(LB.COLEND_SHARD, "vol02:138:6:top") is not None       # h = 列首 = 上端


# ── 批次文件 / 控制台旁路 ────────────────────────────────────────────

def test_write_batch_and_is_label_batch(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_BATCHES_DIR", str(tmp_path / "b"))
    assert not LB.is_label_batch("x1")
    cards = [_end_card("top")]
    out = LB._write_batch("x1", "t", "column_warp", "border_class", "tbook", LB.COLEND_SHARD, cards,
                          {"strata": {}}, list(LB.END_CLASSES), "n")
    assert out["n_cards"] == 1 and LB.is_label_batch("x1")
    assert LB.read_cards("x1")[0]["id"] == cards[0]["id"]
    with pytest.raises(FileExistsError):
        LB._write_batch("x1", "t", "column_warp", "border_class", "tbook", LB.COLEND_SHARD, cards,
                        {"strata": {}}, [], "n")


def test_harvest_batch_without_events_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_BATCHES_DIR", str(tmp_path / "b"))
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(tmp_path / "fb"))
    LB._write_batch("x2", "t", "column_warp", "border_class", "tbook", LB.COLEND_SHARD, [_end_card()],
                    {"strata": {}}, [], "n")
    with pytest.raises(FileNotFoundError) as ei:
        LB.harvest_batch("x2", dataset=GoldStore(tmp_path / "ds"))
    assert "还没有任何裁决事件" in str(ei.value)


# ── 真产物冒烟：冻结样页跑 Step1→3，再出两批 ─────────────────────────

def test_build_both_batches_on_frozen_fixture_page(tmp_path, monkeypatch, ws):
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.engine import Engine
    from open_guji_cv.core.pipeline import load_pipeline
    from open_guji_cv.feedback.events import EventLog
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore

    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(tmp_path / "products"))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GUJI_BATCHES_DIR", str(tmp_path / "batches"))
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(tmp_path / "fb"))
    book = load_book("keben")
    store, cache = ProductStore(tmp_path / "products"), ImageCache(tmp_path / "cache")
    # 还没有产物：清楚报错、不现算
    with pytest.raises(ProductMissing):
        LB.build_column_end("keben", n=10, pages="1", store=store)
    eng = Engine(book, load_pipeline("keben_body_v2"), store=store, cache=cache, log=lambda s: None)
    eng.run(steps=["border_detect", "column_warp", "row_segment"], pages=[1])

    b = LB.build_column_end("keben", n=20, pages="1", store=store)
    cards = LB.read_cards(b["batch"])
    assert 0 < len(cards) <= 20
    c0 = cards[0]
    assert c0["id"].startswith("colborder:keben:1:") and c0["end"] in ("top", "bot")
    assert c0["space"] == LB.SPACE_TR and c0["end_fingerprint"] and c0["bbox"] and c0["product_key"]["fingerprint"]
    assert "src=raw" in c0["img"] and c0["stratum_weight"] >= 1.0       # 看削前图

    a = LB.build_cutline_gold("keben", n=20, pages="1", store=store, exclude_ids=set())
    cuts = LB.read_cards(a["batch"])
    assert a["console_pages"] == f"list:{a['batch']}"
    assert [ln for ln in open(a["list_file"], encoding="utf-8") if not ln.startswith("#")]
    assert all(c["page_w"] > 0 and c["geom_sig"] and c["bbox"] for c in cuts)
    assert (tmp_path / "batches" / f"{a['batch']}_sampling.json").exists()
    with pytest.raises(FileExistsError):
        LB.build_cutline_gold("keben", n=20, pages="1", store=store, exclude_ids=set(), batch_id=a["batch"])

    # 收割走通：对第一张切线卡写一条带页面坐标的事件
    cc = cuts[0]
    log = EventLog()
    log.append([_ev(a["batch"], 1, "cutline", cc["id"],
                    {"verdict": "ok", "y": cc["y_engine"], "y_old": cc["y_engine"], "col_h": 1000,
                     "page_x": 200.0, "page_y": 300.0})])
    ds = GoldStore(tmp_path / "ds")
    out = LB.harvest_batch(a["batch"], dataset=ds, log=log)
    assert out["n_added"] == 1 and out["n_pending"] == len(cuts) - 1
    assert ds.get(LB.CUTLINE_SHARD, cc["id"]).expected["page_x_tr"] == cc["page_w"] - 1 - 200.0
