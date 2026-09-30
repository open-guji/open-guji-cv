# -*- coding: utf-8 -*-
"""按类别审（overview#247）：`cards(cls=…)`、己已巳专用卡的事件协议、整理本优先的上下文。

产物自己造（`PageAdmit` / `PageAlignRef` 直接构造），不扫真书。要守的：

1. 一张卡只归**优先级最高**的一类；计数不受 `limit` 截断；不传 `cls` 时响应里没有新字段。
2. 卡片「整理本」一栏读 `align_ref` 产物，混进来的康熙部首码位归一成正字。
3. 上下文每格默认给整理本对位字（`text`），对不上的退回刻本定字；带 sub 的项按 (slot, sub) 取。
4. 己已巳三选一发出的事件行与普通卡点同一个字**逐字段相同**，下游 `human_chars` 读出的字不变。
5. 切线用例的进程内记忆：同产物第二次不重算，产物一变就失效，没取全的不记。
"""
from __future__ import annotations

import importlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import open_guji_cv.steps  # noqa: F401  注册产物种类


def _rec(cid, slot, doubts, *, admit=False, char="之", evidence=None, sub=None):
    from open_guji_cv.products.kinds.recog import AdmitRec
    return AdmitRec(id=cid, slot=slot, sub=sub, admit=admit, char=char, doubts=doubts,
                    evidence=evidence or {})


# ── 1. 归类规则（纯函数）───────────────────────────────────────────────

def test_card_class_priority_one_class_per_card():
    from open_guji_cv.review.cards import REVIEW_CLASSES, card_class
    # vol03 最常见的组合：三条疑因同时在 → 只归优先级最高的「对齐改字层」
    assert card_class(["replace_align", "上下文 margin 不足(0.10)", "库 unsure(cov=0.9)"]) == "replace_align"
    # 印章遮挡压过一切，哪怕字是 己
    assert card_class(["occluded", "near_form"], char="己") == "occluded"
    # 己已巳：字 / 整理本字 / 库首选 任一在本族，或有 ji_yi_si 证据、ji_yi_si_review 码
    assert card_class(["replace_align", "near_form"], char="已") == "ji_yi_si"
    assert card_class(["库 unsure(cov=0.9)"], ref_char="巳") == "ji_yi_si"
    assert card_class([], lib_top="己") == "ji_yi_si"
    assert card_class([], evidence={"ji_yi_si": {"char": "已", "why": "默认:已"}}) == "ji_yi_si"
    assert card_class(["ji_yi_si_review"]) == "ji_yi_si"
    assert card_class(["form_open", "near_form"]) == "form_open"
    assert card_class(["near_form", "context_vs_ref", "replace_align"]) == "ref_conflict"
    assert card_class(["solo_confusable", "库里没有这个字"]) == "near_form"
    assert card_class(["replace_align", "库里没有这个字"]) == "lib_miss"
    assert card_class(["channel_off", "replace_align"]) == "variant"
    assert card_class(["上下文 margin 不足(0.1)"]) == "other"
    assert card_class(None) == "other"
    # 表序即优先级，键唯一
    keys = [k for k, _l, _h in REVIEW_CLASSES]
    assert len(keys) == len(set(keys)) and keys[0] == "occluded" and keys[-1] == "other"


def test_parse_class_filter():
    from open_guji_cv.review.cards import parse_class_filter
    assert parse_class_filter("") is None and parse_class_filter("  ") is None
    assert parse_class_filter("*") == "*" == parse_class_filter("all")
    assert parse_class_filter("ji_yi_si") == "ji_yi_si"
    with pytest.raises(ValueError):
        parse_class_filter("己已巳")


# ── 2. cards(cls=…) ────────────────────────────────────────────────

