# -*- coding: utf-8 -*-
"""近似字（overview#276）：人裁卡「无匹配（近似字）」→ 事件 → 侧表 `approx_labels` → 导出/同步 → 闸与文本。

钉住：
1. 老事件（不带 approx）行为完全不变：读回形状、进库结果、库内容、指纹、seed_admit 参数哈希；
2. 带 approx 的 confirm 写侧表（ids/note/reviewer 可空），人改口撤掉并记 `approx_clears`，撤例跟着删；
3. 库指纹（`db_fingerprint`）空表不变、有行也不变（建议见 HANDOFF_H276）；
4. 查询「某字有没有近似例」与字表角标计数；
5. seed_admit：匹配到近似例缺省照常放行、evidence 标注（用户 09-29 裁定 #277 选 C）；开闸则落人审；
6. 文本：缺省正文照填 + 侧表（来源 人裁/匹配），`inline_ids` 选项括注；
7. 前端 `verdictRow`（node 跑 reviewClass.ts）。
store 导出与三方同步的用例在 `test_approx_store_sync.py`。
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.clustering.audit import evict_instance
from open_guji_cv.clustering.glyph_db import GlyphDB
from open_guji_cv.feedback.consumers import glyphdb_admit
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
from open_guji_cv.review.verdict_view import review_verdicts

BOOK = "abook"


def _png(k: int = 0) -> bytes:
    img = np.full((80, 80), 255, np.uint8)
    cv2.rectangle(img, (6 + k % 20, 10), (70, 70 - k % 15), 0, 4)
    cv2.line(img, (10, 10 + k % 30), (70, 40), 0, 3)
    return cv2.imencode(".png", img)[1].tobytes()


def _ev(key: str, payload: dict, seq: int = 1, ts: str | None = None, actor: str = "user",
        reviewer: str | None = None, batch: str = "b"):
    _b, pg, col, slot = key.split(":")
    return make_event(batch, seq, "confirm",
                      EventTarget(step="seed_admit", unit="cell", key=key, book=_b,
                                  page=int(pg), col=int(col), slot=int(slot)),
                      payload, actor=actor, ts=ts, reviewer=reviewer)


@pytest.fixture
def db(tmp_path, monkeypatch):
    """空库里已有一格人裁（`v2:abook:1:1:1` 定「之」）：消费者走「缓存里没有 → 用库里那张」的路，
    不必现跑 Step1→Step4。"""
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    p = tmp_path / "g.db"
    g = GlyphDB(p)
    assert g.admit_instance(f"v2:{BOOK}:1:1:1", "之", _png(1), provenance="human",
                            page="1", col=1, idx=1)
    g.conn.commit()
    g.close()
    return p


def _dump(p: Path) -> dict:
    c = sqlite3.connect(p)
    try:
        out = {}
        for t in ("instances", "admissions", "exemplars", "glyphs", "evictions",
                  "approx_labels", "approx_clears"):
            cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
            keep = [x for x in cols if x not in ("patch_png", "updated_at", "admitted_at",
                                                 "added_at", "at")]
            out[t] = sorted(c.execute(f"SELECT {','.join(keep)} FROM {t}").fetchall(), key=repr)
        return out
    finally:
        c.close()


# ── 1. 读回 ──────────────────────────────────────────────────────────────

def test_verdict_view_old_event_unchanged_and_approx_read_back(tmp_path):
    log = EventLog(tmp_path)
    log.append([_ev(f"{BOOK}:1:1:1", {"v": "confirm", "shape": "之", "no_glyph_lib": False}, 1)])
    log.append([_ev(f"{BOOK}:1:1:2", {"v": "confirm", "shape": "乃", "approx": True,
                                      "ids": "⿱丿乃", "note": "多一撇"}, 2)])
    log.append([_ev(f"{BOOK}:1:1:3", {"v": "confirm", "shape": "乃", "approx": True}, 3)])
    got = review_verdicts("b", log)["verdicts"]
    assert got[f"{BOOK}:1:1:1"] == {"shape": "之", "done": "1", "noGlyphLib": False}, "老事件形状逐键不变"
    assert got[f"{BOOK}:1:1:2"] == {"shape": "乃", "done": "1", "noGlyphLib": False, "approx": True,
                                    "approxIds": "⿱丿乃", "approxNote": "多一撇"}
    assert got[f"{BOOK}:1:1:3"]["approx"] is True and got[f"{BOOK}:1:1:3"]["approxIds"] == ""


# ── 2. 进库 ──────────────────────────────────────────────────────────────

def test_old_event_behaviour_unchanged(db, tmp_path):
    """不带 approx 的 confirm：结果、库内容与加功能前逐项相同，侧表两张都空。"""
    from open_guji_cv.steps.glyph_match import db_fingerprint, human_verdicts_fingerprint
    before, fp, hfp = _dump(db), db_fingerprint(db), human_verdicts_fingerprint(db)
    r = glyphdb_admit([(_ev(f"{BOOK}:1:1:1", {"v": "confirm", "shape": "之"}), None)], db_path=str(db))
    assert (r.added, r.updated, r.skipped, r.errors) == (0, 0, 1, [])     # 幂等闸：同字已在库
    assert _dump(db) == before
    assert (db_fingerprint(db), human_verdicts_fingerprint(db)) == (fp, hfp)
    assert before["approx_labels"] == [] and before["approx_clears"] == []


def test_approx_confirm_writes_side_table_then_user_clears(db):
    iid = f"v2:{BOOK}:1:1:1"
    ev = _ev(f"{BOOK}:1:1:1", {"v": "confirm", "shape": "之", "approx": True, "ids": " ⿰丶之 ",
                                "note": ""}, ts="2026-09-29T01:00:00Z", reviewer="r@x")
    glyphdb_admit([(ev, None)], db_path=str(db))
    g = GlyphDB(db)
    row = g.approx_of(iid)
    assert row == {"instance_id": iid, "label": "之", "ids": "⿰丶之", "note": None,
                   "reviewer": "r@x", "created_at": "2026-09-29T01:00:00Z"}
    g.close()
    # 同一条事件重放：内容相同，created_at 不动
    glyphdb_admit([(ev, None)], db_path=str(db))
    g = GlyphDB(db)
    assert g.approx_of(iid)["created_at"] == "2026-09-29T01:00:00Z"
    g.close()
    # 机器事件不带 approx：不撤
    glyphdb_admit([(_ev(f"{BOOK}:1:1:1", {"v": "confirm", "shape": "之"}, actor="model"), None)],
                  db_path=str(db))
    g = GlyphDB(db)
    assert g.approx_of(iid) is not None
    g.close()
    # 人再定一次没勾：撤，留审计
    glyphdb_admit([(_ev(f"{BOOK}:1:1:1", {"v": "confirm", "shape": "之"},
                        ts="2026-09-29T02:00:00Z"), None)], db_path=str(db))
    g = GlyphDB(db)
    assert g.approx_of(iid) is None
    assert g.conn.execute("SELECT instance_id, label, at FROM approx_clears").fetchall() == [
        (iid, "之", "2026-09-29T02:00:00Z")]
    g.close()


def test_relabel_with_approx_and_evict_drops_row(db):
    """改判（换字）走撤旧进新：旧近似行跟着撤，新的近似按新字记；撤例同样带走近似行。"""
    iid = f"v2:{BOOK}:1:1:1"
    glyphdb_admit([(_ev(f"{BOOK}:1:1:1", {"v": "confirm", "shape": "乎", "approx": True}), None)],
                  db_path=str(db))
    g = GlyphDB(db)
    assert g.approx_of(iid)["label"] == "乎"
    assert g.conn.execute("SELECT char FROM admissions WHERE instance_id=?", (iid,)).fetchone()[0] == "乎"
    evict_instance(g, iid, reason="test")
    assert g.approx_of(iid) is None
    assert g.conn.execute("SELECT count(*) FROM approx_clears").fetchone()[0] == 0, "撤例由 evictions 审计"
    g.close()


def test_no_glyph_lib_approx_not_in_db(db):
    """勾了「字形不入库」的格不进库，侧表挂不上（文本侧表从事件读，见 render/approx.py）。"""
    r = glyphdb_admit([(_ev(f"{BOOK}:1:1:5", {"v": "confirm", "shape": "乃", "approx": True,
                                               "no_glyph_lib": True}), None)], db_path=str(db))
    assert r.no_lib == 1
    g = GlyphDB(db)
    assert g.conn.execute("SELECT count(*) FROM approx_labels").fetchone()[0] == 0
    g.close()


# ── 3. 指纹 ──────────────────────────────────────────────────────────────

def test_fingerprints_ignore_approx_tables(tmp_path):
    """老库（没有这两张表）→ 打开建空表 → 记一条近似：`db_fingerprint` 三次相同；同步签名空表不变。"""
    from open_guji_cv.steps.glyph_match import db_fingerprint, human_verdicts_fingerprint
    p = tmp_path / "old.db"
    g = GlyphDB(p)
    g.admit_instance(f"v2:{BOOK}:1:1:1", "之", _png(1), provenance="human", page="1", col=1, idx=1)
    g.conn.commit()
    g.conn.execute("DROP TABLE approx_labels")
    g.conn.execute("DROP TABLE approx_clears")
    g.conn.commit()
    g.close()
    sync = _load_sync()
    fp0, h0, sig0 = db_fingerprint(p), human_verdicts_fingerprint(p), sync.db_signature(p)
    g = GlyphDB(p)                       # 建空表
    g.close()
    assert (db_fingerprint(p), human_verdicts_fingerprint(p), sync.db_signature(p)) == (fp0, h0, sig0)
    g = GlyphDB(p)
    assert g.set_approx(f"v2:{BOOK}:1:1:1", "之", ids="⿰丶之")
    assert not g.set_approx("v2:nope:1:1:1", "之"), "库里没有的实例不写"
    g.close()
    assert db_fingerprint(p) == fp0, "近似标记不改变匹配器看到的东西，库指纹不变"
    assert human_verdicts_fingerprint(p) == h0
    assert sync.db_signature(p) != sig0, "同步签名要变：只标了近似也得导出"


def _load_sync():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "glyph_store_sync", Path(__file__).resolve().parent.parent / "scripts" / "glyph_store_sync.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── 4. 查询 ──────────────────────────────────────────────────────────────

def test_has_approx_query_and_char_table(db):
    from open_guji_cv.clustering.glyph_ledger import char_detail, char_table, has_approx
    assert not has_approx(db, "之")
    g = GlyphDB(db)
    g.admit_instance(f"v2:{BOOK}:1:1:2", "之", _png(2), provenance="human", page="1", col=1, idx=2)
    g.conn.commit()
    g.set_approx(f"v2:{BOOK}:1:1:2", "之", note="下多一點")
    g.close()
    assert has_approx(db, "之") and not has_approx(db, "乎")
    row = next(r for r in char_table(db) if r["char"] == "之")
    assert row["approx"] == 1 and row["n"] == 2
    d = char_detail(db, "之")
    assert d["n_approx"] == 1
    by = {x["instance_id"]: x["approx"] for x in d["exemplars"]}
    assert by[f"v2:{BOOK}:1:1:1"] is None and by[f"v2:{BOOK}:1:1:2"]["note"] == "下多一點"


# ── 5. seed_admit 闸 ─────────────────────────────────────────────────────

def test_seed_admit_params_hash_unchanged_without_approx(tmp_path):
    from open_guji_cv.steps.seed_admit import SeedAdmitParams
    p = tmp_path / "e.db"
    GlyphDB(p).close()
    d = SeedAdmitParams(db_path=str(p)).model_dump()
    assert "approx_gate" not in d and "approx_fingerprint" not in d, "没有近似例的书参数哈希不能变"
    g = GlyphDB(p)
    g.admit_instance("v2:lib:1:1:1", "衡", _png(3), provenance="human", page="1", col=1, idx=1)
    g.conn.commit()
    g.set_approx("v2:lib:1:1:1", "衡")
    g.close()
    d = SeedAdmitParams(db_path=str(p)).model_dump()
    assert "approx_gate" not in d, "闸缺省关、不进 dump"
    assert d["approx_fingerprint"].startswith("1:"), "有近似例：要标注，产物跟着过期"
    assert SeedAdmitParams(db_path=str(p), approx_gate=True).model_dump()["approx_gate"] is True


def _run_seed(tmp_path, monkeypatch, db_path, recs, **params):
    from helpers import make_book, make_ctx, page_decision, write_product
    from open_guji_cv.core.step import STEPS, RunContext
    from open_guji_cv.products.kinds.cells import CellRec, ColumnCells, PageCells
    from open_guji_cv.products.kinds.recog import ColumnMatch, PageAlignRef, PageMatch
    from open_guji_cv.steps.seed_admit import SeedAdmitParams
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(tmp_path / "fb"))
    img = np.full((600, 600), 255, np.uint8)
    ctx = make_ctx(tmp_path, make_book("tbook"), raw={1: img}, monkeypatch=monkeypatch)
    ctx = RunContext(ctx.book, ctx.store, ctx.cache,
                     params={"seed_admit": SeedAdmitParams(db_path=str(db_path), **params)},
                     log=lambda s: None)
    ctx._raw[1] = img
    cells = [CellRec(slot=s, pos=s, y0=0, y1=10, x0=0, x1=10, kind="char", order=s) for s in (1, 2, 3)]
    write_product(ctx, "glyph_match", 1,
                  glyph_match=PageMatch(page=1, columns=[ColumnMatch(col=3, ok=True, chars=recs)]))
    write_product(ctx, "context_decide", 1, context_decision=page_decision(1, "tbook", recs=[], col=3))
    write_product(ctx, "row_segment", 1,
                  cells=PageCells(page=1, period=10.0, ref_w=10.0,
                                  columns=[ColumnCells(col=3, ok=True, n_body_slots=3, period=10.0,
                                                       border_top=0.0, cells=cells)]))
    write_product(ctx, "align_ref", 1, align_ref=PageAlignRef(page=1, anchored=False, coord=[]))
    sa = STEPS["seed_admit"].run_page(ctx, 1)["seed_admit"]
    return {r.slot: r for cc in sa.columns for r in cc.chars}


def test_seed_admit_marks_or_blocks_approx_exemplar(tmp_path, monkeypatch):
    from open_guji_cv.products.kinds.recog import MatchRec
    p = tmp_path / "lib.db"
    g = GlyphDB(p)
    for k, ch in ((1, "衡"), (2, "衡"), (3, "乃")):
        g.admit_instance(f"v2:lib:1:1:{k}", ch, _png(k), provenance="human", page="1", col=1, idx=k)
    g.conn.commit()
    g.set_approx("v2:lib:1:1:1", "衡")          # 衡 两例里一例近似
    g.set_approx("v2:lib:1:1:3", "乃")          # 乃 唯一一例就是近似
    g.close()
    recs = [
        MatchRec(id="tbook:1:3:1", slot=1, verdict="same", char="衡", matched_id="v2:lib:1:1:1",
                 cov=0.999, candidates=[("衡", 0.999)]),
        MatchRec(id="tbook:1:3:2", slot=2, verdict="same", char="衡", matched_id="v2:lib:1:1:2",
                 cov=0.999, candidates=[("衡", 0.999)]),
        MatchRec(id="tbook:1:3:3", slot=3, verdict="same", char="乃", matched_id="v2:lib:1:1:9",
                 cov=0.999, candidates=[("乃", 0.999)]),
    ]
    got = _run_seed(tmp_path, monkeypatch, p, recs)
    assert all(r.admit for r in got.values()), "缺省不拦：近似例像普通刻例一样放行"
    assert got[1].evidence["approx"] == {"source": "matched", "via": "matched_id",
                                         "exemplar": "v2:lib:1:1:1", "ids": None, "note": None}
    assert "approx" not in got[2].evidence, "命中的是普通刻例：不标"
    assert got[3].evidence["approx"]["via"] == "char_only", "这个字在库里只有近似例"
    gate = _run_seed(tmp_path / "gate", monkeypatch, p, recs, approx_gate=True)
    assert not gate[1].admit and "approx_exemplar" in gate[1].doubts and gate[1].char == "衡", \
        "开闸：命中近似例落人审，字不改"
    assert gate[2].admit and not gate[3].admit


# ── 6. 文本 ──────────────────────────────────────────────────────────────

def test_text_sidecar_default_and_inline_option(tmp_path):
    from open_guji_cv.render.approx import approx_marks, inline_ids_map, sidecar_rows, sidecar_tsv
    from open_guji_cv.render.guji_markdown import _char_text
    from open_guji_cv.report.slots import SlotRec
    log = EventLog(tmp_path)
    log.append([_ev(f"{BOOK}:3:2:5", {"v": "confirm", "shape": "乃", "approx": True, "ids": "⿱丿乃",
                                      "note": "多一撇"}, 1, ts="2026-09-29T01:00:00Z")])
    log.append([_ev(f"{BOOK}:3:2:6", {"v": "confirm", "shape": "之", "approx": True}, 2,
                    ts="2026-09-29T01:00:00Z")])
    log.append([_ev(f"{BOOK}:3:2:6", {"v": "confirm", "shape": "之"}, 3, ts="2026-09-29T02:00:00Z")])
    log.append([_ev(f"{BOOK}:4:1:1", {"v": "confirm", "shape": "乎", "approx": True}, 4,
                    ts="2026-09-29T01:00:00Z")])
    marks = approx_marks(BOOK, log)
    assert set(marks) == {f"{BOOK}:3:2:5", f"{BOOK}:4:1:1"}, "改口的那格撤掉"
    rows = sidecar_rows(marks, [3])
    assert [(r["pos"], r["ids"], r["note"], r["source"]) for r in rows] == [("3:2:5", "⿱丿乃", "多一撇", "human")]
    assert sidecar_tsv(rows) == "pos\tshape\tids\tnote\tsource\n3:2:5\t乃\t⿱丿乃\t多一撇\thuman\n"

    def slot(key, ch):
        _b, pg, col, s = key.split(":")
        return SlotRec(id=key, page=int(pg), col=int(col), slot=int(s), sub=None, kind="char",
                       char=ch, admit=True, channel="human", excluded=False, unreadable=False, human=True)
    rec = slot(f"{BOOK}:3:2:5", "乃")
    assert _char_text(rec) == "乃", "缺省：正文照填"
    inline = inline_ids_map(marks)
    assert _char_text(rec, inline) == "乃{ids=⿱丿乃}"
    assert _char_text(slot(f"{BOOK}:4:1:1", "乎"), inline) == "乎", "没填 IDS 的不括注"
    assert _char_text(slot(f"{BOOK}:3:2:5", "及"), inline) == "及", "正文已不是那个字就不括注"


# ── 7. 前端事件行 ─────────────────────────────────────────────────────────

TS = (Path(__file__).resolve().parents[1]
      / "open_guji_cv/console/frontend/src/components/review/reviewClass.ts")


def _node_ok() -> bool:
    node = shutil.which("node")
    return bool(node) and subprocess.run([node, "--experimental-strip-types", "-e", "0"],
                                         capture_output=True).returncode == 0


@pytest.mark.skipif(not _node_ok(), reason="没有支持 --experimental-strip-types 的 node（≥22.6）")
def test_ts_verdict_row_approx(tmp_path):
    shutil.copy(TS, tmp_path / "reviewClass.mts")
    runner = tmp_path / "run.mts"
    runner.write_text("""import * as R from './reviewClass.mts'
