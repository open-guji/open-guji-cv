# -*- coding: utf-8 -*-
"""scripts/code_equiv.py：子进程 PYTHONPATH 是追加不是覆盖（史記跑批线程 11-12 反馈）。"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("code_equiv_script", ROOT / "scripts" / "code_equiv.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


def test_pythonpath_keeps_existing_entries_after_code_root():
    got = M._pythonpath(Path("/x/old"), "/mgr/src" + os.pathsep + "/other")
    assert got.split(os.pathsep) == ["/x/old", "/mgr/src", "/other"]


def test_pythonpath_without_existing_is_just_code_root():
    assert M._pythonpath(Path("/x/old"), None) == str(Path("/x/old"))
    assert M._pythonpath(Path("/x/old"), "") == str(Path("/x/old"))
