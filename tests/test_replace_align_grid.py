# -*- coding: utf-8 -*-
"""对齐改字层 · 网格 + 「小注当正文」（overview#265）。

产物自己造，不扫真书。要守的：

1. 细项划分（`replace_align_sub`）：列尾（slot≥20）→ tail；形近疑因／整理本空／惯刻形≠整理本字 → manual；
   其余 → grid。`cards(cls_sub=…)` 只出这个细项，细项计数不受 `limit` 截断；不传 `cls` 时没有新字段。
2. 网格整屏提交的事件行与逐张裁决（按 1 采信整理本 / T / S）**逐字段相同**（node 跑 reviewClass.ts）。
3. 「小注当正文」写 `v=seg_defect` + `reason=jiazhu_as_main`；下游 `human_chars`、`decided_cells`、
   打回路由、金标、`seed_admit` 对它的处理与不带 `reason` 的同一条 seg_defect 完全一样。
"""
from __future__ import annotations

import importlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import open_guji_cv.steps  # noqa: F401  注册产物种类


def _rec(cid, slot, doubts, *, char="之"):
    from open_guji_cv.products.kinds.recog import AdmitRec
    return AdmitRec(id=cid, slot=slot, admit=False, char=char, doubts=doubts, evidence={})


RA = ["replace_align", "上下文 margin 不足(0.1)", "库 unsure(cov=0.9)"]


# ── 1. 细项划分 ───────────────────────────────────────────────────────

def test_replace_align_sub_pure():
    from open_guji_cv.review.cards import REPLACE_ALIGN_SUB_KEYS, TAIL_SLOT, replace_align_sub
    ref = {"char": "天", "form": None}
    assert TAIL_SLOT == 20 and REPLACE_ALIGN_SUB_KEYS == ("grid", "tail", "manual")
    assert replace_align_sub(19, RA, ref) == "grid"
    assert replace_align_sub(20, RA, ref) == "tail" == replace_align_sub(21, RA, ref)
    # 列尾优先：哪怕也带形近疑因、整理本空
    assert replace_align_sub(21, RA + ["near_form"], None) == "tail"
    assert replace_align_sub(5, RA + ["near_form"], ref) == "manual"
    assert replace_align_sub(5, RA + ["solo_confusable"], ref) == "manual"
    assert replace_align_sub(5, RA, None) == "manual"
    assert replace_align_sub(5, RA, {"char": "", "form": None}) == "manual"
    assert replace_align_sub(5, RA, {"char": "睹", "form": "覩"}) == "manual"   # 两个形得逐张挑
    # 上次只标了缺陷没给字：回网格又是缺省采信，归逐张
    assert replace_align_sub(5, RA, ref, defect_before=True) == "manual"
    assert replace_align_sub(21, RA, ref, defect_before=True) == "tail"


def test_defect_only_cells_latest_wins(tmp_path):
    from open_guji_cv.feedback.events import EventLog
    from open_guji_cv.review.verdict_view import defect_only_cells
    log = EventLog(tmp_path)
    log.append([_ev("vol01:4:1:3", {"v": "seg_defect", "quality": "truncated", "shape": ""}, 1),
                _ev("vol01:4:1:4", {"v": "seg_defect", "quality": "truncated", "shape": "天"}, 2),
                _ev("vol01:4:1:5", {"v": "seg_defect", "quality": "truncated", "reason": "jiazhu_as_main"}, 3),
                _ev("vol01:4:1:6", {"v": "seg_defect", "quality": "truncated"}, 4),
                _ev("vol01:4:1:6", {"v": "confirm", "shape": "地"}, 5)])       # 后来定了字
    assert defect_only_cells("vol01", log) == {"vol01:4:1:3", "vol01:4:1:5"}


