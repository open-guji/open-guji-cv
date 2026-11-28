"""3d `cell_traits`（2026-11-28）：各键子判据（纯函数）、步骤端到端、收尾 `traits`、缺省关、骨架位置。全部自造数据。"""
from __future__ import annotations

import json

import numpy as np

from open_guji_cv.clustering import cell_traits as T
from open_guji_cv.core.anchor import to_cv
from open_guji_cv.core.pipeline import load_pipeline
from open_guji_cv.products.kinds.read import FinalRec, TraitRec
from open_guji_cv.steps.cell_traits import CellTraitsParams
from open_guji_cv.steps.glyph_analyzer import merge_cell

from helpers import make_book, make_ctx, page_chars, page_match, run_steps, write_product


def _patch(h=40, w=40, rows=(4, 36), cols=(8, 32)):
    p = np.full((h, w), 255, np.uint8)
    p[rows[0]:rows[1], cols[0]:cols[1]] = 0
    return p


def _score(p, **kw):
    return T.score_cell(p, T.patch_shape(p), **kw)


# ── 各键子判据 ───────────────────────────────────────────────────────

def test_clean_char_scores_low_everywhere():
    s, ev = _score(_patch(), end=None, height=40, period=40, merge_base=40, page_ink_med=768, conf3a=1.0)
    assert set(s) == set(T.KEYS) and max(s.values()) < 0.5
    assert ev["flags"] == [] and set(ev["cut"]) >= {"end", "rh", "seam_ink", "sub"}


def test_merged_valley_two_blobs():
    p = np.full((90, 40), 255, np.uint8)
    p[5:40, 8:32] = 0
    p[50:85, 8:32] = 0
    s, ev = _score(p, height=90, period=45, merge_base=45)
    assert s["merged"] >= 0.5 and ev["merged"]["valley"] and ev["merged"]["sub"]["valley"] == s["merged"]
    s1, _ = _score(_patch(), height=40, period=45, merge_base=45)
    assert s1["merged"] == 0.0


def test_border_end_debris_only_at_column_end():
    p = _patch(rows=(2, 30), cols=(10, 30))
    p[36:38, :] = 0                                   # 字脚下一截和字身分开的细框线
    s, ev = _score(p, end="bottom")
    assert s["border"] >= 0.5 and ev["border"]["debris"] > T.FRAME_DEBRIS
    s_mid, _ = _score(p, end=None)
    assert s_mid["border"] < 0.5                      # 列中格不看端区框线样


def test_residue_detached_blob_but_not_own_top_stroke():
    p = np.full((100, 60), 255, np.uint8)
    p[25:80, 15:45] = 0                                # 字身
    p[92:99, 36:47] = 0                                # 字脚下隔开的一小团（邻字残笔）
    s, ev = _score(p)
    assert s["residue"] >= 0.5 and ev["residue"]["blob"] > T.EDGE_BLOB_INK
    q = np.full((100, 60), 255, np.uint8)
    q[2:8, 18:42] = 0                                  # 「元」的顶横：扁、落在字身左右范围内
    q[30:95, 10:28] = 0                                # 字身分成两块
    q[30:95, 34:50] = 0
    s2, ev2 = _score(q)
    assert s2["residue"] == 0.0 and ev2["residue"]["edge_blob"] > 0   # extractor 的 edge_blob 会算它


def test_cut_same_char_shorter_at_end_only():
    p = _patch(rows=(4, 20))                           # 墨高 16
    ref = (32.0, 40.0, 5, 24.0)                        # 同字墨高中位 32
    s, ev = _score(p, end="bottom", ref=ref, period=40)
    assert s["cut"] >= 0.5 and ev["cut"]["rh"] == 0.5 and ev["cut"]["n_ref"] == 5
    s_mid, ev_mid = _score(p, end=None, ref=ref, period=40)
    assert s_mid["cut"] == 0.0 and ev_mid["cut"]["rh"] == 0.5    # 列中只记证据
    s_ok, _ = _score(_patch(rows=(4, 36)), end="bottom", ref=ref, period=40)
    assert s_ok["cut"] == 0.0


def test_cut_seam_ink_skipped_on_seal_page():
    s, _ = _score(_patch(), seam_ink=45)
    assert s["cut"] >= 0.5
    s2, ev2 = _score(_patch(), seam_ink=45, stain_page=True)
    assert s2["cut"] == 0.0 and ev2["cut"]["seam_skipped"] == "seal"


def test_flags_map_to_keys():
    s, ev = _score(_patch(), flags=["rule_bar", "edge_blob", "boundary_ink", "jiazhu"])
    assert s["border"] == 0.9 and s["residue"] == 0.7 and s["cut"] == 0.25
    assert ev["flags"] == ["rule_bar", "edge_blob", "boundary_ink", "jiazhu"]


def test_blank_small_ink_discounted_by_3a():
    p = _patch(rows=(18, 22), cols=(18, 22))           # 一个小墨点
    s, _ = _score(p, page_ink_med=768, conf3a=0.0)
    assert s["blank"] >= 0.5
    s2, _ = _score(p, page_ink_med=768, conf3a=1.0)
    assert s2["blank"] == 0.0