const base = { shape: '乃', done: '1', ts: 1, dwell: 2 }
const prev = { ...base, approx: true, approxIds: '⿱丿乃', approxNote: '' }
console.log(JSON.stringify({
  old: R.verdictRow('a', base),
  off: R.verdictRow('a', { ...base, approx: false, approxIds: 'x' }),
  on: R.verdictRow('a', prev),
  kept: R.pickVerdict('及', prev, 0, 5),
  seg: R.verdictRow('a', { ...prev, done: 'truncated' }),
}))
""", encoding="utf-8")
    out = json.loads(subprocess.run([shutil.which("node"), "--experimental-strip-types", "--no-warnings",
                                     str(runner)], capture_output=True, text=True, check=True).stdout)
    assert out["old"] == {"id": "a", "v": "confirm", "shape": "乃", "no_glyph_lib": False,
                          "client_ts": 1, "dwell_ms": 2}, "不勾近似：事件逐字段与原来相同"
    assert out["off"] == out["old"]
    assert out["on"] == {**out["old"], "approx": True, "ids": "⿱丿乃"}, "note 空串不写"
    assert out["kept"]["approx"] is True and out["kept"]["shape"] == "及", "改字不丢勾选"
    assert "approx" not in out["seg"], "近似只随定字（v=confirm）走"


def test_text_sidecar_includes_matched_cells(tmp_path, monkeypatch):
    """Step7 靠近似例放行的格进侧表（来源 matched）；没放行的不进；人裁同格覆盖。"""
    from helpers import make_book, make_ctx, write_product
    from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit, PageAdmit
    from open_guji_cv.render.approx import book_marks, sidecar_rows
    ctx = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    apx = {"source": "matched", "via": "matched_id", "exemplar": "v2:lib:1:1:1", "ids": "⿰亻衡", "note": None}
    recs = [AdmitRec(id=f"{BOOK}:3:1:{s}", slot=s, admit=adm, channel="match_solo" if adm else None,
                     char="衡", evidence={"approx": apx}) for s, adm in ((1, True), (2, False), (3, True))]
    write_product(ctx, "seed_admit", 3,
                  seed_admit=PageAdmit(page=3, columns=[ColumnAdmit(col=1, ok=True, chars=recs)]))
    log = EventLog(tmp_path / "ev")
    log.append([_ev(f"{BOOK}:3:1:3", {"v": "confirm", "shape": "衡", "approx": True, "note": "人看过"}, 1)])
    rows = sidecar_rows(book_marks(ctx.store, BOOK, [3], log))
    assert [(r["pos"], r["source"], r["ids"], r["note"]) for r in rows] == [
        ("3:1:1", "matched", "⿰亻衡", ""), ("3:1:3", "human", "", "人看过")]
