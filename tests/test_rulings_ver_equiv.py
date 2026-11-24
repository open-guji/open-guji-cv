# -*- coding: utf-8 -*-
"""裁定版本等价登记表（`<feedback>/rulings/ver_equiv.yaml`，`RulingStore.get_equiv`；GM4／CV4 2026-11-24）。数据自造，临时目录。"""
from __future__ import annotations

import pytest

from open_guji_cv.feedback.rulings import EQUIV_FILE, RulingStore, base_ver
from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _vis_ruling_pass

B = "tbook:1"


def _table(tmp_path, text):
    d = tmp_path / "rulings"
    d.mkdir(parents=True, exist_ok=True)
    (d / EQUIV_FILE).write_text(text, encoding="utf-8")


def _put(st, ver, char="說", conf="high", group="O", left="甲", right="乙", **extra):
    p = st.put(group, ver, left, right, char=char, conf=conf, why="x", model="m", cell=f"{B}:1:2")
    p.update(extra)
    return p


def test_no_table_is_exact_get(tmp_path):
    st = RulingStore(tmp_path)
    _put(st, "old")
    assert st.get_equiv("O", "new", "甲", "乙") is None
    _put(st, "new#m:high")
    assert st.get_equiv("O", "new", "甲", "乙") is None            # 没表：后缀也不通配
    p = _put(st, "new")
    assert st.get_equiv("O", "new", "甲", "乙") is p                 # 精确命中：原对象，不带 ruling_key
    assert "ruling_key" not in p


def test_pairs_group_and_transitive(tmp_path):
    _table(tmp_path, "equiv:\n  - {from: a, to: b}\n  - {group: ry, from: b, to: c}\n")
    st = RulingStore(tmp_path)
    _put(st, "a", group="ry")
    v = st.get_equiv("ry", "c", "甲", "乙")
    assert v["char"] == "說" and (v["ruling_key"], v["ruling_ver"]) == ("ver_equiv", "a")
    assert st.get_equiv("O", "c", "甲", "乙") is None               # b→c 只登记给 ry
    assert st.get_equiv("ry", "a", "甲", "乙")["prompt_ver"] == "a"   # 有向：查旧版本不会拿新版本
    assert st.get_equiv("ry", "c", "甲", "丙") is None               # 窗口不同照样不中
    assert "ruling_key" not in st.get("ry", "a", "甲", "乙")          # 存的 payload 没被改


def test_model_suffix(tmp_path):
    _table(tmp_path, "model_suffix: true\n")
    st = RulingStore(tmp_path)
    _put(st, "ctx-m1#x:high", conf="high")
    _put(st, "ctx-m1#y:high", conf="mid")
    v = st.get_equiv("O", "ctx-m1", "甲", "乙")
    assert v["ruling_key"] == "ver_equiv" and v["conf"] == "mid"     # 各后缀同字，conf 取最低
    _put(st, "ctx-m1#z:high", char="悅")
    assert st.get_equiv("O", "ctx-m1", "甲", "乙") is None           # 后缀间不同字：不算
    assert base_ver("ctx-m1#x:high") == "ctx-m1" and base_ver(None) == ""


def test_bad_table_raises(tmp_path):
    _table(tmp_path, "equiv:\n  - {from: a}\n")
    with pytest.raises(ValueError):
        RulingStore(tmp_path).get_equiv("O", "b", "甲", "乙")


def _run(st, amap2="說"):
    recs = [AdmitRec(id=f"{B}:1:1", slot=1, admit=True, char="甲", doubts=[], channel=None, provenance="", evidence={}),
            AdmitRec(id=f"{B}:1:2", slot=2, admit=False, char="誤", doubts=[], channel=None, provenance="", evidence={}),
            AdmitRec(id=f"{B}:1:3", slot=3, admit=True, char="乙", doubts=[], channel=None, provenance="", evidence={})]
    amap = {f"{B}:1:1": ("甲", None), f"{B}:1:2": (amap2, None), f"{B}:1:3": ("乙", None)}
    n = _vis_ruling_pass(SeedAdmitParams(db_path="x"), [ColumnAdmit(col=1, chars=recs)], amap, st)
    return n, recs[1]


def test_vis_ruling_pass_equiv_hit_marks_evidence(tmp_path):
    kw = dict(admit_ok=True, subclass="A68", ref="說")
    st = RulingStore(tmp_path / "e")
    _put(st, "vis-o0", **kw)
    assert _run(st)[0] == 0                                          # 没登记：不中
    _table(tmp_path, "equiv:\n  - {group: O, from: vis-o0, to: vis-o1}\n")
    st = RulingStore(tmp_path)
    _put(st, "vis-o0", **kw)
    n, r = _run(st)
    assert n == 1 and r.char == "說" and r.channel == "vis_ruling"
    assert (r.evidence["vis_ruling"]["ruling_key"], r.evidence["vis_ruling"]["ruling_ver"]) == ("ver_equiv", "vis-o0")
    assert _run(st, amap2="他")[0] == 0                              # 护栏照旧：整理本对位字变了不放


def test_vis_ruling_pass_exact_hit_no_ruling_key(tmp_path):
    _table(tmp_path, "model_suffix: true\n")
    st = RulingStore(tmp_path)
    _put(st, "vis-o1", admit_ok=True, subclass="A68", ref="說")
    n, r = _run(st)
    assert n == 1 and "ruling_key" not in r.evidence["vis_ruling"] and "ruling_ver" not in r.evidence["vis_ruling"]


def test_fold_pass_equiv_hit(tmp_path):
    from open_guji_cv.steps import seed_admit as sa
    p = SeedAdmitParams(db_path="x", fold_groups=("ry",), fold_ref_char=False, fold_aspect=(0.85, 1.0))
    _table(tmp_path, "equiv:\n  - {group: ry, from: v0, to: v1}\n")
    st = RulingStore(tmp_path)
    st.put("ry", "v0", "", "", char="曰", conf="high", why="x", model="m", cell=f"{B}:1:1")
    r = AdmitRec(id=f"{B}:1:1", slot=1, admit=False, char="乙", doubts=[], channel=None, provenance="", evidence={"group": {"id": "ry"}})
    orig, sa._l3_online = sa._l3_online, (lambda p_: {"ry": {"system": "s", "ver": "v1"}})
    try:
        n = sa._fold_pass(p, [ColumnAdmit(col=1, chars=[r])], {r.id: ("日", None)}, None, store=st, wh={r.id: (92, 100)})
    finally:
        sa._l3_online = orig
    assert n == 1 and r.char == "曰"
    f = r.evidence["fold"]
    assert (f["via"], f["ruling_key"], f["ruling_ver"]) == ("ruling", "ver_equiv", "v0"), f
