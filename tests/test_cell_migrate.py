# -*- coding: utf-8 -*-
"""`feedback/cell_migrate.py`：换图源迁票提案。对照表、事件、票全在测试里造。"""
from __future__ import annotations

import gzip
import json

import pytest

from open_guji_cv.feedback.cell_migrate import Row, load_table, migrate_events, migrate_votes, write_report
from open_guji_cv.feedback.events import EventTarget, make_event

HEAD = "旧格\t新格\t旧字\t新字\t类别\tIoU\t说明\n"
TABLE = HEAD + "\n".join([
    "vol04:3:1:1\tvol04:1:1:1\t欽\t欽\t同格\t0.88\t",
    "vol04:11:2:4\tvol04:9:2:3\t乾\t乾\t改号\t0.96\t",
    "vol04:11:2:5\tvol04:9:2:4\t隆\t龍\t改号\t0.95\t定字不同",
    "vol04:3:9:-1\t\t世\t\t删\t0.00\t新页 1 上没有 IoU≥0.5 的格",
    "vol04:5:1:1\tvol04:4:1:1\t甲\t甲\t同格\t0.31\t",
    "vol04:6:1:1\tvol04:5:1:1\t乙\t乙\t同格\t0.90\t",
    "vol04:6:1:2\tvol04:5:1:1\t丙\t乙\t改号\t0.80\t",
    "vol04:7:1:1a\tvol04:6:1:1a\t湖\t湖\t同格\t0.90\t",
    "\tvol04:9:9:9\t\t新\t新增\t0\t",
]) + "\n"


def ev(key, shape="", v="confirm", seq=1, ts="2026-10-01T00:00:00Z", batch="H-t", unit="cell", **pl):
    p = {"v": v, **({"shape": shape} if shape else {}), **pl}
    e = make_event(batch, seq, "confirm", EventTarget(step="seed_admit", unit=unit, key=key, anchor={"evidence": {"fp": "x"}}), p)
    return e.model_copy(update={"ts": ts})


@pytest.fixture
def rows(tmp_path):
    p = tmp_path / "c.tsv"
    p.write_text(TABLE, encoding="utf-8")
    return load_table(p)


