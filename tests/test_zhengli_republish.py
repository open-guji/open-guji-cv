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
    new = {"rev": "006-r3", "cells": [{"cell": "1:1:4"}, {"cell": "2:1:1", "pending_reason_cause": "B"}]}
    d = rp.diff(old, new, dropped=[{"cell": "1:1:1"}], states={"1:1:2": ("admit", "己"), "1:1:5": ("excluded", None)}, votes=Counter({"1:1:4": 2}))
    assert (d["old"], d["new"], d["kept"]) == (5, 2, 1)
    assert [(x["cell"], x["why"]) for x in d["removed"]] == [
        ("1:1:1", "人裁过"), ("1:1:2", "机器放行「己」"), ("1:1:3", "格号没了（多半重切）"), ("1:1:5", "排除名单（非字）")]
    assert d["added"] == [{"cell": "2:1:1", "cls": "B"}]
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
    monkeypatch.delenv("CELLREVIEW_TOKEN", raising=False)                                       # 换单门别去连网站 KV
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


def test_prep_recheck_puts_decided_and_admitted_cells_back(tmp_path, monkeypatch):
    """--recheck：人裁过的 1:1:3、已放行的 1:1:1 都回到单上并带说明；切分里没有的 1:1:9 列进差异单。"""
    ws, export, online = _setup(tmp_path)
    monkeypatch.delenv("GUJI_PRODUCTS_DIR", raising=False)
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    rc = tmp_path / "recheck.tsv"
    rc.write_text("格位\t说明\t旧人裁\t旧人裁的字\t旧人裁时间\n1:1:3\t上次投了「乙」，和已有判断不同\tev1\t甲\t2026-10-20T00:00:00Z\n"
                  "1:1:1\t机改无票，请核\n1:1:9\t切字改过\n", encoding="utf-8")
    assert rp.main(["prep", "--book", "vol06", "-w", str(ws), "--export-dir", str(export), "--no-alt", "--no-sprite",
                    "--cv-commit", "abc1234", "--recheck", str(rc)]) == 0
    out = ws / "reports" / "vol06" / "_publish" / "006-r3"
    new = {c["cell"]: c for c in json.loads((out / "006.pending.json").read_text(encoding="utf-8"))["cells"]}
    assert sorted(new) == ["1:1:1", "1:1:2", "1:1:3", "1:1:4"]
    assert new["1:1:3"]["prior"] == {"c": "甲", "id": "ev1", "ts": "2026-10-20T00:00:00Z"} and new["1:1:1"]["note"] == "机改无票，请核"
    md = (out / "差异单.md").read_text(encoding="utf-8")
    assert "复审格（--recheck）：上单 2 格，现行切分里没有 1 格" in md and "`1:1:9`" in md


