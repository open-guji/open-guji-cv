# -*- coding: utf-8 -*-
"""guji-page v0.2：用户 10-02 三条裁定（overview#361·3/7/10，任务卡 #381）。

全部自造数据（产物沿用 `test_guji_page_format._write` 那一页，另造 Step5 四路候选产物）。钉住：
- 阙文：text 里放可见的「□」，页上 `lacuna` 标出；不带标记的「□」是真字；md 带标记的出 `[[]]`、不带的出「□」，
  与 Step9 `render_page` 逐字相同；不再出现空串；
- 未收字两层：text 放近似的已收字，`zi` 记 ids/desc + rel；md 写 `:zi[…]`；检查拦住 IDS 写进 text、ids/desc 并存、
  rel 缺失、指向阙文；
- 记录先行：每个字框 `cand`（lib/ocr/rare/ref 各路首位）+ `channel`；缺哪步就缺哪路；strip_ext 后还在；
- v0、v0.1 照样能读，`upgrade()` 到 0.2 后 md 逐字不变；去 ext 后 md 不变；yolo 空串字元 ↔ 阙文往返一致。
"""
from __future__ import annotations

import copy
import json

import pytest

from open_guji_cv.formats import guji_page as gp
from open_guji_cv.formats import guji_page_yolo as gy
from open_guji_cv.formats.guji_page_cv import from_cv_products
from open_guji_cv.products.kinds.recog import (AlignRec, ColumnMatch, ColumnOcr, ColumnRare, CoordRec, MatchRec,
                                               OcrRec, PageAlignRef, PageMatch, PageOcr, PageRare, RareCand,
                                               RareRec)
from open_guji_cv.products.store import ProductStore
from open_guji_cv.render.guji_markdown import render_page
from test_guji_page_format import BOOK, META, PAGE, _write

KEY = f"p{PAGE:04d}"


def cid(col, slot, sub=""):
    return f"{BOOK}:{PAGE}:{col}:{slot}{sub}"


def _write_candidates(st: ProductStore, *, ocr=True):
    """Step5 四路：库（same 档与 diff 档各一）、OCR、5-b、整理本（过闸对齐 + 坐标对位）。"""
    gm = PageMatch(page=PAGE, columns=[
        ColumnMatch(col=1, chars=[MatchRec(id=cid(1, 2), slot=2, verdict="same", char="臣", candidates=[("巨", 0.9)]),
                                  MatchRec(id=cid(1, 3), slot=3, verdict="diff", candidates=[("等", 0.8), ("笇", 0.7)])]),
        ColumnMatch(col=2, chars=[MatchRec(id=cid(2, 2), slot=2, verdict="diff", candidates=[])])])
    st.write(BOOK, "glyph_match", KEY, {"glyph_match": gm})
    if ocr:
        st.write(BOOK, "ocr_candidates", KEY, {"ocr_candidates": PageOcr(page=PAGE, columns=[
            ColumnOcr(col=2, chars=[OcrRec(id=cid(2, 1), slot=1, topk=[("謹", 0.95), ("勤", 0.02)])])])})
    st.write(BOOK, "rare_candidates", KEY, {"rare_candidates": PageRare(page=PAGE, columns=[
        ColumnRare(col=2, chars=[RareRec(id=cid(2, 2), slot=2, candidates=[RareCand(char="𠀤", score=0.4)])])])})
    st.write(BOOK, "align_ref", KEY, {"align_ref": PageAlignRef(
        page=PAGE, chars=[AlignRec(id=cid(1, 3), col=1, slot=3, align_char="等", align_op="equal")],
        coord=[CoordRec(id=cid(1, 3), col=1, slot=3, ref_char="笇"),          # 过闸对齐优先
               CoordRec(id=cid(2, 2), col=2, slot=2, ref_char="之"),
               CoordRec(id=cid(2, 5), col=2, slot=5, ref_char="")])})       # 整理本是空格：不算候选


@pytest.fixture
def store(tmp_path):
    st = ProductStore(tmp_path / "products")
    _write(st)
    return st


@pytest.fixture
def page(store):
    return from_cv_products(store, BOOK, PAGE, copy.deepcopy(META))


def _ok(p):
    assert gp.check(p) == []
    errs = gp.validate_schema(p)
    assert errs == [] or errs == ["jsonschema 未安装"], errs


def _g(p, c):
    return next(x for x in p["glyphs"] if x.get("cv_id") == c)


# ───────────── 阙文 ─────────────

def test_lacuna_is_visible_box_with_sparse_marker(store, page):
    _ok(page)
    assert page["schema"] == "guji-page/0.2"
    assert "" not in page["text"]
    i = page["lacuna"][0]
    assert page["text"][i] == "□" and page["lacuna"] == [7]
    assert _g(page, cid(2, 2))["lacuna"] == "unreadable"
    md = gp.to_guji_markdown(page, page_comment=False)
    assert md == render_page(store, BOOK, PAGE, []) == "^.臣等<浙採|江進>\n謹[[]]:jz[瀛]{type=单行}按"


