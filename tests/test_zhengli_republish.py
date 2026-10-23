# -*- coding: utf-8 -*-
"""scripts/zhengli/republish.py（重跑后重发待审单，GUJI-680）：自造产物、线上单与人裁事件，不碰真书。"""
from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "zhengli" / "republish.py"
spec = importlib.util.spec_from_file_location("zhengli_republish", SCRIPT)
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)


def test_next_rev_and_ids(tmp_path):
    assert rp.next_rev("006-r2", "006") == "006-r3"
    assert rp.next_rev(None, "006") == "006-r0"
    assert rp.chapter_of("vol06") == "006"
    assert rp.text_id_of(tmp_path / "96mid1ogzk-欽定四庫全書總目") == "96mid1ogzk"
    assert sorted(["10:1:1", "2:3:4b", "2:3:4a", "2:10:1"], key=rp._key) == ["2:3:4a", "2:3:4b", "2:10:1", "10:1:1"]


def test_diff_explains_each_removed_cell():
    old = {"rev": "006-r2", "cells": [{"cell": c} for c in ("1:1:1", "1:1:2", "1:1:3", "1:1:4", "1:1:5")]}
    new = {"rev": "006-r3", "cells": [{"cell": "1:1:4"}, {"cell": "2:1:1", "cls": "near_form"}]}
    d = rp.diff(old, new, dropped=[{"cell": "1:1:1"}], states={"1:1:2": ("admit", "己"), "1:1:5": ("excluded", None)}, votes=Counter({"1:1:4": 2}))
    assert (d["old"], d["new"], d["kept"]) == (5, 2, 1)
    assert [(x["cell"], x["why"]) for x in d["removed"]] == [
        ("1:1:1", "人裁过"), ("1:1:2", "机器放行「己」"), ("1:1:3", "格号没了（多半重切）"), ("1:1:5", "排除名单（非字）")]
    assert d["added"] == [{"cell": "2:1:1", "cls": "near_form"}]
    assert d["votes_on_old"] == 2 and d["voted_cells_kept"] == ["1:1:4"]
    md = rp.diff_md("vol06", d, team=0, reflow=0)
    assert "006-r2 → 006-r3" in md and "精校票 2 张" in md


def _setup(tmp_path):
    """没迁中心库的工作区（数据根就是工作区）：一页产物、一张线上单、一条人裁事件、一份 cord。"""
    ws = tmp_path / "abc123-书"
    seed = ws / "products" / "vol06" / "seed_admit"
    seed.mkdir(parents=True)
    seed.joinpath("p0001.json").write_text(json.dumps({"seed_admit": {"n_review": 3, "columns": [{"chars": [
        {"id": "vol06:1:1:1", "admit": True, "char": "己"},
        {"id": "vol06:1:1:2", "admit": False, "doubts": ["lib_miss"]},
        {"id": "vol06:1:1:3", "admit": False},
        {"id": "vol06:1:1:4", "admit": False},
    ]}]}}), encoding="utf-8")
    online = ws / "feedback" / "lists" / "proofing" / "abc123" / "006.pending.json"
    online.parent.mkdir(parents=True)
    online.write_text(json.dumps({"rev": "006-r2", "cells": [{"cell": c, "review": "pending"} for c in
                                                             ("1:1:1", "1:1:2", "1:1:9")]}), encoding="utf-8")
    ev = ws / "feedback" / "events"
    ev.mkdir(parents=True)
    ev.joinpath("a.jsonl").write_text(json.dumps({"kind": "confirm", "ts": "2026-10-20T00:00:00Z",
                                                  "target": {"unit": "cell", "key": "vol06:1:1:3"},
                                                  "payload": {"v": "confirm", "shape": "甲"}}) + "\n", encoding="utf-8")
    export = ws / "reports" / "vol06" / "_export"
    export.mkdir(parents=True)
    export.joinpath("006.cord.json").write_text("{}", encoding="utf-8")
    return ws, export, online


