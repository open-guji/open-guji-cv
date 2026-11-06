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


def test_ruling_override_groups_gate(tmp_path):
    """ctx-m1 裁定越过整理本（字≠整理本）：书级白名单核同属字组；None 不核；src-1 等不受影响。"""
    def run(groups, ch="日", ref="曰"):
        st = RulingStore(tmp_path / str(groups))
        p = st.put("O", "ctx-m1", "甲", "乙", char=ch, conf="high", why="x", model="m", cell=f"{B}:1:2")
        p.update({"admit_ok": True, "subclass": "Z", "ref": ref})
        recs = [AdmitRec(id=f"{B}:1:{s}", slot=s, admit=s != 2, char={1: "甲", 2: "誤", 3: "乙"}[s], doubts=[], channel=None, provenance="match" if s != 2 else "", evidence={}) for s in (1, 2, 3)]
        n = _vis_ruling_pass(SeedAdmitParams(db_path="x", ruling_override_groups=groups), [ColumnAdmit(col=1, chars=recs)],
                             {f"{B}:1:{s}": (c, None) for s, c in {1: "甲", 2: ref, 3: "乙"}.items()}, st)
        return n
    from open_guji_cv.groups.registry import FLOW_GROUPS
    gid = next(g for g, s in FLOW_GROUPS.items() if "日" in s.members and "曰" in s.members)
    assert run(None) == 1                       # 缺省不核
    assert run((gid,)) == 1                     # 同属白名单组
    assert run(()) == 0                         # 空名单＝不许越过
    assert run(("nonexistent",)) == 0
    assert run((), ch="曰", ref="曰") == 1      # 字＝整理本，不算越过
    assert "ruling_override_groups" not in SeedAdmitParams(db_path="x").model_dump()


def test_ruling_glyph_params_default_off_and_in_dump_when_set():
    d0 = SeedAdmitParams(db_path="x").model_dump()
    assert "ruling_glyph_min_score" not in d0 and "ruling_glyph_min_margin" not in d0
    d1 = SeedAdmitParams(db_path="x", ruling_glyph_min_score=0.98, ruling_glyph_min_margin=0.02).model_dump()
    assert d1["ruling_glyph_min_score"] == 0.98 and d1["ruling_glyph_min_margin"] == 0.02


def test_ruling_ref_lead_params_default_off_and_in_dump_when_set():
    d0 = SeedAdmitParams(db_path="x").model_dump()
    assert "ruling_ref_lead_min_unseen" not in d0 and "ruling_ref_lead_min_oov" not in d0
    d1 = SeedAdmitParams(db_path="x", ruling_ref_lead_min_unseen=0.01, ruling_ref_lead_min_oov=0.02).model_dump()
    assert d1["ruling_ref_lead_min_unseen"] == 0.01 and d1["ruling_ref_lead_min_oov"] == 0.02
    d2 = SeedAdmitParams(db_path="x", ruling_ref_lead_min_oov=0.02).model_dump()
    assert "ruling_ref_lead_min_unseen" not in d2 and d2["ruling_ref_lead_min_oov"] == 0.02


def test_skip_half_blocks_ruling_on_half_cells(tmp_path):
    st = _store(tmp_path, "甲", "乙")
    recs = [AdmitRec(id=f"{B}:1:{s}", slot=1, admit=a, char=c, doubts=[], channel=None, provenance="match" if a else "", evidence={})
            for s, a, c in (("1", True, "甲"), ("2a", False, "誤"), ("3", True, "乙"))]
    amap = {f"{B}:1:{s}": (c, None) for s, c in (("1", "甲"), ("2a", "說"), ("3", "乙"))}
    run = lambda on: _vis_ruling_pass(SeedAdmitParams(db_path="x", group_flow_llm_skip_half=on), [ColumnAdmit(col=1, chars=recs)], amap, st)  # noqa: E731
    assert run(True) == 0 and not recs[1].admit
    assert run(False) == 1 and recs[1].admit


