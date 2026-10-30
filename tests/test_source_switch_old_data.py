# -*- coding: utf-8 -*-
"""换图源后旧格号数据的三处读口（GUJI-748，v0.5.29）：数据全部自己造，不读工作区。

1. 换单门（`republish.votes_gate`）：旧单出在换源前时，旧格号的票经 ~q 迁移事件（`anchor.migrated_from`）
   或格级对照表对到新格再看落没落；无法对位的列清单、写文件，不笼统拦。
2. 看图结论（`feedback/vision/`）：换源前的（锚里没有 source_rev）不进请审单、不让导出标 pending；
   换源后导入的带上产物的 source_rev。
3. `gold rebuild`：换源前的事件不重放；同 id 的旧条目已标 stale 时，新页表的事件另立新条目，不拿旧条目打底。
"""
from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path

import pytest

import open_guji_cv.steps  # noqa: F401  注册产物种类
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "zhengli"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"zhengli_{name}_ss", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rp = _load("republish")


def _yaml(books: Path, book: str, rev: int | None) -> None:
    books.mkdir(parents=True, exist_ok=True)
    (books / f"{book}.yaml").write_text(f"id: {book}\n" + (f"source_rev: {rev}\n" if rev is not None else ""),
                                        encoding="utf-8")


def _cell_ev(key: str, seq: int, *, rev=None, migrated_from: str | None = None, ts="2026-10-20T00:00:00Z",
             payload=None, batch="b", step="seed_admit"):
    book, pg, col, slot = key.split(":")
    anchor = {}
    if rev is not None:
        anchor["source_rev"] = rev
    if migrated_from:
        anchor["migrated_from"] = {"key": migrated_from, "id": f"evt_old_{seq}"}
    e = make_event(batch, seq, "confirm",
                   EventTarget(step=step, unit="cell", key=key, book=book, page=int(pg), col=int(col),
                               slot=int(slot), anchor=anchor or None),
                   payload or {"v": "confirm", "shape": "甲"}, source_format="server")
    return e.model_copy(update={"ts": ts})


# ── 1. 换单门 ────────────────────────────────────────────────────────

def _ws_switched(tmp_path: Path) -> Path:
    """没迁中心库的工作区（数据根就是工作区）：vol06 已换源（source_rev 3）。"""
    ws = tmp_path / "abc123-书"
    _yaml(ws / "books", "vol06", 3)
    log = EventLog(ws / "feedback")
    log.append([
        _cell_ev("vol06:1:1:2", 1, rev="3", migrated_from="vol06:3:1:2", batch="old~q"),   # 换源前已落、迁过来的
        _cell_ev("vol06:1:1:5", 2, rev="3", batch="new"),                                  # 换源后在新格上落的
    ])
    e = _cell_ev("vol06:1:1:6", 9, rev="3", batch="page~q")             # 早先整页迁移脚本：migrated_from 只记旧页号
    e.target.anchor["migrated_from"] = {"book": "vol06", "page": 3, "source": "siku-qiefen-v2"}
    log.append([e])
    return ws


def _table(path: Path) -> Path:
    rows = ["旧格\t新格\t旧字\t新字\t类别\tIoU\t说明",
            "vol06:3:1:2\tvol06:1:1:2\t甲\t甲\t同格\t0.9\t",
            "vol06:3:1:5\tvol06:1:1:5\t乙\t乙\t同格\t0.9\t",
            "vol06:3:1:7\tvol06:1:1:7\t丙\t丙\t改号\t0.8\t",
            "vol06:3:1:8\tvol06:1:1:8\t丁\t丁\t同格\t0.3\t",
            "vol06:3:1:9\t\t戊\t\t删\t0\t新图无此格"]
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    return path


def _votes():
    v = lambda a, choice="char", ch="甲": {"book": "abc123", "rev": "006-r5", "a": a, "choice": choice,
                                          "char": ch, "voter": "u1", "ts": 1792000000000}
    return [v("3:1:2"), v("3:1:5"), v("3:1:6"), v("3:1:7"), v("3:1:8"), v("3:1:9"), v("4:1:1"), v("5:1:1", "unsure")]


OLD_SHEET = {"rev": "006-r5", "routed_as_of": "2026-10-24T03:29:13Z"}       # 换源前出的单，还没记 source_rev