@pytest.fixture
def env(ws, tmp_path, monkeypatch):
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.products.kinds.recog import AlignRec, ColumnAdmit, PageAdmit, PageAlignRef
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.review import cards as C
    fb = tmp_path / "fb"
    (fb / "events").mkdir(parents=True)
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(fb))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(tmp_path / "products"))
    st = ProductStore(tmp_path / "products")
    recs = [
        _rec("keben:1:1:3", 3, RA),                      # grid
        _rec("keben:1:1:4", 4, RA),                      # grid
        _rec("keben:1:1:5", 5, RA),                      # manual：整理本空
        _rec("keben:1:1:20", 20, RA),                    # tail
        _rec("keben:1:1:21", 21, RA),                    # tail
        _rec("keben:1:1:6", 6, ["channel_off"]),         # 别的类别，不进细项
    ]
    st.write("keben", "seed_admit", page_key(1),
             {"seed_admit": PageAdmit(page=1, columns=[ColumnAdmit(col=1, chars=recs)])})
    st.write("keben", "align_ref", page_key(1), {"align_ref": PageAlignRef(
        page=1, anchored=True,
        chars=[AlignRec(id=f"keben:1:1:{s}", col=1, slot=s, align_char=ch, align_op="replace", ref_run=1)
               for s, ch in ((3, "天"), (4, "地"), (20, "玄"), (21, "黃"), (6, "宇"))])})
    C.clear_cards_cache()
    yield st
    C.clear_cards_cache()


def test_cards_cls_sub_filter_and_counts(env):
    from open_guji_cv.review.cards import cards
    kw = dict(gate_cut=False, skip_decided=False)
    d = cards("keben", "1", 1, "review", env, cls="replace_align", cls_sub="grid", **kw)
    assert [c["id"] for c in d["cards"]] == ["keben:1:1:3"]           # limit 1
    assert d["class_sub_counts"] == {"replace_align": {"grid": 2, "tail": 2, "manual": 1}}  # 不受 limit 截断
    assert d["class_counts"]["replace_align"] == 5
    assert [m["key"] for m in d["class_subs"]["replace_align"]] == ["grid", "tail", "manual"]
    assert d["cards"][0]["cls_sub"] == "grid" and d["cards"][0]["ref"]["char"] == "天"
    t = cards("keben", "1", 30, "review", env, cls="replace_align", cls_sub="tail", **kw)
    assert [c["id"] for c in t["cards"]] == ["keben:1:1:20", "keben:1:1:21"]
    # 不给细项：整类照出，每张带 cls_sub；别的类别的卡不带
    a = cards("keben", "1", 30, "review", env, cls="*", **kw)
    by = {c["id"]: c for c in a["cards"]}
    assert by["keben:1:1:5"]["cls_sub"] == "manual" and "cls_sub" not in by["keben:1:1:6"]
    with pytest.raises(ValueError):
        cards("keben", "1", 30, "review", env, cls="variant", cls_sub="grid", **kw)
    with pytest.raises(ValueError):
        cards("keben", "1", 30, "review", env, cls="replace_align", cls_sub="bogus", **kw)


def test_grid_defect_goes_manual(env):
    """网格里点掉（字形不完整、不带字）的格下次不回网格，归逐张。"""
    from open_guji_cv.feedback.events import EventLog
    from open_guji_cv.review.cards import cards
    EventLog().append([_ev("keben:1:1:3", {"v": "seg_defect", "quality": "truncated", "shape": ""}, 1,
                           book="keben")])
    d = cards("keben", "1", 30, "review", env, cls="replace_align", cls_sub="grid",
              gate_cut=False, skip_decided=True)
    assert [c["id"] for c in d["cards"]] == ["keben:1:1:4"]
    assert d["class_sub_counts"]["replace_align"] == {"grid": 1, "tail": 2, "manual": 2}


def test_cards_without_cls_unchanged(env):
    from open_guji_cv.review.cards import cards
    d = cards("keben", "1", 30, "review", env, gate_cut=False, skip_decided=False)
    assert not {"class_sub_counts", "class_subs"} & set(d)
    assert all("cls_sub" not in c for c in d["cards"])


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


def test_route_cls_sub(client):
    q = "/api/review/cards?book=keben&pages=1&gate_cut=false&skip_decided=false"
    r = client.get(q + "&cls=replace_align&cls_sub=tail")
    assert r.status_code == 200, r.text
    assert [c["id"] for c in r.json()["cards"]] == ["keben:1:1:20", "keben:1:1:21"]
    g = client.get(q + "&cls=replace_align&cls_sub=grid").json()      # 缓存键带 cls_sub，不串
    assert [c["id"] for c in g["cards"]] == ["keben:1:1:3", "keben:1:1:4"]
    assert client.get(q + "&cls=variant&cls_sub=grid").status_code == 400
    assert client.get(q + "&cls=replace_align&cls_sub=bogus").status_code == 400


