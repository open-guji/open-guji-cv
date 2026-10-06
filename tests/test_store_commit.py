# -*- coding: utf-8 -*-
"""`guji store check|commit` 的防呆与提交（overview#413 R5）：tmp 里现造 git 仓，不导出真库（no_export）。"""
from __future__ import annotations

import subprocess

from open_guji_cv.ops import store_commit as SC


def _repo(tmp_path):
    def git(*a):
        return subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True, text=True).stdout
    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    store = tmp_path / "output" / "glyph_store"
    store.mkdir(parents=True)
    (store / "glyphs.jsonl").write_text("".join(f'{{"id": {i}}}\n' for i in range(300)), encoding="utf-8")
    (tmp_path / "products").mkdir()
    (tmp_path / "products" / "x.json").write_text("{}", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "init")
    return git


def test_check_passes_on_additions_and_commit_only_adds_store_dirs(tmp_path):
    git = _repo(tmp_path)
    (tmp_path / "output/glyph_store/glyphs.jsonl").open("a", encoding="utf-8").write('{"id": 300}\n')
    (tmp_path / "feedback").mkdir()
    (tmp_path / "feedback/e.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "products/x.json").write_text('{"changed": 1}', encoding="utf-8")   # 不该被提交
    res = SC.run(tmp_path, commit=False, push=False, allow_deletions=False, no_export=True, message=None, fetch=False)
    assert not res.get("blocked") and res["changes"]["added_lines"] == 1 and res["changes"]["untracked"] == 1
    res = SC.run(tmp_path, commit=True, push=False, allow_deletions=False, no_export=True, message="m", fetch=False)
    assert res["committed"]
    assert "products/x.json" in git("status", "--porcelain")          # products 留在工作区没提交
    assert "feedback/e.jsonl" in git("show", "--name-only", "--format=", "HEAD")


def test_mass_deletion_blocks_unless_allowed(tmp_path):
    _repo(tmp_path)
    (tmp_path / "output/glyph_store/glyphs.jsonl").write_text('{"id": 0}\n', encoding="utf-8")   # 299 行没了
    res = SC.run(tmp_path, commit=True, push=False, allow_deletions=False, no_export=True, message=None, fetch=False)
    assert res.get("blocked") and "成片删除" in res["blocked"] and not res.get("committed")
    res = SC.run(tmp_path, commit=True, push=False, allow_deletions=True, no_export=True, message=None, fetch=False)
    assert res["committed"]


def test_no_changes_no_commit(tmp_path):
    _repo(tmp_path)
    res = SC.run(tmp_path, commit=True, push=False, allow_deletions=False, no_export=True, message=None, fetch=False)
    assert res["committed"] is None


def test_mass_deletion_rule():
    assert SC.mass_deletion({"deleted_files": [], "deleted_lines": 10, "added_lines": 0}) is None
    assert SC.mass_deletion({"deleted_files": ["a"] * 21, "deleted_lines": 0, "added_lines": 0})
    assert SC.mass_deletion({"deleted_files": [], "deleted_lines": 500, "added_lines": 2000}) is None
