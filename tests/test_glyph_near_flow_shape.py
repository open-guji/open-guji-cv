"""3b `glyph_near` 的 flow_shape 方法（3a `glyph_match.stages` 的 5a.2 字组看图判法搬进 3b，结构拆分 A4，2026-11-28）。

一致性：同一张图、同一组，走 3a `glyph_stages.stage_shape` 与走 3b 方法，证据同键同值（同一个 `shape_stage.judge`）。
字块图用 cv2 现画，不读真书数据。
"""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import numpy as np
import pytest

from open_guji_cv.groups import near_methods as NM
from open_guji_cv.groups import shape_stage

from helpers import make_book, make_ctx, page_chars, page_match, run_steps, write_product

cv2 = pytest.importorskip("cv2")

SPEC = {"path": "config/groups", "group": "rr"}


def _glyph(kind: str) -> np.ndarray:
    g = np.full((80, 80), 255, np.uint8)
    if kind == "入":
        cv2.line(g, (40, 10), (15, 70), 0, 5)
        cv2.line(g, (30, 25), (68, 70), 0, 5)
    elif kind == "人":
        cv2.line(g, (40, 10), (12, 70), 0, 5)
        cv2.line(g, (40, 30), (68, 70), 0, 5)
    elif kind == "八":
        cv2.line(g, (32, 15), (15, 68), 0, 5)
        cv2.line(g, (48, 15), (66, 68), 0, 5)
    return g


def test_spec_and_errors():
    m = NM.load_method("flow_shape", SPEC)
    assert m.patch == "char_patch" and m.group == "rr" and set(m.members) == {"入", "人", "八"}
    assert m.methods == tuple(x.name for x in shape_stage.shape_methods("rr"))
    with pytest.raises(ValueError, match="不是注册组"):
        NM.load_method("flow_shape", {"path": "config/groups", "group": "nope"})
    with pytest.raises(ValueError, match="不是注册组"):
        NM.load_method("flow_shape", "config/groups")
    with pytest.raises(ValueError, match="没有只吃字块图的方法"):
        NM.load_method("flow_shape", {"path": "config/groups", "group": "jys"})


def test_fingerprint_by_group_not_path():
    f = NM.method_fingerprint("flow_shape", SPEC)
    assert f.startswith("flow_shape=") and f == NM.method_fingerprint("flow_shape", {"path": "config", "group": "rr"})
    assert f != NM.method_fingerprint("flow_shape", {"path": "config/groups", "group": "zy"})
    assert f == "flow_shape=" + NM.load_method("flow_shape", SPEC).fingerprint()


@pytest.mark.parametrize("kind", ["入", "人", "八", "blank"])
@pytest.mark.parametrize("gid", ["rr", "zy", "dt"])
def test_same_evidence_as_3a_stage_shape(kind, gid):
    """3a 5a.2 那一行（`MatchRec.stage.shape[]`）与 3b 证据同键同值。"""
    from open_guji_cv.groups.flow import FlowConfig
    from open_guji_cv.groups.registry import FLOW_GROUPS
    from open_guji_cv.steps.glyph_stages import StageInput, stage_shape
    g = _glyph(kind)
    cands = [("入", 0.9), ("人", 0.88)] if gid == "rr" else [(c, 0.9 - 0.01 * i) for i, c in enumerate(sorted(FLOW_GROUPS[gid].members))]
    ev3a, _c, _g = stage_shape(StageInput("b:1:1:1", cands[0][0], (gid,), cands, g), NS(final=()), FlowConfig(groups=tuple(FLOW_GROUPS)))
    (row,) = ev3a["shape"]
    m = NM.load_method("flow_shape", {"path": "config/groups", "group": gid})
    (o,) = NM.score(m, [g], "b", cells=[{"id": "b:1:1:1", "candidates": cands}])
    assert {k: o["evidence"][k] for k in row} == row
    assert o["evidence"]["method"] == "flow_shape"
    if o["evidence"]["char"] is None:
        assert o["sims"] == {}
    else:
        assert o["sims"][o["evidence"]["char"]] == 1.0 and sum(o["sims"].values()) == 1.0
    assert m.calibrate(o["sims"]) is None


def test_sims_on_agree(monkeypatch):
    v = shape_stage.ShapeVerdict("rr", "人", "agree", False, (("rr_img", "人", 0.8123456, "ok"),))
    monkeypatch.setattr(shape_stage, "judge", lambda *a, **k: v)
    (o,) = NM.load_method("flow_shape", SPEC).score([_glyph("人")], "b", cells=[{"id": "x", "candidates": []}])
    assert o["sims"] == {"人": 1.0, "入": 0.0, "八": 0.0}
    assert o["evidence"] == {"method": "flow_shape", "group": "rr", "char": "人", "why": "agree", "final": False,
                             "solvers": [["rr_img", "人", 0.8123, "ok"]]}


def test_registry_handling_allows_flow_shape():
    from open_guji_cv.groups import near_registry as NR
    inv = shape_stage.inventory()
    has = set(inv["final"]) | set(inv["evidence"])
    for gid in has:
        ms = NR.handling_of(gid)["methods"]
        assert ("flow_shape" in ms) == (gid != "ry"), gid          # 日曰 人定 []：不做字形区分
    assert "flow_shape" not in NR.handling_of("jys")["methods"]


def test_glyph_near_flow_shape_end_to_end(tmp_path):
    book = make_book("tbook", params={"glyph_near": {"groups": {"rr": {"ref": "rr", "trigger": "cands", "methods": {"flow_shape": SPEC}}}}})
    ctx = make_ctx(tmp_path, book, raw={1: np.full((300, 300), 255, np.uint8)})
    write_product(ctx, "glyph_match", 1, glyph_match=page_match(recs=[
        {"slot": 1, "verdict": "unsure", "candidates": [("入", 0.90), ("人", 0.89)]},
        {"slot": 2, "verdict": "same", "char": "言", "cov": 0.95}]))
    write_product(ctx, "cell_shrink", 1, char_index=page_chars(recs=[
        {"slot": s, "bbox_page": (30.0, 10.0 + 50 * s, 70.0, 50.0 + 50 * s), "patch_key": f"p0001c01s{s}"} for s in (1, 2)]))
    g = _glyph("入")
    ctx.cache.put("tbook", "char_patch", "p0001c01s1", g)
    pn = run_steps(ctx, 1, ["glyph_near"])["glyph_near"]
    assert pn.skipped_methods == [] and set(pn.by_id_all()) == {"tbook:1:1:1"}
    (mo,) = pn.get("tbook:1:1:1", "rr").methods
    (o,) = NM.load_method("flow_shape", SPEC).score([g], "tbook", cells=[{"id": "tbook:1:1:1", "candidates": [("入", 0.90), ("人", 0.89)]}])
    assert mo.method == "flow_shape:rr" and mo.evidence == o["evidence"] and mo.sims == o["sims"]
    assert pn.models == {"flow_shape:rr": NM.method_fingerprint("flow_shape", SPEC).split("=", 1)[1]}
