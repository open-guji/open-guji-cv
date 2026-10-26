# -*- coding: utf-8 -*-
"""Step7 照录整理本的异体对（`follow_ref`，通道 `follow_ref`）：整理本是表里的少见形 → 改回或放行整理本形。

直接测页末那一遍 `_follow_ref_pass`，数据全是自造的。"""
from __future__ import annotations

from types import SimpleNamespace as NS

from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _follow_ref_pass, _parse_follow_ref

B = "tbook:1"


def _page(cells: dict):
    """一列：`cells={slot: dict(admit, char, channel, doubts, provenance)}`。"""
    recs = [AdmitRec(id=f"{B}:1:{s}", slot=s, admit=c.get("admit", False), char=c.get("char"),
                     doubts=list(c.get("doubts", [])), channel=c.get("channel"),
                     provenance=c.get("provenance", "")) for s, c in cells.items()]
    return [ColumnAdmit(col=1, chars=recs)]


def _mm(lib: dict):
    """{slot: ([(字, cov), ...], verdict, guard)}"""
    out = {}
    for s, v in lib.items():
        cands, verdict, guard = (list(v) + [None, None])[:3]
        out[f"{B}:1:{s}"] = NS(char=None, candidates=cands, verdict=verdict or "unsure", guard=guard)
    return out


def _run(cells, lib, coord=None, amap=None, ctx=None, **params):
    params.setdefault("follow_ref", "㓜=幼,勅=敕,盖=蓋")
    p = SeedAdmitParams(db_path="x", **params)
    out = _page(cells)
    dmap = {f"{B}:1:{s}": NS(char=c) for s, c in (ctx or {}).items()}
    n = _follow_ref_pass(p, out, _mm(lib), amap or {}, {f"{B}:1:{s}": c for s, c in (coord or {}).items()}, dmap)
    return n, {r.slot: r for r in out[0].chars}


def test_parse():
    assert _parse_follow_ref("㓜=幼, 勅 = 敕,盖,ab=c,蓋=蓋,,") == {"㓜": "幼", "勅": "敕"}
    assert _parse_follow_ref("") == {}


def test_admits_ref_form():
    n, r = _run({1: {}, 2: {}}, {1: ([("幼", 0.96), ("切", 0.93)],), 2: ([("勅", 0.97), ("敕", 0.96)],)},
                coord={1: "㓜", 2: "勅"})
    assert n == 2
    assert (r[1].admit, r[1].channel, r[1].provenance, r[1].char) == (True, "follow_ref", "match", "㓜")
    assert r[1].evidence["lane"]["lib"] == "幼" and r[1].doubts == ["lane_follow_ref"]
    assert r[2].char == "勅"


def test_fixes_admitted_other_form():
    """已放行成另一形（非人裁）→ 改回整理本形，不计放行数；人裁不动。"""
    n, r = _run({1: {"admit": True, "char": "蓋", "channel": "match_replace"},
                 2: {"admit": True, "char": "蓋", "channel": "human", "provenance": "human"},
                 3: {"admit": True, "char": "盖", "channel": "match_ref"}}, {}, coord={1: "盖", 2: "盖", 3: "盖"})
    assert n == 0
    assert r[1].char == "盖" and r[1].evidence["follow_ref"] == {"from": "蓋", "ref": "盖"}
    assert r[2].char == "蓋" and r[3].char == "盖"


def test_ref_falls_back_to_align():
    n, r = _run({1: {}}, {1: ([("幼", 0.96)],)}, amap={f"{B}:1:1": ("㓜",)})
    assert n == 1 and r[1].char == "㓜"


def test_coord_wins_over_align():
    n, _ = _run({1: {}}, {1: ([("幼", 0.96)],)}, coord={1: "幼"}, amap={f"{B}:1:1": ("㓜",)})
    assert n == 0


def test_gates():
    lib = {1: ([("幼", 0.90)],),                      # cov 不够
           2: ([("切", 0.97), ("幼", 0.96)],),         # 首位不在对里
           3: ([("幼", 0.960), ("切", 0.958)],),       # 领先对外不够
           4: ([("幼", 0.97)], "diff"),                # 库判 diff
           5: ([("幼", 0.97)],),                       # occluded
           6: ([("幼", 0.97)],)}                       # 表外整理本字
    cells = {s: {} for s in lib}
    cells[5] = {"doubts": ["occluded"]}
    n, r = _run(cells, lib, coord={1: "㓜", 2: "㓜", 3: "㓜", 4: "㓜", 5: "㓜", 6: "幻"})
    assert n == 0 and all(not x.admit for x in r.values())


def test_ctx_guard_ref_needs_ctx_in_pair():
    cells = {1: {"doubts": ["ctx_guard_ref"]}, 2: {"doubts": ["ctx_guard_ref"]}}
    lib = {1: ([("幼", 0.96)],), 2: ([("幼", 0.96)],)}
    n, r = _run(cells, lib, coord={1: "㓜", 2: "㓜"}, ctx={1: "幼", 2: "初"})
    assert n == 1 and r[1].admit and not r[2].admit


def test_off_by_default_and_not_dumped():
    p = SeedAdmitParams(db_path="x")
    assert p.follow_ref == ""
    d = p.model_dump()
    assert "follow_ref" not in d and "follow_ref_cov" not in d
    assert "follow_ref" in SeedAdmitParams(db_path="x", follow_ref="㓜=幼").model_dump()