@pytest.fixture
def env(ws, tmp_path, monkeypatch):
    """keben 两页待审卡 + 一页整理本对位（第 1 页锚上、第 2 页只有坐标对位）。"""
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.products.kinds.recog import (AlignRec, ColumnAdmit, CoordRec, PageAdmit,
                                                   PageAlignRef)
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.review import cards as C
    fb = tmp_path / "fb"
    (fb / "events").mkdir(parents=True)
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(fb))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(tmp_path / "products"))
    st = ProductStore(tmp_path / "products")
    p1 = [
        _rec("keben:1:1:1", 1, ["replace_align", "上下文 margin 不足(0.1)", "库 unsure(cov=0.9)"]),
        _rec("keben:1:1:2", 2, ["库 unsure(cov=0.8)"], char="而"),      # 整理本给 ⼰（部首码位）→ 己已巳
        _rec("keben:1:1:3", 3, ["near_form", "replace_align"]),
        _rec("keben:1:1:4", 4, ["occluded"], evidence={"occluded": {"via": "coord", "ref_blank": False}}),
        _rec("keben:1:1:5", 5, [], admit=True),
        _rec("keben:1:1:6", 6, ["replace_align"]),
    ]
    p2 = [
        _rec("keben:2:1:1", 1, ["channel_off"]),
        _rec("keben:2:1:2", 2, ["replace_align"]),
    ]
    for pg, recs in ((1, p1), (2, p2)):
        st.write("keben", "seed_admit", page_key(pg),
                 {"seed_admit": PageAdmit(page=pg, columns=[ColumnAdmit(col=1, chars=recs)])})
    st.write("keben", "align_ref", page_key(1), {"align_ref": PageAlignRef(
        page=1, anchored=True,
        chars=[AlignRec(id="keben:1:1:1", col=1, slot=1, align_char="天", align_op="equal", ref_run=5),
               AlignRec(id="keben:1:1:2", col=1, slot=2, align_char="⼰", align_op="replace", ref_run=1)])})
    st.write("keben", "align_ref", page_key(2), {"align_ref": PageAlignRef(
        page=2, anchored=False, coord=[CoordRec(id="keben:2:1:2", col=1, slot=2, ref_char="地"),
                                       CoordRec(id="keben:2:1:1", col=1, slot=1, ref_char="〓")])})
    C.clear_cards_cache()
    yield st
    C.clear_cards_cache()


def test_cards_class_counts_not_truncated_and_filter(env):
    from open_guji_cv.review.cards import cards
    d = cards("keben", "1-2", 1, "review", env, gate_cut=False, skip_decided=False, cls="*")
    assert d["class_counts"] == {"occluded": 1, "ji_yi_si": 1, "near_form": 1, "variant": 1,
                                 "replace_align": 3}
    assert d["class_total"] == 7 and len(d["cards"]) == 1 and d["truncated"] is True
    assert [m["key"] for m in d["classes"]][:2] == ["occluded", "ji_yi_si"]
    assert all("cls" in c for c in d["cards"])
    ra = cards("keben", "1-2", 2, "review", env, gate_cut=False, skip_decided=False, cls="replace_align")
    assert [c["id"] for c in ra["cards"]] == ["keben:1:1:1", "keben:1:1:6"]
    assert ra["class_counts"]["replace_align"] == 3          # 「本类还剩」不受 limit 截断
    jys = cards("keben", "1-2", 30, "review", env, gate_cut=False, skip_decided=False, cls="ji_yi_si")
    assert [c["id"] for c in jys["cards"]] == ["keben:1:1:2"] and jys["cards"][0]["cls"] == "ji_yi_si"


def test_cards_without_cls_has_no_new_fields(env):
    from open_guji_cv.review.cards import cards
    d = cards("keben", "1-2", 30, "review", env, gate_cut=False, skip_decided=False)
    assert not {"class_counts", "class_total", "classes"} & set(d)
    assert all("cls" not in c for c in d["cards"])


def test_ref_reads_align_ref_product_and_folds_radicals(env):
    from open_guji_cv.review.cards import cards
    d = cards("keben", "1-2", 30, "review", env, gate_cut=False, skip_decided=False)
    by = {c["id"]: c for c in d["cards"]}
    assert by["keben:1:1:1"]["ref"] == {"char": "天", "op": "equal", "run": 5, "form": None}
    assert by["keben:1:1:2"]["ref"]["char"] == "己"            # U+2F30 ⼰ → 己
    assert by["keben:2:1:2"]["ref"]["op"] == "coord" and by["keben:2:1:2"]["ref"]["char"] == "地"
    assert by["keben:2:1:1"]["ref"] is None                     # 〓 占位不当整理本字


