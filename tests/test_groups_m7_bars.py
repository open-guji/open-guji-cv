# -*- coding: utf-8 -*-
"""M7 量横接进 `m7_pass`（`seed_admit.m7_bars`）。自造两横一竖字块图与桩上下文，不读真书。"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

import open_guji_cv.groups.m7_pass as mp
import open_guji_cv.steps  # noqa: F401
from open_guji_cv.groups.protocol import GroupVerdict
from open_guji_cv.steps.seed_admit import SeedAdmitParams


def _glyph(top, bottom):
    g = np.full((110, 100), 255, np.uint8)
    g[5:105, 46:54] = 0
    for y0, w in ((30, top), (92, bottom)):
        g[y0:y0 + 6, 50 - w // 2:50 + w // 2] = 0
    return g


def _rec(cid="c1", char="士", admit=False):
    return SimpleNamespace(id=cid, char=char, admit=admit, channel=None, provenance="", doubts=[], evidence=None)


def _run(rec, img, bars=("ts",), ctx_verdict=None, monkeypatch=None):
    if ctx_verdict is not None:
        monkeypatch.setattr(mp, "judge", lambda *a, **k: ctx_verdict)
    seq = [rec]
    res = mp.m7_pass(seq, {rec.id: (rec.char, None)}, ("ts",), {}, lambda s, i, st: "",
                     bars=bars, patch_fn=(lambda cid: img))
    return res["ts"]


def test_ctx_abstains_bars_lift():
    r = _rec(char="士")                      # 现行字士，字形却是下横长（土）→ 文意弃权时按量横抬为土
    res = _run(r, _glyph(40, 80))
    assert (r.char, r.admit) == ("土", True) and res.lifted == 1
    assert r.evidence["m7_group"]["ts"]["via"] == "bars"
    assert r.evidence["m7_group"]["ts"]["bars"]["char"] == "土"


def test_bars_off_by_default_no_change():
    r = _rec(char="士")
    res = _run(r, _glyph(40, 80), bars=())
    assert (r.char, r.admit) == ("士", False) and res.lifted == 0 and r.evidence is None


def test_close_ratio_leaves_cell_alone():
    r = _rec(char="士")
    _run(r, _glyph(60, 62))
    assert (r.char, r.admit) == ("士", False)


def test_conflict_with_ctx_abstains_and_leaves_trace(monkeypatch):
    r = _rec(char="士", admit=False)
    ctx = GroupVerdict("士", why="agree", via="rule")
    res = _run(r, _glyph(40, 80), ctx_verdict=ctx, monkeypatch=monkeypatch)     # 字形说土，文意说士
    assert (r.char, r.admit) == ("士", False) and res.lifted == 0
    ev = r.evidence["m7_group"]["ts"]
    assert ev["why"] == "bars_conflict" and ev["bars"]["char"] == "土"


def test_ctx_and_bars_agree_keeps_ctx(monkeypatch):
    r = _rec(char="土")
    ctx = GroupVerdict("土", why="agree", via="rule")
    res = _run(r, _glyph(40, 80), ctx_verdict=ctx, monkeypatch=monkeypatch)
    assert (r.char, r.admit, r.channel) == ("土", True, "ji_yi_si") and res.lifted == 1
    assert r.evidence["m7_group"]["ts"]["via"] == "rule"


def test_patch_skipped_keeps_ctx_result(monkeypatch):
    r = _rec(char="士")
    seq = [r]
    res = mp.m7_pass(seq, {r.id: ("士", None)}, ("ts",), {}, lambda s, i, st: "", bars=("ts",),
                     patch_fn=lambda cid: None)
    assert res["ts"].lifted == 0 and (r.char, r.admit) == ("士", False)


def test_fingerprint_and_params_hash_unchanged_when_off():
    assert mp.fingerprint(("ts",), {}) == mp.fingerprint(("ts",), {}, ())
    assert mp.fingerprint(("ts",), {}, ("ts",)) != mp.fingerprint(("ts",), {})
    assert "m7_bars" not in SeedAdmitParams().model_dump()                          # 全关：参数哈希不变
    assert "m7_bars" not in SeedAdmitParams(m7_groups=("ts",)).model_dump()         # 只开文意路：同前
    assert "m7_bars" in SeedAdmitParams(m7_groups=("ts",), m7_bars=("ts",)).model_dump()
    d_off = SeedAdmitParams(m7_groups=("ts",))
    d_on = SeedAdmitParams(m7_groups=("ts",), m7_bars=("ts",))
    assert d_off.m7_fingerprint != d_on.m7_fingerprint
