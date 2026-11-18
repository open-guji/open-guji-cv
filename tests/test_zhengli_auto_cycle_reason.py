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
