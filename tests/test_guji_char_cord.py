# -*- coding: utf-8 -*-
"""pages.json（guji-pages/0.1）→ book-text 新形态 char.json ＋ cord.json ＋ norm.json。F4，overview#419。

全部自造数据：
- CV 来路：沿用 `test_guji_format` 那两页（抬头、行首留白、双行夹注、单行小注里的阙文、未收字、规范层、
  列中排除格、印章），走 `to_guji_format` 出 pages.json 再转；
- 手造一份 pages.json，把 CV 页里不常有的几样凑齐：版心列、空列、单边夹注、残字、切坏格（`defect`）、
  一格两字、版框为空、印章压字、`lacuna_extra`。

钉住：两份都过 guji-format schema；cord 不带字、格位都在 char 里、页列号一致；**char 生成的分行稿与同一份导出的
lines.md 逐字相同**（cv、lines 两种格位口径都是）；lines 口径的 key 与 book-text `lines_slots` 同法数出来。
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
from test_guji_format import _second_page, page  # noqa: F401 — page 是 fixture
from test_guji_page_format import BOOK, META, PAGE, _write

from open_guji_cv.formats import guji_char_cord as cc
from open_guji_cv.formats import guji_format as gf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))   # 两个入口脚本


def _cells(char):
    return [c for p in char["pages"] for col in p["columns"] for c in col["cells"]]


@pytest.fixture
def legacy(page):  # noqa: F811
    q = _second_page(page)
    for m in q["marks"]:                     # _second_page 只换了字框 id，印章压字的引用跟着换
        m["occludes"] = ["g2" + x[2:] for x in m.get("occludes", [])]
    return gf.to_guji_format([page, q], chapter="002")


@pytest.mark.parametrize("keys", cc.KEYS)
def test_cv_pages_json_roundtrip(legacy, keys):
    files, rep = cc.from_pages_json(legacy["002.pages.json"], zi=legacy["002.zi.json"],
                                    norm=legacy["002.norm.json"], keys=keys)
    assert set(files) == {"002.char.json", "002.cord.json", "002.norm.json"}
    char, cord, norm = files["002.char.json"], files["002.cord.json"], files["002.norm.json"]
    assert cc.validate(char, "char") == [] and cc.validate(cord, "cord") == []
    assert cc.check(char, cord, norm) == []
    assert cc.char_to_lines_md(char) == legacy["002.lines.md"]            # 往返不丢字
    assert char["book_id"] == "testbook01" and char["volume"] == 2 and char["version"] == "0.1.0"
    assert [p["page"] for p in char["pages"]] == [p["page"] for p in cord["pages"]] == [PAGE, PAGE + 1]
    # cord 不带字；每格一个框
    assert all(set(c) <= {"a", "box", "id"} for p in cord["pages"] for c in p["cells"])
    assert rep["cells"] == rep["boxed"] == len(_cells(char))
    # 第二页：单行小注里的阙文（md 里写「□」）、未收字、规范层
    p2 = [c for c in _cells(char) if c["a"].startswith(f"{PAGE + 1}:")]
    lac = [c for c in p2 if c.get("lacuna")]
    assert len(lac) == 2 and all(c["c"] == "□" for c in lac)
    assert any(c.get("lane") == "solo" for c in lac)
    zi = [c for c in p2 if "zi" in c]
    assert zi == [{**zi[0], "c": "按", "zi": "⿰扌安"}]
    assert norm["schema"] == cc.NORM_SCHEMA and [(n["t"], n["by"], n["why"]) for n in norm["items"]] == [("謹", "manual", "异体")]
    assert "o" not in norm["items"][0]
    marks = [m for p in cord["pages"] for m in p.get("marks", [])]
    assert {m["kind"] for m in marks} >= {"seal", "excluded"}
    assert all(isinstance(m.get("col", 0), int) and "by" not in m and "cv_id" not in m for m in marks)


def test_cv_keys_are_cv_anchors(legacy):
    files, _ = cc.from_pages_json(legacy["002.pages.json"], keys="cv")
    anchors = [c["a"] for p in legacy["002.pages.json"]["pages"] for c in p["cells"]]
    assert [c["a"] for c in _cells(files["002.char.json"])] == anchors


def test_lines_keys_match_lines_slots(legacy):
    files, rep = cc.from_pages_json(legacy["002.pages.json"], zi=legacy["002.zi.json"], keys="lines")
    char = files["002.char.json"]
    assert [c["a"] for c in _cells(char)] == cc.lines_slots(legacy["002.lines.md"])
    # 列 1 行首的留白格在 lines 口径不占号：CV slot 2 起的「臣」在 lines 口径是 .（1 格）之后的第 2 格——两边一样；
    # 列中排除格之后 CV 的 slot 跳号，lines 口径不跳 → 至少有一格的 key 不同
    assert rep["rekeyed"] > 0


# ───────────────────────── 手造 pages.json ─────────────────────────

def _pj(multi=True):
    """两页。p7：列 1 版心（无字）、列 2 抬头一级 + 双行夹注 + 单边夹注（只有左）+ 残字、列 3 空、列 4 一格两字 +
    切坏格 + 单行小注；p8：只有版框为空的 region，没有列。"""
    def cell(cid, a, o, c, **kw):
        return {"id": cid, "a": a, "o": o, "c": c, "box": [10, 10 * (o if isinstance(o, int) else o[0]), 9, 9], **kw}
    cells = [
        cell("g1", "7:2:-1", 0, "皇"),
        cell("g2", "7:2:1", 1, "易"),
        cell("g3", "7:2:2a", 2, "兩", lane="jz_r"), cell("g4", "7:2:3a", 3, "江", lane="jz_r"),
        cell("g5", "7:2:2b", 4, "採", lane="jz_l"),
        cell("g6", "7:2:4", 5, "□", guess="春"),
        cell("g7", "7:2:5b", 6, "注", lane="jz_l"),
        cell("g8", "7:2:7", 7, "□", lacuna="unreadable"),
        cell("g9", "7:4:3", [8, 10], "卅一") if multi else cell("g9", "7:4:3", 8, "卅"),
        cell("g10", "7:4:4", 10, "殘", lacuna="defect"),
        cell("g11", "7:4:5", 11, "小", lane="solo"), cell("g12", "7:4:6", 12, "□", lane="solo"),
    ]
    cells[-1]["box"] = None                                        # 还没切到框
    cols = [
        {"id": "c1", "n": 1, "kind": "banxin", "box": [900, 0, 50, 900], "raised": 0, "lead_blank": 0, "runs": []},
        {"id": "c2", "n": 2, "kind": "body", "box": [800, 0, 90, 900], "raised": 1, "lead_blank": 0,
         "runs": [{"lane": "main", "o": [0, 2]}, {"lane": "jz_r", "o": [2, 4]}, {"lane": "jz_l", "o": [4, 5]},
                  {"lane": "main", "o": [5, 6]}, {"lane": "jz_l", "o": [6, 7]}, {"lane": "main", "o": [7, 8]}]},
        {"id": "c3", "n": 3, "kind": "body", "box": [700, 0, 90, 900], "raised": 0, "lead_blank": 0, "runs": []},
        {"id": "c4", "n": 4, "kind": "body", "box": [600, 0, 90, 900], "raised": 0, "lead_blank": 2,
         "runs": [{"lane": "main", "o": [8, 11]}, {"lane": "solo", "o": [11, 13]}]},
    ]
    if not multi:                                                  # 一格一字：后面的偏移都往前挪一位
        for c in cells[9:]:
            c["o"] -= 1
        cols[3]["runs"] = [{"lane": "main", "o": [8, 10]}, {"lane": "solo", "o": [10, 12]}]
    n = 13 if multi else 12
    page7 = {"page_id": "bk/3/7", "page": {"index": 7, "label": "五"}, "image": {"width": 1000, "height": 1000},
             "canvas": {"id": "https://x/iiif/bk/canvas/03/0007", "seq": "0007", "width": 1000, "height": 1000},
             "producers": {"cv": {"tool": "open-guji-cv", "rev": "abc"}},
             "marks": [{"id": "m1", "kind": "blank", "col": "c4", "slot": 1, "box": [600, 0, 90, 90], "by": "cv"},
                       {"id": "m2", "kind": "seal", "box": [500, 0, 300, 300], "by": "manual",
                        "occludes": ["vol03:7:2:1"]},
                       {"id": "m3", "kind": "weird", "box": [0, 0, 1, 1]}],
             "o": [0, n], "lacuna_extra": [n - 1],
             "regions": [{"id": "r1", "kind": "body", "box": [600, 0, 400, 900], "rules": [], "columns": ["c1", "c2", "c3", "c4"]}],
             "columns": cols, "cells": cells}
    page8 = {"page_id": "bk/3/8", "page": {"index": 8}, "canvas": {"id": "https://x/iiif/bk/canvas/03/0008"},
             "marks": [], "o": [n, n], "regions": [{"id": "r1", "kind": "body", "box": None, "columns": []}],
             "columns": [], "cells": []}
    return {"schema": gf.PAGES_SCHEMA, "book": {"id": "bk"}, "volume": {"index": 3, "cv_book": "vol03"},
            "chapter": "003", "n_chars": n, "pages": [page7, page8]}


LINES_MD = ("<!-- p7 -->\n"
            "^皇易<兩江|採>□{guess=春}<注>[[]]\n"
            "..卅一殘:jz[小□]{type=单行}\n"
            "<!-- p8 -->\n")


@pytest.mark.parametrize("keys", cc.KEYS)
def test_handmade_pages_json(keys):
    multi = keys == "cv"                     # lines 口径数不了一格多字（见 test_lines_keys_refuse_multi_char）
    files, rep = cc.from_pages_json(_pj(multi), version="1.0.0", keys=keys)
    char, cord = files["003.char.json"], files["003.cord.json"]
    assert cc.validate(char, "char") == [] and cc.validate(cord, "cord") == []
    assert cc.check(char, cord) == []
    assert cc.char_to_lines_md(char) == (LINES_MD if multi else LINES_MD.replace("卅一", "卅"))
    p7 = char["pages"][0]
    assert p7["label"] == "五" and char["pages"][1] == {"page": 8, "columns": []}
    by = {c["c"]: c for c in _cells(char)}
    assert by["春"]["guess"] is True and "lacuna" not in by["殘"]           # defect 不是阙文
    assert ("卅一" if multi else "卅") in by
    assert [c.get("lacuna") for c in _cells(char)].count(True) == 2       # unreadable + lacuna_extra
    assert by["小"]["lane"] == "solo"
    assert rep["dropped"] == {"regions": 1, "columns": 0, "cells": 1, "marks": 1}
    assert len(cord["pages"][0]["cells"]) == 11 and "regions" not in cord["pages"][1]
    if keys == "cv":
        assert [c["col"] for c in p7["columns"]] == [1, 2, 3, 4]
        assert [c.get("kind") for c in p7["columns"]] == ["blank", None, "blank", None]  # 版心列没字也记 blank
        assert p7["columns"][1]["raised"] == 1 and p7["columns"][3]["lead_blank"] == 2
        assert by["注"]["a"] == "7:2:5b" and "lane" not in by["注"]
        seal = next(m for m in cord["pages"][0]["marks"] if m["kind"] == "seal")
        assert seal["occludes"] == ["7:2:1"]
        blank = next(m for m in cord["pages"][0]["marks"] if m["kind"] == "blank")
        assert (blank["col"], blank["slot"]) == (4, 1)
    else:
        assert [c["col"] for c in p7["columns"]] == [1, 2]                   # 空列、无字版心不编号
        assert [c["a"] for c in _cells(char)] == ["7:1:-1", "7:1:1", "7:1:2a", "7:1:3a", "7:1:2b", "7:1:4",
                                                  "7:1:5a", "7:1:6", "7:2:3", "7:2:4", "7:2:5", "7:2:6"]
        assert by["注"]["lane"] == "jz_l"                                    # 单边夹注后缀记 a，左右靠 lane
        assert [c["col"] for c in cord["pages"][0]["columns"]] == [1, 2]
        blank = next(m for m in cord["pages"][0]["marks"] if m["kind"] == "blank")
        assert blank["col"] == 2 and "slot" not in blank
        seal = next(m for m in cord["pages"][0]["marks"] if m["kind"] == "seal")
        assert seal["occludes"] == ["7:1:1"]


def test_lines_keys_refuse_multi_char():
    with pytest.raises(ValueError, match="一格多字"):
        cc.from_pages_json(_pj(), keys="lines")


def test_lines_slots_zi_is_one_cell():
    md = "<!-- p3 -->\n^^甲:zi[⿰扌安]<乙[[]]|丙>丁\n.:jz[戊己]{type=单行}\n"
    assert cc.lines_slots(md) == ["3:1:-2", "3:1:-1", "3:1:1a", "3:1:2a", "3:1:1b", "3:1:3", "3:2:2", "3:2:3"]


def test_uncovered_text_is_refused():
    pj = _pj()
    pj["n_chars"] = 14
    with pytest.raises(ValueError, match="有字没框"):
        cc.from_pages_json(pj)


def test_check_catches_mismatch():
    files, _ = cc.from_pages_json(_pj())
    char, cord = files["003.char.json"], files["003.cord.json"]
    bad = copy.deepcopy(cord)
    bad["pages"][0]["cells"][0]["a"] = "7:2:9"
    bad["pages"][0]["columns"].append({"col": 9, "box": [0, 0, 1, 1]})
    errs = cc.check(char, bad)
    assert any("7:2:9" in e for e in errs) and any("列 [9]" in e for e in errs)
    bad = copy.deepcopy(cord)
    bad["pages"].pop()
    assert any("页号两边不同" in e for e in cc.check(char, bad))
    dup = copy.deepcopy(char)
    dup["pages"][0]["columns"][1]["cells"].append(dict(dup["pages"][0]["columns"][1]["cells"][0]))
    assert any("重复" in e for e in cc.check(dup))
    assert any("在 char 里没有" in e for e in cc.check(char, None, {"items": [{"a": "7:9:1", "t": "x"}]}))
    # cord 里带字被 schema 拒
    withc = copy.deepcopy(cord)
    withc["pages"][0]["cells"][0]["c"] = "皇"
    assert cc.validate(withc, "cord")


def test_dumps_one_cell_per_line(tmp_path):
    files, _ = cc.from_pages_json(_pj())
    paths = cc.write_files(files, tmp_path)
    txt = (tmp_path / "003.char.json").read_text(encoding="utf-8")
    assert any(ln.strip().rstrip(",") == '{"a": "7:2:-1", "c": "皇"}' for ln in txt.splitlines())
    for p in paths:
        assert json.loads(p.read_text(encoding="utf-8")) == files[p.name]


# ───────────────────────── 两个入口 ─────────────────────────

def test_convert_script(tmp_path, legacy):
    from convert_pages_to_char_cord import main
    paths = gf.write_files(legacy, tmp_path / "old")
    d = {p.name: p for p in paths}
    args = ["--pages-json", str(d["002.pages.json"]), "--zi", str(d["002.zi.json"]), "--norm", str(d["002.norm.json"]),
            "--lines-md", str(d["002.lines.md"]), "--out", str(tmp_path / "new")]
    assert main(args) == 0
    char = json.loads((tmp_path / "new" / "002.char.json").read_text(encoding="utf-8"))
    assert cc.char_to_lines_md(char) == legacy["002.lines.md"]
    d["002.lines.md"].write_text(legacy["002.lines.md"].replace("臣", "巨", 1), encoding="utf-8")
    assert main(args) == 1                                                 # 往返对不上要报


def test_exporter_char_cord(tmp_path):
    from export_guji_format import main

    from open_guji_cv.products.store import ProductStore
    st = ProductStore(tmp_path / "products")
    _write(st)
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"defaults": META}, ensure_ascii=False), encoding="utf-8")
    base = ["--products", str(tmp_path / "products"), "--book", BOOK, "--chapter", "002", "--meta", str(meta),
            "--pages", str(PAGE)]
    assert main(base + ["--out", str(tmp_path / "old")]) == 0
    assert main(base + ["--out", str(tmp_path / "new"), "--format", "char-cord"]) == 0
    assert sorted(p.name for p in (tmp_path / "new").iterdir()) == ["002.char.json", "002.cord.json", "002.norm.json"]
    char = json.loads((tmp_path / "new" / "002.char.json").read_text(encoding="utf-8"))
    old = sorted(p.name for p in (tmp_path / "old").iterdir())               # 旧形态照出、不受影响
    assert old == [f"002.{k}" for k in ("lines.md", "norm.json", "pages.json", "proof.json", "zi.json")]
    assert cc.char_to_lines_md(char) == (tmp_path / "old" / "002.lines.md").read_text(encoding="utf-8")
