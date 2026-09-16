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

import numpy as np
import pytest

from open_guji_cv.clustering.glyph_db import GlyphDB
from open_guji_cv.feedback.consumers import crop_exclude, glyphdb_admit, route_and_consume
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
from open_guji_cv.feedback.harvest import (from_marks, from_page_html, from_seed_log,
                                           from_seg_log, from_verdicts, harvest_text,
                                           parse_card_id, to_shell_verdicts)
from open_guji_cv.feedback.routes import RouteTable
from open_guji_cv.gold.store import GoldStore
from open_guji_cv.products.cache import ImageCache
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


def test_route_and_consume_dedupes_mark_consumed_for_multi_dest_events(tmp_path):
    """同一事件命中同一消费者的多条路由（cutline+border 同时进 touching-cuts
    与 side-rule）时，`consumed/gold_add.jsonl` 只该记一行，不是两行。

    2026-09-10 金标对账道实测：`route_and_consume` 把 `pairs`（含同一事件的
    多条 (event, destination) 组合）原样传给 `mark_consumed`，同一事件被记
    两次——`consumed_ids()` 用 set 收，不影响幂等判定，但账本行数失真（是
    `consumed/gold_add.jsonl` 总行数比唯一事件数多出来的全部原因）。
    """
    log = EventLog(tmp_path / "feedback")
    store = GoldStore(tmp_path / "dataset")
    e = make_event("r1", 1, "cutline",
                    EventTarget(step="row_segment", unit="cell", key="vol02:1:1:1"),
                    {"y": 10, "y_old": 12, "verdict": "moved", "tags": ["border"]})
    log.append([e])
    route_and_consume(log, "r1", RouteTable.load(None), store)
    # 金标本身：两个分片各写一条，没有丢
    assert len(store.list("char-segmentation/touching-cuts")) == 1
    assert len(store.list("char-segmentation/side-rule")) == 1
    # 记账：consumed/gold_add.jsonl 只该有一行，不是两行
    consumed_path = log.consumed_dir / "gold_add.jsonl"
    lines = consumed_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == e.id


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


# ── Step8：名分与位置 ────────────────────────────────────────────────
def test_step8_outlets_match_consumers():
    """Step8 的三个出口必须与 consumers.CONSUMERS 里真正在跑的消费者对上，
    不是自己重写了一套平行的说法。"""
    from open_guji_cv.feedback.step8 import STEP8, describe

    assert {o.consumer for o in STEP8.outlets} == {"gold_add", "glyphdb_admit", "crop_exclude"}
    d = describe()
    assert d["id"] == "step8_feedback" and len(d["outlets"]) == 3


# ── 落库六条纪律：glyphdb_admit（① 落字形库）────────────────────────
def _cell_target(key: str, book: str, page: int, col: int, slot: int) -> EventTarget:
    return EventTarget(step="seed_admit", unit="cell", key=key, book=book, page=page,
                       col=col, slot=slot)


def _put_char_patch(monkeypatch, tmp_path: Path, book: str, page: int, col: int,
                    slot: int, sub: str = "") -> None:
    """给 `glyphdb_admit` 内部硬编码的 `ImageCache()` 铺一张测试图块。

    `glyphdb_admit` 自己 new 一个 `ImageCache()`，不接收 cache 参数——测试靠
    `GUJI_CACHE_DIR` 环境变量把默认根指到 tmp_path，双方读写同一处，不碰仓内
    真缓存。"""
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    cache = ImageCache(root=tmp_path / "cache")
    img = np.full((32, 32), 40, dtype=np.uint8)
    ckey = f"p{page:04d}c{col:02d}s{slot}{sub}"
    cache.put(book, "char_patch", ckey, img)


