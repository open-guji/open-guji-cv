# -*- coding: utf-8 -*-
"""撤销已发布的修订批：A 类改字＋B′ 插格一批发布，再撤销，char／cord／punct 回到原样；现文被后来改过就拒绝。"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from booktext_fixture import BOOK
from test_opinions_auto import A_REV, _git, _op, _pool, _tri, bt, rules  # noqa: F401  (fixtures)

from open_guji_cv.opinions import auto as A
from open_guji_cv.opinions import revert as RV
from open_guji_cv.opinions.schema import Opinion, make_id

B_REV = {"class": "B′", "cells": [{"a": "3:1:4", "after": "3:1:3", "mark": "mseal1", "from": "excluded", "to": "□",
                                   "lacuna": True, "guess": "一"}]}


def _vd(bt: Path) -> Path:
    return bt / "Book" / "x" / "y" / "z" / BOOK / "default"


def _pages(bt: Path, ref: str, name: str):
    return json.loads(_git(bt, "show", f"{ref}:Book/x/y/z/{BOOK}/default/{name}"))["pages"]


def _published(tmp_path, rules, bt):
    st = _pool(tmp_path)
    o1, o2 = st.add(_op(1)), st.add(_op(2, "3:1:4"))
    _tri(st, o1, "accept", 0.9, rev=A_REV)
    _tri(st, o2, "lacuna_guess", 0.95, rev=B_REV)
    A.decide_pending(st, rules)
    p = A.prepare(st, bt, BOOK, rules, run_checks=False, base="main", today="2026-10-23")[0]
    assert p["status"] == "checked", p
    A.finish_pr(st, bt, p["release"], 304)
    A.finish_merged(st, p["release"], "abc1234", publish_status=lambda: {"rows": 2})
    _git(bt, "checkout", "-q", "main")
    _git(bt, "merge", "-q", "--ff-only", p["branch"])           # 模拟 PR 合并
    return st, p, (o1, o2)


def test_revert_round_trip(tmp_path, rules, bt):
    st, p, (o1, o2) = _published(tmp_path, rules, bt)
    orig = _git(bt, "rev-list", "--max-parents=0", "HEAD")
    r = RV.prepare_revert(st, bt, p["release"], "图上其实是「製」", run_checks=False, base="main", today="2026-10-24")
    assert r["reverts"] == p["release"] and _git(bt, "status", "--porcelain") == ""
    for name in ("002.char.json", "002.cord.json"):
        assert _pages(bt, r["branch"], name) == _pages(bt, orig, name), name
    pu_new, pu_old = _pages_punct(bt, r["branch"]), _pages_punct(bt, orig)
    assert [(x["anchor"], x["char_offset"]) for x in pu_new] == [(x["anchor"], x["char_offset"]) for x in pu_old]
    ch = _git(bt, "show", f"{r['branch']}:Book/x/y/z/{BOOK}/default/CHANGES.md").splitlines()
    ch = next(ln for ln in ch if "撤销发布批" in ln)
    assert p["release"] in ch and o1.id in ch and "图上其实是" in ch and "#TBD" in ch
    row = st.release_latest()[r["release"]]
    assert row["kind"] == "revert" and row["status"] == "checked" and row["from"]["text"] == "1.0.2" and row["to"]["text"] == "1.0.3"
    # 同一批不能重复撤销
    with pytest.raises(A.AutoError, match="已有进行中"):
        RV.prepare_revert(st, bt, p["release"], "再来一次", run_checks=False, base="main")
    A.finish_pr(st, bt, r["release"], 310)
    out = RV.finish_revert_merged(st, r["release"], "def5678", publish_status=lambda: {"rows": 0})
    assert out["reverted"] == 2 and st.status(o1.id) == "reverted" and st.status(o2.id) == "reverted"
    assert st.last(o1.id, "reverted").data["reason"] == "图上其实是「製」"
    assert st.release_latest()[p["release"]]["status"] == "reverted"
    assert any(x.get("revert_of") == p["release"] for x in st.lineage)
    assert "不重做" in RV.finish_revert_merged(st, r["release"], "def5678")["note"]


def _pages_punct(bt: Path, ref: str):
    return json.loads(_git(bt, "show", f"{ref}:Book/x/y/z/{BOOK}/default/002.punct.json"))["punctuations"]


def test_revert_refuses_when_changed_since(tmp_path, rules, bt):
    st, p, _ = _published(tmp_path, rules, bt)
    f = _vd(bt) / "002.char.json"
    f.write_text(f.read_text(encoding="utf-8").replace("制", "製"), encoding="utf-8")
    _git(bt, "commit", "-qam", "后来又手改")
    with pytest.raises(A.AutoError, match="之后被改过"):
        RV.prepare_revert(st, bt, p["release"], "x", run_checks=False, base="main", today="2026-10-24")
    assert _git(bt, "status", "--porcelain") == "" and _git(bt, "branch", "--list", "auto/revert*") == ""
    assert _git(bt, "rev-parse", "--abbrev-ref", "HEAD") == "main"


def test_revert_needs_reason_and_published(tmp_path, rules, bt):
    st, p, _ = _published(tmp_path, rules, bt)
    with pytest.raises(A.AutoError, match="理由"):
        RV.prepare_revert(st, bt, p["release"], " ", run_checks=False, base="main")
    with pytest.raises(A.AutoError, match="没有发布批"):
        RV.prepare_revert(st, bt, "rel_nope", "x", run_checks=False, base="main")
