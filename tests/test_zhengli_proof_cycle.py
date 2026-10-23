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
    for step in ("写人裁并消费", "推库", "取出单版产物包到沙箱", "重跑 2 页到 seed_admit", "导出", "出新单 006-r4", "推单", "推 book-text 分支"):
        assert step in log, step
    assert "--held-file" in log and "--pages 3,12" in log