def test_sheet_predates_source(tmp_path):
    ws = _ws_switched(tmp_path)
    assert rp.sheet_predates_source(ws, "vol06", OLD_SHEET)
    assert rp.sheet_predates_source(ws, "vol06", {"rev": "006-r5"})                     # 更老的单连时刻都没记
    assert rp.sheet_predates_source(ws, "vol06", {"rev": "006-r7", "routed_as_of": "2026-10-27T00:35:07Z"}) is None
    assert rp.sheet_predates_source(ws, "vol06", {"rev": "006-r8", "source_rev": 3}) is None
    assert rp.sheet_predates_source(ws, "vol06", {"rev": "006-r8", "source_rev": 2})
    assert rp.sheet_predates_source(ws, "vol06", {"rev": "006-r7", "routed_as_of": "2026-10-27T00:35:07Z"},
                                    override=2)                                          # 命令行指明旧单的页表 rev
    _yaml(ws / "books", "vol07", None)
    assert rp.sheet_predates_source(ws, "vol07", OLD_SHEET) is None                      # 没换源的册不设判据


def test_ledger_maps_old_votes_through_migration_and_table(tmp_path):
    ws = _ws_switched(tmp_path)
    tab = _table(tmp_path / "vol06.tsv.gz")
    pre = rp.sheet_predates_source(ws, "vol06", OLD_SHEET)
    led = rp.ticket_ledger(ws, "vol06", "abc123", "006-r5", _votes(), predates=pre, cells=tab)
    c = led["counts"]
    assert c["看不出"] == 1
    assert c["写入"] + c["与已有人裁一致"] == 3      # 3:1:2、3:1:6 经 ~q 迁移事件，3:1:5 经对照表落在新格
    assert [v["a"] for v in led["rows"]["未落"]] == ["3:1:7"] and led["rows"]["未落"][0]["new"] == "1:1:7"
    why = {v["a"]: v["why"] for v in led["rows"]["无法对位"]}
    assert why == {"3:1:8": "IoU低", "3:1:9": "删", "4:1:1": "表里没有"}
    assert sum(c.values()) == led["votes"] == 8 and "账平" in rp.ledger_md(led)
    # 没给对照表：除了 ~q 迁移事件对得上的，旧格号的票一律算未落（判不出能不能对位，不放）
    led2 = rp.ticket_ledger(ws, "vol06", "abc123", "006-r5", _votes(), predates=pre)
    assert led2["counts"]["写入"] + led2["counts"]["与已有人裁一致"] == 2
    assert len(led2["rows"]["未落"]) == 5 and led2["counts"].get("无法对位", 0) == 0


def test_old_votes_not_mapped_by_number_on_same_source_sheet(tmp_path):
    """换源后出的单（格号就是新格号）：照旧按格号比，不拿 ~q 的旧格号去对。"""
    ws = _ws_switched(tmp_path)
    v = {"book": "abc123", "rev": "006-r7", "a": "3:1:2", "choice": "char", "char": "甲", "voter": "u1", "ts": 1}
    led = rp.ticket_ledger(ws, "vol06", "abc123", "006-r7", [v], predates=None)
    assert [x["a"] for x in led["rows"]["未落"]] == ["3:1:2"] and "无法对位" not in led["counts"]


def test_votes_gate_on_pre_switch_sheet(tmp_path, monkeypatch, capsys):
    ws = _ws_switched(tmp_path)
    monkeypatch.delenv("CELLREVIEW_TOKEN", raising=False)
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    web = ws / "feedback" / "lists" / "web" / "abc123" / "006-r5.jsonl"
    web.parent.mkdir(parents=True)
    web.write_text("\n".join(json.dumps(v, ensure_ascii=False) for v in _votes()) + "\n", encoding="utf-8")
    tab = _table(tmp_path / "vol06.tsv.gz")
    out = tmp_path / "pub"
    a = lambda **kw: type("A", (), {"held_file": None, "ack_unlanded_votes": None, "cells": str(tab),
                                    "old_source_rev": None, **kw})()
    with pytest.raises(SystemExit, match="1:1:7"):                  # 对得上新格、新格上还没人裁：照旧拦，报新格号
        rp.votes_gate(ws, "vol06", "abc123", "006-r5", "006-r6", a(), old_doc=OLD_SHEET, out=out)
    EventLog(ws / "feedback").append([_cell_ev("vol06:1:1:7", 3, rev="3", batch="new2")])
    rp.votes_gate(ws, "vol06", "abc123", "006-r5", "006-r6", a(), old_doc=OLD_SHEET, out=out)
    msg = capsys.readouterr().out
    assert "无法对位 3" in msg and "4:1:1" in msg
    rows = (out / "旧单票无法对位.tsv").read_text(encoding="utf-8").splitlines()
    assert rows[0].startswith("旧格") and len(rows) == 4
    # 对照表放目录也行（<目录>/<册>.tsv.gz）
    rp.votes_gate(ws, "vol06", "abc123", "006-r5", "006-r6", a(cells=str(tmp_path)), old_doc=OLD_SHEET, out=out)


