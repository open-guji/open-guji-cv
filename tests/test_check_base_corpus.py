# -*- coding: utf-8 -*-
"""发版前核对底库（scripts/check_base_corpus.py）：自造一个小引擎仓，清单对得上 0、改了文件 1。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check_base_corpus", ROOT / "scripts" / "check_base_corpus.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


def _repo(tmp_path):
    r = tmp_path / "repo"
    (r / "config" / "ids").mkdir(parents=True)
    (r / "config" / "ids" / "a.txt").write_text("一\n", encoding="utf-8")
    (r / "config" / "ids" / "README.md").write_text("说明\n", encoding="utf-8")     # 不算语料
    return r


def _manifest(tmp_path, repo):
    items = [{"root": "repo", "path": p, "sha256": s} for p, s in M.repo_items(repo).items()]
    mp = tmp_path / "b3.json"
    mp.write_text(json.dumps({"base_version": 3, "items": items}), encoding="utf-8")
    return mp


def test_same_is_zero(tmp_path, capsys):
    repo = _repo(tmp_path)
    mp = _manifest(tmp_path, repo)
    assert list(M.repo_items(repo)) == ["config/ids/a.txt"]
    assert M.main(["--manifest", str(mp), "--repo", str(repo)]) == 0


def test_changed_and_extra_is_one(tmp_path, capsys):
    repo = _repo(tmp_path)
    mp = _manifest(tmp_path, repo)
    (repo / "config" / "ids" / "a.txt").write_text("二\n", encoding="utf-8")
    (repo / "config" / "ids" / "b.txt").write_text("三\n", encoding="utf-8")
    assert M.main(["--manifest", str(mp), "--repo", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "改了 1" in out and "新增 1" in out and "b4" in out


def test_missing_manifest_is_two(tmp_path):
    assert M.main(["--manifest", str(tmp_path / "nope.json"), "--repo", str(tmp_path)]) == 2
