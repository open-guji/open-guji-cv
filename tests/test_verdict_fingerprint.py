# -*- coding: utf-8 -*-
"""人裁事件的图像凭证（`anchor.evidence_for`）与绑定表的指纹优先（`bindings.compute_page`）。

全部自造数据：产物库/图像缓存落 tmp，不碰工作区。
"""
from __future__ import annotations

from types import SimpleNamespace as NS

import cv2
import numpy as np

import open_guji_cv.feedback.bindings as B
from open_guji_cv.feedback.anchor import enrich_events, evidence_for, patch_key
from open_guji_cv.feedback.events import EventTarget, make_event
from open_guji_cv.gold.drift import FP_SIZE, fingerprint
from open_guji_cv.products.cache import ImageCache


def _glyph(kind="a") -> np.ndarray:
    img = np.full((80, 60), 255, np.uint8)
    if kind == "a":
        cv2.rectangle(img, (10, 10), (50, 20), 0, -1)      # 一横
    else:
        cv2.rectangle(img, (10, 10), (50, 70), 0, -1)      # 满块：完全不同的图
    return img


class _Store:
    def __init__(self, ent=None):
        self.ent = ent

    def manifest(self, book, step):
        return NS(get=lambda key: self.ent)


def _cell_ev(key="v:1:1:5", anchor=None, kind="confirm"):
    _, pg, col, slot = key.split(":")
    return make_event("b", 1, kind, EventTarget(step="seed_admit", unit="cell", key=key, book="v",
                                                 page=int(pg), col=int(col), slot=int(slot), anchor=anchor),
                      {"v": "confirm", "shape": "X"})


def test_cell_evidence_has_fp_and_product_version(tmp_path):
    cache = ImageCache(tmp_path / "cache")
    cache.put("v", "char_patch", patch_key(1, 1, 5), _glyph("a"))
    ent = NS(sha256="s" * 8, params_hash="p" * 8, fingerprint="f" * 8)
    ev = evidence_for(_cell_ev(), store=_Store(ent), cache=cache)
    assert ev["fp_of"] == "char_patch" and ev["fp_size"] == list(FP_SIZE)
    assert ev["fp"] == fingerprint(_glyph("a"), FP_SIZE)
    assert (ev["sha256"], ev["params_hash"], ev["manifest_fp"]) == ("s" * 8, "p" * 8, "f" * 8)
    assert ev["step"] and ev["key"] == "p0001"


def test_evidence_none_when_nothing_available(tmp_path):
    assert evidence_for(_cell_ev(), store=_Store(None), cache=ImageCache(tmp_path / "c")) is None
    other = make_event("b", 1, "note", EventTarget(step="x", unit="page", key="k"), {})
    assert evidence_for(other, store=_Store(None), cache=ImageCache(tmp_path / "c")) is None


def test_cutline_evidence_uses_column_image_segment(tmp_path):
    cache = ImageCache(tmp_path / "cache")
    col = np.full((400, 50), 255, np.uint8)
    col[150:180] = 0
    cache.put("v", "column_image", "p0001c01", col)
    e = make_event("b", 1, "cutline", EventTarget(step="s", unit="cell", key="v:1:1:5", book="v", page=1, col=1),
                   {"y": 200.0})
    ev = evidence_for(e, store=_Store(NS(sha256="x", params_hash="y", fingerprint="z")), cache=cache)
    assert ev["fp_of"] == "column_image" and ev["y0"] == 136
    assert ev["fp"] == fingerprint(col[136:264], FP_SIZE)
    assert ev["step"] == "column_warp"


def test_enrich_merges_into_product_key_only_anchor(tmp_path, monkeypatch):
    """控制台先放了只含 product_key 的锚：原先 enrich 整条跳过；现在合并补 evidence、不动已有键。"""
    cache = ImageCache(tmp_path / "cache")
    cache.put("v", "char_patch", patch_key(1, 1, 5), _glyph("a"))
    import open_guji_cv.feedback.anchor as A
    monkeypatch.setattr(A, "cell_anchor", lambda *a, **k: None)
    pk = {"product_key": {"step": "s", "key": "p0001", "fingerprint": "F"}}
    e = _cell_ev(anchor=pk)
    assert enrich_events([e], store=_Store(NS(sha256="a", params_hash="b", fingerprint="c")), cache=cache) == 1
    assert e.target.anchor["product_key"] == pk["product_key"]
    assert e.target.anchor["evidence"]["fp"]


def test_enrich_keeps_existing_evidence_and_old_events_still_load():
    e = _cell_ev(anchor={"evidence": {"fp": "keep"}})
    assert enrich_events([e], store=_Store(None), cache=None) == 0
    assert e.target.anchor["evidence"]["fp"] == "keep"
    old = make_event("b", 2, "confirm", EventTarget(step="s", unit="cell", key="v:1:1:5"), {})
    assert old.target.anchor is None          # 旧事件没有凭证照常可读