def test_pending_list_stamps_source_rev(tmp_path):
    pl = _load("pending_list")
    prod = tmp_path / "products"
    seed = prod / "vol06" / "seed_admit"
    seed.mkdir(parents=True)
    seed.joinpath("p0001.json").write_text(json.dumps({"seed_admit": {"n_review": 1, "columns": [{"chars": [
        {"id": "vol06:1:1:1", "admit": False}]}]}}), encoding="utf-8")
    args = ["--products", str(prod), "--book", "vol06", "--chapter", "006", "--rev", "006-r1", "--cv-commit", "x"]
    pl.main(args + ["--out", str(tmp_path / "a")])
    assert "source_rev" not in json.loads((tmp_path / "a" / "006.pending.json").read_text(encoding="utf-8"))
    (prod / "vol06" / "_source.json").write_text(json.dumps({"book_id": "abc", "vol": "6", "rev": 3}), encoding="utf-8")
    pl.main(args + ["--out", str(tmp_path / "b")])
    assert json.loads((tmp_path / "b" / "006.pending.json").read_text(encoding="utf-8"))["source_rev"] == 3


# ── 2. 看图结论 ──────────────────────────────────────────────────────

def _vision_ev(key, seq, v="wrong", rev=None):
    from open_guji_cv.feedback.vision import _STEP
    book, pg, col, slot = key.split(":")
    return make_event("vision-x", seq, "vision_check",
                      EventTarget(step=_STEP, unit="cell", key=key, book=book, page=int(pg), col=int(col),
                                  slot=int(slot), anchor=None if rev is None else {"source_rev": rev}),
                      {"source": "vision", "judge": "m", "v": v, "char": "曰", "shown": "日"}, actor="model")


def test_pre_switch_vision_checks_ignored(tmp_path):
    """换源前的看图判错（锚里没有 source_rev，旧格号）不再让新格号进请审单。"""
    from open_guji_cv.feedback.vision import VisionLog, vision_checks, vision_flags
    _yaml(tmp_path / "books", "vol04", 3)
    _yaml(tmp_path / "books", "vol09", None)
    fb = tmp_path / "feedback"
    (fb / "vision").mkdir(parents=True)
    old = [_vision_ev("vol04:12:3:5", 1), _vision_ev("vol04:12:3:6", 2, v="unsure"), _vision_ev("vol09:1:1:1", 3)]
    (fb / "vision" / "vision-x.jsonl").write_text(
        "".join(e.model_dump_json() + "\n" for e in old), encoding="utf-8")       # 换源前写下的（写入口现在会拒）
    log = VisionLog(fb)
    assert vision_checks("vol04", log) == {} and vision_flags("vol04", log) == {}
    assert log.dropped == {"vision-x": {"vol04": 2}}                                # 不静默：丢了几条有数
    assert set(vision_flags("vol09", log)) == {"vol09:1:1:1"}                       # 没换源的册照旧
    log.append([_vision_ev("vol04:12:3:5", 4, rev=3)])                              # 换源后（带新 rev）照常生效
    assert set(vision_flags("vol04", log)) == {"vol04:12:3:5"}


def test_import_vision_needs_explicit_source_rev(tmp_path):
    """换过源的册：不给 --source-rev 整批报错（不抛异常、不写）；给了与册 yaml 相同的才写，读口照常认。
    不自动按产物盖 rev——旧格号的老文件重导一遍会被当成新图上的结论。"""
    from open_guji_cv.feedback.vision import VisionLog, import_vision, vision_flags
    _yaml(tmp_path / "books", "vol04", 3)
    src = tmp_path / "看图结论.jsonl"
    src.write_text(json.dumps({"cell": "vol04:1:1:3", "v": "wrong", "char": "曰", "shown": "日", "judge": "m"})
                   + "\n", encoding="utf-8")
    log = VisionLog(tmp_path / "feedback")
    res = import_vision(src, log, gold=False)
    assert res["written"] == 0 and "--source-rev" in res["errors"][0]
    assert import_vision(src, log, gold=False, source_rev=2)["written"] == 0           # 旧 rev 也不收
    res = import_vision(src, log, gold=False, source_rev=3)
    assert res["errors"] == [] and res["written"] == 1
    assert set(vision_flags("vol04", log)) == {"vol04:1:1:3"}