def test_publish_web_only_falls_back_to_full(monkeypatch):
    """issue 只发这一章（only=<书>/<章>）；网站还没 only 输入（触发失败）就退回全站发布。"""
    import argparse
    import subprocess
    calls = []

    def _run(cmd, **kw):
        cmd = [str(c) for c in cmd]
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1 if any(x.startswith("only=") for x in cmd) else 0, "", "")

    monkeypatch.setattr(rp.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(rp, "run", _run)
    assert rp.publish_web(argparse.Namespace(no_publish_web=False, publish_only="abc123/006")) is True
    assert "only=abc123/006" in calls[0] and not any(x.startswith("only=") for x in calls[1])


def test_issue_runs_prep_push_and_skips_empty(tmp_path, monkeypatch):
    """issue：prep → push（--yes --sync、只发这一章）→ 等发布 → 冒烟；新单 0 格就不推。"""
    ws, export, online = _setup(tmp_path)
    monkeypatch.delenv("GUJI_PRODUCTS_DIR", raising=False)
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    seen = {}
    monkeypatch.setattr(rp, "cmd_push", lambda a: seen.update(yes=a.yes, sync=a.sync, only=a.publish_only, rev=a.rev) or 0)
    monkeypatch.setattr(rp, "wait_publish", lambda since: "success")
    monkeypatch.setattr(rp, "smoke", lambda t, c, r: [])
    base = ["issue", "--book", "vol06", "-w", str(ws), "--export-dir", str(export), "--no-alt", "--no-sprite", "--cv-commit", "abc1234"]
    assert rp.main(base) == 0
    assert seen == {"yes": True, "sync": True, "only": "abc123/006", "rev": "006-r3"}
    monkeypatch.setattr(rp, "smoke", lambda t, c, r: ["p0001.webp → 404"])
    assert rp.main(base) == 2                                     # 已上线、冒烟没过：2，调用方照样开文本 PR


def test_wait_publish_skips_null_run(monkeypatch):
    """刚触发时 REST 还查不到 run，jq 吐 "null null null"：不能当成 run id，继续等。"""
    outs = iter(["null null null", "123 in_progress null", "123 completed success"])
    monkeypatch.setattr(rp.subprocess, "run",
                        lambda *a, **k: type("P", (), {"returncode": 0, "stdout": next(outs)})())
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert rp.wait_publish("2026-10-24T00:00:00Z", timeout_s=60, poll_s=0) == "success"


def test_book_text_dev_sync_and_push(tmp_path):
    """book-text 切到最新 dev、提交后推 dev；别人先推了就 rebase 再推（2026-10-24 起流程化小改直接提交 dev）。"""
    import subprocess as sp

    def git(cwd, *a):
        sp.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=cwd, check=True, capture_output=True)

    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        git(tmp_path, "clone", "-q", "--single-branch", str(remote), str(d))
    (a / "x.txt").write_text("0\n")
    git(a, "add", "x.txt"); git(a, "commit", "-qm", "init"); git(a, "push", "-q", "origin", "HEAD:main", "HEAD:dev")

    rp.book_text_to_dev(b)                                   # 单分支克隆也能拿到 origin/dev
    assert (b / "x.txt").read_text() == "0\n"
    (a / "y.txt").write_text("a\n"); git(a, "add", "y.txt"); git(a, "commit", "-qm", "a"); git(a, "push", "-q", "origin", "HEAD:dev")
    (b / "z.txt").write_text("b\n"); git(b, "add", "z.txt"); git(b, "commit", "-qm", "b")
    assert rp.push_book_text_dev(b)                          # 先被拒，rebase 后推上
    log = sp.run(["git", "log", "--format=%s", "dev"], cwd=remote, capture_output=True, text=True).stdout.split()
    assert log[:3] == ["b", "a", "init"]

    (b / "x.txt").write_text("dirty\n")
    with pytest.raises(SystemExit):
        rp.book_text_to_dev(b)                               # 工作区不干净就停


def test_pack_rev_uses_engine(tmp_path, monkeypatch):
    """出单版产物包用重跑的那份 cv 存（engine_run.py＋PYTHONPATH），包里才记它的版本。"""
    import argparse
    calls = []
    monkeypatch.setattr(rp, "run", lambda cmd, **kw: calls.append((cmd, kw)) or type("P", (), {"returncode": 0})())
    monkeypatch.setattr(rp, "products_root", lambda ws: tmp_path / "products")
    eng = tmp_path / "cv-old"
    eng.mkdir()
    assert rp.pack_rev(argparse.Namespace(engine=str(eng)), tmp_path, "vol06", "006-r6") == "rev-006-r6"
    cmd, kw = calls[-1]
    assert str(cmd[1]).endswith("engine_run.py") and kw["cwd"] == str(eng) and kw["env"]["PYTHONPATH"] == str(eng)
    rp.pack_rev(argparse.Namespace(engine=None), tmp_path, "vol06", "006-r6")
    assert calls[-1][0][1:3] == ["-m", "open_guji_cv.cli_v2"]


def _rebase_table(H=((2, 0, 10), (0, 2, 20), (0, 0, 1))):
    return {"rev": 4, "status": "staged", "pages": [
        {"seq": "0001", "page": 1, "w": 500, "h": 700, "sha256": "new1",
         "from_rev": {"rev": 3, "sha256": "old1", "w": 200, "h": 300, "H": [list(r) for r in H]}},
        {"seq": "0002", "page": 2, "w": 500, "h": 700, "sha256": "new2",
         "from_rev": {"rev": 3, "sha256": "old2", "w": 200, "h": 300, "H": [list(r) for r in H]}}]}


def _rebase_cord():
    return {"book_id": "96mid1ogzk", "volume": 5, "pages": [
        {"page": 1, "image": {"width": 200, "height": 300, "sha256": "old1"},
         "canvas": {"id": "c1", "seq": 1, "width": 200, "height": 300},
         "regions": [{"box": [0, 0, 100, 150], "rules": [[[0, 0], [100, 0]]]}],
         "columns": [{"box": [50, 0, 10, 100]}], "cells": [{"a": "1:1:1", "box": [50, 5, 10, 10]}]},
        {"page": 2, "image": {"width": 500, "height": 700, "sha256": "new2"},   # 已换过的页不再换
         "canvas": {"id": "c2", "seq": 2, "width": 500, "height": 700}, "cells": [{"a": "2:1:1", "box": [1, 2, 3, 4]}]}]}


