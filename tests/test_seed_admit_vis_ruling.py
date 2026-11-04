# -*- coding: utf-8 -*-
"""Step7 看图判裁定无组入口（`vis_rulings`，通道 `vis_ruling`）。直接测 `_vis_ruling_pass`，数据自造，裁定库用临时目录。"""
from __future__ import annotations

from open_guji_cv.feedback.rulings import RulingStore
from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _vis_ruling_pass

B = "tbook:1"


def _store(tmp_path, left, right, **kw):
    st = RulingStore(tmp_path)
    d = dict(char="說", conf="high", why="x", model="m", cell=f"{B}:1:2")
    d.update(kw)
    p = st.put("O", "vis-o1", left, right, char=d.pop("char"), conf=d.pop("conf"), why=d.pop("why"), model=d.pop("model"), cell=d.pop("cell"))
    p.update({"admit_ok": kw.get("admit_ok", True), "subclass": kw.get("subclass", "A68"), "ref": kw.get("ref", "說"), "machine": "誤"})
    return st


def _run(cells, amap, st):
    recs = [AdmitRec(id=f"{B}:1:{s}", slot=s, admit=c.get("admit", False), char=c.get("char"), doubts=list(c.get("doubts", [])),
                     channel=c.get("channel"), provenance=c.get("provenance", ""), evidence=c.get("evidence") or {})
            for s, c in cells.items()]
    n = _vis_ruling_pass(SeedAdmitParams(db_path="x"), [ColumnAdmit(col=1, chars=recs)], {f"{B}:1:{s}": (c, None) for s, c in amap.items()}, st)
    return n, {r.slot: r for r in recs}


CELLS = {1: {"admit": True, "char": "甲"}, 2: {"char": "誤"}, 3: {"admit": True, "char": "乙"}}
AMAP = {1: "甲", 2: "說", 3: "乙"}


def test_hit_lifts(tmp_path):
    n, r = _run(CELLS, AMAP, _store(tmp_path, "甲", "乙"))
    assert n == 1 and (r[2].admit, r[2].char, r[2].channel, r[2].provenance) == (True, "說", "vis_ruling", "match")
    assert r[2].evidence["vis_ruling"]["char"] == "說" and r[2].evidence["lifted_from"]["char"] == "誤"


def test_miss_conf_ref_subclass_hard_human(tmp_path):
    assert _run(CELLS, AMAP, _store(tmp_path, "甲", "丙"))[0] == 0                      # 窗口不同
    assert _run(CELLS, AMAP, _store(tmp_path, "甲", "乙", conf="mid"))[0] == 0
    assert _run(CELLS, AMAP, _store(tmp_path, "甲", "乙", admit_ok=False))[0] == 0
    assert _run(CELLS, AMAP, _store(tmp_path, "甲", "乙", subclass="C240"))[0] == 0     # 非 A24 名下子类
    assert _run(CELLS, {**AMAP, 2: "他"}, _store(tmp_path, "甲", "乙"))[0] == 0         # 整理本对位字变了
    for c in ({"char": "誤", "doubts": ["occluded"]}, {"char": "誤", "provenance": "human"}):
        assert _run({**CELLS, 2: c}, AMAP, _store(tmp_path, "甲", "乙"))[0] == 0


def test_adjacent_blank_cells_use_pre_pass_windows(tmp_path):
    """相邻两个漏字格：窗口按改字前算，第一格放行不改第二格的键。"""
    st = RulingStore(tmp_path)
    for cell, left, right, ch in (("a", "甲", "□乙", "靑"), ("b", "甲□", "乙", "時")):
        p = st.put("O", "vis-o1", left, right, char=ch, conf="high", why="", model="m", cell=cell)
        p.update({"admit_ok": True, "subclass": "B99", "ref": ""})
    cells = {1: {"admit": True, "char": "甲"}, 2: {"char": "X"}, 3: {"char": "Y"}, 4: {"admit": True, "char": "乙"}}
    n, r = _run(cells, {1: "甲", 2: "", 3: "", 4: "乙"}, st)
    assert n == 2 and (r[2].char, r[3].char) == ("靑", "時")


def test_src_text_ruling_lifts_and_subclass_isolated(tmp_path):
    """新图源文本层／码表裁定（prompt_ver=src-1，子类 PUA）：整理本此位无字（ref 空）也放行；子类串到别的版本不放。"""
    st = RulingStore(tmp_path)
    p = st.put("O", "src-1", "甲", "乙", char="洶", conf="high", why="x", model="src-text-text_layer", cell=f"{B}:1:2")
    p.update({"admit_ok": True, "subclass": "PUA", "ref": "", "route": "text_layer"})
    n, r = _run(CELLS, {1: "甲", 2: "", 3: "乙"}, st)
    assert n == 1 and (r[2].char, r[2].channel) == ("洶", "vis_ruling") and r[2].evidence["vis_ruling"]["route"] == "text_layer"
    p["subclass"] = "A68"                                     # src-1 只收 PUA
    assert _run(CELLS, {1: "甲", 2: "", 3: "乙"}, st)[0] == 0


def test_dump_default_clean():
    assert "vis_rulings" not in SeedAdmitParams(db_path="x").model_dump()
    assert SeedAdmitParams(db_path="x", vis_rulings=False).model_dump()["vis_rulings"] is False


def test_code_conflict_demotes_admitted_not_human(tmp_path):
    st = _store(tmp_path, "甲", "乙", char="垂", ref="", admit_ok=False, subclass="PUA")
    st.put("O", "src-1", "甲", "乙", char="垂", conf="high", why="码表", model="m", cell=f"{B}:1:2")
    p = st.put("O", "src-1", "甲", "乙", char="垂", conf="high", why="码表", model="m", cell=f"{B}:1:2")
    p.update({"admit_ok": False, "subclass": "PUA", "ref": "", "route": "code_conflict", "src": "x"})
    cells = {1: {"admit": True, "char": "甲"}, 2: {"admit": True, "char": "埀", "channel": "match_solo", "provenance": "match"},
             3: {"admit": True, "char": "乙"}}
    n, r = _run(cells, {1: "甲", 2: "", 3: "乙"}, st)
    assert n == -1 and not r[2].admit and r[2].channel is None and "src_code_conflict" in r[2].doubts
    assert r[2].evidence["demoted_from"]["channel"] == "match_solo" and r[2].evidence["src_code_conflict"]["char"] == "垂"
    cells[2].update(provenance="human", channel="human")                                 # 人裁格不碰
    assert _run(cells, {1: "甲", 2: "", 3: "乙"}, st)[1][2].admit
    cells[2].update(provenance="match", channel="match_solo", char="垂")                  # 字已一致不降
    assert _run(cells, {1: "甲", 2: "", 3: "乙"}, st)[1][2].admit


def test_src_gb_subclass_lifts(tmp_path):
    st = RulingStore(tmp_path)
    p = st.put("O", "src-1", "甲", "乙", char="說", conf="high", why="文本层同", model="m", cell=f"{B}:1:2")
    p.update({"admit_ok": True, "subclass": "GB", "ref": "說", "route": "text_ref"})
    n, r = _run({**CELLS, 2: {"char": "誤", "doubts": ["ctx_garble_shape"]}}, AMAP, st)
    assert n == 1 and r[2].char == "說" and r[2].channel == "vis_ruling" and not r[2].doubts