# ── 3. gold rebuild ─────────────────────────────────────────────────

def test_rebuild_does_not_revive_pre_switch_verdicts(tmp_path):
    from open_guji_cv.feedback.routes import RouteTable
    from open_guji_cv.gold.store import GoldStore
    from open_guji_cv.gold.transfer import rebuild_verdicts
    _yaml(tmp_path / "books", "vol01", 3)
    log = EventLog(tmp_path / "feedback")
    log.events_dir.mkdir(parents=True)
    old = [_cell_ev("vol01:5:3:4", 1, payload={"v": "seg_defect", "quality": "truncated"}, step="cell_shrink"),
           _cell_ev("vol01:9:1:1", 2, payload={"v": "seg_defect", "quality": "truncated"}, step="cell_shrink")]
    (log.events_dir / "old.jsonl").write_text("".join(e.model_dump_json() + "\n" for e in old), encoding="utf-8")
    store = GoldStore(tmp_path / "verdicts")
    table = RouteTable.load(log.root / "routes.yaml")
    shard = table.plan(old)["gold_add"][0][1].shard
    # 换源前重放出来、后来标了 stale 的两条（同 10-27 apply.py）
    from open_guji_cv.gold.item import Anchor, GoldItem
    store.upsert(shard, [GoldItem(id=e.target.key, anchor=Anchor(book="vol01", page=e.target.page, col=e.target.col,
                                                                   slot=e.target.slot),
                                  expected={"quality": "truncated", "note": "旧图"}, source_events=[e.id])
                         for e in old], "旧")
    store.mark_stale(shard, [e.target.key for e in old], "GUJI-748 换源")
    # 换源后：迁移事件落在新格 vol01:5:3:4（与旧格同号）
    new = _cell_ev("vol01:5:3:4", 3, rev="3", migrated_from="vol01:7:3:4", batch="m~q",
                   payload={"v": "seg_defect", "quality": "clean"}, step="cell_shrink")
    log.append([new])
    out = rebuild_verdicts(log, store, table)
    assert out["events"] == 1 and out["dropped_by_source_rev"] == {"vol01": 2}
    items = {i.id: i for i in store.list(shard)}
    assert items["vol01:9:1:1"].status == "stale"                                  # 旧裁决不复活
    it = items["vol01:5:3:4"]
    assert it.status == "active" and it.expected == {"quality": "clean"}           # 不拿旧条目打底（note 不漏进来）
    assert it.source_events == [new.id] and it.anchor.source_rev == 3
    assert any("换源" in h.why or "页表" in h.change for h in it.history)
    # 再重放一遍：幂等
    rebuild_verdicts(log, store, table)
    again = {i.id: i for i in store.list(shard)}
    assert again["vol01:5:3:4"].expected == {"quality": "clean"} and again["vol01:9:1:1"].status == "stale"


def test_source_gate(tmp_path, capsys):
    """图源门（A32 精校前移 A3）：册 yaml 钉了 source_rev 的，单子要出自那一版；没钉的只提示。"""
    from types import SimpleNamespace
    ws = tmp_path / "abc123-书"
    a = lambda why=None: SimpleNamespace(source_why=why)
    _yaml(ws / "books", "vol06", 3)
    rp.source_gate(ws, "vol06", {"source_rev": 3}, a())                  # 对得上：过
    rp.source_gate(ws, "vol06", {}, a())                                 # 单子没记：只提示
    assert "没记 source_rev" in capsys.readouterr().err
    with pytest.raises(SystemExit, match="r2"):
        rp.source_gate(ws, "vol06", {"source_rev": 2}, a())
    rp.source_gate(ws, "vol06", {"source_rev": 2}, a("知情"))
    assert "已按 --source-why 越过" in capsys.readouterr().err
    _yaml(ws / "books", "vol07", None)
    rp.source_gate(ws, "vol07", {"source_rev": 1}, a())                  # 没钉：只提示（钉了会丢旧事件，先补锚）
    assert "没钉 source_rev" in capsys.readouterr().err
    rp.source_gate(ws, "vol07", {}, a())                                 # 两边都没有（原图不是从页表取的）：只提示
    assert "没法核图源" in capsys.readouterr().err
