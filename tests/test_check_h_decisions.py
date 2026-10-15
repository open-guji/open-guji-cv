# -*- coding: utf-8 -*-
"""scripts/check_h_decisions.py 的单元测试：数据全部用 tmp_path 现造。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_h_decisions.py"
_spec = importlib.util.spec_from_file_location("check_h_decisions", _SCRIPT)
chd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chd)


def _index() -> list[dict]:
    return [
        {"cell": "001:1:1", "seq": 1, "default_char": "天"},
        {"cell": "001:1:2", "seq": 2, "default_char": "地"},
        {"cell": "001:2:1", "seq": 3, "default_char": "玄"},
    ]


def _decisions() -> dict:
    return {
        "actor": "整理看图",
        "batch": 1,
        "confirmed": {
            "001:1:1": {"char": "天", "default": "天", "kind": "same"},
            "001:1:2": {"char": "墬", "default": "地", "kind": "variant_identity"},
        },
        "unsure": {
            "001:2:1": {"default": "玄", "why": "墨迹糊"},
        },
    }


def _write(root: Path, index: list[dict], decisions: dict) -> None:
    (root / "index_batch01.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    (root / "decisions_batch01.json").write_text(json.dumps(decisions, ensure_ascii=False), encoding="utf-8")


def test_all_pass(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path, _index(), _decisions())
    assert chd.main(["check", str(tmp_path)]) == 0
    assert "2 格确定／1 格不确定" in capsys.readouterr().out


def test_missing_cell_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    d = _decisions()
    del d["unsure"]["001:2:1"]  # 001:2:1 既不在 confirmed 也不在 unsure
    _write(tmp_path, _index(), d)
    assert chd.main(["check", str(tmp_path)]) == 1
    assert "001:2:1 在 confirmed 与 unsure 里都没有" in capsys.readouterr().out


def test_duplicate_cell_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    d = _decisions()
    d["unsure"]["001:1:1"] = {"default": "天", "why": "重复"}  # 同一格在 confirmed 与 unsure 各一次
    _write(tmp_path, _index(), d)
    assert chd.main(["check", str(tmp_path)]) == 1
    assert "001:1:1 同时出现在 confirmed 与 unsure" in capsys.readouterr().out


def test_wrong_actor_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    d = _decisions()
    d["actor"] = "别人"
    _write(tmp_path, _index(), d)
    assert chd.main(["check", str(tmp_path)]) == 1
    assert "actor 应为「整理看图」" in capsys.readouterr().out


def test_kind_contradicting_char_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    d = _decisions()
    d["confirmed"]["001:1:1"] = {"char": "夭", "default": "天", "kind": "same"}  # kind=same 但字不同
    _write(tmp_path, _index(), d)
    assert chd.main(["check", str(tmp_path)]) == 1
    assert "kind=same 但 char≠default" in capsys.readouterr().out
