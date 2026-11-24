# -*- coding: utf-8 -*-
"""裁定按字格永久编号 u 查（`ruling_by_u`／`RulingStore.get_by_u`／`UidLedger`，CV0 T3 11-24）。数据自造，临时目录。"""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest

from open_guji_cv.feedback import rulings as R
from open_guji_cv.feedback.rulings import RulingStore, UidLedger
from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _vis_ruling_pass

BOOK = "tbook"
OLD = f"{BOOK}:1:9:9"           # 写裁定时的格号（重切前）
CELL = f"{BOOK}:1:1:2"          # 现格号
L, RT = "甲乙", "丙丁"


def _put(tmp_path, **kw):
    st = RulingStore(tmp_path)
    left, right = kw.pop("left", L), kw.pop("right", RT)
    payload = {"source": "llm", "group": kw.pop("group", "O"), "char": kw.pop("char", "說"), "other": False,
               "conf": kw.pop("conf", "high"), "why": "", "model": "m", "prompt_ver": kw.pop("ver", "vis-o1"),
               "cell": kw.pop("cell", OLD), "tok": {}, "ctx": {"left": left, "right": right, "hash": R.ctx_hash(left, right)},
               "ref": "說", "admit_ok": True, "subclass": "A68", "u": kw.pop("u", 7), **kw}
    ev = R.make_event("t-u", 1 + len(list(st.log.read("t-u", raw=True))), R.KIND,
                      R.EventTarget(step="seed_admit", unit="cell", key=payload["cell"] or "", book=BOOK), payload, actor="model")
    st.log.append([ev], validate=False)
    return RulingStore(tmp_path)


def _ledger(tmp_path, rows):
    d = tmp_path / "uid"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{BOOK}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


# —— 身份账读取器 ——

def test_ledger_lookup(tmp_path):
    _ledger(tmp_path, [
        {"v": 1, "book": BOOK, "page": 1, "cells_sha": "s1", "map": {CELL: 3}, "src": "advance"},
        {"v": 1, "book": BOOK, "page": 1, "cells_sha": "s1", "map": {CELL: 7}, "src": "advance"},   # 同页同切分：取最后一行
        {"v": 1, "book": BOOK, "page": 1, "cells_sha": None, "map": {CELL: 9}, "src": "init"},       # 无 sha：不用
        {"v": 1, "book": BOOK, "page": 2, "cells_sha": "s2", "map": {"x": "8", "y": True, "z": 0}},  # 非正整数丢掉
    ])
    led = UidLedger(tmp_path)
    assert led.lookup(BOOK, 1, "s1") == {CELL: 7}
    assert led.lookup(BOOK, 1, "other") == {} and led.lookup(BOOK, 1, None) == {}
    assert led.lookup(BOOK, 2, "s2") == {}
    assert UidLedger(tmp_path).lookup("nobook", 1, "s1") == {}            # 文件不在＝没有 u


def test_ledger_bad_json(tmp_path):
    (tmp_path / "uid").mkdir()
    (tmp_path / "uid" / f"{BOOK}.jsonl").write_text("{坏\n", encoding="utf-8")
    with pytest.raises(ValueError):
        UidLedger(tmp_path).lookup(BOOK, 1, "s1")


# —— RulingStore.get_by_u ——

def test_get_by_u_basic(tmp_path):
    st = _put(tmp_path)
    assert st.has_u()
    a = st.get_by_u("O", "vis-o1", BOOK, 7, "某甲乙", "改改")
    assert a["ruling_key"] == "u" and a["win_sides"] == ["left"] and a["char"] == "說"
    assert st.get_by_u("O", "vis-o1", BOOK, 7, "改乙", "丙改") is None        # 两侧 2 字都不同
    assert st.get_by_u("O", "vis-o1", BOOK, 8, L, RT) is None                 # u 不同
    assert st.get_by_u("O", "vis-o1", "other", 7, L, RT) is None              # 册不同
    assert st.get_by_u("O", "vis-o1", BOOK, None, L, RT) is None


def test_get_by_u_high_only_conflict_versions(tmp_path):
    assert _put(tmp_path / "a", conf="mid").get_by_u("O", "vis-o1", BOOK, 7, L, RT) is None
    _put(tmp_path / "b", ver="vis-o1#a:high", char="說")
    a = _put(tmp_path / "b", ver="vis-o1#b:high", char="悅").get_by_u("O", "vis-o1", BOOK, 7, L, RT)
    assert a["ruling_conflict"] and a["ruling_key"] == "u"
    # O 组别的版本不串用
    assert _put(tmp_path / "c", ver="src-1", subclass="PUA").get_by_u("O", "vis-o1", BOOK, 7, L, RT) is None


def test_no_u_payload(tmp_path):
    st = _put(tmp_path, u=None)
    assert not st.has_u()
    st2 = _put(tmp_path / "s", u="7")                                       # 字符串不认
    assert not st2.has_u()
    st3 = _put(tmp_path / "b", cell=None, book=BOOK)                        # 没格号时用 payload.book
    assert st3.get_by_u("O", "vis-o1", BOOK, 7, L, RT)["char"] == "說"