def test_prep_then_push(tmp_path, monkeypatch, capsys):
    ws, export, online = _setup(tmp_path)
    monkeypatch.delenv("GUJI_PRODUCTS_DIR", raising=False)
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    assert rp.main(["prep", "--book", "vol06", "-w", str(ws), "--export-dir", str(export),
                    "--no-alt", "--no-sprite", "--cv-commit", "abc1234"]) == 0
    out = ws / "reports" / "vol06" / "_publish" / "006-r3"
    new = json.loads((out / "006.pending.json").read_text(encoding="utf-8"))
    assert new["rev"] == "006-r3" and [c["cell"] for c in new["cells"]] == ["1:1:2", "1:1:4"]   # 1:1:3 人裁过，扣掉
    d = json.loads((out / "diff.json").read_text(encoding="utf-8"))
    assert {x["cell"]: x["why"] for x in d["removed"]} == {"1:1:1": "机器放行「己」", "1:1:9": "格号没了（多半重切）"}
    assert [x["cell"] for x in d["added"]] == ["1:1:4"]
    assert json.loads(online.read_text(encoding="utf-8"))["rev"] == "006-r2"                  # prep 不碰线上单

    with pytest.raises(SystemExit):                                                             # 不给 --yes 不推
        rp.main(["push", "--book", "vol06", "-w", str(ws), "--rev", "006-r3"])
    monkeypatch.setattr(rp, "run", lambda cmd, **kw: None)                                      # 台账脚本另有测试
    assert rp.main(["push", "--book", "vol06", "-w", str(ws), "--rev", "006-r3", "--yes"]) == 0
    assert json.loads(online.read_text(encoding="utf-8"))["rev"] == "006-r3"
    assert (out / "online.006-r2.pending.json").exists()
    assert "book-text" in capsys.readouterr().out


def test_push_refuses_while_old_votes_unlanded(tmp_path, monkeypatch):
    """旧单 006-r2 上有票没落成人裁就不换单（G0）；看不出的票、已有人裁的格不算；--ack-unlanded-votes 照换。"""
    ws, export, online = _setup(tmp_path)
    monkeypatch.delenv("GUJI_PRODUCTS_DIR", raising=False)
    monkeypatch.delenv("CELLREVIEW_TOKEN", raising=False)
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    assert rp.main(["prep", "--book", "vol06", "-w", str(ws), "--export-dir", str(export),
                    "--no-alt", "--no-sprite", "--cv-commit", "abc1234"]) == 0
    web = ws / "feedback" / "lists" / "web" / "abc123" / "006-r2.jsonl"
    web.parent.mkdir(parents=True)
    vote = lambda a, choice, ch="": {"book": "abc123", "rev": "006-r2", "a": a, "choice": choice, "char": ch, "voter": "u1", "ts": 1}
    web.write_text("\n".join(json.dumps(v) for v in (
        vote("1:1:3", "char", "甲"),          # 已有人裁：落了
        vote("1:1:9", "unsure"),              # 看不出：不用落
        vote("1:1:2", "char", "乙"),          # 没落
    )) + "\n", encoding="utf-8")
    monkeypatch.setattr(rp, "run", lambda cmd, **kw: None)
    push = ["push", "--book", "vol06", "-w", str(ws), "--rev", "006-r3", "--yes"]
    with pytest.raises(SystemExit, match="1:1:2"):
        rp.main(push)
    assert json.loads(online.read_text(encoding="utf-8"))["rev"] == "006-r2"                  # 门在动任何东西之前
    assert rp.main(push + ["--ack-unlanded-votes", "测试"]) == 0
    assert json.loads(online.read_text(encoding="utf-8"))["rev"] == "006-r3"


