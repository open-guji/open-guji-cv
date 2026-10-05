# -*- coding: utf-8 -*-
"""已裁却不出字（overview#403 缺口 A、C）。产物与绑定行都自己造，不读工作区。

A：`decided_cells` 只收**现在仍有效**的裁决——最新绑定行 `usable(...)` 非空、或没有绑定行
   （非 confirm 事件／还没进绑定表）。老事件 `anchor:null` 判 `unanchored`、`bound=None` 的格回到
   待审队列，卡片带 `stale_verdict` 当预勾。排除名单格带字仍算已裁（缺口 B 口径），失效了也回队列。
C：`closure_gaps`：「有定字裁决」∩「seed_admit `admit=False` 且没出字」，收尾前必须为空。
"""
from __future__ import annotations

import pytest

import open_guji_cv.steps  # noqa: F401  注册产物种类
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
from open_guji_cv.review.verdict_view import closure_gaps, closure_mismatches, decided_cells, decided_view


def _ev(key: str, payload: dict, seq: int, *, kind: str = "confirm", batch: str = "b"):
    book, pg, col, slot = key.split(":")
    return make_event(batch, seq, kind,
                      EventTarget(step="seed_admit", unit="cell", key=key, book=book,
                                  page=int(pg), col=int(col), slot=int(slot)),
                      payload, source_format="server")


def _row(e, status: str, bound: str | None):
    return {"event": e.id, "key": e.target.key, "ts": e.ts, "bound": bound,
            "shape": (e.payload or {}).get("shape"), "status": status}


# ── A：decided_view ──────────────────────────────────────────────────

def test_unanchored_old_verdict_is_not_decided_and_prefills(tmp_path):
    log = EventLog(tmp_path)
    old = _ev("vol03:9:8:4", {"v": "confirm", "shape": "困"}, 1, batch="vol03-5-10-decide")
    ok = _ev("vol03:9:8:5", {"v": "confirm", "shape": "之"}, 2)
    log.append([old, ok])
    rows = {old.id: _row(old, "unanchored", None), ok.id: _row(ok, "valid", ok.target.key)}
    decided, stale = decided_view("vol03", log, rows)
    assert decided == {"vol03:9:8:5"}
    assert stale["vol03:9:8:4"]["verdict"] == {"shape": "困", "done": "1", "noGlyphLib": False}
    assert stale["vol03:9:8:4"]["status"] == "unanchored"
    assert stale["vol03:9:8:4"]["batch"] == "vol03-5-10-decide"


def test_rebound_counts_on_new_key_only(tmp_path):
    log = EventLog(tmp_path)
    e = _ev("vol02:97:4:18", {"v": "confirm", "shape": "已"}, 1)
    log.append([e])
    decided, stale = decided_view("vol02", log, {e.id: _row(e, "rebound", "vol02:97:4:19")})
    assert decided == {"vol02:97:4:19"} and stale == {}


def test_newer_valid_verdict_supersedes_stale(tmp_path):
    """用户在控制台补确认（带锚点的新事件）之后，这一格就是已裁，不再挂预勾。"""
    log = EventLog(tmp_path)
    old = _ev("vol03:9:8:4", {"v": "confirm", "shape": "困"}, 1)
    new = _ev("vol03:9:8:4", {"v": "confirm", "shape": "困"}, 2)
    log.append([old, new])
    rows = {old.id: _row(old, "unanchored", None), new.id: _row(new, "valid", new.target.key)}
    assert decided_view("vol03", log, rows) == ({"vol03:9:8:4"}, {})


def test_events_without_binding_row_keep_old_behaviour(tmp_path):
    """没有绑定行（非 confirm 事件、或给了空表 = 绑定算不出来）→ 照原编号算已裁，同改前。"""
    log = EventLog(tmp_path)
    a = _ev("vol01:5:2:10", {"v": "confirm", "shape": "復"}, 1)
    b = _ev("vol01:5:2:11", {"from": "甲", "to": "乙"}, 2, kind="relabel")
    log.append([a, b])
    assert decided_cells("vol01", log, {}) == {"vol01:5:2:10", "vol01:5:2:11"}
    assert decided_cells("vol01", log) == {"vol01:5:2:10", "vol01:5:2:11"}   # 测试日志缺省不绑


def test_seg_defect_without_shape_still_not_decided_nor_stale(tmp_path):
    log = EventLog(tmp_path)
    e = _ev("vol01:5:2:9", {"v": "seg_defect", "quality": "contaminated"}, 1)
    log.append([e])
    assert decided_view("vol01", log, {e.id: _row(e, "unanchored", None)}) == (set(), {})


