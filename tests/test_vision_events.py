# -*- coding: utf-8 -*-
"""看图结论事件通道（overview#428）：模型看图判的结论**不是人裁**。

- 落 `feedback/vision/`，不进 `feedback/events/`；事件 `actor="model"`、`payload.source="vision"`、`judge`；
- 不进字形库、`human_chars` 不认、不算已裁、不进绑定表（误写进 events/ 的 `source="vision"` 也不认）；
  但 events/ 里早有的 `actor="model"` 人裁机械更正（码位统一、乱码还原）照旧生效；
- 金标 `label_origin="vision"`；
- 判 wrong 的格回待审队列（doubt `vision_flag`），人裁过 / 字已改的不再送。
数据全部自己造，不读工作区。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import open_guji_cv.steps  # noqa: F401  注册产物种类
from open_guji_cv.feedback.events import EventLog, EventTarget, counts_as_human, make_event
from open_guji_cv.feedback.vision import (VISION_DOUBT, VISION_SHARD, VisionLog, flag_active, import_vision,
                                          parse_jsonl, vision_checks, vision_pending)


def _ev(key: str, payload: dict, seq: int, *, kind: str = "confirm", actor: str = "user", batch: str = "b"):
    book, pg, col, slot = key.split(":")
    return make_event(batch, seq, kind,
                      EventTarget(step="seed_admit", unit="cell", key=key, book=book,
                                  page=int(pg), col=int(col), slot=int(slot)),
                      payload, actor=actor, source_format="server")


def _jsonl(path, rows):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return path


ROWS = [
    {"cell": "keben:1:1:3", "v": "wrong", "char": "曰", "shown": "日", "judge": "m1", "note": "中横不贯"},
    {"cell": "keben:1:1:4", "v": "ok", "shown": "人", "judge": "m1"},
    {"cell": "keben:1:1:5", "v": "unsure", "judge": "m1", "group": "入人八"},
]


# ── 写入 ─────────────────────────────────────────────────────────────

def test_import_writes_model_events_under_vision_only(tmp_path):
    src = _jsonl(tmp_path / "看图结论.jsonl", ROWS)
    vlog = VisionLog(tmp_path / "fb")
    res = import_vision(src, vlog, gold=False)
    assert res["errors"] == [] and res["written"] == 3
    assert res["by_v"] == {"ok": 1, "wrong": 1, "unsure": 1}
    assert res["batch"] == "vision-看图结论"
    assert (tmp_path / "fb" / "vision" / "vision-看图结论.jsonl").exists()
    assert not (tmp_path / "fb" / "events").exists()           # 不进人裁事件目录
    assert list(EventLog(tmp_path / "fb").iter_all()) == []
    evs = list(vlog.iter_all())
    assert {e.kind for e in evs} == {"vision_check"}
    assert all(e.actor == "model" and e.payload["source"] == "vision" and e.payload["judge"] == "m1"
               for e in evs)
    assert not any(counts_as_human(e) for e in evs)
    # 再导一遍：没动的行不重复写
    assert import_vision(src, vlog, gold=False)["written"] == 0


def test_bad_rows_reject_whole_batch(tmp_path):
    src = _jsonl(tmp_path / "x.jsonl", ROWS + [{"cell": "keben:1:1", "v": "wrong", "judge": "m1"},
                                              {"cell": "keben:1:1:9", "v": "错", "judge": "m1"},
                                              {"cell": "keben:1:1:9", "v": "ok"},
                                              {"cell": "keben:1:1:9", "v": "ok", "judge": "m", "chars": "曰"}])
    vlog = VisionLog(tmp_path / "fb")
    res = import_vision(src, vlog, gold=False)
    assert res["written"] == 0 and len(res["errors"]) == 4
    assert not vlog.events_dir.exists()


def test_judge_default_and_book_filter(tmp_path):
    src = _jsonl(tmp_path / "x.jsonl", [{"cell": "keben:1:1:3", "v": "ok"},
                                        {"cell": "other:1:1:3", "v": "ok"}])
    pr = parse_jsonl(src, "b", judge="m2")
    assert pr.errors == [] and {e.payload["judge"] for e in pr.events} == {"m2"}
    assert len(parse_jsonl(src, "b", judge="m2", book="keben").errors) == 1


# ── 不当人裁用 ───────────────────────────────────────────────────────

def test_model_events_not_in_glyph_store():
    from open_guji_cv.feedback.consumers import glyphdb_admit
    human = _ev("keben:1:1:3", {"v": "confirm", "shape": "曰"}, 1)
    fix = _ev("keben:1:1:4", {"v": "confirm", "shape": "曰"}, 2, actor="model")   # 码位统一类机械更正
    vis = _ev("keben:1:1:5", {"v": "confirm", "shape": "曰", "source": "vision"}, 3, actor="model")
    chk = _ev("keben:1:1:6", {"v": "wrong", "char": "曰", "source": "vision"}, 4, kind="vision_check",
              actor="model")
    res = glyphdb_admit([(human, None), (fix, None), (vis, None), (chk, None)], dry_run=True)
    assert res.added == 2 and res.skipped == 2


def test_human_chars_ignores_model_events(tmp_path):
    from open_guji_cv.feedback.lookup import human_chars
    log = EventLog(tmp_path)
    log.append([_ev("keben:1:1:3", {"v": "confirm", "shape": "曰", "source": "vision"}, 1, actor="model"),
                _ev("keben:1:1:4", {"v": "confirm", "shape": "人"}, 2),
                _ev("keben:1:1:4", {"v": "confirm", "shape": "八", "source": "vision"}, 3,
                    actor="model"),                                             # 不压过人裁
                _ev("keben:1:1:5", {"v": "confirm", "shape": "别"}, 4),
                _ev("keben:1:1:5", {"v": "confirm", "shape": "別"}, 5, actor="model")])  # 码位统一：照旧生效
    assert human_chars("keben", log, stale={}, bind=False) == {"keben:1:1:4": "人", "keben:1:1:5": "別"}


def test_decided_view_and_bindings_ignore_model_events(tmp_path):
    from open_guji_cv.feedback.bindings import _verdict_events
    from open_guji_cv.review.verdict_view import closure_gaps, decided_cells, shape_decided_cells
    log = EventLog(tmp_path)
    log.append([_ev("keben:1:1:3", {"v": "confirm", "shape": "曰", "source": "vision"}, 1, actor="model"),
                _ev("keben:1:1:4", {"v": "confirm", "shape": "人"}, 2)])
    assert decided_cells("keben", log, {}) == {"keben:1:1:4"}
    assert shape_decided_cells("keben", log) == {"keben:1:1:4": "人"}
    assert [e.target.key for evs in _verdict_events("keben", log).values() for e in evs] == ["keben:1:1:4"]
    assert closure_gaps("keben", [1], store=None, log=EventLog(tmp_path / "empty")) == []


# ── 金标 ─────────────────────────────────────────────────────────────

def test_gold_label_origin_is_vision(tmp_path):
    from open_guji_cv.feedback.consumers import label_origin_of
    from open_guji_cv.gold.store import GoldStore
    store = GoldStore(tmp_path / "verdicts")
    src = _jsonl(tmp_path / "x.jsonl", ROWS)
    res = import_vision(src, VisionLog(tmp_path / "fb"), gold_store=store)
    assert res["gold"]["added"] == 3
    items = {i.id: i for i in store.list(VISION_SHARD)}
    assert {i.label_origin for i in items.values()} == {"vision"}
    assert items["keben:1:1:3"].expected == {"v": "wrong", "char": "曰", "shown": "日", "judge": "m1",
                                             "note": "中横不贯"}
    assert items["keben:1:1:5"].status == "uncertain" and items["keben:1:1:4"].status == "active"
    # 口径：误写进 events/ 的 confirm 带 source=vision 也记 vision，user 记 human，model 记 model
    assert label_origin_of(_ev("k:1:1:1", {"source": "vision"}, 1, actor="model")) == "vision"
    assert label_origin_of(_ev("k:1:1:1", {}, 1)) == "human"
    assert label_origin_of(_ev("k:1:1:1", {}, 1, actor="model")) == "model"


# ── 送人审 ───────────────────────────────────────────────────────────

def test_flag_active_rules():
    chk = {"v": "wrong", "char": "曰", "shown": "日"}
    assert flag_active(chk, "日")
    assert not flag_active(chk, "曰")                       # 已改成看图认的字
    assert not flag_active(chk, "口")                       # 字已动过，旧结论说的不是现在这个字
    assert flag_active({"v": "wrong"}, "日")                # 认不出该是什么字也送审
    assert not flag_active({"v": "ok", "shown": "日"}, "日")
    assert not flag_active({"v": "unsure"}, "日")
    assert not flag_active(None, "日")


def _rec(cid, slot, *, admit=True, char="日", doubts=None):
    from open_guji_cv.products.kinds.recog import AdmitRec
    return AdmitRec(id=cid, slot=slot, admit=admit, char=char, doubts=doubts or [], evidence={})


@pytest.fixture
def env(ws, tmp_path, monkeypatch):
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.products.kinds.recog import ColumnAdmit, PageAdmit
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.review import cards as C
    fb = tmp_path / "fb"
    (fb / "events").mkdir(parents=True)
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(fb))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(tmp_path / "products"))
    import open_guji_cv.feedback.bindings as B
    monkeypatch.setattr(B, "book_bindings", lambda book, log=None, **kw: {})
    st = ProductStore(tmp_path / "products")
    recs = [_rec("keben:1:1:3", 3),                    # 放行「日」，看图判错（该是「曰」）→ 回队列
            _rec("keben:1:1:4", 4, char="人"),         # 看图判对 → 不出
            _rec("keben:1:1:5", 5, char="曰"),         # 看图判错，但现行字已是看图认的字 → 不出
            _rec("keben:1:1:6", 6),                    # 看图判错，人已裁过 → 不出
            _rec("keben:1:1:7", 7)]                    # 没看过 → 放行的照旧不出
    st.write("keben", "seed_admit", page_key(1),
             {"seed_admit": PageAdmit(page=1, columns=[ColumnAdmit(col=1, chars=recs)])})
    _jsonl(tmp_path / "v.jsonl", [
        {"cell": "keben:1:1:3", "v": "wrong", "char": "曰", "shown": "日", "judge": "m1"},
        {"cell": "keben:1:1:4", "v": "ok", "shown": "人", "judge": "m1"},
        {"cell": "keben:1:1:5", "v": "wrong", "char": "曰", "shown": "日", "judge": "m1"},
        {"cell": "keben:1:1:6", "v": "wrong", "char": "曰", "shown": "日", "judge": "m1"}])
    from open_guji_cv.gold.store import GoldStore
    assert import_vision(tmp_path / "v.jsonl", gold_store=GoldStore(tmp_path / "verdicts"))["written"] == 4
    EventLog().append([_ev("keben:1:1:6", {"v": "confirm", "shape": "日"}, 1)])
    C.clear_cards_cache()
    yield st
    C.clear_cards_cache()


def test_vision_wrong_cell_enters_review_queue(env):
    from open_guji_cv.review.cards import cards
    d = cards("keben", "1", 30, "review", env, gate_cut=False, skip_decided=True, doubt="*")
    by = {c["id"]: c for c in d["cards"]}
    assert set(by) == {"keben:1:1:3"}
    c = by["keben:1:1:3"]
    assert VISION_DOUBT in c["doubts"] and c["char"] == "日" and c["admit"] is True   # 不改字
    assert c["vision"]["char"] == "曰" and c["vision"]["judge"] == "m1"
    assert d["doubt_counts"].get(VISION_DOUBT) == 1
    d2 = cards("keben", "1", 30, "review", env, gate_cut=False, skip_decided=True, doubt=VISION_DOUBT)
    assert [c["id"] for c in d2["cards"]] == ["keben:1:1:3"]


def test_vision_pending_report(env):
    rows = vision_pending("keben", [1], env)
    assert [(r["id"], r["char"], r["vision"]) for r in rows] == [("keben:1:1:3", "日", "曰")]
    assert set(vision_checks("keben")) == {"keben:1:1:3", "keben:1:1:4", "keben:1:1:5", "keben:1:1:6"}


def test_vision_events_do_not_touch_human_paths(env):
    """导入看图结论后，人裁那几条路一格都没多：human_chars / decided_cells 只认那条人裁。"""
    from open_guji_cv.feedback.lookup import human_chars
    from open_guji_cv.review.verdict_view import decided_cells
    assert human_chars("keben", stale={}, bind=False) == {"keben:1:1:6": "日"}
    assert decided_cells("keben") == {"keben:1:1:6"}


def test_cli_import_vision(ws, tmp_path, monkeypatch, capsys):
    from open_guji_cv.cli_v2 import _import_vision
    fb = tmp_path / "fb"
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(fb))
    monkeypatch.setenv("GUJI_VERDICTS_DIR", str(tmp_path / "verdicts"))
    src = _jsonl(tmp_path / "v.jsonl", ROWS)
    args = SimpleNamespace(workspace=str(ws), batch=str(src), as_batch=None, judge=None, book="keben",
                           no_gold=True, dry_run=False)
    _import_vision(args)
    assert len(list(VisionLog(fb).iter_all())) == 3
    with pytest.raises(SystemExit):
        _import_vision(SimpleNamespace(**{**vars(args), "workspace": None}))