def test_sync_then_publish_web(tmp_path, monkeypatch):
    """推库成功才触发网站 proofing-sync；sync 失败、--no-publish-web、没有 gh 都不触发。"""
    import argparse
    import subprocess
    calls = []

    def fake_run(rc_sync):
        def _run(cmd, **kw):
            cmd = [str(c) for c in cmd]
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, rc_sync if "sync" in cmd else 0, "", "")
        return _run

    monkeypatch.setattr(rp.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(rp, "run", fake_run(0))
    assert rp.sync_and_publish(argparse.Namespace(no_publish_web=False), tmp_path) is True
    assert calls[-1][:3] == ["gh", "workflow", "run"] and "parts=publish" in calls[-1] and "dry_run=false" in calls[-1] and "--ref" in calls[-1]

    calls.clear()
    monkeypatch.setattr(rp, "run", fake_run(1))
    assert rp.sync_and_publish(argparse.Namespace(no_publish_web=False), tmp_path) is False
    assert not any(c[0] == "gh" for c in calls)

    calls.clear()
    monkeypatch.setattr(rp, "run", fake_run(0))
    assert rp.sync_and_publish(argparse.Namespace(no_publish_web=True), tmp_path) is False
    monkeypatch.setattr(rp.shutil, "which", lambda name: None)
    assert rp.sync_and_publish(argparse.Namespace(no_publish_web=False), tmp_path) is False
    assert not any(c[0] == "gh" for c in calls)


def test_from_pack_helpers(tmp_path, monkeypatch):
    d = tmp_path / "bt" / "Book" / "g" / "z" / "k" / "96mid1ogzk" / "default"
    d.mkdir(parents=True)
    (d / "index.json").write_text(json.dumps({"chapters": [{"n": 5, "file": "005", "text_version": "0.2.0"}]}), encoding="utf-8")
    assert rp.online_text_version(tmp_path / "bt", "96mid1ogzk", "005") == "0.2.0"
    with pytest.raises(SystemExit):
        rp.online_text_version(tmp_path / "bt", "96mid1ogzk", "006")
    b = {"events": 3, "status": {"valid": 2, "review": 1}, "newer": [], "id_mismatch": ["vol05:3:1:2"],
         "unbound": ["vol05:3:1:2"], "decided_not_admitted": []}
    md = "\n".join(rp.bind_md(b))
    assert "定字人裁 3 条" in md and "绑不上的 1 格不扣" in md and "`vol05:3:1:2`" in md
    monkeypatch.delenv("GUJI_PRODUCTS_DIR", raising=False)        # 不给沙箱产物根就不取包，免得覆盖正式 products/
    with pytest.raises(SystemExit, match="GUJI_PRODUCTS_DIR"):
        rp.main(["from-pack", "--book", "vol05", "-w", str(tmp_path), "--label", "x"])


def test_prep_stops_when_alt_fails(tmp_path, monkeypatch):
    """audit alt 出不来相似字（10-21 殿本：包里没有字块图缓存）就停，不照发一张没有相似字的单子。"""
    ws, export, _ = _setup(tmp_path)
    monkeypatch.delenv("GUJI_PRODUCTS_DIR", raising=False)
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    monkeypatch.setattr(rp, "run", lambda cmd, **kw: type("P", (), {"returncode": 1})())
    with pytest.raises(SystemExit, match="--no-alt"):
        rp.main(["prep", "--book", "vol06", "-w", str(ws), "--export-dir", str(export), "--no-sprite"])


def test_add_alt_patches_online_in_place(tmp_path, monkeypatch):
    ws, _, online = _setup(tmp_path)
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps([{"id": "vol06:1:1:1", "alt": [{"c": "已", "s": 0.91234, "p": "己", "src": "v"}]},
                                 {"id": "vol06:1:1:2", "alt": [{"c": "巳", "s": 0.8, "p": "己", "src": "rt"}]}]),
                     encoding="utf-8")
    before = json.loads(online.read_text(encoding="utf-8"))
    assert rp.main(["add-alt", "--book", "vol06", "-w", str(ws), "--cards", str(cards)]) == 0
    assert json.loads(online.read_text(encoding="utf-8")) == before                            # 不给 --yes 不写回
    assert rp.main(["add-alt", "--book", "vol06", "-w", str(ws), "--cards", str(cards), "--yes"]) == 0
    after = json.loads(online.read_text(encoding="utf-8"))
    assert after["rev"] == "006-r2"                                                             # 不换 rev，已投的票照旧有效
    assert [c["cell"] for c in after["cells"]] == ["1:1:1", "1:1:2", "1:1:9"]
    assert after["cells"][0]["alt"] == [{"c": "已", "s": 0.9123, "p": "己", "src": "v"}]
    assert "alt" not in after["cells"][2]                                                       # 卡片里没有的格不补
    cards.write_text(json.dumps([{"id": "vol06:1:1:1", "alt": [{"c": "○", "s": 0.97, "p": "○", "src": "piv"}]}]), encoding="utf-8")
    assert rp.main(["add-alt", "--book", "vol06", "-w", str(ws), "--cards", str(cards), "--yes"]) == 0
    assert json.loads(online.read_text(encoding="utf-8"))["cells"][0]["alt"][0]["c"] == "已"      # 不加 --replace 不动已有的
    assert rp.main(["add-alt", "--book", "vol06", "-w", str(ws), "--cards", str(cards), "--yes", "--replace"]) == 0
    after = json.loads(online.read_text(encoding="utf-8"))
    assert after["cells"][0]["alt"][0]["c"] == "○" and after["cells"][1]["alt"][0]["c"] == "巳"