def test_rebase_cord_to_site_pages():
    """拷进 book-text 的 cord 换到网站新页（页表 from_rev.H）：旧页换、已换的页不动，导出原件不归它管。"""
    pytest.importorskip("guji_manager")
    cord = _rebase_cord()
    assert rp.rebase_cord(cord, _rebase_table()) == 1
    p1, p2 = cord["pages"]
    assert p1["image"] == {"width": 500, "height": 700, "sha256": "new1"}
    assert (p1["canvas"]["id"], p1["canvas"]["width"], p1["canvas"]["height"]) == ("c1", 500, 700)
    assert p1["cells"][0]["box"] == [110, 30, 20, 20]
    assert p1["columns"][0]["box"] == [110, 20, 20, 200]
    assert p1["regions"][0]["box"] == [10, 20, 200, 300]
    assert p1["regions"][0]["rules"] == [[[10, 20], [210, 20]]]
    assert p1["producers"]["rebase"]["from_source_rev"] == 3 and p1["producers"]["rebase"]["to_source_rev"] == 4
    assert p2["cells"][0]["box"] == [1, 2, 3, 4] and "producers" not in p2
    assert rp.rebase_cord(cord, _rebase_table()) == 0                       # 再跑一遍不动


def test_rebase_cord_noop_and_mismatch():
    pytest.importorskip("guji_manager")
    cord = _rebase_cord()
    assert rp.rebase_cord(cord, None) == 0                                  # R2 没页表的书
    assert rp.rebase_cord(cord, {"rev": 2, "pages": [{"seq": "0001", "page": 1, "w": 1, "h": 1, "sha256": "x"}]}) == 0
    cord["pages"][0]["image"]["sha256"] = "other"
    with pytest.raises(ValueError, match="1"):
        rp.rebase_cord(cord, _rebase_table())


def test_copy_cord_for_site_keeps_export(tmp_path, monkeypatch):
    pytest.importorskip("guji_manager")
    src, dst = tmp_path / "005.cord.json", tmp_path / "bt" / "005.cord.json"
    dst.parent.mkdir()
    src.write_text(json.dumps(_rebase_cord()), encoding="utf-8")
    before = src.read_bytes()
    monkeypatch.setattr(rp, "site_page_table", lambda book, vol: _rebase_table())
    assert rp.copy_cord_for_site(src, dst) == 1
    assert src.read_bytes() == before
    assert json.loads(dst.read_text(encoding="utf-8"))["pages"][0]["image"]["sha256"] == "new1"
    bad = _rebase_cord()
    bad["pages"][0]["image"]["sha256"] = "other"
    src.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(SystemExit):
        rp.copy_cord_for_site(src, dst)


def test_add_anchor_reasons(tmp_path):
    """标 main 后收尾（方案 8.9）：出单时把 A01/A02 现算写进待审单；manager 没有 closeout.plan 或没给 book-text 就跳过。"""
    pytest.importorskip("guji_manager.closeout.plan")
    char = {"pages": [{"columns": [{"cells": [{"a": f"1:1:{i}", "c": c} for i, c in enumerate("甲乙丙", 1)]}]}]}
    (tmp_path / "001.char.json").write_text(json.dumps(char), encoding="utf-8")
    (tmp_path / "001.punct.json").write_text(json.dumps({"punctuations": [
        {"mark": "，", "pre_char": "乙", "anchor": "1:1:2"}, {"mark": "。", "pre_char": "丁", "anchor": "1:1:9"}]}), encoding="utf-8")
    pend = tmp_path / "001.pending.json"
    pend.write_text(json.dumps({"cells": [{"cell": "1:1:1", "pending_reason": "group_abstain"}]}), encoding="utf-8")
    rp.add_anchor_reasons(pend, tmp_path, None, "001")                                    # 没给 book-text：不动
    assert len(json.loads(pend.read_text(encoding="utf-8"))["cells"]) == 1
    rp.add_anchor_reasons(pend, tmp_path, tmp_path, "001")
    doc = json.loads(pend.read_text(encoding="utf-8"))
    cells = {c["cell"]: c for c in doc["cells"]}
    # 只因标点要重挂的格（字没问题）放 anchor_cells[]，不混进判字用的 cells[]（11-13）
    assert list(cells) == ["1:1:1"] and cells["1:1:1"]["pending_reason"] == "group_abstain"
    side = {c["cell"]: c for c in doc["anchor_cells"]}
    assert side["1:1:3"]["pending_reason"] == "anchor_miss" and side["1:1:3"]["src"] == "closeout_anchor"


