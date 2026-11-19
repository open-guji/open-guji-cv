"""auto_cycle 断点续跑、只清本册沙箱、守卫拦下出待重挂清单、换完统一发站（A31 11-18，ZM 换单提速第 2、4、5、6 项）。"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "zhengli"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("zl_auto_cycle_resume", SCRIPTS / "auto_cycle.py")
ac = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ac)


def _git_repo(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=p, check=True)
    (p / "Book").mkdir(exist_ok=True)
    (p / "Book" / "a.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=p, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"], cwd=p, check=True)
    return p


def test_drop_sandbox_keeps_other_books(tmp_path):
    sb = tmp_path / "_packs" / "r12g24"
    for b in ("vol42", "vol43"):
        (sb / b).mkdir(parents=True)
        (sb / b / "x").write_text("1")
    ac.drop_sandbox(sb, "vol42")
    assert not (sb / "vol42").exists()
    assert (sb / "vol43" / "x").exists()          # vol43 不能被别的册清掉
    ac.drop_sandbox(sb, "vol43")
    assert not sb.exists()                          # 空了才删标签目录


def _fake_run_book_env(tmp_path, monkeypatch, apply_rc=0, apply_out=""):
    ws = tmp_path / "ws"
    bt = _git_repo(tmp_path / "bt")

    def fake_sh(cmd, tries=3, **kw):
        c = [str(x) for x in cmd]
        if "plan" in c:
            d = ws / "reports" / "vol42" / "_cycle" / "042-r3"
            d.mkdir(parents=True, exist_ok=True)
            (d / "plan.json").write_text(json.dumps({"hash": "h", "ready": 1, "held": 0}), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, apply_rc if "apply" in c else 0, apply_out if "apply" in c else "", "")
    monkeypatch.setattr(ac, "sh", fake_sh)
    monkeypatch.setattr(ac.pc, "pack_info", lambda *a, **k: {"cv_commit": "abc"})
    monkeypatch.setattr(ac, "engine_for", lambda c: tmp_path)
    monkeypatch.setattr(ac.rp, "next_rev", lambda rev, ch: "042-r4")
    monkeypatch.setattr(ac.rp, "chapter_of", lambda b: "042")
    return ws, bt, {"main": "L", "online_rev": "042-r3", "status": {"voted": 2, "cells": 5, "done": True}}


def test_run_book_refuses_half_unpacked_sandbox(tmp_path, monkeypatch):
    ws, bt, d = _fake_run_book_env(tmp_path, monkeypatch)
    (ws / "_packs" / "L" / "vol42").mkdir(parents=True)             # 没有 .pack.json：解到一半
    (ws / "_packs" / "L" / "vol43").mkdir(parents=True)
    (ws / "_packs" / "L" / "vol43" / ac.PACK_MARK).write_text("{}")
    r = ac.run_book(ws, "vol42", bt, d, "sheldon")
    assert r["verdict"] == "blocked" and "不完整" in r["why"]
    assert (ws / "_packs" / "L" / "vol43" / ac.PACK_MARK).exists()


def test_run_book_done_clears_only_own_sandbox(tmp_path, monkeypatch):
    ws, bt, d = _fake_run_book_env(tmp_path, monkeypatch)
    for b in ("vol42", "vol43"):
        (ws / "_packs" / "L" / b).mkdir(parents=True)
        (ws / "_packs" / "L" / b / ac.PACK_MARK).write_text("{}")
    r = ac.run_book(ws, "vol42", bt, d, "sheldon")
    assert r["verdict"] == "done" and r["new_rev"] == "042-r4"
    assert not (ws / "_packs" / "L" / "vol42").exists()
    assert (ws / "_packs" / "L" / "vol43" / ac.PACK_MARK).exists()


def test_guard_stop_writes_reanchor_list_and_keeps_untracked(tmp_path, monkeypatch):
    out = "…\n✗ book-text 这步失败：格号变动守卫不过（标点条目（按 mark／kind／source／pos 计）变了），对照表 /x.tsv\n"
    ws, bt, d = _fake_run_book_env(tmp_path, monkeypatch, apply_rc=1, apply_out=out)
    (ws / "_packs" / "L" / "vol42").mkdir(parents=True)
    (ws / "_packs" / "L" / "vol42" / ac.PACK_MARK).write_text("{}")
    cyc = ws / "reports" / "vol42" / "_cycle" / "042-r3"
    (cyc / "cellmap").mkdir(parents=True)
    (cyc / "cellmap" / "left_vol42.tsv").write_text("层\t条目\t旧锚\t新锚\t内容\t原因码｜说明\npunct\tp1\t3:1:2\t\t，\t旧格被删\n", encoding="utf-8")
    (bt / "Book" / "042.punct-stale.json").write_text("{}", encoding="utf-8")       # 未跟踪：会被 git clean 清掉
    r = ac.run_book(ws, "vol42", bt, d, "sheldon")
    assert r["verdict"] == "guard-stop"
    g = r["guard"]
    assert g["left"] == 1 and "A33" in "、".join(g["to"]) and "标点条目" in g["problem"]
    assert (cyc / "待重挂锚点.tsv").read_text(encoding="utf-8").count("\n") == 2
    assert (cyc / "book-text-未提交" / "Book" / "042.punct-stale.json").exists()
    assert not (bt / "Book" / "042.punct-stale.json").exists()
    assert not (ws / "_packs" / "L" / "vol42").exists()
    rep = ac.write_guard_report(ws, {"books": {"vol42": r}}, "2026-11-18", bt, "96mid1ogzk")
    assert rep and "--resume-guard" in rep.read_text(encoding="utf-8")


def _main_env(tmp_path, monkeypatch, decide_map, run_map, published):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    bt = _git_repo(tmp_path / "bt")
    monkeypatch.setitem(sys.modules, "ensure_manager", types.SimpleNamespace(ensure=lambda: None))
    monkeypatch.setattr(ac.rp, "text_id_of", lambda ws: "96mid1ogzk")
    monkeypatch.setattr(ac, "decide", lambda ws, b, lv=False: {"verdict": decide_map.get(b, "go"), "why": "", "main": "L",
                                                               "online_rev": "x", "status": {"voted": 0}})
    monkeypatch.setattr(ac, "run_book", lambda ws, b, *a, **k: dict(run_map[b]))
    monkeypatch.setattr(ac, "publish_all", lambda done, tid: (published.append(list(done)), {b: "ok" for b, _ in done})[1])
    return ws, bt


def test_main_resume_skips_done_and_stopped_and_publishes_once(tmp_path, monkeypatch):
    published: list = []
    run_map = {"vol01": {"verdict": "done", "why": "", "new_rev": "001-r2"},
               "vol02": {"verdict": "guard-stop", "why": "守卫"},
               "vol03": {"verdict": "done", "why": "", "new_rev": "003-r2"}}
    ws, bt = _main_env(tmp_path, monkeypatch, {}, run_map, published)
    sp = ws / "reports" / "_auto_cycle" / "state.json"
    # 第一次：跑满时限前只做了 vol01（max-minutes 极小 → 第二册前停）
    monkeypatch.setattr(ac.time, "monotonic", iter([0.0] + [0.0] + [1e9] * 50).__next__)
    ac.main(["--books", "vol01-vol03", "-w", str(ws), "--book-text", str(bt), "--max-minutes", "1"])
    st = json.loads(sp.read_text(encoding="utf-8"))
    assert st["books"]["vol01"]["verdict"] == "done" and "vol02" not in st["books"]
    assert published == []                                         # 还有册没跑：不发站
    # 第二次：同一条命令接着做；vol01 跳过，vol02 guard-stop，vol03 done；全部有结论 → 统一发一次（vol01＋vol03）
    monkeypatch.setattr(ac.time, "monotonic", lambda: 0.0)
    calls = []
    orig = ac.run_book
    monkeypatch.setattr(ac, "run_book", lambda ws_, b, *a, **k: (calls.append(b), orig(ws_, b, *a, **k))[1])
    ac.main(["--books", "vol01-vol03", "-w", str(ws), "--book-text", str(bt)])
    assert calls == ["vol02", "vol03"]
    assert published == [[("vol01", "001-r2"), ("vol03", "003-r2")]]
    st = json.loads(sp.read_text(encoding="utf-8"))
    assert st["books"]["vol01"]["publish"] == "ok"
    # 第三次：都做过、都发过 → 不再跑也不再发
    calls.clear()
    ac.main(["--books", "vol01-vol03", "-w", str(ws), "--book-text", str(bt)])
    assert calls == [] and len(published) == 1


def test_main_recovers_interrupted_book(tmp_path, monkeypatch):
    published: list = []
    ws, bt = _main_env(tmp_path, monkeypatch, {}, {"vol05": {"verdict": "done", "why": "", "new_rev": "005-r2"}}, published)
    sp = ws / "reports" / "_auto_cycle" / "state.json"
    sp.parent.mkdir(parents=True)
    sp.write_text(json.dumps({"books": {"vol05": {"verdict": "running", "main": "L"}}}), encoding="utf-8")
    (ws / "_packs" / "L" / "vol05").mkdir(parents=True)
    (bt / "Book" / "a.txt").write_text("改到一半", encoding="utf-8")
    monkeypatch.setattr(ac.time, "monotonic", lambda: 0.0)
    ac.main(["--books", "vol05", "-w", str(ws), "--book-text", str(bt), "--no-publish"])
    assert (bt / "Book" / "a.txt").read_text(encoding="utf-8") == "x"
    assert not (ws / "_packs" / "L" / "vol05").exists()
    assert json.loads(sp.read_text(encoding="utf-8"))["books"]["vol05"]["verdict"] == "done"


def test_main_stops_before_book_when_disk_low(tmp_path, monkeypatch):
    published: list = []
    ws, bt = _main_env(tmp_path, monkeypatch, {}, {}, published)
    monkeypatch.setattr(ac, "free_gb", lambda p: 1.0)
    monkeypatch.setattr(ac.time, "monotonic", lambda: 0.0)
    ac.main(["--books", "vol07", "-w", str(ws), "--book-text", str(bt)])
    sp = ws / "reports" / "_auto_cycle" / "state.json"
    assert not sp.exists() or "vol07" not in json.loads(sp.read_text(encoding="utf-8"))["books"]


def test_lock_refuses_second_run_and_ignores_stale(tmp_path):
    lk = tmp_path / ".lock"
    lk.write_text("999999999 old\n")              # 死 pid：当没锁
    with ac.Lock(lk):
        assert lk.exists()
    assert not lk.exists()