def test_stain_density_and_seal_overlap():
    from open_guji_cv.products.kinds.seals import Seal
    g = np.full((200, 200), 255, np.uint8)
    for y in range(60, 140, 8):
        for x in range(60, 140, 8):
            g[y:y + 3, x:x + 3] = 0
    dots = T.medium_dots(g)
    W = g.shape[1]
    box = (W - 1 - 120.0, 80.0, W - 1 - 80.0, 120.0)   # 右上原点：cv 里 x 80..120
    assert to_cv(box, W)[0] == 80
    d = T.dot_density(dots, box, g.shape)
    s, _ = _score(_patch(), density=d)
    assert s["stain"] >= 0.5
    far = (W - 1 - 40.0, 0.0, W - 1 - 10.0, 30.0)
    assert T.dot_density(dots, far, g.shape) < T.OCC_DENSITY
    ov = T.seal_overlap(box, [Seal(kind="stain", bbox=(0, 0, 200, 200), score=9.0, source="density")])
    assert ov == {"stain": 1.0, "crisp": 0.0}


def test_same_char_refs_min_ref():
    items = [("之", False, 30, 40, 25)] * 3 + [("也", False, 30, 40, 25)] * 2
    refs = T.same_char_refs(items, 3)
    assert set(refs) == {("之", False)} and refs[("之", False)][2] == 3


# ── 收尾 ─────────────────────────────────────────────────────────────

def test_final_rec_traits_dropped_when_empty():
    assert "traits" not in json.loads(FinalRec(id="x", slot=1).model_dump_json())
    assert json.loads(FinalRec(id="x", slot=1, traits={"cut": 0.1}).model_dump_json())["traits"] == {"cut": 0.1}


def test_merge_cell_puts_raw_scores_in_traits_not_p_map():
    m = page_match(recs=[{"slot": 1, "verdict": "unsure", "candidates": [("甲", 0.9)]}]).columns[0].chars[0]
    r = merge_cell(m, None, {}, 5, "elastic", traits_rec=TraitRec(id=m.id, slot=1, scores={"cut": 0.7, "border": 0.1}))
    assert r.traits == {"cut": 0.7, "border": 0.1} and r.p_map == {} and r.p_src == ""


# ── 管线 ─────────────────────────────────────────────────────────────

def test_default_off_and_in_read_stage_before_final(tmp_path):
    from open_guji_cv.core.engine import Engine
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore

    assert CellTraitsParams().enabled is False
    pl = load_pipeline("keben_body_v2")
    read = pl.stages["read"]
    assert read.index("glyph_candidate") < read.index("cell_traits") < read.index("glyph_analyzer") == len(read) - 1
    e = Engine(make_book(), pl, store=ProductStore(tmp_path / "p"), cache=ImageCache(tmp_path / "c"), log=lambda s: None)
    assert "cell_traits" not in e._enabled(pl.steps)


def test_step_end_to_end_and_analyzer_traits(tmp_path):
    book = make_book("tbook", params={"cell_traits": {"enabled": True}, "glyph_analyzer": {"enabled": True}})
    W, H = 300, 420
    img = np.full((H, W), 255, np.uint8)
    boxes = {s: (30.0, 10.0 + 50 * (s - 1), 70.0, 50.0 + 50 * (s - 1)) for s in range(1, 8)}
    # 第 4 格四周撒一片中等墨点（印泥斑点）
    x0, y0, x1, y1 = to_cv(boxes[4], W)
    for y in range(y0 - 15, y1 + 15, 7):
        for x in range(x0 - 15, x1 + 15, 7):
            img[y:y + 3, x:x + 3] = 0
    ctx = make_ctx(tmp_path, book, raw={1: img})
    write_product(ctx, "cell_shrink", 1, char_index=page_chars(recs=[
        {"slot": s, "bbox_page": boxes[s], "bbox_col": (0.0, 40.0 * (s - 1), 40.0, 40.0 * s), "height": 40.0,
         "patch_key": f"p0001c01s{s}"} for s in range(1, 8)]))
    write_product(ctx, "glyph_match", 1, glyph_match=page_match(recs=[
        {"slot": s, "verdict": "same", "char": "之", "cov": 0.95} for s in range(1, 8)]))
    for s in range(1, 8):
        ctx.cache.put("tbook", "char_patch", f"p0001c01s{s}", _patch(rows=(4, 20) if s == 7 else (4, 36)))

    out = run_steps(ctx, 1, ["cell_traits", "glyph_analyzer"])
    tr = out["cell_traits"]
    assert tr.model == "cell-traits/0"
    by = tr.by_id()
    assert list(by) == [f"tbook:1:1:{s}" for s in range(1, 8)]
    assert by["tbook:1:1:7"].scores["cut"] >= 0.5                       # 列尾比同字矮一截
    assert by["tbook:1:1:7"].evidence["cut"]["end"] == "bottom" and by["tbook:1:1:7"].evidence["cut"]["ref_char"] == "之"
    assert by["tbook:1:1:1"].scores["cut"] == 0.0 and by["tbook:1:1:1"].evidence["cut"]["end"] == "top"
    assert by["tbook:1:1:4"].scores["stain"] >= 0.5 > by["tbook:1:1:1"].scores["stain"]
    fin = out["glyph_analyzer"].by_id()
    assert fin["tbook:1:1:7"].traits == by["tbook:1:1:7"].scores and fin["tbook:1:1:7"].p_map == {}
