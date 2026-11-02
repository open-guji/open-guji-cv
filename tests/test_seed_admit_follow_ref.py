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
           5: ([("幼", 0.97)],),                       # occluded（`occluded_variant_first` 关着时才是门）
           6: ([("幼", 0.97)],)}                       # 表外整理本字
    cells = {s: {} for s in lib}
    cells[5] = {"doubts": ["occluded"]}
    coord = {1: "㓜", 2: "㓜", 3: "㓜", 4: "㓜", 5: "㓜", 6: "幻"}
    n, r = _run(cells, lib, coord=coord, occluded_variant_first=False)
    assert n == 0 and all(not x.admit for x in r.values())
    # 异体形近规则先于印章（A31 10-28，缺省开）：遮挡格照样走这张表，别的门不变
    n, r = _run(cells, lib, coord=coord)
    assert n == 1 and r[5].admit and r[5].char == "㓜" and not any(r[s].admit for s in (1, 2, 3, 4, 6))


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


class _VM:
    """同义异体关系：隠隱𨼆 一族、傳𫝊 一族；其余字各自一族。"""
    FAM = {"隱": "隱", "隠": "隱", "𨼆": "隱", "傳": "傳", "𫝊": "傳"}

    def semantic(self, c):
        return self.FAM.get(c, c)


def _run_v(cells, lib, coord, vm=_VM(), **params):
    p = SeedAdmitParams(db_path="x", follow_ref_variants=True, **params)
    out = _page(cells)
    n = _follow_ref_pass(p, out, _mm(lib), {}, {f"{B}:1:{s}": c for s, c in coord.items()}, {}, vm)
    return n, {r.slot: r for r in out[0].chars}


def test_variants_mode_follows_ref_without_table():
    """`follow_ref_variants`（史記 2026-11-01，用户定「按参校本取字」）：不用登记表，同义异体照录整理本形。"""
    n, r = _run_v({1: {}, 2: {}, 3: {"admit": True, "char": "隠", "channel": "group_flow"}, 4: {}},
                  {1: ([("隠", 0.97), ("陽", 0.90)],), 2: ([("傳", 0.96)],), 4: ([("隠", 0.97)],)},
                  coord={1: "𨼆", 2: "𫝊", 3: "隱", 4: "陽"})
    assert n == 2
    assert (r[1].admit, r[1].char, r[1].evidence["lane"]["via"]) == (True, "𨼆", "variants")
    assert r[2].char == "𫝊"
    assert r[3].char == "隱" and r[3].evidence["follow_ref"] == {"from": "隠", "ref": "隱", "via": "variants"}
    assert not r[4].admit                                   # 整理本是别的字（不同义）：不碰


def test_variants_mode_gates_still_apply():
    n, r = _run_v({1: {}, 2: {"doubts": ["excluded"]}}, {1: ([("隠", 0.80)],), 2: ([("隠", 0.97)],)},
                  coord={1: "𨼆", 2: "𨼆"})
    assert n == 0 and not r[1].admit and not r[2].admit     # cov 不够、排除名单


def test_variants_mode_off_by_default_and_not_dumped():
    assert SeedAdmitParams(db_path="x").follow_ref_variants is False
    assert "follow_ref_variants" not in SeedAdmitParams(db_path="x").model_dump()
    d = SeedAdmitParams(db_path="x", follow_ref_variants=True).model_dump()
    assert d["follow_ref_variants"] is True and "follow_ref_cov" in d
