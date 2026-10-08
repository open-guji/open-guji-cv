# -*- coding: utf-8 -*-
"""Step7 `solo_margin`（2026-10-08，overview#450）：match_solo 系 top1 领先异语义候选不足 margin 就落审。

vol05 `147:9:9` 金标士：库候选 土 0.9955／士 0.9813，`rival` 只看 ≥ solo_cov(0.99) 没拦住。
缺省 0 = 关 = 旧行为，且不进参数 dump（没开的书参数哈希不变）。
"""
from __future__ import annotations

import open_guji_cv.steps  # noqa: F401
from test_seed_admit_solo_replace_0928 import _run
from open_guji_cv.steps.seed_admit import SeedAdmitParams

CLOSE = [("土", 0.9955), ("士", 0.9813), ("圡", 0.9733)]
FAR = [("明", 0.996), ("朋", 0.90)]
ONE = [("三", 0.9979)]
SKIP = {"patch_missing": "skip"}     # unsure 档会去取 CNN 背书的图块，测试里没有图
ON = {**SKIP, "solo_margin": 0.02}


def test_default_off_admits_close_second(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, cands=CLOSE, verdict="unsure", params=SKIP)
    assert r.admit and r.channel == "match_solo" and r.char == "土"


def test_close_second_goes_to_review(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, cands=CLOSE, verdict="unsure", params=ON)
    assert not r.admit and "solo_confusable" in r.doubts


def test_far_second_still_admitted(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, cands=FAR, verdict="same", params=ON)
    assert r.admit and r.channel == "match_solo" and r.char == "明"


def test_single_candidate_untouched(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, cands=ONE, verdict="same", params=ON)
    assert r.admit and r.channel == "match_solo"


def test_margin_below_gap_admits(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, cands=CLOSE, verdict="unsure", params={**SKIP, "solo_margin": 0.01})
    assert r.admit and r.channel == "match_solo"


def test_off_params_dump_unchanged():
    assert "solo_margin" not in SeedAdmitParams().model_dump()
    assert SeedAdmitParams(solo_margin=0.02).model_dump()["solo_margin"] == 0.02
