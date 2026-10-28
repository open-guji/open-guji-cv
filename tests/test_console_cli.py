# -*- coding: utf-8 -*-
"""控制台调命令行（`console/cli.py`）：写操作走子进程（doc/design/拆分-控制台独立成包与上网站.md 第五节）。"""
from __future__ import annotations

import subprocess

import pytest
from fastapi import HTTPException

from open_guji_cv.console import cli


def test_parse_json_output_shapes():
    assert cli.parse_json_output('{"a": 1}') == {"a": 1}
    # eval run --json：先印逐条结果，JSON 在后面某一行，最后还有一行汇总
    assert cli.parse_json_output('✓ x\n[{"b": 2}]\n\n通过 1 / 回归门失败 0') == [{"b": 2}]
    # gold import：多行 JSON 后面跟一句人话
    assert cli.parse_json_output('{\n "c": 3\n}\n（试算，未写入）') == {"c": 3}
    with pytest.raises(ValueError):
        cli.parse_json_output("只有人话")


class _Done:
    def __init__(self, code=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


def test_run_guji_passes_request_workspace_not_process_env(monkeypatch, tmp_path):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"], seen["env"] = argv, kw["env"]
        return _Done(out='{"ok": true}')

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("GUJI_WORKSPACE", "/somewhere/else")
    monkeypatch.setattr(cli, "workspace_root", lambda: tmp_path)
    assert cli.run_guji("events", "route", "b1", "--dry-run") == {"ok": True}
    assert seen["argv"][1:] == ["-m", "open_guji_cv", "events", "route", "b1", "--dry-run"]
    assert seen["env"]["GUJI_WORKSPACE"] == str(tmp_path)

    monkeypatch.setattr(cli, "workspace_root", lambda: None)
    cli.run_guji("gold", "migrate", "s")
    assert "GUJI_WORKSPACE" not in seen["env"]


def test_run_guji_failure_is_500_with_stderr(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: _Done(code=1, err="Traceback… 路由表坏了"))
    with pytest.raises(HTTPException) as e:
        cli.run_guji("events", "route", "b1")
    assert e.value.status_code == 500 and "路由表坏了" in e.value.detail


def test_route_endpoint_calls_cli(monkeypatch):
    from open_guji_cv.console.routers import feedback as fb
    calls = []
    monkeypatch.setattr(fb, "run_guji", lambda *a, **k: calls.append(a) or {"results": []})
    monkeypatch.setattr(fb.deps, "batch_store", lambda: type("S", (), {"get": lambda self, b: None})())
    assert fb.api_route("b1", dry_run=True) == {"results": []}
    assert calls == [("events", "route", "b1", "--dry-run")]


def test_gold_import_endpoint_builds_args(monkeypatch):
    from open_guji_cv.console.routers import gold
    calls = []
    monkeypatch.setattr(gold, "run_guji", lambda *a, **k: calls.append(a) or {})
    gold.api_gold_import("char-segmentation/touching-cuts", book="vol01", pages="1-3", why="试")
    assert calls == [("gold", "import", "char-segmentation/touching-cuts", "--why", "试",
                      "--book", "vol01", "--pages", "1-3", "--dry-run")]