def test_withdrawn_mark_requeues_without_prefill(tmp_path):
    """字形库撤下标记（human_stale_*）：撤下时刻及以前的裁决不算，格回队列、标 withdrawn（前端不预勾）；
    撤下之后再裁的照常有效（CV 总管 10-05）。"""
    log = EventLog(tmp_path)
    a = _ev("vol02:20:1:1", {"v": "confirm", "shape": "甲"}, 1)
    b = _ev("vol02:20:1:2", {"v": "confirm", "shape": "乙"}, 2)
    log.append([a, b])
    rows = {a.id: _row(a, "valid", a.target.key), b.id: _row(b, "valid", b.target.key)}
    cut_after = (a.ts[:4] + a.ts[5:7] + a.ts[8:10])           # 撤于裁决当天：作废
    marks = {"vol02:20:1:1": cut_after, "vol02:20:1:2": "19990101"}   # 撤于裁决之前：裁决照常
    decided, stale = decided_view("vol02", log, rows, marks)
    assert decided == {"vol02:20:1:2"}
    assert stale["vol02:20:1:1"]["withdrawn"] is True
    assert stale["vol02:20:1:1"]["verdict"]["shape"] == "甲"


def test_binding_stale_is_not_withdrawn(tmp_path):
    log = EventLog(tmp_path)
    e = _ev("vol03:9:8:4", {"v": "confirm", "shape": "困"}, 1)
    log.append([e])
    _, stale = decided_view("vol03", log, {e.id: _row(e, "unanchored", None)}, {})
    assert stale["vol03:9:8:4"]["withdrawn"] is False


# ── A：cards(skip_decided=True) ──────────────────────────────────────

def _rec(cid, slot, *, doubts=None, admit=False, char="因", evidence=None):
    from open_guji_cv.products.kinds.recog import AdmitRec
    return AdmitRec(id=cid, slot=slot, admit=admit, char=char, doubts=doubts or ["上下文 margin 不足(0.1)"],
                    evidence=evidence or {})


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
    st = ProductStore(tmp_path / "products")
    recs = [
        _rec("keben:1:1:3", 3),                                                       # 失效老裁决「困」
        _rec("keben:1:1:4", 4),                                                       # 有效裁决
        _rec("keben:1:1:5", 5, char=None, doubts=["excluded"],
             evidence={"excluded": "human:seg_defect"}),                              # 名单 + 失效带字
        _rec("keben:1:1:6", 6, char=None, doubts=["excluded"],
             evidence={"excluded": "human:seg_defect", "human_char": "地"}),          # 名单 + 有效带字（缺口 B）
        _rec("keben:1:1:7", 7),                                                       # 没裁过
    ]
    st.write("keben", "seed_admit", page_key(1),
             {"seed_admit": PageAdmit(page=1, columns=[ColumnAdmit(col=1, chars=recs)])})
    evs = [_ev("keben:1:1:3", {"v": "confirm", "shape": "困"}, 1, batch="keben-old"),
           _ev("keben:1:1:4", {"v": "confirm", "shape": "天"}, 2),
           _ev("keben:1:1:5", {"v": "seg_defect", "quality": "truncated", "shape": "玄"}, 3, batch="keben-old"),
           _ev("keben:1:1:6", {"v": "seg_defect", "quality": "truncated", "shape": "地"}, 4)]
    EventLog().append(evs)
    status = {"keben:1:1:3": ("unanchored", None), "keben:1:1:4": ("valid", "keben:1:1:4"),
              "keben:1:1:5": ("unanchored", None), "keben:1:1:6": ("valid", "keben:1:1:6")}
    rows = {e.id: _row(e, *status[e.target.key]) for e in evs}
    import open_guji_cv.feedback.bindings as B
    monkeypatch.setattr(B, "book_bindings", lambda book, log=None, **kw: rows)
    C.clear_cards_cache()
    yield st
    C.clear_cards_cache()


def test_cards_skip_decided_shows_stale_with_prefill(env):
    from open_guji_cv.review.cards import cards
    d = cards("keben", "1", 30, "review", env, gate_cut=False, skip_decided=True)
    by = {c["id"]: c for c in d["cards"]}
    assert set(by) == {"keben:1:1:3", "keben:1:1:5", "keben:1:1:7"}
    assert by["keben:1:1:3"]["stale_verdict"]["verdict"]["shape"] == "困"
    assert by["keben:1:1:5"]["stale_verdict"]["verdict"] == {"shape": "玄", "done": "truncated"}
    assert by["keben:1:1:7"]["stale_verdict"] is None
    assert d["n_decided"] == 2