def test_real_box_char_vs_lacuna(page):
    t = page["text"]
    j = t.index("謹")
    t[j] = "□"                                    # 底本真刻的「□」：不带标记
    line = gp.to_guji_markdown(page, page_comment=False).split("\n")[1]
    assert line.startswith("□[[]]")
    page["lacuna"] = sorted(page["lacuna"] + [j])  # 换成阙文：带标记 → 相邻两个各一个 [[]]
    _g(page, cid(2, 1))["lacuna"] = "unreadable"
    _ok(page)
    assert gp.to_guji_markdown(page, page_comment=False).split("\n")[1].startswith("[[]][[]]")
    ann = gp.to_iiif_annotations(page)["items"]
    lac = [a for a in ann if a.get("kyg:lacuna")]
    assert len(lac) == 2 and all(a["body"]["value"] == "□" for a in lac)


def test_lacuna_checks(page):
    page["text"][0] = ""
    assert any("空串" in e for e in gp.check(page))
    page["text"][0] = "臣"
    page["lacuna"] = [0]                          # 标在一个不是「□」的位上
    assert any("必须是「□」" in e for e in gp.check(page))
    page["lacuna"] = [7, 7]
    assert any("升序" in e for e in gp.check(page))
    page["lacuna"] = []                           # unreadable 字框却没标
    assert any("unreadable" in e for e in gp.check(page))


# ───────────── 未收字两层 ─────────────

def test_zi_two_layers(page):
    t = page["text"]
    a, b = t.index("謹"), t.index("按")
    t[a] = "員"                                    # 近似的已收字（部件近）
    page["zi"] = [{"i": a, "ids": "⿰句員", "rel": "部件近"},
                  {"i": b, "desc": "左扌右安", "rel": "形近"}]
    _ok(page)
    line = gp.to_guji_markdown(page, page_comment=False).split("\n")[1]
    assert line.startswith(":zi[⿰句員][[]]") and line.endswith(":zi[左扌右安]")
    assert gp.to_iiif_annotations(page)["items"][6]["body"]["value"] == "員"   # 注释 body 是近似字
    # 还没有近似字：text 放「〓」、rel 为空
    t[a] = "〓"
    page["zi"][0]["rel"] = None
    _ok(page)


@pytest.mark.parametrize("bad, msg", [
    ({"ids": "⿰句員", "rel": "近"}, "rel 只允许"),
    ({"ids": "⿰句員", "desc": "左句右員", "rel": "异体"}, "只有 ids、desc 之一"),
    ({"rel": "异体"}, "只有 ids、desc 之一"),
])
def test_zi_checks(page, bad, msg):
    page["zi"] = [dict(bad, i=page["text"].index("按"))]
    assert any(msg in e for e in gp.check(page))


def test_zi_rejects_ids_in_text_and_lacuna(page):
    a = page["text"].index("按")
    page["text"][a] = "⿰扌安"
    page["zi"] = [{"i": a, "ids": "⿰扌安", "rel": "形近"}]
    assert any("近似的已收字" in e for e in gp.check(page))
    page["text"][a] = "按"
    page["zi"] = [{"i": page["lacuna"][0], "ids": "⿰句員", "rel": "形近"}]
    errs = gp.check(page)
    assert any("阙文" in e for e in errs)


# ───────────── 记录先行：候选字与放行通道 ─────────────

def test_candidates_and_channel(store):
    _write_candidates(store)
    p = from_cv_products(store, BOOK, PAGE, copy.deepcopy(META))
    _ok(p)
    assert _g(p, cid(1, 2))["cand"] == {"lib": "臣"}                      # same 档取 char，不取 candidates[0]
    assert _g(p, cid(1, 2))["channel"] == "human"
    assert _g(p, cid(1, 3))["cand"] == {"lib": "等", "ref": "等"}          # diff 档取 candidates[0]；对齐优先于坐标
    assert _g(p, cid(1, 3))["channel"] == "match_ref"
    assert _g(p, cid(2, 1))["cand"] == {"ocr": "謹"}
    assert _g(p, cid(2, 2))["cand"] == {"rare": "𠀤", "ref": "之"}         # 阙文位也记候选
    assert _g(p, cid(2, 2))["channel"] is None                            # 未放行
    assert "cand" not in _g(p, cid(2, 5))                                  # 整理本空格不算候选
    # 候选与通道不属 ext：入库去 ext 后还在
    st = gp.strip_ext(p)
    assert _g(st, cid(1, 3))["cand"] == {"lib": "等", "ref": "等"} and _g(st, cid(1, 3))["channel"] == "match_ref"
    assert gp.to_guji_markdown(st) == gp.to_guji_markdown(p)