def test_closeout_derive_after_text_push(tmp_path, monkeypatch, capsys):
    """文本推进 book-text dev 之后现算 A01–A03（方案 8.9）：以推前的 dev 为漂移基准；本章没有标点／专名就不跑；
    算失败只警告、不拦推单。"""
    vdir = tmp_path / "bt" / "Book" / "x" / "y" / "z" / "abc123" / "default"
    vdir.mkdir(parents=True)
    monkeypatch.setattr(rp, "book_text_dir", lambda repo, tid: vdir)
    calls, rc = [], [0]
    monkeypatch.setattr(rp, "run", lambda cmd, **kw: calls.append([str(c) for c in cmd]) or type("P", (), {"returncode": rc[0]})())
    plan = {"chapter": "006", "text_id": "abc123", "pending": str(tmp_path / "006.pending.json")}
    rp.closeout_derive(tmp_path / "bt", plan, "base123")
    assert calls == []                                       # 没有标点／专名：没有锚点可算
    (vdir / "006.punct.json").write_text("{}", encoding="utf-8")
    rp.closeout_derive(tmp_path / "bt", plan, None)
    assert calls == []                                       # 没推文本（没有基准）就不算
    rp.closeout_derive(tmp_path / "bt", plan, "base123")
    cmd = calls[-1]
    assert cmd[1:5] == ["-m", "open_guji_cv.cli_v2", "closeout", "derive"] and cmd[5] == plan["pending"]
    assert cmd[cmd.index("--chapter") + 1] == "006" and cmd[cmd.index("--drift-base") + 1] == "base123"
    assert cmd[cmd.index("--vdir") + 1] == str(vdir)
    rc[0] = 1
    rp.closeout_derive(tmp_path / "bt", plan, "base123")     # 失败不抛
    assert "没跑通" in capsys.readouterr().out


def test_evict_recheck_merges_and_skips_decided(tmp_path, monkeypatch):
    """撤库重审格自动上单（Sheldon 11-09）：并进手给清单、手给的说明优先、撤库后人已再裁的不上。"""
    import open_guji_cv.feedback.lookup as lookup
    monkeypatch.setattr(lookup, "evict_review_cells", lambda book, log=None: {
        "vol01:1:1:1": {"char": "甲"}, "vol01:1:1:2": {"char": "乙"}, "vol01:1:1:3": {"char": "丙"}})
    monkeypatch.setattr(lookup, "human_chars", lambda book, **kw: {"vol01:1:1:3": "丙"})
    user = tmp_path / "rc.tsv"
    user.write_text("1:1:2\t手给说明\n2:2:2\t别的复审\n", encoding="utf-8")
    p = rp.evict_recheck(tmp_path, "vol01", str(user), tmp_path)
    rows = [ln.split("\t") for ln in p.read_text(encoding="utf-8").splitlines()]
    assert [r[0] for r in rows] == ["1:1:2", "2:2:2", "1:1:1"]
    assert rows[0][1] == "手给说明" and rows[2][1] == rp.EVICT_NOTE


def test_evict_recheck_none_when_no_events(tmp_path, monkeypatch):
    import open_guji_cv.feedback.lookup as lookup
    monkeypatch.setattr(lookup, "evict_review_cells", lambda book, log=None: {})
    assert rp.evict_recheck(tmp_path, "vol01", None, tmp_path) is None


def test_edit_cells_withdraw_restore_note():
    """单格原地改（sheldon 11-10）：撤下、放回、改说明，不碰别的格，记 edits。"""
    doc = {"rev": "001-r3", "cells": [{"cell": "1:1:1"}, {"cell": "1:1:2", "note": "旧"}, {"cell": "1:1:3"}]}
    r = rp.edit_cells(doc, withdraw=["vol01:1:1:1", "9:9:9"], notes={"1:1:2": "新说明", "1:1:3": ""}, by="A31", why="试",
                      at="2026-11-10T00:00:00Z")
    assert r["撤"] == ["1:1:1"] and r["找不到"] == ["9:9:9"] and sorted(r["改说明"]) == ["1:1:2", "1:1:3"]
    assert [c["cell"] for c in doc["cells"]] == ["1:1:2", "1:1:3"] and doc["cells"][0]["note"] == "新说明"
    assert doc["withdrawn"][0]["withdrawn"]["by"] == "A31"
    r = rp.edit_cells(doc, restore=["1:1:1"], by="A31")
    assert r["放回"] == ["1:1:1"] and "withdrawn" not in doc and "withdrawn" not in doc["cells"][-1]
    assert [e["op"] for e in doc["edits"]] == ["withdraw", "note", "note", "restore"]


