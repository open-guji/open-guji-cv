# -*- coding: utf-8 -*-
"""格锚点宽松档（`ruling_anchor_loose`／`RulingStore._anchor_loose`，GM4 合并方案 11-24）。数据自造，临时目录。"""
from __future__ import annotations

from types import SimpleNamespace as NS

from open_guji_cv.feedback import rulings as R
from open_guji_cv.feedback.rulings import EQUIV_FILE, RulingStore
from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _vis_ruling_pass

B = "tbook:1"
CELL = f"{B}:1:2"
SHA = "cells1+patch1"
L, RT = "甲乙", "丙丁"          # 裁定记的窗口（前后各 2 字）


def _put(tmp_path, **kw):
    st = RulingStore(tmp_path)
    left, right = kw.pop("left", L), kw.pop("right", RT)
    payload = {"source": "llm", "group": kw.pop("group", "O"), "char": kw.pop("char", "說"), "other": False,
               "conf": kw.pop("conf", "high"), "why": "", "model": "m", "prompt_ver": kw.pop("ver", "vis-o1"), "cell": CELL,
               "tok": {}, "ctx": {"left": left, "right": right, "hash": R.ctx_hash(left, right)}, "cells_sha": SHA,
               "ref": "說", "admit_ok": True, "subclass": "A68", **kw}
    ev = R.make_event("t-loose", 1 + len(list(st.log.read("t-loose", raw=True))), R.KIND,
                      R.EventTarget(step="seed_admit", unit="cell", key=CELL, book="tbook"), payload, actor="model")
    st.log.append([ev], validate=False)
    return RulingStore(tmp_path)


def _equiv(tmp_path, text):
    d = tmp_path / "rulings"
    d.mkdir(parents=True, exist_ok=True)
    (d / EQUIV_FILE).write_text(text, encoding="utf-8")


def test_load_void(tmp_path):
    _equiv(tmp_path, "void:\n  - ctx-wenyi-1\n  - {group: ry, ver: 'ry-l2-1#m:high'}\n")
    eq = R.load_ver_equiv(tmp_path / "rulings" / EQUIV_FILE)
    assert eq["void"] == {("*", "ctx-wenyi-1"), ("ry", "ry-l2-1")}
    assert R.load_ver_equiv(tmp_path / "nope.yaml")["void"] == set()


def test_window_one_side(tmp_path):
    st = _put(tmp_path)
    g = lambda left, right: st.get_anchor("O", "vis-o1", CELL, SHA, "說", left, right, loose=True)
    assert g("某甲乙", "丙丁某")["win_sides"] == ["left", "right"]
    assert g("某某甲乙", "改丁")["win_sides"] == ["left"]            # 编辑距离再大，左 2 字同就中
    assert g("改乙", "丙丁")["win_sides"] == ["right"]
    assert g("改乙", "丙改") is None                                 # 两侧都不同


def test_loose_high_only_and_conflict(tmp_path):
    assert _put(tmp_path / "a", conf="mid").get_anchor("O", "vis-o1", CELL, SHA, "說", L, RT, loose=True) is None
    _put(tmp_path / "b", ver="vis-o1#a:high", char="說")
    st = _put(tmp_path / "b", ver="vis-o1#b:high", char="悅")
    a = st.get_anchor("O", "vis-o1", CELL, SHA, "說", L, RT, loose=True)
    assert a["ruling_conflict"] and {x["char"] for x in a["rows"]} == {"說", "悅"}


def test_loose_takes_latest_same_char(tmp_path):
    _put(tmp_path, ver="vis-o1#a:high", conf="mid")
    st = _put(tmp_path, ver="vis-o1#b:high", conf="high")             # 同字，最新一条 high
    assert st.get_anchor("O", "vis-o1", CELL, SHA, "說", L, RT, loose=True)["ruling_ver"] == "vis-o1#b:high"
    assert st.get_anchor("O", "vis-o1", CELL, SHA, "說", L, RT) is None    # 关着：没开 model_suffix，版本不认