def test_load_table_gzip_and_header(tmp_path):
    p = tmp_path / "c.tsv.gz"
    p.write_bytes(gzip.compress(TABLE.encode()))
    assert len(load_table(p)) == 9
    bad = tmp_path / "bad.tsv"
    bad.write_text("a\tb\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_table(bad)


def test_migrate_events_moves_by_table_not_by_number(rows):
    r = migrate_events([ev("vol04:11:2:4", "乾", seq=1), ev("vol04:7:1:1a", "湖", seq=2)], rows, "vol04", "3")
    got = {d["target"]["key"]: d for d in r.events}
    d = got["vol04:9:2:3"]
    assert d["id"].endswith("~q") and d["batch"] == "H-t~q" and d["seq"] == 1
    assert (d["target"]["page"], d["target"]["col"], d["target"]["slot"]) == (9, 2, 3)
    assert d["target"]["anchor"] == {"migrated_from": {"key": "vol04:11:2:4", "id": "evt_H-t_000001"}, "source_rev": "3"}
    assert d["payload"]["shape"] == "乾" and d["ts"] == "2026-10-01T00:00:00Z"
    assert "vol04:6:1:1a" in got                      # 带 a/b 后缀的格号照用
    assert r.id_map["evt_H-t_000001"] == "evt_H-t_000001~q"
    r.check()


def test_pending_reasons_and_reconciliation(rows):
    evs = [ev("vol04:3:9:-1", "世", seq=1), ev("vol04:5:1:1", "甲", seq=2), ev("vol04:99:1:1", "x", seq=3),
           ev("vol04:3:1:1", "欽", seq=4)]
    r = migrate_events(evs, rows, "vol04", "3")
    assert dict(r.reasons("人裁")) == {"删": 1, "IoU低": 1, "表里没有": 1}
    assert len(r.events) == 1 and r.n_events_in == 4
    r.check()
    assert r.reasons("人裁")["删"] == 1 and "新页 1" in next(p.detail for p in r.pending if p.reason == "删")
    low = migrate_events([evs[1]], rows, "vol04", "3", min_iou=0.3)
    assert len(low.events) == 1                       # 门槛可调


def test_only_latest_human_per_cell_and_other_events_counted(rows):
    old = ev("vol04:3:1:1", "舊", seq=1, ts="2026-10-01T00:00:00Z")
    new = ev("vol04:3:1:1", "欽", seq=2, ts="2026-10-02T00:00:00Z")
    page = ev("vol04:p3", v="x", seq=3, unit="page")
    machine = ev("vol04:3:1:1", "欽", seq=4, source="auto")
    r = migrate_events([old, new, page, machine], rows, "vol04", "3")
    assert [d["payload"]["shape"] for d in r.events] == ["欽"]
    assert r.n_events_in == 1
    assert sum(r.ignored.values()) == 3
    r.check()


def test_merge_same_verdict_and_conflict(rows):
    same = migrate_events([ev("vol04:6:1:1", "乙", seq=1, ts="2026-10-01T00:00:00Z"),
                           ev("vol04:6:1:2", "乙", seq=2, ts="2026-10-02T00:00:00Z")], rows, "vol04", "3")
    assert len(same.events) == 1 and same.n_merged == 1
    assert same.id_map["evt_H-t_000001"] == same.id_map["evt_H-t_000002"]    # 被合并的也有去向，prior.id 能改
    same.check()
    diff = migrate_events([ev("vol04:6:1:1", "乙", seq=1, ts="2026-10-01T00:00:00Z"),
                           ev("vol04:6:1:2", "丙", seq=2, ts="2026-10-02T00:00:00Z")], rows, "vol04", "3")
    assert len(diff.events) == 1 and diff.events[0]["payload"]["shape"] == "丙"        # 更晚的留下
    assert dict(diff.reasons("人裁")) == {"合并冲突": 1}
    diff.check()


def test_overrides_follow_new_id_or_dropped(rows):
    a = ev("vol04:3:1:1", "舊", seq=1, ts="2026-10-01T00:00:00Z")
    b = ev("vol04:3:1:1", "欽", seq=2, ts="2026-10-02T00:00:00Z", overrides=a.id)
    c = ev("vol04:11:2:4", "乾", seq=3, overrides="evt_gone_000009")
    r = migrate_events([a, b, c], rows, "vol04", "3")
    pl = {d["target"]["key"]: d["payload"] for d in r.events}
    assert "overrides" not in pl["vol04:1:1:1"]       # a 被 b 盖掉没迁，指过去也无意义
    assert "overrides" not in pl["vol04:9:2:3"]


def test_watch_lists_changed_char_but_still_migrates(rows):
    r = migrate_events([ev("vol04:11:2:5", "隆", seq=1)], rows, "vol04", "3")
    assert len(r.events) == 1 and r.n_watch_events == 1
    assert r.watch[0][:4] == ("vol04:11:2:5", "vol04:9:2:4", "隆", "龍")


def test_migrate_votes_rewrites_cell_and_lists_unmigrated(rows):
    v = lambda a, c="char", ch="乾", voter="v1": {"a": a, "choice": c, "char": ch, "voter": voter, "rev": "004-r7", "ts": 1}   # noqa: E731
    r = migrate_votes([v("11:2:4"), v("3:9:-1", "none", ""), v("77:1:1")], rows, "vol04", "3", new_rev="004-r8")
    assert [(x["a"], x["migrated_from_a"], x["rev"]) for x in r.votes] == [("9:2:3", "11:2:4", "004-r8")]
    assert dict(r.reasons("票")) == {"删": 1, "表里没有": 1}
    r.check()


def test_write_report_files_and_counts_cross_check(rows, tmp_path):
    r = migrate_events([ev("vol04:11:2:4", "乾", seq=1), ev("vol04:3:9:-1", "世", seq=2)], rows, "vol04", "3")
    write_report(r, tmp_path / "o", cells_path="c.tsv")
    out = tmp_path / "o"
    assert json.loads((out / "events.jsonl").read_text(encoding="utf-8").splitlines()[0])["target"]["key"] == "vol04:9:2:3"
    assert "人裁\tvol04:3:9:-1\t删\t" in (out / "pending.tsv").read_text(encoding="utf-8")
    txt = (out / "report.md").read_text(encoding="utf-8")
    assert "输入 2 = 迁出 1 + 合并 0 + 没迁 1（核对通过）" in txt and "没有写库" in txt
    r.n_events_in += 1
    with pytest.raises(AssertionError):
        r.check()


def test_bindings_map_by_bound_cell_and_skip_unbound(rows):
    """旧 main 上 rebound 的按绑定格查表（原始 key 偏一格）；没认上格的不迁、列待审。"""
    a = ev("vol04:11:2:4", "隆", seq=1)               # 原始 key 11:2:4，旧 main 改绑到 11:2:5
    b = ev("vol04:3:1:1", "欽", seq=2)                # 旧 main 上 review，没采信
    c = ev("vol04:7:1:1a", "湖", seq=3)               # 绑定表里没有：照原始 key
    bind = {a.id: {"bound": "vol04:11:2:5", "status": "rebound"}, b.id: {"bound": None, "status": "review"}}
    r = migrate_events([a, b, c], rows, "vol04", "3", bindings=bind)
    got = {d["id"]: d for d in r.events}
    assert got[a.id + "~q"]["target"]["key"] == "vol04:9:2:4"
    assert got[a.id + "~q"]["target"]["anchor"]["migrated_from"] == {"key": "vol04:11:2:4", "id": a.id, "bound": "vol04:11:2:5"}
    assert got[c.id + "~q"]["target"]["key"] == "vol04:6:1:1a"
    assert dict(r.reasons("人裁")) == {"旧绑定失效": 1}
    assert r.watch[0][0] == "vol04:11:2:5"            # 观察表记的是绑定格
    r.check()


def test_already_migrated_events_are_skipped(rows):
    done = ev("vol04:9:2:3", "乾", seq=1).model_copy(update={"target": EventTarget(
        step="seed_admit", unit="cell", key="vol04:9:2:3",
        anchor={"migrated_from": {"key": "vol04:11:2:4", "id": "evt_x"}, "source_rev": "3"})})
    r = migrate_events([done, ev("vol04:11:2:4", "乾", seq=2)], rows, "vol04", "3")
    assert len(r.events) == 1 and r.n_events_in == 1 and r.ignored["已是迁移事件（新页号）"] == 1
    r.check()


def test_rebound_into_cell_with_later_native_verdict_is_superseded(rows):
    """旧 main 上 rebound 到 11:2:5，而 11:2:5 自己有更晚的人裁：更晚的留下，早的算被盖掉，不列冲突；review 的不迁。"""
    a = ev("vol04:11:2:4", "讖", seq=1, ts="2026-10-20T00:00:00Z")
    b = ev("vol04:11:2:5", "䜟", seq=2, ts="2026-10-25T00:00:00Z")
    c = ev("vol04:3:1:1", "欽", seq=3)
    bind = {a.id: {"bound": "vol04:11:2:5", "status": "rebound"}, b.id: {"bound": "vol04:11:2:5", "status": "valid"},
            c.id: {"bound": "vol04:3:1:1", "status": "review"}}
    r = migrate_events([a, b, c], rows, "vol04", "3", bindings=bind)
    assert [(d["target"]["key"], d["payload"]["shape"]) for d in r.events] == [("vol04:9:2:4", "䜟")]
    assert dict(r.reasons("人裁")) == {"旧绑定失效": 1} and r.ignored["被同格更晚的人裁盖掉"] == 1
    r.check()