def test_reconcile_items_keeps_votes_withdrawn_and_unchanged(tmp_path, monkeypatch):
    """待审条目化（sheldon 11-10）：换单逐格对条目，没变的不动、撤下的不放回，导出的单每格带 id。"""
    P = pytest.importorskip("guji_manager.review.pending_items")
    import argparse
    monkeypatch.setattr(rp, "data_dir", lambda ws: tmp_path / "data")
    monkeypatch.setattr(rp, "cell_fingerprints", lambda book, cells: {c: "fp" + c for c in cells})
    old = {"rev": "004-r1", "cells": [{"cell": "1:1:1", "review": "pending", "why": ["a"]},
                                      {"cell": "1:1:2", "review": "pending", "why": ["b"]}],
           "withdrawn": [{"cell": "1:1:3", "why": ["c"]}]}
    new = {"rev": "004-r2", "sprites": [], "cells": [{"cell": "1:1:1", "review": "pending", "why": ["a"]},
                                                      {"cell": "1:1:3", "review": "pending", "why": ["c2"]},
                                                      {"cell": "1:1:4", "review": "pending", "why": ["d"]}]}
    pend = tmp_path / "new.pending.json"
    pend.write_text(json.dumps(new), encoding="utf-8")
    plan = {"pending": str(pend), "chapter": "004", "text_id": "bk"}
    assert rp.reconcile_items(tmp_path / "bk-书", "vol04", plan, argparse.Namespace(rev="004-r2"), old)
    doc = json.loads(pend.read_text(encoding="utf-8"))
    assert doc["rev"] == "004-r2"
    assert [c["cell"] for c in doc["cells"]] == ["1:1:1", "1:1:4"]
    assert [c["cell"] for c in doc["withdrawn"]] == ["1:1:3"]
    store = P.ItemStore.open(tmp_path / "data", "bk", "004")
    assert store.find("1:1:2")[0]["state"] == "closed"
    keep = store.find("1:1:1")[0]
    assert doc["cells"][0]["id"] == keep["id"] and keep["fp"] == "fp1:1:1"


def test_add_cell_opens_item_with_own_image(tmp_path, monkeypatch):
    """单上加一格不换 rev（待审条目化第 2 步）：条目带按内容寻址的单图，导出的单 sprites[] 里有它。"""
    P = pytest.importorskip("guji_manager.review.pending_items")
    import argparse
    data = tmp_path / "data"
    online = data / "feedback" / "lists" / "proofing" / "bk" / "004.pending.json"
    online.parent.mkdir(parents=True)
    online.write_text(json.dumps({"rev": "004-r1", "cells": [{"cell": "1:1:1", "review": "pending"}], "sprites": []}),
                      encoding="utf-8")
    monkeypatch.setattr(rp, "data_dir", lambda ws: data)
    monkeypatch.setattr(rp, "cell_states", lambda products, book: {"7:2:3": ("admit", "曰")})
    monkeypatch.setattr(rp, "cell_image", lambda book, cell: (b"RIFFxxxxWEBP", 40, 42, "sha1fp"))
    uploaded = []
    monkeypatch.setattr(rp.sprite_pub, "upload", lambda entries, pub: uploaded.extend(entries) or {"uploaded": len(entries)})
    a = argparse.Namespace(workspace=str(tmp_path / "bk-书"), book="vol04", chapter="004", text_id="bk", cell=["vol04:7:2:3"],
                           note="撤库重审", recheck=True, src=None, why="", by="sheldon", no_image=False, out=None,
                           yes=True, sync=False, no_publish_web=True)
    assert rp.cmd_add_cell(a) == 0
    doc = json.loads(online.read_text(encoding="utf-8"))
    assert doc["rev"] == "004-r1"
    c = next(x for x in doc["cells"] if x["cell"] == "7:2:3")
    assert c["c"] == "曰" and c["note"] == "撤库重审" and c["recheck"] and c["id"].startswith("pi_")
    assert c["img"]["s"] in {e["name"] for e in doc["sprites"]} and len(uploaded) == 1
    assert P.ItemStore.open(data, "bk", "004").find("7:2:3")[0]["fp"] == "sha1fp"


