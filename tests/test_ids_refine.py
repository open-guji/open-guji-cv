# -*- coding: utf-8 -*-
"""IdsSpec.refine：xjz 一起判后用两类细判库再判（榮／滎）。逻辑用假库与假整字判别。"""
import numpy as np

from open_guji_cv.groups import ids_online as io
from open_guji_cv.groups.protocol import GroupVerdict


def _setup(monkeypatch, tmp_path, second):
    p2 = tmp_path / "xjz_rx.json"
    p2.write_text('{"spec": {"min_class": 7}}', encoding="utf-8")
    monkeypatch.setattr(io, "_refine_path", lambda name: p2 if name else None)
    monkeypatch.setattr(io, "load_bank", lambda p: {"榮": [np.zeros((2, 2))], "滎": [np.zeros((2, 2))]})
    seen = {}

    def fake(gray, bank, spec, members):
        seen["spec"], seen["members"] = spec, members
        return second
    monkeypatch.setattr(io, "_judge_whole", fake)
    return seen


def test_refine_overrides_joint_and_uses_bank_spec(monkeypatch, tmp_path):
    from dataclasses import replace
    spec = replace(io.SPECS["xjz"], refine="xjz_rx")
    seen = _setup(monkeypatch, tmp_path, GroupVerdict("滎", conf=1.2, why="agree", via="ids"))
    # 一起判给了 榮：细判改成 滎
    v = io._refine_verdict("xjz", object(), GroupVerdict("榮", conf=0.9, why="agree", via="ids"), spec)
    assert v.char == "滎" and v.extra["refine"] == "xjz_rx" and v.extra["first"]["char"] == "榮"
    assert seen["spec"].min_class == 7 and seen["spec"].refine == "" and seen["members"] == {"榮", "滎"}
    # 一起判低分差弃权、最像字是 榮：也触发
    v = io._refine_verdict("xjz", object(), GroupVerdict(None, why="abstain:low_margin", via="ids", extra={"form": "榮"}), spec)
    assert v.char == "滎"
    # 最像字在细判库外：不动
    v0 = GroupVerdict("冶", conf=1.0, why="agree", via="ids")
    assert io._refine_verdict("xjz", object(), v0, spec) is v0
    # 一起判别的原因弃权（如 aspect）：不动
    v0 = GroupVerdict(None, why="abstain:aspect", via="ids", extra={"form": "榮"})
    assert io._refine_verdict("xjz", object(), v0, spec) is v0


def test_refine_abstain_and_off(monkeypatch, tmp_path):
    from dataclasses import replace
    spec = replace(io.SPECS["xjz"], refine="xjz_rx")
    _setup(monkeypatch, tmp_path, GroupVerdict(None, conf=0.1, why="abstain:low_margin", via="ids"))
    v = io._refine_verdict("xjz", object(), GroupVerdict("榮", conf=0.9, why="agree", via="ids"), spec)
    assert v.char is None and v.why == "abstain:refine_low_margin"
    # 缺省关、无细判库
    v0 = GroupVerdict("榮", conf=0.9, why="agree", via="ids")
    assert io._refine_verdict("xjz", object(), v0, io.SPECS["xjz"]) is v0
    monkeypatch.setattr(io, "_refine_path", lambda name: None)
    assert io._refine_verdict("xjz", object(), v0, spec) is v0
    assert not io.SPECS["xjz"].refine


def test_refine_not_in_fingerprint_when_off():
    assert "refine" not in io.fingerprint(["xjz"]) and ".r" not in io.fingerprint(["xjz"]).split("xjz=")[-1].split(",")[0][8:]