def test_cards_without_skip_still_carries_stale(env):
    from open_guji_cv.review.cards import cards
    d = cards("keben", "1", 30, "review", env, gate_cut=False, skip_decided=False)
    by = {c["id"]: c for c in d["cards"]}
    assert "keben:1:1:4" in by and by["keben:1:1:4"]["stale_verdict"] is None
    assert by["keben:1:1:3"]["stale_verdict"]["verdict"]["shape"] == "困"
    assert "keben:1:1:6" not in by          # 名单上、有效带字：照旧不出卡（缺口 B）


# ── C：closure_gaps ──────────────────────────────────────────────────

def test_closure_gaps_lists_decided_but_silent(env):
    gaps = closure_gaps("keben", [1], env)
    # 3：失效 → admit=False 没出字；5：名单 + 失效带字、没挂 human_char；6：挂了 human_char 算出字；
    # 4：有效裁决但产物还没重跑（admit=False）——闸照样报，提醒重跑 Step7
    assert [(g["id"], g["shape"], g["excluded"]) for g in gaps] == [
        ("keben:1:1:3", "困", False), ("keben:1:1:4", "天", False), ("keben:1:1:5", "玄", True)]


def test_closure_gaps_zero_when_text_has_char(tmp_path):
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.products.kinds.recog import ColumnAdmit, PageAdmit
    from open_guji_cv.products.store import ProductStore
    st = ProductStore(tmp_path / "products")
    recs = [_rec("bk:2:1:1", 1, admit=True, char="困"),
            _rec("bk:2:1:2", 2, char="印", evidence={"occluded": {"via": "coord"}}),
            _rec("bk:2:1:3", 3, char=None, doubts=["excluded"], evidence={"excluded": "human:not_a_char"})]
    st.write("bk", "seed_admit", page_key(2),
             {"seed_admit": PageAdmit(page=2, columns=[ColumnAdmit(col=1, chars=recs)])})
    log = EventLog(tmp_path / "ev")
    log.append([_ev("bk:2:1:1", {"v": "confirm", "shape": "困"}, 1),
                _ev("bk:2:1:2", {"v": "confirm", "shape": "印"}, 2),
                _ev("bk:2:1:3", {"v": "confirm", "shape": "之"}, 3),
                _ev("bk:2:1:3", {"v": "not_a_char"}, 4)])           # 后来改判非字：不算定了字
    assert closure_gaps("bk", [2], st, log) == []


def test_closure_mismatches_report(tmp_path):
    """报告项：人裁字 ≠ 现行放行字（不要求为 0）；己已巳族单列；同一位按最新裁决比。"""
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.products.kinds.recog import ColumnAdmit, PageAdmit
    from open_guji_cv.products.store import ProductStore
    st = ProductStore(tmp_path / "products")
    recs = [_rec("vol02:22:4:20", 20, admit=True, char="邢"),     # 人裁 璹、机器放行 邢
            _rec("vol02:22:4:21", 21, admit=True, char="已"),     # 人裁 巳：己已巳族
            _rec("vol02:22:4:22", 22, admit=True, char="天"),     # 先裁 地 后改 天：按最新比，一致
            _rec("vol02:22:4:23", 23, admit=False, char="玄")]    # 没放行：归收尾闸，不进报告项
    st.write("vol02", "seed_admit", page_key(22),
             {"seed_admit": PageAdmit(page=22, columns=[ColumnAdmit(col=4, chars=recs)])})
    log = EventLog(tmp_path / "ev")
    log.append([_ev("vol02:22:4:20", {"v": "confirm", "shape": "璹"}, 1),
                _ev("vol02:22:4:21", {"v": "confirm", "shape": "巳"}, 2),
                _ev("vol02:22:4:22", {"v": "confirm", "shape": "地"}, 3),
                _ev("vol02:22:4:22", {"v": "confirm", "shape": "天"}, 4),
                _ev("vol02:22:4:23", {"v": "confirm", "shape": "黃"}, 5)])
    got = closure_mismatches("vol02", [22], st, log)
    assert [(m["id"], m["shape"], m["char"], m["kind"]) for m in got] == [
        ("vol02:22:4:20", "璹", "邢", "main"), ("vol02:22:4:21", "巳", "已", "jys")]