# ── 绑定表 ─────────────────────────────────────────────────────────────

def _cells(boxes):
    cols = {}
    for (col, slot), (x0, y0, x1, y1) in boxes.items():
        q = [(x1, y0), (x0, y0), (x0, y1), (x1, y1)]
        cols.setdefault(col, []).append(NS(slot=slot, sub=None, kind="char", quad_page=q))
    return NS(columns=[NS(col=c, cells=cs) for c, cs in cols.items()])


def _run(monkeypatch, tmp_path, cur_img, events, boxes=None):
    boxes = boxes or {(1, 5): (0, 400, 100, 500)}
    vers = [("current", B._ts("2026-09-25T00:00:00Z"), float("inf"), _cells(boxes))]
    monkeypatch.setattr(B, "_cells_versions", lambda *a, **k: vers)
    monkeypatch.setattr(B, "_similar", lambda *a, **k: None)
    cache = ImageCache(tmp_path / "cache")
    for (col, slot) in boxes:
        if cur_img is not None:
            cache.put("v", "char_patch", patch_key(1, col, slot), cur_img)
    return B.compute_page("v", 1, events, store=object(), cache=cache, glyph_db=None)


def _fp_anchor(img, bbox=None):
    a = {"evidence": {"fp": fingerprint(img, FP_SIZE), "fp_size": list(FP_SIZE), "fp_of": "char_patch"}}
    if bbox:
        a.update(bbox=bbox, source="live")
    return a


def test_fp_same_image_valid(monkeypatch, tmp_path):
    ev = _cell_ev(anchor=_fp_anchor(_glyph("a"), [0, 400, 100, 500]))
    r = _run(monkeypatch, tmp_path, _glyph("a"), [ev])[0]
    assert r["status"] == "valid" and r["fp_diff"] == 0.0


def test_fp_changed_image_goes_to_review_even_if_box_unmoved(monkeypatch, tmp_path):
    """X2 的场景：框没动（IoU=1），但这一格现在是另一张图（缺陷 → 完整字）——老规则会判 valid。"""
    ev = _cell_ev(anchor=_fp_anchor(_glyph("a"), [0, 400, 100, 500]))
    r = _run(monkeypatch, tmp_path, _glyph("b"), [ev])[0]
    assert r["status"] == "review" and r["fp_diff"] > B.FP_TOL
    assert B.usable(r) is None


def test_fp_without_bbox_same_key(monkeypatch, tmp_path):
    ev = _cell_ev(anchor=_fp_anchor(_glyph("a")))
    assert _run(monkeypatch, tmp_path, _glyph("a"), [ev])[0]["status"] == "valid"
    assert _run(monkeypatch, tmp_path, _glyph("b"), [ev])[0]["status"] == "review"


def test_fp_rebound_when_column_shifted(monkeypatch, tmp_path):
    boxes = {(1, 5): (0, 300, 100, 400), (1, 6): (0, 400, 100, 500)}
    ev = _cell_ev(anchor=_fp_anchor(_glyph("a"), [0, 400, 100, 500]))
    r = _run(monkeypatch, tmp_path, _glyph("a"), [ev], boxes)[0]
    assert r["status"] == "rebound" and r["bound"] == "v:1:1:6"


def test_no_fp_or_no_current_patch_falls_back_to_old_rules(monkeypatch, tmp_path):
    old = _cell_ev(anchor={"bbox": [0, 400, 100, 500], "source": "live"})
    r = _run(monkeypatch, tmp_path, _glyph("b"), [old])[0]
    assert r["status"] == "valid" and "fp_diff" not in r
    ev = _cell_ev(anchor=_fp_anchor(_glyph("a"), [0, 400, 100, 500]))
    r = _run(monkeypatch, tmp_path / "empty", None, [ev])[0]       # 现格没有字块图 → 老规则（IoU=1 → valid）
    assert r["status"] == "valid" and "fp_diff" not in r


def test_stat_script_counts(tmp_path):
    import importlib.util
    import json
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "stat_ev", Path(__file__).resolve().parents[1] / "scripts" / "stat_verdict_evidence.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    rows = [
        {"kind": "confirm", "target": {"book": "v", "key": "v:1:1:1", "anchor": None}},
        {"kind": "confirm", "target": {"book": "v", "key": "v:1:1:2",
                                       "anchor": {"bbox": [0, 0, 1, 1], "evidence": {"fp": "x", "sha256": "s"}}}},
        {"kind": "note", "target": {"book": "v", "key": "k"}},
    ]
    (tmp_path / "b.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    r = m.scan(tmp_path)["v"]
    assert r["n"] == 2 and r["fp"] == 1 and r["bbox"] == 1 and r.get("anchor") == 1
