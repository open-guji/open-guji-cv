# -*- coding: utf-8 -*-
"""scripts/zhengli/proof_cycle.py（一轮精校的计划＋执行，GUJI-730 P1-2）：只测计划、核对和演练，不连网。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "zhengli"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("zl_proof_cycle", SCRIPTS / "proof_cycle.py")
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)


def _ws(tmp_path):
    ws = tmp_path / "abc123-书"
    online = ws / "feedback" / "lists" / "proofing" / "abc123" / "006.pending.json"
    online.parent.mkdir(parents=True)
    online.write_text(json.dumps({"rev": "006-r3", "cells": []}), encoding="utf-8")
    draft = ws / "reports" / "vol06" / "_cycle" / "006-r3" / "draft"
    draft.mkdir(parents=True)
    (draft / "drafts.jsonl").write_text("\n".join(json.dumps({"id": k, "v": "confirm", "shape": "甲"})
                                                  for k in ("vol06:12:3:4", "vol06:3:1:1", "vol06:12:9:2a")) + "\n", encoding="utf-8")
    (draft / "held.tsv").write_text("格位\t拟写\t理由\t票\n", encoding="utf-8")
    plan = {"book": "vol06", "text_id": "abc123", "chapter": "006", "rev": "006-r3", "batch": "H-web-vol06-x",
            "reviewer": "sheldon", "draft_dir": str(draft), "drafts_sha": pc.sha_file(draft / "drafts.jsonl"),
            "ready": 3, "held": 0, "skipped": 0, "votes": 3, "votes_from": "测试", "pack": "rev-006-r3",
            "pack_cv_commit": "abcdef1234", "pack_cv_version": "0.5.7", "cord": None, "pages": [3, 12], "created": "t"}
    plan["hash"] = pc.plan_hash(plan)
    p = draft.parent / "plan.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    return ws, plan, p


def test_voted_pages_and_hash(tmp_path):
    ws, plan, _ = _ws(tmp_path)
    assert pc.voted_pages(Path(plan["draft_dir"]) / "drafts.jsonl") == [3, 12]
    assert pc.plan_hash(plan) == plan["hash"] and pc.plan_hash({**plan, "ready": 4}) != plan["hash"]


def test_verify_catches_every_drift(tmp_path, monkeypatch):
    ws, plan, _ = _ws(tmp_path)
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    assert pc.verify(plan, plan["hash"], ws) == []
    assert any("哈希" in b for b in pc.verify(plan, "0" * 16, ws))
    assert any("哈希" in b for b in pc.verify({**plan, "ready": 99}, plan["hash"], ws))     # 计划被改过
    d = Path(plan["draft_dir"]) / "drafts.jsonl"
    d.write_text(d.read_text(encoding="utf-8") + json.dumps({"id": "vol06:1:1:1"}) + "\n", encoding="utf-8")
    assert any("草稿" in b for b in pc.verify(plan, plan["hash"], ws))
    online = ws / "feedback" / "lists" / "proofing" / "abc123" / "006.pending.json"
    online.write_text(json.dumps({"rev": "006-r4"}), encoding="utf-8")
    assert any("006-r4" in b for b in pc.verify(plan, plan["hash"], ws))


def test_apply_refuses_bad_hash_and_cv_drift(tmp_path, monkeypatch):
    ws, plan, p = _ws(tmp_path)
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    base = ["apply", "--book", "vol06", "-w", str(ws), "--plan", str(p), "--book-text", str(tmp_path / "bt"), "--dry-run"]
    with pytest.raises(SystemExit, match="对不上"):
        pc.main(base + ["--hash", "0" * 16])
    monkeypatch.setattr(pc.rp, "git_head", lambda: "9999999999")
    with pytest.raises(SystemExit, match="worktree"):
        pc.main(base + ["--hash", plan["hash"]])


def test_apply_dry_run_lists_every_step(tmp_path, monkeypatch):
    ws, plan, p = _ws(tmp_path)
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    monkeypatch.setattr(pc.rp, "git_head", lambda: "abcdef1234ffff")
    monkeypatch.setattr(pc.rp, "online_text_version", lambda repo, tid, ch: "0.5.0")
    assert pc.main(["apply", "--book", "vol06", "-w", str(ws), "--plan", str(p), "--hash", plan["hash"],
                    "--book-text", str(tmp_path / "bt"), "--dry-run"]) == 0
    log = (p.parent / "执行记录.md").read_text(encoding="utf-8")
    for step in ("写人裁并消费", "推库", "取出单版产物包到沙箱", "重跑 2 页到 seed_admit", "导出", "出新单 006-r4", "文本升版已推到 dev"):
        assert step in log, step
    assert "--held-file" in log and "--pages 3,12" in log and "republish.py issue" in log


def test_apply_full_book_with_pinned_engine(tmp_path, monkeypatch):
    """plan 记了 full_book 和 engine：全册 seed_admit、在引擎 worktree 里跑；核的是引擎的 HEAD。"""
    ws, plan, p = _ws(tmp_path)
    eng = tmp_path / "cv-v057"
    eng.mkdir()
    plan.update(full_book=True, engine=str(eng), engine_commit="abcdef1234")
    plan["hash"] = pc.plan_hash(plan)
    p.write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    monkeypatch.setattr(pc.rp, "git_head", lambda: "9999999999")          # 本仓是 dev：不碍事
    monkeypatch.setattr(pc, "engine_head", lambda e: "abcdef1234ffff" if Path(e) == eng else "9999")
    monkeypatch.setattr(pc.rp, "online_text_version", lambda repo, tid, ch: "0.5.0")
    assert pc.main(["apply", "--book", "vol06", "-w", str(ws), "--plan", str(p), "--hash", plan["hash"],
                    "--book-text", str(tmp_path / "bt"), "--dry-run"]) == 0
    log = (p.parent / "执行记录.md").read_text(encoding="utf-8")
    assert "全册重跑 seed_admit" in log and "--pages" not in log


def _char(tmp_path, name, cells):
    f = tmp_path / name
    f.write_text(json.dumps({"pages": [{"page": 3, "columns": [{"col": 1, "cells": [{"a": a, **({"c": c} if c else {})}
                                                                                    for a, c in cells]}]}]}), encoding="utf-8")
    return f


def test_split_changes_human_vs_machine_and_revert(tmp_path):
    """变了的格：最新人裁就是新字＝人裁改字；其余机器改判，文本退回旧字。"""
    old = _char(tmp_path, "old.json", [("3:1:1", "宫"), ("3:1:2", ""), ("3:1:3", "象"), ("3:1:4", "甲")])
    new = _char(tmp_path, "new.json", [("3:1:1", "官"), ("3:1:2", "論"), ("3:1:3", "彖"), ("3:1:4", "甲")])
    sp = pc.split_changes(old, new, {"3:1:2": "論", "3:1:3": "象"})
    assert sp == {"human": [("3:1:2", "", "論")], "machine": [("3:1:1", "宫", "官"), ("3:1:3", "象", "彖")]}
    pc.revert_cells(new, {a: o for a, o, _ in sp["machine"]})
    assert pc._cells(new) == {"3:1:1": "宫", "3:1:2": "論", "3:1:3": "象", "3:1:4": "甲"}


def test_status_done_when_all_voted_or_idle(tmp_path, monkeypatch):
    ws = tmp_path / "abc123-书"
    online = ws / "feedback" / "lists" / "proofing" / "abc123" / "006.pending.json"
    online.parent.mkdir(parents=True)
    online.write_text(json.dumps({"rev": "006-r4", "cells": [{"cell": c, "review": "pending"} for c in ("1:1:1", "1:1:2")]
                                  + [{"cell": "1:1:3", "review": "human"}]}), encoding="utf-8")
    import time
    v = lambda a, ago: {"book": "abc123", "rev": "006-r4", "a": a, "choice": "char", "char": "甲", "voter": "u", "ts": (time.time() - ago * 60) * 1000}
    monkeypatch.setattr(pc.rp, "old_rev_votes", lambda ws_, t, r: ([v("1:1:1", 5)], "测试"))
    st = pc.sheet_status(ws, "vol06")
    assert (st["cells"], st["voted"], st["done"]) == (2, 1, False)
    assert pc.sheet_status(ws, "vol06", share=0.5, idle_min=3)["done"] is True
    monkeypatch.setattr(pc.rp, "old_rev_votes", lambda ws_, t, r: ([v("1:1:1", 5), v("1:1:2", 1)], "测试"))
    assert pc.sheet_status(ws, "vol06")["why"] == "全投完"


def test_merge_recheck_adds_and_overrides(tmp_path):
    dst, extra = tmp_path / "recheck.tsv", tmp_path / "extra.tsv"
    dst.write_text(pc.RECHECK_HEAD + "4:4:6\t机器改判\t\t\t\n9:6:10\t旧说明\t\t\t\n", encoding="utf-8")
    extra.write_text(pc.RECHECK_HEAD + "vol06:9:6:10\t重标疑为「日」\tevt_x\t曰\t2026-10-24T02:01:33Z\n"
                     "18:1:3\t重标疑为「日」\tevt_y\t曰\t2026-10-24T02:01:33Z\n", encoding="utf-8")
    assert pc.merge_recheck(dst, extra) == 2
    rows = [ln.split("\t") for ln in dst.read_text(encoding="utf-8").splitlines()[1:]]
    assert [r[0] for r in rows] == ["4:4:6", "9:6:10", "18:1:3"]
    assert rows[1][1:4] == ["重标疑为「日」", "evt_x", "曰"]


def test_engine_version_from_tag(tmp_path):
    import subprocess as sp
    g = lambda *a: sp.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=tmp_path, check=True, capture_output=True)
    g("init", "-q"); (tmp_path / "x").write_text("1"); g("add", "x"); g("commit", "-qm", "a")
    assert pc.engine_version(tmp_path) is None
    g("tag", "v0.5.17")
    assert pc.engine_version(tmp_path) == "0.5.17"