def test_glyphdb_admit_reading_forced_to_shape_outside_exception(monkeypatch, tmp_path):
    """纪律1（字形与释读分开存）在 glyphdb_admit 这一处的守卫：非己/已/巳时，
    reading 必须被拉回等于 shape——旧组视图曾对所有组无条件填整理本字当文意，
    脏了 62 条，这条守卫就是防这个案底在消费者这一层重演。"""
    _put_char_patch(monkeypatch, tmp_path, "vol01", 4, 1, 3)
    t = _cell_target("vol01:4:1:3", "vol01", 4, 1, 3)
    e = make_event("r1", 1, "confirm", t, {"shape": "卽", "reading": "即", "conversion": 1})
    db_path = str(tmp_path / "g.db")
    res = glyphdb_admit([(e, None)], db_path=db_path)
    assert res.added == 1 and not res.errors
    db = GlyphDB(db_path)
    label = db.conn.execute("SELECT label FROM instances WHERE instance_id=?",
                            ("v2:vol01:4:1:3",)).fetchone()[0]
    char = db.conn.execute("SELECT char FROM admissions WHERE instance_id=?",
                           ("v2:vol01:4:1:3",)).fetchone()[0]
    assert label == "卽"    # instances.label 永远照录刻本形，不被文意覆盖
    assert char == "卽"     # 非己/已/巳：admissions.char 也被拉回 shape，"即" 不採信


def test_glyphdb_admit_ji_yi_si_exception_keeps_shape_on_label(monkeypatch, tmp_path):
    """己/已/巳允许字形与文意分岔，但 instances.label 仍照录刻本形（唯一例外
    也不例外的那一半）。"""
    _put_char_patch(monkeypatch, tmp_path, "vol01", 9, 2, 5)
    t = _cell_target("vol01:9:2:5", "vol01", 9, 2, 5)
    e = make_event("r1", 1, "confirm", t, {"shape": "巳", "reading": "已", "conversion": 1})
    db_path = str(tmp_path / "g.db")
    res = glyphdb_admit([(e, None)], db_path=db_path)
    assert res.added == 1
    db = GlyphDB(db_path)
    label = db.conn.execute("SELECT label FROM instances WHERE instance_id=?",
                            ("v2:vol01:9:2:5",)).fetchone()[0]
    char = db.conn.execute("SELECT char FROM admissions WHERE instance_id=?",
                           ("v2:vol01:9:2:5",)).fetchone()[0]
    assert label == "巳" and char == "已"


def test_glyphdb_admit_relabel_goes_through_evict_and_readmit(monkeypatch, tmp_path):
    """纪律2：改判必须走「撤库+重放」，不能被 `admit_instance` 的幂等闸吞掉——
    这个坑咬过三次（29:4:19、80:5:7、32:7:10 都是它）。"""
    _put_char_patch(monkeypatch, tmp_path, "vol01", 29, 4, 19)
    t = _cell_target("vol01:29:4:19", "vol01", 29, 4, 19)
    db_path = str(tmp_path / "g.db")
    e1 = make_event("r1", 1, "confirm", t, {"shape": "巳"})
    res1 = glyphdb_admit([(e1, None)], db_path=db_path)
    assert res1.added == 1
    e2 = make_event("r2", 1, "confirm", t, {"shape": "已"})   # 改判
    res2 = glyphdb_admit([(e2, None)], db_path=db_path)
    assert res2.added == 1 and res2.updated == 1              # 撤库后重进，不是被幂等闸吞掉
    db = GlyphDB(db_path)
    label = db.conn.execute("SELECT label FROM instances WHERE instance_id=?",
                            ("v2:vol01:29:4:19",)).fetchone()[0]
    assert label == "已"                                       # 库里最终是改判后的值


def test_glyphdb_admit_duplicate_call_is_idempotent(monkeypatch, tmp_path):
    """同一条事件（同一批）再消费一次，第二次什么也不做——不是改判，直接被幂等闸挡住。"""
    _put_char_patch(monkeypatch, tmp_path, "vol01", 40, 9, 17)
    t = _cell_target("vol01:40:9:17", "vol01", 40, 9, 17)
    e = make_event("r1", 1, "confirm", t, {"shape": "蠹"})
    db_path = str(tmp_path / "g.db")
    res1 = glyphdb_admit([(e, None)], db_path=db_path)
    assert res1.added == 1
    res2 = glyphdb_admit([(e, None)], db_path=db_path)
    assert res2.added == 0 and res2.skipped == 1


def test_glyphdb_admit_provenance_is_human(monkeypatch, tmp_path):
    """纪律3现状：glyphdb_admit 只接人裁的 confirm 事件，provenance 一律 human——
    v2 自动放行（纪律5，方针待定）目前没有事件通道喂给这个消费者，本道按现状
    实现即可，不替它拍板。"""
    _put_char_patch(monkeypatch, tmp_path, "vol01", 6, 1, 1)
    t = _cell_target("vol01:6:1:1", "vol01", 6, 1, 1)
    e = make_event("r1", 1, "confirm", t, {"shape": "日"}, actor="user")
    db_path = str(tmp_path / "g.db")
    glyphdb_admit([(e, None)], db_path=db_path)
    db = GlyphDB(db_path)
    prov = db.conn.execute("SELECT provenance FROM admissions WHERE instance_id=?",
                           ("v2:vol01:6:1:1",)).fetchone()[0]
    assert prov == "human"