def test_structure_changed_only_on_cell_add_del(tmp_path):
    """格号集合或次序变了才走格级对照表（增删格、改号）；只换字仍走原路（ZM 11-10）。"""
    def char(p, s):
        d = {"pages": [{"page": 1, "columns": [{"cells": [{"a": f"1:1:{i + 1}", "c": c} for i, c in enumerate(s)]}]}]}
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return p
    a, b, c = char(tmp_path / "a.json", "語子"), char(tmp_path / "b.json", "語孟子"), char(tmp_path / "c.json", "論子")
    assert rp._structure_changed(a, b)
    assert not rp._structure_changed(a, c)


def test_add_del_chars_route_to_cellmap(tmp_path, monkeypatch):
    """格号没变但有增删字（一边是空）：也走格级对照表，不再报「推分支等 A33」（ZM 11-10 单一路径）。"""
    import subprocess
    repo = tmp_path / "bt"
    d = repo / "Book" / "x" / "default"
    d.mkdir(parents=True)
    ex = tmp_path / "ex"
    ex.mkdir()
    def char(p, s):
        doc = {"pages": [{"page": 1, "columns": [{"cells": [{"a": f"1:1:{i + 1}", "c": c} for i, c in enumerate(s)]}]}]}
        p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    char(d / "001.char.json", "甲乙")
    char(ex / "001.char.json", "甲乙")
    (d / "001.punct.json").write_text('{"punctuations": []}', encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.setattr(rp, "book_text_to_dev", lambda r: None)
    monkeypatch.setattr(rp, "book_text_dir", lambda r, t: d)
    monkeypatch.setattr(rp, "hold_pending_current", lambda *a, **k: None)
    monkeypatch.setattr(rp, "punct_stale_update", lambda *a, **k: (None, ["1:1:2 乙→"]))
    monkeypatch.setattr(rp, "_bump_book_text_cellmap", lambda r, plan, note, base: "cellmap")
    plan = {"text_id": "x", "chapter": "001", "export_dir": str(ex)}
    assert rp.bump_book_text(repo, plan, "t") == "cellmap"


def test_sheet_gate_blocks_false_overturn(capsys):
    """出单门（11-13）：机器无字当「推翻人裁」、失效老人裁当「被推翻」、锚点格混进判字单，都不让上线。"""
    pytest.importorskip("guji_manager.review.sheet_audit")
    ws = Path("/nonexistent-ws")
    good = {"cells": [{"cell": "1:1:1", "pending_reason": "hard_pair"}], "anchor_cells": [{"cell": "9:1:1", "src": "closeout_anchor"}]}
    a = type("A", (), {})()
    rp.sheet_gate(good, ws, "vol06", a)                       # 通过，不退出
    bad = {"cells": [{"cell": "1:4:7", "recheck": True, "pending_reason": "machine_changed",
                      "note": "机器改判「卷」→「□」，推翻人裁，请核"}]}
    with pytest.raises(SystemExit) as e:
        rp.sheet_gate(bad, ws, "vol06", a)
    assert "单子体检不过" in str(e.value)
    a.ack_sheet_audit = "测试放行"
    rp.sheet_gate(bad, ws, "vol06", a)                        # 写明原因可放行


def test_need_source_images_stops_without_raw(monkeypatch):
    """原图不在：绑定会把老人裁大片判成 unanchored 悄悄丢掉，出单前必须停（11-13 vol04）。"""
    import open_guji_cv.core.book as bookmod

    class FakeBook:
        def __init__(self, pages):
            self._p = pages

        def all_pages(self):
            return self._p

    monkeypatch.setattr(bookmod, "load_book", lambda b: FakeBook([]))
    with pytest.raises(SystemExit) as e:
        rp.need_source_images("vol04")
    assert "guji source pull vol04" in str(e.value)
    monkeypatch.setattr(bookmod, "load_book", lambda b: FakeBook([1, 2]))
    rp.need_source_images("vol04")


def test_http_sends_referer(monkeypatch):
    seen = {}

    class R:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b""

    import urllib.request

    def fake(req, timeout=0):
        seen.update(req.headers)
        return R()

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    rp._http("https://data.openguji.com/x", method="HEAD")
    assert seen.get("Referer") == "https://www.openguji.com/"
