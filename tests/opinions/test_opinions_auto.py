# -*- coding: utf-8 -*-
"""意见池自动化调和器：自动结案、聚批改文本（真 git 仓里建分支提交）、收尾落库、汇总。
桩 bump 脚本与自造 book-text 同 test_opinions_revise；真 book-text 的 local_check 不在测试里跑（run_checks=False）。"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from booktext_fixture import BOOK, CHANGES_101, make
from test_opinions_revise import BUMP_STUB

from open_guji_cv.opinions import auto as A
from open_guji_cv.opinions import rules as R
from open_guji_cv.opinions.schema import Opinion, make_id
from open_guji_cv.opinions.store import LocalBackend, OpinionStore


def _git(root: Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def bt(tmp_path, monkeypatch) -> Path:
    for k, v in (("NAME", "t"), ("EMAIL", "t@example.com")):
        monkeypatch.setenv(f"GIT_AUTHOR_{k}", v)
        monkeypatch.setenv(f"GIT_COMMITTER_{k}", v)
    root = tmp_path / "bt"
    make(root, changes=CHANGES_101)
    s = root / "scripts" / "book-text" / "bump_original.py"
    s.parent.mkdir(parents=True)
    s.write_text(BUMP_STUB, encoding="utf-8")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


@pytest.fixture
def rules() -> dict:
    return R.load_rules()


def _op(i: int, start: str = "3:2:1") -> Opinion:
    return Opinion(id=make_id("charfix", f"k{i}"), book=BOOK, vol="002", channel="charfix", raw_id=f"r{i}",
                   ts=f"2026-10-20T00:00:0{i}Z", target={"start": start, "end": start, "text_version": "1.0.1"},
                   category="wrong")


def _tri(st, op, verdict, conf, rule=("交用户",), rev=None, public="图上如此。"):
    st.log(op.id, "triaged", {"verdict": verdict, "confidence": conf, "rationale_public": public, "judge": "t",
                              "route": "to_user", "rule": list(rule), **({"revision": rev} if rev else {})})


def _pool(tmp_path) -> OpinionStore:
    return OpinionStore(BOOK, LocalBackend(tmp_path / "pool" / BOOK)).load()


A_REV = {"class": "A", "cells": [{"a": "3:2:1", "from": "製", "to": "制"}]}


def test_decide_pending_rules(tmp_path, rules):
    st = _pool(tmp_path)
    ops = [st.add(_op(i)) for i in range(1, 7)]
    _tri(st, ops[0], "accept", 0.9, rev=A_REV)                                        # 自动采纳
    _tri(st, ops[1], "text_ok", 0.9)                                                  # 自动驳回
    _tri(st, ops[2], "seg_issue", 0.99, rev={"class": "C", "cells": [{"a": "3:2:1"}]})   # C 类留着
    _tri(st, ops[3], "accept", 0.99, rule=("疑似刷票：同格 5 个来源",), rev=A_REV)      # 命中保护原因留着
    _tri(st, ops[4], "accept", 0.5, rev=A_REV)                                        # 置信低留着
    _tri(st, ops[5], "lacuna_guess", 0.95, rev={"class": "B′", "cells": [{"a": "3:1:4", "after": "3:1:3", "mark": "m"}]})
    rows = {r["id"]: r for r in A.decide_pending(st, rules)}
    act = [rows[o.id]["action"] for o in ops]
    assert act == ["accept", "reject", "park", "park", "park", "accept"]
    assert st.status(ops[0].id) == "accepted" and st.status(ops[1].id) == "rejected"
    assert st.status(ops[2].id) == "to_user"
    d = st.last(ops[0].id, "decided")
    assert d.by == "policy:auto-v1" and d.data["auto"] is True and d.data["decision"] == "accept"
    # 再跑一遍不重复结案
    assert [r["action"] for r in A.decide_pending(st, rules)] == ["park", "park", "park"]


def test_auto_switch_off(tmp_path, rules):
    st = _pool(tmp_path)
    o = st.add(_op(1))
    _tri(st, o, "accept", 0.99, rev=A_REV)
    rules["auto"]["enabled"] = False
    assert A.decide_pending(st, rules) == [] and st.status(o.id) == "to_user"


def test_prepare_finish_pr_and_merged(tmp_path, rules, bt):
    st = _pool(tmp_path)
    o = st.add(_op(1))
    _tri(st, o, "accept", 0.9, rev=A_REV)
    A.decide_pending(st, rules)
    plans = A.prepare(st, bt, BOOK, rules, run_checks=False, base="main", trailers=["Co-Authored-By: t <t@example.com>"],
                      today="2026-10-23")
    assert len(plans) == 1 and plans[0]["status"] == "checked"
    p = plans[0]
    assert p["branch"] == f"auto/{BOOK}-002-2026-10-23" and p["release"] == f"rel_{BOOK}_002_1.0.2"
    assert p["merge_ok"][0] is False                      # 缺省不自动合并
    assert _git(bt, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert _git(bt, "status", "--porcelain") == ""
    assert "制" in _git(bt, "show", f"{p['branch']}:Book/x/y/z/{BOOK}/default/002.char.json")
    assert "Co-Authored-By" in _git(bt, "log", "-1", "--format=%B", p["branch"])
    rel = st.release_latest()[p["release"]]
    assert rel["status"] == "checked" and rel["opinions"] == [o.id] and rel["cells"][0]["a"] == "3:2:1"
    assert rel["to"]["text"] == "1.0.2" and rel["from"]["text"] == "1.0.1"
    assert st.status(o.id) == "accepted" and st.last(o.id, "batched").data == {"release": p["release"]}
    # 已在批里的不会进第二批
    assert A.prepare(st, bt, BOOK, rules, run_checks=False, base="main") == []

    fp = A.finish_pr(st, bt, p["release"], 304)
    assert fp["changes_lines_fixed"] == 2                  # 文本、标点各一行（这格没有实体）
    ch = _git(bt, "show", f"{p['branch']}:Book/x/y/z/{BOOK}/default/CHANGES.md")
    assert "#TBD" not in ch and "#304" in ch and "#300" not in ch.splitlines()[-1]
    assert st.release_latest()[p["release"]]["status"] == "pr_open"
    assert st.last(o.id, "pr_opened").data["pr"] == "304"

    seen = {}
    out = A.finish_merged(st, p["release"], "abc1234", publish_status=lambda: seen.setdefault("n", 1) and {"rows": 1})
    assert out["applied"] == 1 and st.status(o.id) == "applied"
    assert st.last(o.id, "applied").data["text_version"] == "1.0.2" and st.last(o.id, "published")
    assert st.release_latest()[p["release"]]["status"] == "published"
    assert st.lineage[0]["cell"] == "3:2:1" and st.lineage[0]["after"]["c"] == "制" and st.lineage[0]["opinion"] == o.id
    assert st.metrics[0]["auto_decided"] == 1 and st.metrics[0]["cells"] == 1
    # 结案后再调不重做
    assert "不重做" in A.finish_merged(st, p["release"], "abc1234")["note"]
    # 落盘再读回来一致
    st.save()
    st2 = _pool(tmp_path)
    assert st2.status(o.id) == "applied" and len(st2.release_latest()) == 1 and len(st2.releases) >= 4
    assert len(st2.lineage) == 1 and len(st2.metrics) == 1


def test_prepare_holds_protected_and_duplicates(tmp_path, rules, bt):
    st = _pool(tmp_path)
    a, b, c = st.add(_op(1)), st.add(_op(2)), st.add(_op(3, "3:2:5"))
    for o, rev in ((a, A_REV), (b, A_REV), (c, {"class": "A", "cells": [{"a": "3:2:5", "from": "文", "to": "紋"}]})):
        _tri(st, o, "accept", 0.9, rev=rev)
    A.decide_pending(st, rules)
    take, held = A.select(st, "002", rules, human_cells={"3:2:5"})
    assert [o.id for o, _ in take] == [a.id]
    reasons = {h["id"]: h["reason"] for h in held}
    assert "保护格" in reasons[c.id] and "同一格" in reasons[b.id]
    rules["auto"]["batch"]["max_cells"] = 1
    take, held = A.select(st, "002", rules)
    assert [o.id for o, _ in take] == [a.id] and any("超过一批" in h["reason"] for h in held if h["id"] == c.id)


def test_prepare_failure_leaves_no_residue(tmp_path, rules, bt):
    st = _pool(tmp_path)
    o = st.add(_op(1))
    _tri(st, o, "accept", 0.9, rev={"class": "A", "cells": [{"a": "3:2:1", "from": "错", "to": "制"}]})   # from 对不上现文
    A.decide_pending(st, rules)
    plans = A.prepare(st, bt, BOOK, rules, run_checks=False, base="main", today="2026-10-23")
    assert plans[0]["status"] == "failed" and "版本对不上" in plans[0]["error"]
    assert _git(bt, "status", "--porcelain") == "" and _git(bt, "branch", "--list", "auto/*") == ""
    assert _git(bt, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    rel = next(iter(st.release_latest().values()))
    assert rel["status"] == "failed" and st.status(o.id) == "accepted"
    assert A.in_flight(st) == set()                        # 失败的批不占住意见


def test_merge_ok_policy(rules):
    rel = {"checks": {"local_check": "pass"}, "diff": {"cells": 3}, "protected_conflicts": 0}
    assert A.merge_ok(rel, rules)[0] is False
    rules["auto"]["merge"]["enabled"] = True
    assert A.merge_ok(rel, rules)[0] is True
    assert A.merge_ok({**rel, "checks": {"local_check": "fail"}}, rules)[0] is False
    assert A.merge_ok({**rel, "diff": {"cells": 99}}, rules)[0] is False
    assert A.merge_ok({**rel, "protected_conflicts": 1}, rules)[0] is False


def test_digest_sections(tmp_path, rules):
    st = _pool(tmp_path)
    a, b = st.add(_op(1)), st.add(_op(2))
    _tri(st, a, "accept", 0.9, rev=A_REV)
    _tri(st, b, "unclear", 0.4, rule=("看不清，交用户",))
    A.decide_pending(st, rules)
    md = A.digest(st, rules)
    assert "## 自动结案（1 条）" in md and "## 留着的（1 条" in md and "看不清" in md and "自动合并关" in md