def test_glyphdb_admit_records_per_instance_evidence(monkeypatch, tmp_path):
    """纪律4：逐实例证据，不做盲传播——起因是 glyph_store 94 个"人工"标签全是
    簇级传播、逐张复核 11.7% 是错的。每条 admissions.evidence 都要能各自追回
    触发它的那条事件 id，不能两个实例共享一条证据。"""
    _put_char_patch(monkeypatch, tmp_path, "vol01", 3, 1, 1)
    _put_char_patch(monkeypatch, tmp_path, "vol01", 3, 1, 2)
    t1 = _cell_target("vol01:3:1:1", "vol01", 3, 1, 1)
    t2 = _cell_target("vol01:3:1:2", "vol01", 3, 1, 2)
    e1 = make_event("r1", 1, "confirm", t1, {"shape": "月"})
    e2 = make_event("r1", 2, "confirm", t2, {"shape": "月"})
    db_path = str(tmp_path / "g.db")
    res = glyphdb_admit([(e1, None), (e2, None)], db_path=db_path)
    assert res.added == 2
    db = GlyphDB(db_path)
    ev1 = json.loads(db.conn.execute(
        "SELECT evidence FROM admissions WHERE instance_id=?", ("v2:vol01:3:1:1",)).fetchone()[0])
    ev2 = json.loads(db.conn.execute(
        "SELECT evidence FROM admissions WHERE instance_id=?", ("v2:vol01:3:1:2",)).fetchone()[0])
    assert ev1["event"] == "evt_r1_000001" and ev2["event"] == "evt_r1_000002"
    assert ev1["event"] != ev2["event"]      # 各自的证据，不是共享一条


def test_glyphdb_admit_skips_seg_defect_events(monkeypatch, tmp_path):
    """切分缺陷（confirm 但 payload.v=="seg_defect"）答的是"这块图能不能用"，
    不是"这是什么字"，不能进字形库——那是 gold_add / crop_exclude 的事。"""
    _put_char_patch(monkeypatch, tmp_path, "vol01", 1, 1, 1)
    t = _cell_target("vol01:1:1:1", "vol01", 1, 1, 1)
    e = make_event("r1", 1, "confirm", t, {"v": "seg_defect", "quality": "truncated", "shape": "月"})
    res = glyphdb_admit([(e, None)], db_path=str(tmp_path / "g.db"))
    assert res.added == 0 and res.skipped == 1


# ── 落库六条纪律：crop_exclude（③ 排除名单）─────────────────────────
def test_crop_exclude_appends_seg_defect_and_not_a_char():
    """2026-09-05 补的缺口：标了缺陷／判非字都要写进排除名单，不能只落金标——
    否则「标了缺陷」与「以后别再用这块图」之间就是断的。"""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "crop_exclusions.jsonl"
        t1 = _cell_target("vol01:5:2:9", "vol01", 5, 2, 9)
        t2 = _cell_target("vol01:5:2:10", "vol01", 5, 2, 10)
        e1 = make_event("r1", 1, "confirm", t1, {"v": "seg_defect", "quality": "contaminated"})
        e2 = make_event("r1", 2, "not_a_char", t2, {})
        res = crop_exclude([(e1, None), (e2, None)], list_path=str(path))
        assert res.added == 2 and not res.errors
        rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
        reasons = {r["instance_id"]: r["reason"] for r in rows}
        assert reasons == {"vol01:5:2:9": "seg_defect", "vol01:5:2:10": "not_a_char"}
        assert all(r["origin"] == "human" for r in rows)   # 人眼实锤这一档