# —— seed_admit 两个读口 ——

def _run(st, by_u, umap, left="某甲乙", right="丙丁某"):
    recs = [AdmitRec(id=f"{BOOK}:1:1:1", slot=1, admit=True, char=left, doubts=[], channel=None, provenance="", evidence={}),
            AdmitRec(id=CELL, slot=2, admit=False, char="誤", doubts=[], channel=None, provenance="", evidence={}),
            AdmitRec(id=f"{BOOK}:1:1:3", slot=3, admit=True, char=right, doubts=[], channel=None, provenance="", evidence={})]
    amap = {f"{BOOK}:1:1:1": (left, None), CELL: ("說", None), f"{BOOK}:1:1:3": (right, None)}
    p = SeedAdmitParams(db_path="x", ruling_by_u=by_u)
    n = _vis_ruling_pass(p, [ColumnAdmit(col=1, chars=recs)], amap, st, mmap={CELL: NS(candidates=[])},
                         umap=umap if by_u else None)
    return n, recs[1]


def test_vis_pass_by_u(tmp_path):
    st = _put(tmp_path)
    n, r = _run(st, True, {CELL: 7})
    assert n == 1 and r.char == "說" and r.evidence["vis_ruling"]["ruling_key"] == "u"
    assert r.evidence["vis_ruling"]["u"] == 7 and r.evidence["vis_ruling"]["win_sides"] == ["left", "right"]
    assert _run(_put(tmp_path / "b"), True, {CELL: 8})[0] == 0               # 账里本格是别的 u
    assert _run(_put(tmp_path / "c"), True, {})[0] == 0                      # 账里没这一页
    assert _run(_put(tmp_path / "d"), False, {CELL: 7})[0] == 0              # 关着


def test_vis_pass_by_u_conflict(tmp_path):
    _put(tmp_path, ver="vis-o1#a:high", char="說")
    st = _put(tmp_path, ver="vis-o1#b:high", char="悅")
    n, r = _run(st, True, {CELL: 7})
    assert n == 0 and len(r.evidence["ruling_conflict"]) == 2


def test_fold_by_u(tmp_path):
    from open_guji_cv.steps import seed_admit as sa
    orig, sa._l3_online = sa._l3_online, (lambda p_: {"ry": {"system": "s", "ver": "ry-l2-2"}})
    try:
        for conf, cand, want in (("mid", "曰", 0), ("high", "目", 0), ("high", "曰", 1)):
            st = _put(tmp_path / f"{conf}{cand}", group="ry", ver="ry-l2-2", char="曰", ref="日", conf=conf, left="", right="某")
            p = SeedAdmitParams(db_path="x", fold_groups=("ry",), fold_ref_char=False, fold_aspect=(0.85, 1.0), ruling_by_u=True)
            r = AdmitRec(id=CELL, slot=2, admit=False, char="乙", doubts=[], channel=None, provenance="", evidence={"group": {"id": "ry"}})
            args = ([ColumnAdmit(col=1, chars=[r])], {r.id: ("日", None)}, {r.id: NS(candidates=[(cand, 0.9)])})
            assert sa._fold_pass(p, *args, store=st, wh={r.id: (92, 100)}, umap={CELL: 7}) == want
            if want:
                assert r.evidence["fold"]["ruling_key"] == "u" and r.evidence["fold"]["u"] == 7
    finally:
        sa._l3_online = orig


def test_uid_map_off_reads_nothing(monkeypatch):
    from open_guji_cv.steps import seed_admit as sa
    monkeypatch.setattr(sa, "_vis_cache", lambda: (_ for _ in ()).throw(AssertionError("关着不该碰裁定库")))
    assert sa._uid_map(SeedAdmitParams(db_path="x"), NS(), 1) is None


def test_param_not_in_dump_when_off():
    assert "ruling_by_u" not in SeedAdmitParams(db_path="x").model_dump(mode="json")
    assert SeedAdmitParams(db_path="x", ruling_by_u=True).model_dump(mode="json")["ruling_by_u"] is True


def test_put_with_u(tmp_path):
    st = RulingStore(tmp_path)
    p0 = st.put("ry", "ry-l2-2", "甲乙", "丙丁", char="曰", conf="high", why="", model="m", cell=CELL)
    assert "u" not in p0
    st.put("ry", "ry-l2-2", "某甲乙", "丙丁", char="曰", conf="high", why="", model="m", cell=CELL, u=5)
    assert st.get_by_u("ry", "ry-l2-2", BOOK, 5, "甲乙", "丙丁")["char"] == "曰"          # 内存索引即时可查
    assert RulingStore(tmp_path).get_by_u("ry", "ry-l2-2", BOOK, 5, "甲乙", "丙丁")["u"] == 5   # 落盘后重读
