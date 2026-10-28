"""换图源后的页表 rev 判据（GUJI-748，设计稿 `殿本换图源-siku-qiefen-v2.md` §六）。

切过图源的册（yaml 有 `source_rev`），指向页的事件锚里 `source_rev` 必须相符才采信；
写入拒写、所有读口同一判据，维护自身日志（压实、编号）照原样读。"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from open_guji_cv.core.event_files import (
    RevGate,
    book_source_rev,
    iter_event_dicts,
    iter_event_records,
    sibling_books_dir,
)
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event


def _data(tmp_path: Path, revs: dict[str, int | None]) -> Path:
    """<数据>/books/<册>.yaml ＋ <数据>/feedback/events/"""
    books = tmp_path / "books"
    books.mkdir()
    for b, r in revs.items():
        (books / f"{b}.yaml").write_text(f"id: {b}\n" + (f"source_rev: {r}\n" if r is not None else ""),
                                         encoding="utf-8")
    (tmp_path / "feedback" / "events").mkdir(parents=True)
    return tmp_path


def _ev(seq, book="vol11", page=3, rev=None, kind="confirm", batch="b"):
    anchor = {"space": "page"} if rev is None else {"space": "page", "source_rev": rev}
    return make_event(batch, seq, kind,
                      EventTarget(step="seed_admit", unit="cell", key=f"{book}:{page}:1:{seq}",
                                  book=book, page=page, col=1, slot=seq, anchor=anchor),
                      {"v": "confirm", "shape": "之"}, source_format="server")


# ── 判据本身 ─────────────────────────────────────────────────────────

def test_gate_rules(tmp_path):
    d = _data(tmp_path, {"vol11": 3, "vol01": None})
    g = RevGate(d / "books")
    t = lambda book, rev, page=3: {"book": book, "page": page, "key": f"{book}:{page}:1:1",
                                   "anchor": None if rev is None else {"source_rev": rev}}
    assert g.admits("confirm", t("vol11", 3))
    assert g.admits("confirm", t("vol11", "3"))             # 字符串也认
    assert not g.admits("confirm", t("vol11", 2))           # 旧 rev
    assert not g.admits("confirm", t("vol11", None))        # 锚里没写 rev：不看 ts，一律不采信
    assert not g.admits("confirm", t("vol11", "x"))
    assert g.admits("glyph_audit", t("vol11", None))        # 按实例 id 寻址，豁免
    assert g.admits("confirm", {"book": "vol11", "key": "vol11"})     # 不指向页
    assert g.admits("confirm", t("vol01", None))            # 没切的册不设判据
    assert g.admits("confirm", t("vol99", None))            # 没有这册
    assert g.dropped == {"vol11": 3}
    assert "vol11 3 条" in g.note()
    assert RevGate(d / "books").note() == ""


def test_page_from_key_only(tmp_path):
    d = _data(tmp_path, {"vol11": 3})
    g = RevGate(d / "books")
    assert not g.admits("confirm", {"key": "v2:vol11:5:1:2"})
    assert g.admits("confirm", {"key": "v2:vol11:5:1:2", "anchor": {"source_rev": 3}})


def test_source_rev_follows_yaml_edit(tmp_path):
    d = _data(tmp_path, {"vol11": None})
    assert book_source_rev("vol11", d / "books") is None
    (d / "books" / "vol11.yaml").write_text("id: vol11\nsource_rev: 3\n", encoding="utf-8")
    assert book_source_rev("vol11", d / "books") == 3
    (d / "books" / "vol11.yaml").write_text("id: [坏\n", encoding="utf-8")
    assert book_source_rev("vol11", d / "books") is None


def test_sibling_books_dir(tmp_path):
    d = _data(tmp_path, {})
    assert sibling_books_dir(d / "feedback" / "events") == d / "books"
    assert sibling_books_dir(d / "feedback") == d / "books"
    assert sibling_books_dir(tmp_path / "nowhere" / "x" / "y") is None


# ── EventLog ─────────────────────────────────────────────────────────

def _write_raw(d: Path, batch: str, evs) -> None:
    with open(d / "feedback" / "events" / f"{batch}.jsonl", "a", encoding="utf-8") as f:
        f.writelines(e.model_dump_json() + "\n" for e in evs)


def test_eventlog_read_gates_and_raw_does_not(tmp_path):
    d = _data(tmp_path, {"vol11": 3, "vol01": None})
    _write_raw(d, "b", [_ev(1, rev=2), _ev(2, rev=3), _ev(3, book="vol01"), _ev(4, kind="glyph_audit")])
    log = EventLog(d / "feedback")
    assert [e.seq for e in log.read("b")] == [2, 3, 4]
    assert log.dropped == {"b": {"vol11": 1}}
    assert [e.seq for e in log.read("b", raw=True)] == [1, 2, 3, 4]
    assert [e.seq for e in log.iter_all()] == [2, 3, 4]
    assert [e.seq for e in log.read_cached("b")] == [2, 3, 4]
    assert log.latest_seq("b") == 4                          # 编号看全量，不会撞号


def test_read_cached_rejudges_after_switch(tmp_path):
    d = _data(tmp_path, {"vol11": None})
    _write_raw(d, "b", [_ev(1), _ev(2, rev=3)])
    log = EventLog(d / "feedback")
    assert len(log.read_cached("b")) == 2
    (d / "books" / "vol11.yaml").write_text("id: vol11\nsource_rev: 3\n", encoding="utf-8")
    assert [e.seq for e in log.read_cached("b")] == [2]      # 日志没动，册刚切：判据现判


def test_compact_keeps_gated_events(tmp_path):
    d = _data(tmp_path, {"vol11": 3})
    _write_raw(d, "b", [_ev(1, rev=2), _ev(2, rev=3)])
    log = EventLog(d / "feedback")
    log.compact("b")
    assert [e.seq for e in log.read("b", raw=True)] == [1, 2]   # 旧页号的事件是账，不因判据删掉


def test_append_rejects_stale(tmp_path):
    from open_guji_cv.errors import BadRequest
    d = _data(tmp_path, {"vol11": 3})
    log = EventLog(d / "feedback")
    with pytest.raises(BadRequest, match="cellvotes migrate"):
        log.append([_ev(1, rev=2)])
    with pytest.raises(BadRequest):
        log.append([_ev(1)])                                   # 没写 rev
    log.append([_ev(1, rev=3), _ev(2, book="vol01")])
    assert [e.seq for e in log.read("b")] == [1, 2]


# ── 低层读口 ─────────────────────────────────────────────────────────

def test_iter_event_dicts(tmp_path):
    d = _data(tmp_path, {"vol11": 3})
    _write_raw(d, "a", [_ev(1, rev=2, batch="a"), _ev(2, rev=3, batch="a")])
    with open(d / "feedback" / "events" / "a.jsonl", "a", encoding="utf-8") as f:
        f.write("{坏行\n\n")
    ev_dir = d / "feedback" / "events"
    assert [e["seq"] for e in iter_event_dicts(ev_dir)] == [2]          # 自动找同目录的 books/
    assert [e["seq"] for e in iter_event_dicts(ev_dir, gate=False)] == [1, 2]
    g = RevGate(d / "books")
    recs = list(iter_event_records(ev_dir, gate=g))
    assert [(f.name, e["seq"]) for f, e in recs] == [("a.jsonl", 2)] and g.dropped == {"vol11": 1}
    assert list(iter_event_dicts(tmp_path / "missing")) == []


# ── 读口收拢：别处不许再直接扫人裁事件文件 ────────────────────────────

#: 可以直接 glob 事件目录的地方：读口本身；只看 stat／存在的；读原样的维护工具；字形库自己的事件。
_ALLOWED = {
    "core/event_files.py", "feedback/events.py",
    "feedback/lookup.py",          # 只取文件签名做缓存键
    "review/cards.py",             # 只取 mtime 水位
    "eval/round_check.py",         # 只判有没有
    "feedback/lint.py",            # 校验原样内容
    "clustering/glyph_db.py",      # 字形库 store 的事件，不是人裁事件
    "ops/glyphlib.py",             # 扫的是字形库 instances/；人裁事件已走 iter_event_dicts
    "feedback/candidates.py",      # 候选清单文件
    "eval/llm_online_accuracy.py", # 线上调用日志
}


def test_no_direct_event_globs_outside_reader():
    root = Path(__file__).resolve().parents[1] / "open_guji_cv"
    pat = re.compile(r"""\.r?glob\(\s*["']\*\.jsonl["']""")
    bad = []
    for p in root.rglob("*.py"):
        rel = p.relative_to(root).as_posix()
        if rel in _ALLOWED:
            continue
        src = p.read_text(encoding="utf-8")
        if pat.search(src) and re.search(r"""["']events["']|events_dir""", src):
            bad.append(rel)
    assert not bad, f"直接扫人裁事件文件、绕过页表 rev 判据：{bad}；请用 core.event_files.iter_event_dicts"


def test_json_roundtrip_of_anchor_rev(tmp_path):
    """控制台写来的事件是 JSON，rev 可能是字符串；落盘再读回仍按判据判。"""
    d = _data(tmp_path, {"vol11": 3})
    e = json.loads(_ev(1, rev=3).model_dump_json())
    e["target"]["anchor"]["source_rev"] = "3"
    (d / "feedback" / "events" / "b.jsonl").write_text(json.dumps(e, ensure_ascii=False) + "\n", encoding="utf-8")
    assert len(EventLog(d / "feedback").read("b")) == 1


def test_db_status_counts_dropped(tmp_path):
    from open_guji_cv.cli_db import _rev_gate_dropped
    d = _data(tmp_path, {"vol11": 3})
    _write_raw(d, "a", [_ev(1, rev=2, batch="a"), _ev(2, batch="a"), _ev(3, rev=3, batch="a")])
    assert _rev_gate_dropped(d) == {"vol11": 2}