@pytest.fixture
def client(env):
    from fastapi.testclient import TestClient
    app = importlib.import_module("open_guji_cv.console.app").app
    console_auth = importlib.import_module("open_guji_cv.console.auth")
    Identity = importlib.import_module("open_guji_cv.console.auth.identity").Identity
    app.dependency_overrides[console_auth.get_identity] = lambda: Identity(
        email="r@example.com", role="reviewer", tier="reviewer")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_route_cls_param_and_cache_key(client):
    q = "/api/review/cards?book=keben&pages=1-2&gate_cut=false&skip_decided=false"
    r0 = client.get(q)
    r1 = client.get(q + "&cls=*")
    r2 = client.get(q + "&cls=ji_yi_si")
    assert r1.status_code == 200 and r2.status_code == 200, r1.text
    assert r0.headers["X-Cards-Cache"] == "miss" and r1.headers["X-Cards-Cache"] == "miss"
    assert "class_counts" not in r0.json() and r1.json()["class_counts"]["replace_align"] == 3
    assert [c["id"] for c in r2.json()["cards"]] == ["keben:1:1:2"]
    assert client.get(q + "&cls=bogus").status_code == 400


# ── 3. 上下文：整理本优先 ─────────────────────────────────────────────

def test_around_prefers_ref_text_and_sub(ws, tmp_path, monkeypatch):
    from open_guji_cv.console.routers.review import _around, _column_slots
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.products.kinds.recog import (AlignRec, ColumnDecision, DecisionRec,
                                                   PageAlignRef, PageDecision)
    from open_guji_cv.products.store import ProductStore
    st = ProductStore(tmp_path / "products")
    recs = [DecisionRec(id="b:1:1:1", slot=1, char="甲"), DecisionRec(id="b:1:1:2", slot=2, char="乙"),
            DecisionRec(id="b:1:1:3a", slot=3, sub="a", char="丙"),
            DecisionRec(id="b:1:1:3b", slot=3, sub="b", char="丁"),
            DecisionRec(id="b:1:1:4", slot=4, char="戊")]
    st.write("b", "context_decide", page_key(1),
             {"context_decision": PageDecision(page=1, columns=[ColumnDecision(col=1, chars=recs)])})
    st.write("b", "align_ref", page_key(1), {"align_ref": PageAlignRef(page=1, anchored=True, chars=[
        AlignRec(id="b:1:1:2", col=1, slot=2, align_char="已", align_op="equal"),
        AlignRec(id="b:1:1:3b", col=1, slot=3, sub="b", align_char="⼰", align_op="equal")])})
    out = _column_slots(st, "b", 1, 1, {})
    assert [x["text"] for x in out] == ["甲", "已", "丙", "己", "戊"]
    assert [x["text_src"] for x in out] == ["context", "ref", "context", "ref", "context"]
    assert [x["char"] for x in out] == ["甲", "乙", "丙", "丁", "戊"]      # 刻本读法原样留着
    r = _around(st, "b", 1, 1, 3, before=5, after=5, cache={}, sub="b")
    assert r["slots"][r["at"]]["id"] == "b:1:1:3b"
    assert r["ref_text"] == "甲已丙己戊" and r["text"] == "甲乙丙丁戊"
    # 不带 sub：照旧取这一格的第一条（改前行为）
    r = _around(st, "b", 1, 1, 3, before=1, after=1, cache={})
    assert r["slots"][r["at"]]["id"] == "b:1:1:3a"


def test_around_batch_keys_with_sub(env, client):
    r = client.post("/api/review/around/batch", json={"book": "keben", "before": 20, "after": 20, "items": [
        {"page": 1, "col": 1, "slot": 1}, {"page": 1, "col": 1, "slot": 2, "sub": "a"}]})
    assert r.status_code == 200, r.text
    assert set(r.json()["around"]) == {"1:1:1", "1:1:2a"}


# ── 4. 己已巳专用卡的事件协议（node 跑 reviewClass.ts）─────────────────

TS = (Path(__file__).resolve().parents[1]
      / "open_guji_cv/console/frontend/src/components/review/reviewClass.ts")


def _node_ok() -> bool:
    node = shutil.which("node")
    if not node:
        return False
    return subprocess.run([node, "--experimental-strip-types", "-e", "0"],
                          capture_output=True).returncode == 0


needs_node = pytest.mark.skipif(not _node_ok(), reason="没有支持 --experimental-strip-types 的 node（≥22.6）")