def test_pack_rev_stores_issue_products(tmp_path, monkeypatch):
    """--sync 时存出单版产物包 rev-<rev>；--no-pack 不存；存不成只告警。"""
    import argparse
    import subprocess
    calls = []
    rc = {"v": 0}

    def fake_run(cmd, **kw):
        cmd = [str(c) for c in cmd]
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, rc["v"], "", "")

    monkeypatch.setattr(rp, "run", fake_run)
    assert rp.pack_rev(argparse.Namespace(no_pack=False), tmp_path, "vol06", "006-r3") == "rev-006-r3"
    c = calls[-1]
    assert c[c.index("pack") + 1:c.index("pack") + 3] == ["push", "vol06"] and c[c.index("--label") + 1] == "rev-006-r3"
    assert rp.pack_rev(argparse.Namespace(no_pack=True), tmp_path, "vol06", "006-r3") is None and len(calls) == 1
    rc["v"] = 1
    assert rp.pack_rev(argparse.Namespace(no_pack=False), tmp_path, "vol06", "006-r3") is None


def test_ticket_ledger_balances(tmp_path, monkeypatch):
    """G0 票账：写入（人裁晚于票）、一致（人裁早于票）、看不出、挂起、未落，五项之和 = 有效票格数。"""
    ws, export, online = _setup(tmp_path)                      # 1:1:3 有一条 2026-10-20 的定字人裁
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    vote = lambda a, choice, ts, ch="": {"book": "abc123", "rev": "006-r2", "a": a, "choice": choice, "char": ch, "voter": "u1", "ts": ts}
    t_before, t_after = 1790000000000, 1793000000000           # 毫秒：2026-09-21 与 2026-10-26
    votes = [vote("1:1:3", "char", t_before, "甲"), vote("1:1:9", "unsure", t_after), vote("1:1:2", "char", t_after, "乙"),
             vote("1:1:4", "none", t_after), vote("2:1:1", "char", t_after, "丙"), {"book": "x"}]
    led = rp.ticket_ledger(ws, "vol06", "abc123", "006-r2", votes, held=["1:1:4"])
    assert led["counts"] == {"写入": 1, "与已有人裁一致": 0, "看不出": 1, "挂起": 1, "未落": 2}
    assert sum(led["counts"].values()) == led["votes"] == 5 and "账平" in rp.ledger_md(led)
    led2 = rp.ticket_ledger(ws, "vol06", "abc123", "006-r2", [vote("1:1:3", "char", t_after, "甲")])
    assert led2["counts"]["与已有人裁一致"] == 1                    # 人裁早于票：判一致跳过
