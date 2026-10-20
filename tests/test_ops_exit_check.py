# -*- coding: utf-8 -*-
"""ops/exit_check.py（`guji exit-check`，M10 G8，GUJI-685）：自造 book-text 目录，不碰真书。"""
from __future__ import annotations

import json
from pathlib import Path

from open_guji_cv.ops import exit_check as EC

FREEZE = {"at": "1.0.0", "snapshot": "snap/x/vol01/T1", "cv_commit": "a" * 40, "cv_version": "0.4.5"}
REVIEW = {"date": "2026-10-20", "signed_by": "u", "sample": {"n": 10}}


def _text_dir(tmp_path: Path, *, version="1.0.0", proofing=False, review=REVIEW, lacuna_char="",
              decision=True) -> Path:
    d = tmp_path / "default"
    d.mkdir()
    ch = {"n": 1, "file": "001", "char_file": "001.char.json", "text_version": version}
    if proofing:
        ch["proofing"] = True
    (d / "index.json").write_text(json.dumps({"chapters": [ch]}), encoding="utf-8")
    char = {"pages": [{"page": 52, "columns": [{"col": 2, "cells": [
        {"a": "52:2:1", "c": lacuna_char or "□", "lacuna": True}, {"a": "52:2:2", "c": "定"}]}]}]}
    if review:
        char["review"] = review
    (d / "001.char.json").write_text(json.dumps(char, ensure_ascii=False), encoding="utf-8")
    if decision:
        (d / "001.decision.json").write_text("{}", encoding="utf-8")
    return d


def _by_id(res):
    return {it["id"]: it["ok"] for it in res["items"]}


def test_all_pass(tmp_path):
    d = _text_dir(tmp_path)
    res = EC.run(d, "001", FREEZE, "0.4.5", tag_lookup=lambda repo, c: ["freeze/x"])
    assert res["ok"] and all(v is True for v in _by_id(res).values())


def test_vol01_like_failures(tmp_path):
    d = _text_dir(tmp_path, version="1.0.1", proofing=True, review=None, lacuna_char="定", decision=False)
    res = EC.run(d, "001", FREEZE, None, tag_lookup=lambda repo, c: [])
    ok = _by_id(res)
    assert not res["ok"]
    assert ok == {"E1": False, "E2": False, "E3": False, "E4": False, "E5": True,
                  "E6": False, "E7": False, "E8": False}


def test_pre_1_0_not_applicable(tmp_path):
    d = _text_dir(tmp_path, version="0.2.2", proofing=True, review=None)
    res = EC.run(d, "001", FREEZE, "0.4.5", tag_lookup=lambda repo, c: ["v0.4.5"])
    ok = _by_id(res)
    assert ok["E1"] is None and ok["E2"] is None and ok["E7"] is None
    assert res["ok"]


def test_missing_freeze_and_git_unavailable(tmp_path):
    d = _text_dir(tmp_path)
    res = EC.run(d, "001", {}, "0.4.5", tag_lookup=lambda repo, c: None)
    ok = _by_id(res)
    assert ok["E5"] is False and ok["E6"] is False and ok["E8"] is False   # 没 cv_commit 就不查 git
    res2 = EC.run(d, "001", FREEZE, "0.4.5", tag_lookup=lambda repo, c: None)
    assert _by_id(res2)["E8"] is None


def test_unknown_chapter(tmp_path):
    d = _text_dir(tmp_path)
    try:
        EC.run(d, "009", FREEZE, "0.4.5", tag_lookup=lambda repo, c: [])
    except FileNotFoundError:
        return
    raise AssertionError("应报找不到章")