def _run_ts(tmp_path, body: str):
    mod = tmp_path / "reviewClass.mts"
    shutil.copy(TS, mod)
    runner = tmp_path / "run.mts"
    runner.write_text("import * as R from './reviewClass.mts'\n" + body, encoding="utf-8")
    r = subprocess.run([shutil.which("node"), "--experimental-strip-types", "--no-warnings", str(runner)],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


@needs_node
def test_ts_jys_pick_emits_same_row_as_generic_pick(tmp_path):
    out = _run_ts(tmp_path, """
const now = 1000, seen = 400
const picks = ['1', '2', '3'].map((k) => R.jysPickByKey(k))
// 己已巳卡按 2 = 选「已」；普通卡点候选「已」走的是同一个 pickVerdict（ReviewPanel.setVerdict）
const jys = R.verdictRow('b:1:1:2', R.pickVerdict(R.jysPickByKey('2'), undefined, seen, now))
const gen = R.verdictRow('b:1:1:2', R.pickVerdict('已', undefined, seen, now))
// 先标了 T（字形不完整）再三选一：缺陷档保住，字照样带上
const defect = R.verdictRow('b:1:1:2', R.pickVerdict('巳', { shape: '', done: 'truncated', dwell: 7 }, seen, now))
const none = R.verdictRow('b:1:1:2', { shape: '', done: '' })
console.log(JSON.stringify({ picks, jys, gen, defect, none,
  noneKeys: R.JYS_NONE_KEYS, isJ: R.isJysCard('ji_yi_si', false), opened: R.isJysCard('ji_yi_si', true),
  ctx: [R.ctxChar({ char: '乙', text: '已' }, false), R.ctxChar({ char: '乙', text: '已' }, true),
        R.ctxChar({ char: null }, false)] }))
""")
    assert out["picks"] == ["己", "已", "巳"]
    assert out["jys"] == out["gen"] == {"id": "b:1:1:2", "v": "confirm", "shape": "已",
                                        "no_glyph_lib": False, "client_ts": 1000, "dwell_ms": 600}
    assert out["defect"] == {"id": "b:1:1:2", "v": "seg_defect", "quality": "truncated", "shape": "巳",
                             "client_ts": 1000, "dwell_ms": 7}
    assert out["none"] is None and out["isJ"] is True and out["opened"] is False
    assert "4" in out["noneKeys"]
    assert out["ctx"] == ["已", "乙", "□"]


@needs_node
def test_ts_verdict_row_matches_previous_submit_mapping(tmp_path):
    """`verdictRow` 是从 submit 里原样抽出来的：各档行形状与改前逐字段相同。"""
    out = _run_ts(tmp_path, """
const v = (done, extra = {}) => ({ shape: '天', done, ts: 5, dwell: 9, ...extra })
console.log(JSON.stringify([
  R.verdictRow('x', v('skip')), R.verdictRow('x', v('non')),
  R.verdictRow('x', v('damaged', { guess: '天' })), R.verdictRow('x', v('contaminated')),
  R.verdictRow('x', v('1', { noGlyphLib: true }), true), R.verdictRow('x', v('1'), null),
]))
""")
    assert out == [
        {"id": "x", "v": "skip"},
        {"id": "x", "v": "not_a_char"},
        {"id": "x", "v": "damaged", "guess": "天", "client_ts": 5, "dwell_ms": 9},
        {"id": "x", "v": "seg_defect", "quality": "contaminated", "shape": "天", "client_ts": 5, "dwell_ms": 9},
        {"id": "x", "v": "confirm", "shape": "天", "no_glyph_lib": True, "client_ts": 5, "dwell_ms": 9,
         "ai_accepted": True},
        {"id": "x", "v": "confirm", "shape": "天", "no_glyph_lib": False, "client_ts": 5, "dwell_ms": 9},
    ]


def test_jys_rows_read_downstream_unchanged(tmp_path):
    """己已巳卡发的行（上面 node 用例钉住的形状）经 `/api/events` 同一套信封写进日志后，
    `human_chars` 读出的就是选的那个字——与普通卡点同一个字的结果完全一样；`seg_defect` 带字同理。"""
    from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
    from open_guji_cv.feedback.lookup import human_chars
    rows = [
        {"id": "vol01:4:1:3", "v": "confirm", "shape": "已", "no_glyph_lib": False, "client_ts": 1, "dwell_ms": 2},
        {"id": "vol01:4:1:4", "v": "confirm", "shape": "巳", "no_glyph_lib": False, "client_ts": 1, "dwell_ms": 2},
        {"id": "vol01:4:1:5", "v": "seg_defect", "quality": "truncated", "shape": "己", "client_ts": 1, "dwell_ms": 2},
        {"id": "vol01:4:1:6", "v": "not_a_char"},
    ]
    log = EventLog(tmp_path)
    evs = []
    for i, row in enumerate(rows, 1):
        _, pg, col, slot = row["id"].split(":")
        payload = {k: v for k, v in row.items() if k not in ("id", "t")}   # 与 `_api_events` 同一句
        evs.append(make_event("b", i, "confirm",
                              EventTarget(step="seed_admit", unit="cell", key=row["id"], book="vol01",
                                          page=int(pg), col=int(col), slot=int(slot)),
                              payload, source_format="server"))
    log.append(evs)
    got = human_chars("vol01", log, stale={}, bind=False)
    assert got == {"vol01:4:1:3": "已", "vol01:4:1:4": "巳", "vol01:4:1:5": "己"}


# ── 5. 康熙部首归一 ──────────────────────────────────────────────────

def test_fold_radicals():
    from open_guji_cv.utils.radicals import count_radicals, fold_radicals, is_radical
    assert fold_radicals("而⼰矣") == "而己矣"
    assert fold_radicals("⺟") == "母"            # 部首补充区有兼容分解的
    assert fold_radicals("⺊") == "⺊"        # ⺊ 没有兼容分解：原样（不瞎猜）
    assert fold_radicals("己已巳爲為") == "己已巳爲為"  # 正字、繁简异体一概不动
    assert fold_radicals(None) is None and fold_radicals("") == ""
    assert is_radical("⼰") and not is_radical("己")
    assert count_radicals("⼰⼰⺊己") == {"⼰": 2, "⺊": 1}


# ── 6. 切线用例记忆 ───────────────────────────────────────────────────

def test_cutline_cases_memo(env, monkeypatch):
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.eval import touching as T
    from open_guji_cv.products.kinds.recog import ColumnAdmit, PageAdmit
    from open_guji_cv.review import cards as C
    calls = []

    def r2s(book, pgs, st):
        calls.append(tuple(pgs))
        return [{"id": "x", "page": 1, "col": 1, "slot_above": 1, "slot_below": 2, "bi": 1}]

    monkeypatch.setattr(T, "r2s_boundaries", r2s)
    monkeypatch.setattr(T, "split_char_boundaries", lambda book, pgs, st: [])
    monkeypatch.setattr(C, "_warm_column_images", lambda book, pgs, st: set())
    a = C._cutline_cases("keben", [1, 2], env)
    b = C._cutline_cases("keben", [1, 2], env)
    assert a == b and a[0] and len(calls) == 1                  # 第二次读记忆
    env.write("keben", "seed_admit", page_key(3),
              {"seed_admit": PageAdmit(page=3, columns=[ColumnAdmit(col=1, chars=[])])})
    C._cutline_cases("keben", [1, 2], env)
    assert len(calls) == 1                                      # 页范围外的产物变了：不相干
    env.write("keben", "seed_admit", page_key(1),
              {"seed_admit": PageAdmit(page=1, columns=[ColumnAdmit(col=1, chars=[])])})
    C._cutline_cases("keben", [1, 2], env)
    assert len(calls) == 1          # 识别段（人裁一条就标失效的 seed_admit）变了：切线用例不相干
    # 切分段的产物重写了 → 重算（文件内容无所谓，记忆按文件本身的 stat 认）
    env.write("keben", "row_segment", page_key(1),
              {"seed_admit": PageAdmit(page=1, columns=[ColumnAdmit(col=1, chars=[])])})
    C._cutline_cases("keben", [1, 2], env)
    assert len(calls) == 2
    # 有列取不到列图：不记（下次照旧重试，冷缓存兜底语义不变）
    monkeypatch.setattr(C, "_warm_column_images", lambda book, pgs, st: {(1, 1)})
    C._CASES_MEM.clear()
    _cases, unavailable, _f = C._cutline_cases("keben", [1, 2], env)
    C._cutline_cases("keben", [1, 2], env)
    assert unavailable == {(1, 1)} and len(calls) == 4