# ── 2. 网格事件 = 逐张事件（node 跑 reviewClass.ts）──────────────────

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
def test_ts_grid_rows_equal_per_card_rows(tmp_path):
    out = _run_ts(tmp_path, """
const seen = 400, now = 1000
const cards = [{ id: 'a', ref: { char: '天' } }, { id: 'b', ref: { char: '地' } },
               { id: 'c', ref: { char: '玄' } }, { id: 'd', ref: null }]
const states = { b: 'truncated', c: 'skip' }
const grid = R.gridRows(cards, states, seen, now)
// 逐张卡：a 按 1（候选第一位 = 整理本字）→ setVerdict(i, ch) → pickVerdict；b 按 T；c 按 S（ReviewPanel.setVerdict）
const per = [
  R.verdictRow('a', R.pickVerdict('天', undefined, seen, now)),
  R.verdictRow('b', { shape: '', done: 'truncated', ts: now, dwell: now - seen }),
  R.verdictRow('c', { shape: '', done: 'skip', ts: now, dwell: now - seen }),
]
const withAi = R.gridRows([cards[0]], {}, seen, now, () => true)
const cycle = [R.nextGridState(undefined), R.nextGridState('truncated'), R.nextGridState('skip')]
console.log(JSON.stringify({ grid, per, withAi, cycle,
  help: [R.classHelpKey('replace_align', 'grid'), R.classHelpKey('occluded', 'grid')],
  hasGridHelp: !!R.CLASS_HELP['replace_align:grid'], zInHelp: R.DEFAULT_HELP.includes('小注当正文') }))
""")
    assert out["grid"] == out["per"]                       # 逐字段相同；d 没有整理本字 → 不提交
    assert out["grid"][0] == {"id": "a", "v": "confirm", "shape": "天", "no_glyph_lib": False,
                              "client_ts": 1000, "dwell_ms": 600}
    assert out["grid"][1] == {"id": "b", "v": "seg_defect", "quality": "truncated", "shape": "",
                              "client_ts": 1000, "dwell_ms": 600}
    assert out["grid"][2] == {"id": "c", "v": "skip"}
    assert out["withAi"][0]["ai_accepted"] is True
    assert out["cycle"] == ["truncated", "skip", "accept"]
    assert out["help"] == ["replace_align:grid", "occluded"] and out["hasGridHelp"] and out["zInHelp"]


@needs_node
def test_ts_jiazhu_row_and_defect_kept(tmp_path):
    out = _run_ts(tmp_path, """
const row = R.verdictRow('x', { shape: '', done: 'jiazhu', ts: 5, dwell: 9 })
// 先标「小注当正文」再点候选：缺陷档保住，字照样带上（与 T/C 同一口径）
const kept = R.verdictRow('x', R.pickVerdict('天', { shape: '', done: 'jiazhu', dwell: 7 }, 1, 5))
console.log(JSON.stringify({ row, kept, reason: R.JIAZHU_REASON }))
""")
    assert out["row"] == {"id": "x", "v": "seg_defect", "quality": "truncated", "reason": "jiazhu_as_main",
                          "shape": "", "client_ts": 5, "dwell_ms": 9}
    assert out["kept"] == {"id": "x", "v": "seg_defect", "quality": "truncated", "reason": "jiazhu_as_main",
                           "shape": "天", "client_ts": 5, "dwell_ms": 7}
    assert out["reason"] == "jiazhu_as_main"


# ── 3. 下游：多了 reason 行为不变 ──────────────────────────────────────

def _ev(key: str, payload: dict, seq: int, book: str = "vol01", batch: str = "b"):
    from open_guji_cv.feedback.events import EventTarget, make_event
    _, pg, col, slot = key.split(":")
    return make_event(batch, seq, "confirm",
                      EventTarget(step="seed_admit", unit="cell", key=key, book=book,
                                  page=int(pg), col=int(col), slot=int(slot)),
                      payload, source_format="server")