def test_ref_lead_via_kept_and_fail_recorded(tmp_path):
    """终审 ref_lead：放行格证据带 via=ref_lead；没过的格（gate=ref_lead_fail）留审，证据记 ref_lead_fail。"""
    st = RulingStore(tmp_path / "ok")
    p = st.put("O", "ctx-m1", "甲", "乙", char="說", conf="high", why="x", model="m", cell=f"{B}:1:2")
    p.update({"admit_ok": True, "subclass": "N", "ref": "說", "gate": "ok", "via": "ref_lead", "ref_lead": {"layer": "unseen", "lead": 0.03}})
    n, r = _run(CELLS, AMAP, st)
    assert n == 1 and r[2].evidence["vis_ruling"]["via"] == "ref_lead" and r[2].evidence["vis_ruling"]["ref_lead"]["layer"] == "unseen"
    st2 = RulingStore(tmp_path / "fail")
    p = st2.put("O", "ctx-m1", "甲", "乙", char="說", conf="high", why="x", model="m", cell=f"{B}:1:2")
    p.update({"admit_ok": False, "subclass": "N", "ref": "說", "gate": "ref_lead_fail", "ref_lead": {"layer": "oov", "lead": 0.005}})
    n, r = _run(CELLS, AMAP, st2)
    assert n == 0 and not r[2].admit and r[2].evidence["ref_lead_fail"]["layer"] == "oov"
    n, r = _run(CELLS, {**AMAP, 2: "他"}, st2)                                            # 整理本字变了不记
    assert "ref_lead_fail" not in r[2].evidence
    n, r = _run(CELLS, AMAP, _store(tmp_path / "plain", "甲", "乙"))                       # 普通裁定不带 via
    assert "via" not in r[2].evidence["vis_ruling"]


def test_non_han_ruling_char_not_admitted(tmp_path):
    """裁定字须是汉字：超出汉字区的码位、私用码、符号一律不放（A31 11-05）；扩展区（含 Ext J，U+32BC1 等）汉字照放。"""
    for bad in ("\U00033480", "\ue123", "〓", "○", "ခ"):
        st = RulingStore(tmp_path / ("b" + str(ord(bad))))
        p = st.put("O", "src-1", "甲", "乙", char=bad, conf="high", why="x", model="src-text-text_layer", cell=f"{B}:1:2")
        p.update({"admit_ok": True, "subclass": "PUA", "ref": "", "route": "text_layer"})
        assert _run(CELLS, {1: "甲", 2: "", 3: "乙"}, st)[0] == 0, bad
    st = RulingStore(tmp_path / "ok")
    p = st.put("O", "src-1", "甲", "乙", char="\U00020000", conf="high", why="x", model="src-text-text_layer", cell=f"{B}:1:2")
    p.update({"admit_ok": True, "subclass": "PUA", "ref": "", "route": "text_layer"})
    assert _run(CELLS, {1: "甲", 2: "", 3: "乙"}, st)[0] == 1
    st = RulingStore(tmp_path / "extj")                      # Unicode 17 的 Ext J（U+323B0–3347F）是真汉字，py3.12 的 unicodedata 还不认
    p = st.put("O", "src-1", "甲", "乙", char="\U00032BC1", conf="high", why="x", model="src-text-text_layer", cell=f"{B}:1:2")
    p.update({"admit_ok": True, "subclass": "PUA", "ref": "", "route": "text_layer"})
    assert _run(CELLS, {1: "甲", 2: "", 3: "乙"}, st)[0] == 1


def test_l04_subclass_admitted(tmp_path):
    """L04（A23 11-06，库认不出的高把握看图裁定）收进 vis-o1 无组入口。"""
    n, r = _run(CELLS, AMAP, _store(tmp_path, "甲", "乙", subclass="L04"))
    assert n == 1 and r[2].char == "說" and r[2].channel == "vis_ruling" and r[2].evidence["vis_ruling"]["subclass"] == "L04"
    assert _run(CELLS, AMAP, _store(tmp_path, "甲", "乙", subclass="XXX"))[0] == 0
