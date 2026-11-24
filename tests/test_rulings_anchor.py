# -*- coding: utf-8 -*-
"""裁定格锚点后备键（`RulingStore.get_anchor`，GM4／CV4 2026-11-24 裁定键长期方案③）。数据自造，临时目录。"""
from __future__ import annotations

from types import SimpleNamespace as NS

from open_guji_cv.feedback import rulings as R
from open_guji_cv.feedback.rulings import EQUIV_FILE, RulingStore
from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _vis_ruling_pass

B = "tbook:1"
CELL = f"{B}:1:2"
SHA = "cells1+patch1"


def test_get_anchor_store(tmp_path):
    st = RulingStore(tmp_path)
    assert not st.has_anchors()
    st.put("O", "vis-o1", "a", "b", char="說", conf="high", why="", model="m", cell=CELL)   # 没 cells_sha：不进锚点
    assert not RulingStore(tmp_path).has_anchors()


def _store_with_anchor(tmp_path, **kw):
    """写一条带 cells_sha 的裁定事件（模拟写入方当场带上），重新读库。"""
    st = RulingStore(tmp_path)
    payload = {"source": "llm", "group": kw.pop("group", "O"), "char": kw.pop("char", "說"), "other": False, "conf": "high",
               "why": "", "model": "m", "prompt_ver": kw.pop("ver", "vis-o1"), "cell": CELL, "tok": {},
               "ctx": {"left": "舊", "right": "窗", "hash": R.ctx_hash("舊", "窗")}, "cells_sha": SHA, "ref": "說",
               "admit_ok": True, "subclass": "A68", **kw}
    ev = R.make_event("t-anchor", 1 + len(list(st.log.read("t-anchor", raw=True))), R.KIND,
                      R.EventTarget(step="seed_admit", unit="cell", key=CELL, book="tbook"), payload, actor="model")
    st.log.append([ev])
    return RulingStore(tmp_path)


def test_anchor_requires_all_three(tmp_path):
    st = _store_with_anchor(tmp_path)
    assert st.has_anchors()
    a = st.get_anchor("O", "vis-o1", CELL, SHA, "說")
    assert a["char"] == "說" and (a["ruling_key"], a["ruling_ver"]) == ("anchor", "vis-o1")
    assert st.get_anchor("O", "vis-o1", CELL, "other+sha", "說") is None      # 产物变了
    assert st.get_anchor("O", "vis-o1", CELL, SHA, "他") is None              # 整理本对位字变了
    assert st.get_anchor("O", "vis-o1", f"{B}:1:3", SHA, "說") is None         # 别的格
    assert st.get_anchor("O", "ctx-m1", CELL, SHA, "說") is None              # 版本不对
    assert st.get_anchor("ry", "vis-o1", CELL, SHA, "說") is None             # 组不对
    assert st.get_anchor("O", "vis-o1", CELL, None, "說") is None


def test_anchor_with_ver_equiv(tmp_path):
    d = tmp_path / "rulings"
    d.mkdir(parents=True)
    (d / EQUIV_FILE).write_text("equiv:\n  - {from: vis-o0, to: vis-o1}\n", encoding="utf-8")
    st = _store_with_anchor(tmp_path, ver="vis-o0")
    assert st.get_anchor("O", "vis-o1", CELL, SHA, "說")["ruling_ver"] == "vis-o0"


def _run(st, sha=SHA, ref="說", cands=None, left="甲", right="乙"):
    recs = [AdmitRec(id=f"{B}:1:1", slot=1, admit=True, char=left, doubts=[], channel=None, provenance="", evidence={}),
            AdmitRec(id=CELL, slot=2, admit=False, char="誤", doubts=[], channel=None, provenance="", evidence={}),
            AdmitRec(id=f"{B}:1:3", slot=3, admit=True, char=right, doubts=[], channel=None, provenance="", evidence={})]
    amap = {f"{B}:1:1": (left, None), CELL: (ref, None), f"{B}:1:3": (right, None)}
    mmap = {CELL: NS(candidates=cands or [])}
    n = _vis_ruling_pass(SeedAdmitParams(db_path="x"), [ColumnAdmit(col=1, chars=recs)], amap, st, cells_sha=sha, mmap=mmap)
    return n, recs[1]


def test_vis_ruling_pass_anchor(tmp_path):
    st = _store_with_anchor(tmp_path)          # 裁定窗口是「舊|窗」，现产物窗口「甲|乙」：窗口键不中
    assert _run(st, sha=None)[0] == 0          # 没给 cells_sha（库里没有锚点时调用方就不给）：照旧不中
    n, r = _run(st)
    assert n == 1 and r.char == "說" and r.evidence["vis_ruling"]["ruling_key"] == "anchor"
    assert _run(st, sha="x+y")[0] == 0


def test_vis_ruling_pass_anchor_candidate_rule(tmp_path):
    st = _store_with_anchor(tmp_path, char="悅", ref="說")
    assert _run(st)[0] == 0                                                   # 字≠ref、也不在候选
    n, r = _run(st, cands=[("悅", 0.9), ("說", 0.8)])
    assert n == 1 and r.char == "悅"


def test_vis_ruling_pass_anchor_guards(tmp_path):
    assert _run(_store_with_anchor(tmp_path / "a", admit_ok=False))[0] == 0
    assert _run(_store_with_anchor(tmp_path / "b", conf="mid"))[0] == 0
    assert _run(_store_with_anchor(tmp_path / "c", subclass="C240"))[0] == 0


def test_fold_pass_anchor(tmp_path):
    from open_guji_cv.steps import seed_admit as sa
    p = SeedAdmitParams(db_path="x", fold_groups=("ry",), fold_ref_char=False, fold_aspect=(0.85, 1.0))
    st = _store_with_anchor(tmp_path, group="ry", ver="v1", char="曰", ref="日")
    r = AdmitRec(id=CELL, slot=2, admit=False, char="乙", doubts=[], channel=None, provenance="", evidence={"group": {"id": "ry"}})
    orig, sa._l3_online = sa._l3_online, (lambda p_: {"ry": {"system": "s", "ver": "v1"}})
    try:
        args = ([ColumnAdmit(col=1, chars=[r])], {r.id: ("日", None)}, {r.id: NS(candidates=[("曰", 0.9)])})
        assert sa._fold_pass(p, *args, store=st, wh={r.id: (92, 100)}) == 0
        n = sa._fold_pass(p, *args, store=st, wh={r.id: (92, 100)}, cells_sha=SHA)
    finally:
        sa._l3_online = orig
    assert n == 1 and r.char == "曰" and r.evidence["fold"]["ruling_key"] == "anchor"


def test_page_cells_sha(monkeypatch):
    from open_guji_cv.feedback import bindings
    monkeypatch.setattr(bindings, "page_state", lambda b, pg, st: ("c", "p"))
    assert R.page_cells_sha("tbook", 1, None) == "c+p"
    monkeypatch.setattr(bindings, "page_state", lambda b, pg, st: (None, "p"))
    assert R.page_cells_sha("tbook", 1, None) is None