def test_loose_versions(tmp_path):
    # O 组：其他 O 版本（白名单不同）不串用
    assert _put(tmp_path / "a", ver="src-1", subclass="PUA").get_anchor("O", "vis-o1", CELL, SHA, "說", L, RT, loose=True) is None
    # 不认的版本（validate 不过）、void、看图 L4 缓存都不收
    assert _put(tmp_path / "b", group="ry", ver="rm-l2-1").get_anchor("ry", "ry-l2-2", CELL, SHA, "說", L, RT, loose=True) is None
    _equiv(tmp_path / "c", "void:\n  - ry-l2-2\n")
    assert _put(tmp_path / "c", group="ry", ver="ry-l2-2").get_anchor("ry", "ry-l2-2", CELL, SHA, "說", L, RT, loose=True) is None
    assert _put(tmp_path / "d", group="ry", ver="vis1:abc").get_anchor("ry", "ry-l2-2", CELL, SHA, "說", L, RT, loose=True) is None
    # 本组认的版本带模型后缀：收
    a = _put(tmp_path / "e", group="ry", ver="ry-l2-2#x:high").get_anchor("ry", "ry-l2-2", CELL, SHA, "說", L, RT, loose=True)
    assert a["ruling_ver"] == "ry-l2-2#x:high"


def _run(st, loose, left="某乙", right="丙某"):
    recs = [AdmitRec(id=f"{B}:1:1", slot=1, admit=True, char=left, doubts=[], channel=None, provenance="", evidence={}),
            AdmitRec(id=CELL, slot=2, admit=False, char="誤", doubts=[], channel=None, provenance="", evidence={}),
            AdmitRec(id=f"{B}:1:3", slot=3, admit=True, char=right, doubts=[], channel=None, provenance="", evidence={})]
    amap = {f"{B}:1:1": (left, None), CELL: ("說", None), f"{B}:1:3": (right, None)}
    p = SeedAdmitParams(db_path="x", ruling_anchor_loose=loose)
    n = _vis_ruling_pass(p, [ColumnAdmit(col=1, chars=recs)], amap, st, cells_sha=SHA, mmap={CELL: NS(candidates=[])})
    return n, recs[1]


def test_vis_pass_loose(tmp_path):
    st = _put(tmp_path, left="某某某某甲乙", right="丙丁某某某某")
    # 现窗口：左「…某甲乙」右「丙丁…」都在；把它们改到编辑距离 >3 而一侧 2 字仍同
    n, r = _run(st, True, left="改改改改甲乙", right="改改")
    assert n == 1 and r.evidence["vis_ruling"]["win_sides"] == ["left"] and "window_diff" not in r.evidence["vis_ruling"]
    assert _run(st, False, left="改改改改甲乙", right="改改")[0] == 0                    # 关着：编辑距离超了


def test_vis_pass_loose_conflict(tmp_path):
    _put(tmp_path, ver="vis-o1#a:high", char="說")
    st = _put(tmp_path, ver="vis-o1#b:high", char="悅")
    n, r = _run(st, True, left="甲乙", right="丙丁")
    assert n == 0 and len(r.evidence["ruling_conflict"]) == 2


def test_fold_loose_high_only(tmp_path):
    from open_guji_cv.steps import seed_admit as sa
    orig, sa._l3_online = sa._l3_online, (lambda p_: {"ry": {"system": "s", "ver": "ry-l2-2"}})
    try:
        for conf, want in (("mid", 0), ("high", 1)):
            st = _put(tmp_path / conf, group="ry", ver="ry-l2-2", char="曰", ref="日", conf=conf, left="", right="某")   # 单格列现窗口两侧都空：窗口键不中、左侧同
            p = SeedAdmitParams(db_path="x", fold_groups=("ry",), fold_ref_char=False, fold_aspect=(0.85, 1.0), ruling_anchor_loose=True)
            r = AdmitRec(id=CELL, slot=2, admit=False, char="乙", doubts=[], channel=None, provenance="", evidence={"group": {"id": "ry"}})
            args = ([ColumnAdmit(col=1, chars=[r])], {r.id: ("日", None)}, {r.id: NS(candidates=[("曰", 0.9)])})
            assert sa._fold_pass(p, *args, store=st, wh={r.id: (92, 100)}, cells_sha=SHA) == want
            if want:
                assert r.evidence["fold"]["ruling_key"] == "anchor" and r.evidence["fold"]["win_sides"]
    finally:
        sa._l3_online = orig


def test_param_not_in_dump_when_off():
    assert "ruling_anchor_loose" not in SeedAdmitParams(db_path="x").model_dump(mode="json")
    assert SeedAdmitParams(db_path="x", ruling_anchor_loose=True).model_dump(mode="json")["ruling_anchor_loose"] is True


def test_fold_ruling_vetoed_blocks_lanes():
    """宽松档 fold 按裁定给的字被影子降审后，待审通道不许按整理本字放回（20 册回放 vol49:179:9:4）。"""
    from open_guji_cv.steps import seed_admit as sa
    assert "fold_ruling_vetoed" in sa._LANE_HARD