def test_candidates_missing_products_left_empty(store, page):
    assert all("cand" not in g for g in page["glyphs"])                    # 一步都没有 → 全空，不报错
    _write_candidates(store, ocr=False)
    p = from_cv_products(store, BOOK, PAGE, copy.deepcopy(META))
    assert "cand" not in _g(p, cid(2, 1))                                  # 只缺 OCR 那一路
    page_bad = copy.deepcopy(p)
    _g(page_bad, cid(1, 2))["cand"]["llm"] = "臣"
    assert any("cand 只认" in e for e in gp.check(page_bad))


# ───────────── 兼容、升级、入库 ─────────────

def _as_v01(p):
    p = copy.deepcopy(p)
    for i in p.pop("lacuna"):
        p["text"][i] = ""
    zi = []
    for z in p["zi"]:
        form = "ids" if "ids" in z else "desc"
        p["text"][z["i"]] = z[form]
        zi.append({"i": z["i"], "form": form})
    p["zi"] = zi
    for g in p["glyphs"]:
        g.pop("cand", None)
        g.pop("channel", None)
    p["schema"] = gp.SCHEMA_V01
    return p


def test_upgrade_v01_keeps_markdown(store):
    _write_candidates(store)
    p = from_cv_products(store, BOOK, PAGE, copy.deepcopy(META))
    a = p["text"].index("按")
    p["text"][a] = "〓"
    p["zi"] = [{"i": a, "ids": "⿰扌安", "rel": None}]
    v01 = _as_v01(p)
    _ok(v01)                                       # v0.1 照样过 v0.1 的检查与 schema
    assert gp.to_guji_markdown(v01) == gp.to_guji_markdown(p)
    up = gp.upgrade(copy.deepcopy(v01))
    _ok(up)
    assert up["schema"] == gp.SCHEMA_ID
    assert up["text"] == p["text"] and up["lacuna"] == p["lacuna"] and up["zi"] == p["zi"]
    assert gp.to_guji_markdown(up) == gp.to_guji_markdown(v01)
    assert gp.to_guji_markdown(up, layer="norm") == gp.to_guji_markdown(v01, layer="norm")
    assert _g(up, cid(1, 3))["channel"] == "match_ref"                    # 从 ext.cv.channel 补
    assert "cand" not in _g(up, cid(1, 3))                                 # 旧页没有候选，不编


def test_v0_reads_and_upgrades_to_v02(page):
    v0 = _as_v01(page)
    v0["schema"] = gp.SCHEMA_V0
    for k in ("canvas", "zi"):
        v0.pop(k)
    _ok(v0)
    up = gp.upgrade(copy.deepcopy(v0))
    _ok(up)
    assert up["schema"] == gp.SCHEMA_ID and up["lacuna"] == page["lacuna"]
    assert gp.to_guji_markdown(up) == gp.to_guji_markdown(v0) == gp.to_guji_markdown(page)


def test_strip_ext_keeps_markdown_v02(page):
    page["ext"] = {"tool": 1}
    page["zi"] = [{"i": page["text"].index("按"), "ids": "⿰扌安", "rel": "形近"}]
    st = gp.strip_ext(page)
    _ok(st)
    for kw in ({}, {"layer": "norm"}, {"keep_empty_cols": True}):
        assert gp.to_guji_markdown(st, **kw) == gp.to_guji_markdown(page, **kw)
    assert gp.to_iiif_annotations(st) == gp.to_iiif_annotations(page)


def test_volume_index_page_schema(page):
    assert gp.volume_index([page])["page_schema"] == "guji-page/0.2"


# ───────────── yolo ─────────────

def test_yolo_empty_token_becomes_lacuna_and_roundtrips():
    proj = {"0": {"type": [[800.0, 100.0, 100.0, 900.0, "text", 0.9, "type", 1, "", 0.0, 1]],
                  "slide": [[810.0, 110.0, 80.0, 80.0, "text", 0.8, "slide", 1, "一", 0.9, 1, ""],
                            [810.0, 210.0, 80.0, 80.0, "text", 0.8, "slide", 2, "", 0.0, 2, ""],
                            [810.0, 310.0, 80.0, 80.0, "text", 0.8, "slide", 3, "□", 0.9, 3, ""]],
                  "sort_mode": {"type": "auto", "slide": "auto"},
                  "source_text": ["一", "", "□"]}}
    pg = gy.project_to_pages(copy.deepcopy(proj), book_id="b", volume=1)[0]
    assert pg["schema"] == gp.SCHEMA_ID and pg["text"] == ["一", "□", "□"] and pg["lacuna"] == [1]
    assert gp.check(pg) == []
    assert gp.to_guji_markdown(pg, page_comment=False) == "一[[]]□"
    back = gy.pages_to_project(json.loads(json.dumps([pg])))
    assert json.dumps(back, ensure_ascii=False) == json.dumps(proj, ensure_ascii=False)