def _pair(reason: bool):
    """同一组 seg_defect 事件，带不带 `reason`。"""
    extra = {"reason": "jiazhu_as_main"} if reason else {}
    return [{"v": "seg_defect", "quality": "truncated", "shape": "天", **extra},
            {"v": "seg_defect", "quality": "truncated", "shape": "", **extra}]


def test_downstream_ignores_reason(tmp_path):
    from open_guji_cv.feedback.consumers import _expected_of
    from open_guji_cv.feedback.events import EventLog
    from open_guji_cv.feedback.lookup import human_chars
    from open_guji_cv.feedback.returns import classify_return
    from open_guji_cv.review.verdict_view import decided_cells, review_verdicts
    got = {}
    for reason in (False, True):
        log = EventLog(tmp_path / str(reason))
        evs = [_ev(k, p, i) for i, (k, p) in enumerate(zip(("vol01:4:1:20", "vol01:4:1:21"), _pair(reason)), 1)]
        log.append(evs)
        got[reason] = {
            "human": human_chars("vol01", log, stale={}, bind=False),
            "decided": decided_cells("vol01", log),
            "returns": [classify_return(e) for e in evs],
            "gold": [_expected_of(e) for e in evs],
            "rv": review_verdicts("b", log)["verdicts"],
        }
    a, b = got[False], got[True]
    assert a["human"] == b["human"] == {"vol01:4:1:20": "天"}         # 带字的出字，不带字的仍是缺陷
    assert a["decided"] == b["decided"] == {"vol01:4:1:20"}
    assert a["returns"] == b["returns"] == [("row_segment", "seg_truncated")] * 2
    assert a["gold"] == b["gold"]
    # 读回：只在前端档位上认出「小注当正文」，字照旧
    assert a["rv"]["vol01:4:1:20"] == {"shape": "天", "done": "truncated"}
    assert b["rv"]["vol01:4:1:20"] == {"shape": "天", "done": "jiazhu"}
    assert b["rv"]["vol01:4:1:21"] == {"shape": "", "done": "jiazhu"}


def test_seed_admit_same_with_or_without_reason(tmp_path, monkeypatch):
    """seed_admit 读事件侧人裁（`human_chars`）：带字的 seg_defect 一票定案成 human，不带字的照常走
    自动通道——多一个 `reason` 两次跑出来的产物逐条相同。"""
    from helpers import make_book, make_ctx, page_match, write_product
    from open_guji_cv.core.step import STEPS
    from open_guji_cv.feedback import bindings
    from open_guji_cv.feedback.events import EventLog
    # 这里只摆了 glyph_match，没有切分产物给绑定表找格——绑定表当「没有」（按编号采信），
    # 与 09-25 之前一致；绑定本身另有用例，这里只看 reason 字段。
    monkeypatch.setattr(bindings, "book_bindings", lambda *a, **k: {})
    out = {}
    for reason in (False, True):
        root = tmp_path / str(reason)
        fb = root / "fb"
        monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(fb))
        ctx = make_ctx(root, make_book("tbook"), monkeypatch=monkeypatch)
        write_product(ctx, "glyph_match", 1, glyph_match=page_match(1, "tbook", col=1, recs=[
            dict(slot=1, verdict="unsure", cov=0.96, wmax=0.0, candidates=[("地", 0.96)]),
            dict(slot=2, verdict="unsure", cov=0.96, wmax=0.0, candidates=[("乙", 0.96)]),
        ]))
        EventLog(fb).append([_ev(k, p, i, book="tbook")
                             for i, (k, p) in enumerate(zip(("tbook:1:1:1", "tbook:1:1:2"), _pair(reason)), 1)])
        sa = STEPS["seed_admit"].run_page(ctx, 1)["seed_admit"]
        out[reason] = [r.model_dump() for cc in sa.columns for r in cc.chars]
    assert out[False] == out[True]
    by = {r["id"]: r for r in out[True]}
    assert by["tbook:1:1:1"]["channel"] == "human" and by["tbook:1:1:1"]["char"] == "天"
    assert by["tbook:1:1:2"]["channel"] != "human"
