# -*- coding: utf-8 -*-
"""P1 反馈层：事件信封 / 四种旧格式收割 / 路由 / 幂等消费 / 金标落地 / 批次登记。

三条对齐 bug 各有一条回归（代理复核出来的，都是真格式与解析器对不上）：
- GUJI-SEG-REVIEW 的前缀在 `t` 字段里，不是行前缀，且 `t` 不是时间戳；
- marks 的值是 `{"s": N}`，且 1=切错 / 2=存疑 / 3=没问题；
- 续裁要 `{id: {"v","t"}}`，扁平串会让页面上一轮裁决全消失。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from open_guji_cv.feedback.consumers import route_and_consume
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
from open_guji_cv.feedback.harvest import (from_marks, from_page_html, from_seed_log,
                                           from_seg_log, from_verdicts, harvest_text,
                                           parse_card_id, to_shell_verdicts)
from open_guji_cv.feedback.routes import RouteTable
from open_guji_cv.gold.store import GoldStore
from open_guji_cv.review.batches import Batch, BatchStore, render_registry_markdown

REPO = Path(__file__).resolve().parent.parent
REAL_VERDICTS = REPO.parent / "open-guji-dataset" / "border-detection" / "column-split" / "verdicts_r1.jsonl"


# ── 卡片 id ──────────────────────────────────────────────────────────
def test_parse_card_id():
    assert parse_card_id("cols:vol02:171") == {"book": "vol02", "page": 171}
    assert parse_card_id("vol01:22:5:4") == {"book": "vol01", "page": 22, "col": 5, "slot": 4}
    assert parse_card_id("vol01/50:7:21") == {"book": "vol01", "page": 50, "col": 7, "slot": 21}
    assert parse_card_id("怪东西") == {}


# ── 收割：四种格式 ───────────────────────────────────────────────────
def test_from_verdicts_is_deterministic():
    rows = [{"id": "cols:vol01:9", "verdict": "ok", "t": 200},
            {"id": "cols:vol01:3", "verdict": "miss", "t": 100}]
    a = from_verdicts(rows, "b", "border_detect")
    b = from_verdicts(list(reversed(rows)), "b", "border_detect")
    assert [e.id for e in a] == [e.id for e in b]         # 按 t 排序，输入顺序无关
    assert a[0].target.key == "cols:vol01:3" and a[0].payload["verdict"] == "miss"
    assert a[0].target.page == 3 and a[0].source_format == "verdicts"


def test_from_page_html_reads_data_and_bands():
    data = {"rows": [], "verdicts": {"c1": {"v": "clean", "t": 5},
                                     "c1#band": {"v": "12,180", "t": 6}}}
    html = ('<html><script type="application/json" id="data">'
            + json.dumps(data) + "</script></html>")
    evs = from_page_html(html, "warp-r2", "column_warp", unit="column")
    kinds = {e.kind for e in evs}
    assert kinds == {"verdict", "band"}
    band = next(e for e in evs if e.kind == "band")
    assert band.payload["band"] == "12,180" and band.target.key == "c1"
    with pytest.raises(ValueError):
        from_page_html("<html>没有 data</html>", "x", "y")


def test_from_seed_log():
    text = ('噪声行\n'
            'GUJI-SEED-EVENT {"op":"confirm","instance_id":"vol01:4:1:3","char":"欽","batch":"p4","seq":7}\n'
            'GUJI-SEED-EVENT {"op":"not_a_char","instance_id":"vol01:4:1:9","batch":"p4","seq":8}\n')
    evs = from_seed_log(text, "vol01-seed-p4")
    assert [e.kind for e in evs] == ["confirm", "not_a_char"]
    assert evs[0].target.key == "vol01:4:1:3" and evs[0].payload["char"] == "欽"
    assert evs[0].target.col == 1 and evs[0].target.slot == 3


def test_from_seg_log_handles_prefix_in_t_field():
    """壳导出的是纯 JSON 行、前缀在 t 字段里；t 不是时间戳，拿它排序会 TypeError。"""
    text = ('{"t":"GUJI-SEG-REVIEW","id":"vol01/50:7:21","verdict":"bad"}\n'
            '{"t":"GUJI-SEG-REVIEW","id":"vol01/25:2:11","verdict":"unsure","note":"吃进邻字"}\n')
    evs = from_seg_log(text, "seg-r14")
    assert len(evs) == 2
    assert evs[0].target.key == "vol01/25:2:11"            # 按 id 排
    assert evs[0].payload["verdict"] == "unsure" and evs[0].payload["note"] == "吃进邻字"
    assert all("t" not in e.payload for e in evs)          # 字面量不进 payload


def test_from_marks_uses_s_and_shell_semantics():
    """真实文件是 {"s": N}；1=切错 2=存疑 3=没问题（与壳的循环一致）。"""
    marks = {"marks": {"vol01/21:8:2": {"s": 3}, "vol01/23:6:0": {"s": 1},
                       "vol01/25:2:11": {"s": 2, "note": "存疑"}},
             "visited": []}
    evs = from_marks(marks, "patch-r14")
    got = {e.target.key: e.payload["verdict"] for e in evs}
    assert got == {"vol01/21:8:2": "ok", "vol01/23:6:0": "bad", "vol01/25:2:11": "unsure"}
    assert next(e for e in evs if e.target.key == "vol01/25:2:11").payload["note"] == "存疑"


def test_harvest_text_dispatch():
    marks = json.dumps({"marks": {"vol01/1:1:1": {"s": 1}}, "visited": []}, indent=1)
    assert harvest_text(marks, "b", "cell_shrink")[0].source_format == "marks"
    jsonl = '{"id": "cols:vol01:9", "verdict": "ok", "t": 1}'
    assert harvest_text(jsonl, "b", "border_detect")[0].source_format == "verdicts"
    seed = 'GUJI-SEED-EVENT {"op":"skip","instance_id":"vol01:4:1:3","seq":1}'
    assert harvest_text(seed, "b", "cell_shrink")[0].source_format == "seed"


def test_to_shell_verdicts_shape():
    """续裁要 {id: {"v","t"}}；扁平串会让页面上一轮裁决全消失。"""
    evs = from_verdicts([{"id": "cols:vol01:9", "verdict": "ok", "t": 1}], "b", "border_detect")
    evs += [make_event("b", 99, "band", EventTarget(step="column_warp", unit="column", key="c1"),
                       {"band": "12,180"})]
    shell = to_shell_verdicts(evs)
    assert shell["cols:vol01:9"]["v"] == "ok"
    assert isinstance(shell["cols:vol01:9"]["t"], int)
    assert shell["c1#band"]["v"] == "12,180"


# ── 事件日志 ─────────────────────────────────────────────────────────
def test_eventlog_append_is_idempotent(tmp_path):
    log = EventLog(tmp_path)
    evs = from_verdicts([{"id": "a", "verdict": "ok", "t": 1},
                         {"id": "b", "verdict": "miss", "t": 2}], "r1", "border_detect")
    assert log.append(evs) == 2
    assert log.append(evs) == 0                    # 同 (batch, seq) 不重复写
    assert len(log.read("r1")) == 2
    assert log.batches() == ["r1"]
    assert log.latest_seq("r1") == 2


def test_eventlog_resolve_last_wins(tmp_path):
    log = EventLog(tmp_path)
    t = EventTarget(step="border_detect", unit="page", key="cols:vol01:9")
    log.append([make_event("r1", 1, "verdict", t, {"verdict": "ok"}),
                make_event("r1", 2, "verdict", t, {"verdict": "miss"})])
    assert log.resolve("r1")["cols:vol01:9"].payload["verdict"] == "miss"


def test_consumed_bookkeeping(tmp_path):
    log = EventLog(tmp_path)
    evs = from_verdicts([{"id": "a", "verdict": "ok", "t": 1}], "r1", "border_detect")
    log.append(evs)
    assert len(log.pending("gold_add", "r1")) == 1
    log.mark_consumed("gold_add", log.read("r1"))
    assert log.pending("gold_add", "r1") == []


# ── 路由 ─────────────────────────────────────────────────────────────
def test_routes_match_and_unrouted():
    table = RouteTable.load(None)
    e = from_verdicts([{"id": "cols:vol01:9", "verdict": "ok", "t": 1}], "r1", "border_detect")[0]
    dests = table.destinations(e)
    assert [(d.consumer, d.shard) for d in dests] == [("gold_add", "border-detection/column-split")]
    other = from_verdicts([{"id": "x", "verdict": "ok", "t": 1}], "r1", "不存在的步骤")[0]
    assert table.destinations(other) == []
    assert table.unrouted([e, other]) == [other]
    recrop = make_event("r1", 1, "recrop", EventTarget(step="cell_shrink", unit="cell", key="vol01:4:1:3"),
                        {"old_bbox": [0, 0, 1, 1], "new_bbox": [0, 0, 2, 2]})
    assert {d.consumer for d in table.destinations(recrop)} == {"glyphdb_recrop", "gold_add"}


# ── 端到端：收割 → 路由 → 金标 ──────────────────────────────────────
def test_route_and_consume_to_gold(tmp_path):
    log = EventLog(tmp_path / "feedback")
    store = GoldStore(tmp_path / "dataset")
    rows = [{"id": "cols:vol01:9", "verdict": "ok", "t": 1},
            {"id": "cols:vol01:87", "verdict": "extra", "t": 2},
            {"id": "cols:vol02:3", "verdict": "idk", "t": 3}]
    log.append(from_verdicts(rows, "r1", "border_detect"))
    out = route_and_consume(log, "r1", RouteTable.load(None), store)
    res = out["results"][0]
    assert res["consumer"] == "gold_add" and res["added"] == 3 and not res["errors"]
    items = {i.id: i for i in store.list("border-detection/column-split")}
    assert items["cols:vol01:9"].expected == {"verdict": "ok"}
    assert items["cols:vol01:9"].anchor.book == "vol01" and items["cols:vol01:9"].anchor.page == 9
    assert items["cols:vol02:3"].status == "uncertain"      # idk 不进分类指标
    assert items["cols:vol01:9"].label_origin == "human"
    assert items["cols:vol01:9"].source_events == ["evt_r1_000001"]
    # 幂等：再消费一次不重复加
    out2 = route_and_consume(log, "r1", RouteTable.load(None), store)
    assert out2["results"] == []
    assert len(store.list("border-detection/column-split")) == 3


def test_dry_run_does_not_write_gold(tmp_path):
    """试算只报数，不许落库——曾经 dry_run 也把 59 条写进了金标。"""
    log = EventLog(tmp_path / "feedback")
    store = GoldStore(tmp_path / "dataset")
    log.append(from_verdicts([{"id": "a", "verdict": "ok", "t": 1},
                              {"id": "b", "verdict": "miss", "t": 2}], "r1", "border_detect"))
    out = route_and_consume(log, "r1", RouteTable.load(None), store, dry_run=True)
    assert out["results"][0]["added"] == 2
    assert store.list("border-detection/column-split") == []      # 一条都没写
    assert len(log.pending("gold_add", "r1")) == 2                # 也没记账
    out = route_and_consume(log, "r1", RouteTable.load(None), store)
    assert out["results"][0]["added"] == 2
    assert len(store.list("border-detection/column-split")) == 2


def test_dry_run_counts_match_real_run(tmp_path):
    """试算与真消费口径必须一致：内容没变的不算「更新」。

    否则试算报「会改 2 条」、真跑报「改了 0 条」，人会以为消费没生效。
    """
    log = EventLog(tmp_path / "feedback")
    store = GoldStore(tmp_path / "dataset")
    log.append(from_verdicts([{"id": "a", "verdict": "ok", "t": 1}], "r1", "border_detect"))
    route_and_consume(log, "r1", RouteTable.load(None), store)

    # 第二批：一条同内容（不该算更新）、一条改判（该算更新）、一条新增
    log.append(from_verdicts([{"id": "a", "verdict": "ok", "t": 2},
                              {"id": "b", "verdict": "miss", "t": 3}], "r2", "border_detect"))
    dry = route_and_consume(log, "r2", RouteTable.load(None), store, dry_run=True)["results"][0]
    real = route_and_consume(log, "r2", RouteTable.load(None), store)["results"][0]
    assert (dry["added"], dry["updated"]) == (real["added"], real["updated"])
    assert dry["added"] == 1 and dry["updated"] == 0      # a 同内容，b 是新的


def test_harvest_into_batch_with_existing_events(tmp_path):
    """先 server 直连写过几条，再收割整份文件：新 key 必须续号进来，不能因撞号被丢。"""
    log = EventLog(tmp_path)
    log.append(from_verdicts([{"id": "cols:vol01:9", "verdict": "ok", "t": 1}], "r1", "border_detect"))
    fresh = from_verdicts([{"id": "cols:vol01:9", "verdict": "ok", "t": 1},
                           {"id": "cols:vol02:7", "verdict": "miss", "t": 2}], "r1", "border_detect")
    have = {e.target.key for e in log.read("r1")}
    base = log.latest_seq("r1")
    renum = [make_event("r1", base + i, e.kind, e.target, e.payload, e.actor, e.source_format, e.ts)
             for i, e in enumerate([e for e in fresh if e.target.key not in have], 1)]
    assert log.append(renum) == 1
    keys = {e.target.key for e in log.read("r1")}
    assert keys == {"cols:vol01:9", "cols:vol02:7"}
    assert len({e.seq for e in log.read("r1")}) == 2               # 没撞号


def test_gold_upsert_records_history(tmp_path):
    log = EventLog(tmp_path / "feedback")
    store = GoldStore(tmp_path / "dataset")
    log.append(from_verdicts([{"id": "c", "verdict": "ok", "t": 1}], "r1", "border_detect"))
    route_and_consume(log, "r1", RouteTable.load(None), store)
    log.append(from_verdicts([{"id": "c", "verdict": "miss", "t": 2}], "r2", "border_detect"))
    route_and_consume(log, "r2", RouteTable.load(None), store)
    it = store.get("border-detection/column-split", "c")
    assert it.expected == {"verdict": "miss"}
    assert len(it.history) == 2 and "ok" in it.history[1].change
    assert set(it.source_events) == {"evt_r1_000001", "evt_r2_000001"}
    assert store.summary("border-detection/column-split")["n"] == 1


@pytest.mark.skipif(not REAL_VERDICTS.exists(), reason="需要 open-guji-dataset")
def test_real_border_verdicts_roundtrip(tmp_path):
    """真实的第一轮 60 页裁决：README 记的是 ok 56 / extra 2 / miss 2。"""
    log = EventLog(tmp_path / "feedback")
    store = GoldStore(tmp_path / "dataset")
    evs = harvest_text(REAL_VERDICTS.read_text(encoding="utf-8"), "border-cols-r1",
                       "border_detect", "page")
    assert len(evs) == 60
    log.append(evs)
    route_and_consume(log, "border-cols-r1", RouteTable.load(None), store)
    items = store.list("border-detection/column-split")
    dist: dict[str, int] = {}
    for i in items:
        dist[i.expected["verdict"]] = dist.get(i.expected["verdict"], 0) + 1
    assert dist == {"ok": 56, "extra": 2, "miss": 2}


# ── 批次登记 ─────────────────────────────────────────────────────────
def test_batch_store_and_publish_gate(tmp_path):
    store = BatchStore(tmp_path)
    b = Batch(id="border-cols-r2", title="界行切分裁决台", step="border_detect",
              transport="artifact", url="https://claude.ai/code/artifact/12a1", n_cards=63)
    store.save(b)
    got = store.get("border-cols-r2")
    assert got and got.url == b.url and got.n_cards == 63
    assert got.can_publish()[0] is True                    # draft 可发
    got.status = "open"
    assert got.can_publish()[0] is False                   # 有未收割裁决，不许覆盖
    assert "harvest" in got.can_publish()[1]
    md = render_registry_markdown([got])
    assert "border-cols-r2" in md and "border_detect" in md


def test_batch_refresh_counts(tmp_path):
    log = EventLog(tmp_path / "feedback")
    store = BatchStore(tmp_path / "batches")
    b = Batch(id="r1", title="t", step="border_detect", n_cards=2)
    store.save(b)
    log.append(from_verdicts([{"id": "a", "verdict": "ok", "t": 1}], "r1", "border_detect"))
    b = store.refresh_counts(store.get("r1"), log)
    assert b.n_events == 1 and b.to_dict()["progress"] == 0.5
