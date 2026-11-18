"""auto_cycle 失败原因取最后一条 ✗ 行（ZM 11-17：why 抄成了前面的提示行）。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "zhengli"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("zl_auto_cycle", SCRIPTS / "auto_cycle.py")
ac = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ac)


def test_fail_reason_takes_last_cross_line():
    out = "ⓘ vol89 38 条事件页表 rev 不符\n…\n✗ 单子体检不过：overturn_empty 2 格\n  02:3:4:5\n"
    assert ac.fail_reason(out).startswith("✗ 单子体检不过")


def test_fail_reason_falls_back_to_tail():
    assert ac.fail_reason("a\nb\nc") == "a\nb\nc"


def test_run_book_passes_allow_empty_only_for_zero_votes(tmp_path, monkeypatch):
    """零票判 go 的册，plan 带 --allow-empty（ZM 11-18 殿本 21–99 册）；有票的册不带。"""
    import subprocess as sp
    calls = []

    def fake_sh(cmd, tries=3, **kw):
        calls.append([str(c) for c in cmd])
        return sp.CompletedProcess(cmd, 0 if "source" in calls[-1] else 1, "", "✗ 停在这里")
    monkeypatch.setattr(ac, "sh", fake_sh)
    monkeypatch.setattr(ac.pc, "pack_info", lambda *a, **k: {"cv_commit": "abc"})
    monkeypatch.setattr(ac, "engine_for", lambda c: tmp_path)
    for voted, want in ((0, True), (3, False)):
        calls.clear()
        d = {"main": "L", "online_rev": "021-r1", "status": {"voted": voted, "cells": 5, "done": False}}
        ac.run_book(tmp_path, "vol21", tmp_path, d, "sheldon")
        plan = next(c for c in calls if "plan" in c)
        assert ("--allow-empty" in plan) is want
