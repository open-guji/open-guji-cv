# -*- coding: utf-8 -*-
"""从头跑（没有铺底包）的单：开跑前没有 Step3 产物，人裁绑定数必然是 0，不能拿来拦单（QTW r8，2026-11-03）。
有铺底包（base 非空）时仍照常比较。"""
from __future__ import annotations

import pytest

from open_guji_cv.jobs import runner as R


def _job(base, want=1945):
    j = object.__new__(R.Job)
    j.spec = {"book": "vol05", "base": base, "checks": {"human_chars": want}}
    j.dry, j.id, j.aid = False, 1, 1
    j.dir = None
    j.evs, j.dbs, j.shs = [], [], []
    j.ev = lambda msg, **k: j.evs.append(msg)
    j.db = lambda fn, *a, **k: j.dbs.append(k.get("data"))
    return j


def test_no_base_skips_without_running_check(monkeypatch):
    j = _job(None)
    monkeypatch.setattr(j, "sh", lambda *a, **k: j.shs.append(a) or "0\n", raising=False)
    j.checks()                       # 不抛错：从头跑不拦
    assert j.shs == []               # 没有去查绑定数
    assert j.dbs[-1]["skipped"] == "no_base"
    assert "跳过" in j.evs[-1]


def test_with_base_still_blocks_on_mismatch(monkeypatch):
    j = _job("main")
    monkeypatch.setattr(j, "sh", lambda *a, **k: "0\n", raising=False)
    with pytest.raises(R.StageError) as ei:
        j.checks()
    assert ei.value.outcome == "blocked"


def test_with_base_passes_on_match(monkeypatch):
    j = _job("main", want=3)
    monkeypatch.setattr(j, "sh", lambda *a, **k: "3\n", raising=False)
    j.checks()
    assert j.dbs[-1]["got"] == 3