def test_crop_exclude_dedup_skips_known_id():
    """同一实例第二批又标了一次缺陷（比如改判），不重复写进名单。"""
    from open_guji_cv.clustering.exclusions import load_exclusions
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "crop_exclusions.jsonl"
        t = _cell_target("vol01:5:2:9", "vol01", 5, 2, 9)
        e1 = make_event("r1", 1, "confirm", t, {"v": "seg_defect", "quality": "contaminated"})
        crop_exclude([(e1, None)], list_path=str(path))
        load_exclusions.cache_clear()
        e2 = make_event("r2", 1, "confirm", t, {"v": "seg_defect", "quality": "truncated"})
        res = crop_exclude([(e2, None)], list_path=str(path))
        assert res.added == 0 and res.skipped == 1
        assert len(path.read_text(encoding="utf-8").splitlines()) == 1
        load_exclusions.cache_clear()


def test_crop_exclude_dry_run_does_not_write():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "crop_exclusions.jsonl"
        t = _cell_target("vol01:5:2:9", "vol01", 5, 2, 9)
        e = make_event("r1", 1, "not_a_char", t, {})
        res = crop_exclude([(e, None)], list_path=str(path), dry_run=True)
        assert res.added == 1
        assert not path.exists()


# ── 落库六条纪律：金标记的是当前状态（⑥）＋ 全出口幂等（完成判据3）───
def test_gold_add_seg_defect_quality_reflects_current_not_history(tmp_path):
    """纪律6：金标记的是「当前切得怎么样」，不是历史问题——缺陷修好后复量要能
    改回 clean，历史留在 source_events，不是只能越标越差。"""
    # confirm/seg_defect 同时也会路由给 crop_exclude（甚至 glyphdb_admit）——
    # 不显式指定 list_path/db_path 就会落到仓内真实的 config/crop_exclusions.jsonl，
    # 这条纪律不该以「顺手弄脏真配置」为代价来验证，所以两个都指到 tmp_path。
    excl_path = str(tmp_path / "crop_exclusions.jsonl")
    db_path = str(tmp_path / "g.db")
    log = EventLog(tmp_path / "feedback")
    store = GoldStore(tmp_path / "dataset")
    t = _cell_target("vol01:12:3:8", "vol01", 12, 3, 8)
    log.append([make_event("r1", 1, "confirm", t, {"v": "seg_defect", "quality": "contaminated"})])
    route_and_consume(log, "r1", RouteTable.load(None), store, list_path=excl_path, db_path=db_path)
    item = store.get("char-segmentation/instances", "vol01:12:3:8")
    assert item.expected["quality"] == "contaminated"

    log.append([make_event("r2", 1, "confirm", t, {"v": "seg_defect", "quality": "clean"})])
    route_and_consume(log, "r2", RouteTable.load(None), store, list_path=excl_path, db_path=db_path)
    item = store.get("char-segmentation/instances", "vol01:12:3:8")
    assert item.expected["quality"] == "clean"                              # 当前状态改回 clean
    assert set(item.source_events) == {"evt_r1_000001", "evt_r2_000001"}    # 历史留在 source_events


def test_route_and_consume_all_three_outlets_fan_out_and_idempotent(monkeypatch, tmp_path):
    """三个出口在同一条 confirm 事件上各司其职地跑一遍，且整批（不只是 gold_add
    那一路）再消费一次时第二次什么也不做——完成判据3要的是这个整体幂等，不是
    只测过 gold_add 那一个出口。"""
    _put_char_patch(monkeypatch, tmp_path, "vol01", 20, 2, 4)
    log = EventLog(tmp_path / "feedback")
    store = GoldStore(tmp_path / "dataset")
    t = _cell_target("vol01:20:2:4", "vol01", 20, 2, 4)
    log.append([make_event("r1", 1, "confirm", t, {"shape": "集"})])

    db_path = str(tmp_path / "g.db")
    excl_path = str(tmp_path / "crop_exclusions.jsonl")
    out = route_and_consume(log, "r1", RouteTable.load(None), store,
                            db_path=db_path, list_path=excl_path)
    by_consumer = {r["consumer"]: r for r in out["results"]}
    assert by_consumer["glyphdb_admit"]["added"] == 1     # 定字：进库
    assert by_consumer["gold_add"]["skipped"] == 1        # 定字：gold_add 只管切分缺陷，跳过
    assert by_consumer["crop_exclude"]["skipped"] == 1    # 定字：不是缺陷/非字，跳过

    out2 = route_and_consume(log, "r1", RouteTable.load(None), store,
                             db_path=db_path, list_path=excl_path)
    assert out2["results"] == []                         # 三个出口全部什么也不做
