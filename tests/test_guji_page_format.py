# -*- coding: utf-8 -*-
"""guji-page v0（每字带坐标的页面文本）：格式工具 + CV 产物导出器。

全部自造数据：一页两列的最小产物（版框/格/字框/放行）摆进 tmp 产物库，覆盖
正文、抬头、行首留白、双行夹注、单行小注、阙文、排除名单·非字 七种情形。
钉住的是：
- 导出结果过 Schema 和结构检查；
- 坐标从 CV 右上原点换到左上原点 `[x,y,w,h]` 的口径（向外取整）；
- 从本格式出的 guji-markdown 与 Step9 `render_page` **逐字相同**（同一份字位流，不能漂）；
- 裁切/缩放换算、IIIF 注释的 `#xywh=`、重切后稳定 ID 的承接。
"""
from __future__ import annotations

import json

import pytest

from open_guji_cv.formats import guji_page as gp
from open_guji_cv.formats.guji_page_cv import from_cv_products
from open_guji_cv.products.kinds.borders import Borders, HLineRec, VLineRec
from open_guji_cv.products.kinds.cells import CellRec, ColumnCells, PageCells
from open_guji_cv.products.kinds.chars import CharRec, ColumnChars, PageChars
from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit, PageAdmit
from open_guji_cv.products.store import ProductStore
from open_guji_cv.render.guji_markdown import render_page

BOOK, PAGE = "tbook", 5
W, H = 1000, 1200
COL_X = {1: (700.0, 900.0), 2: (500.0, 700.0)}     # 右上原点：列 1 在最右
ROW = 100.0
TOP = 100.0

META = {
    "book": {"id": "testbook01", "edition": "test"},
    "volume": {"index": 2, "cv_book": BOOK},
    "page": {"index": PAGE, "page_type": "body"},
    "image": {"path": "raw/5.png"},
    "marks": [{"kind": "seal", "box": [150, 100, 120, 220], "by": "manual"}],
}


def _cell(col, slot, kind="char", sub=None, order=0):
    x0, x1 = COL_X[col]
    if sub == "a":                  # 右上原点：x 小 = 靠右，a（右行，先读）是 x 小的一半
        x0, x1 = COL_X[col][0], (COL_X[col][0] + COL_X[col][1]) / 2
    elif sub == "b":
        x0, x1 = (COL_X[col][0] + COL_X[col][1]) / 2, COL_X[col][1]
    y0 = TOP + (slot - 1) * ROW
    quad = [(x0, y0), (x1, y0), (x1, y0 + ROW), (x0, y0 + ROW)]
    return CellRec(slot=slot, pos=slot, y0=0, y1=0, x0=0, x1=0, kind=kind, sub=sub,
                   order=order, quad_page=quad)


def _write(store: ProductStore):
    # 列 1：抬头一级，行首留白 1 格，正文「臣等」，双行夹注 右「浙採」左「江進」
    c1 = [_cell(1, 1, "blank"), _cell(1, 2), _cell(1, 3),
          _cell(1, 4, "jiazhu_a", "a"), _cell(1, 4, "jiazhu_b", "b"),
          _cell(1, 5, "jiazhu_a", "a"), _cell(1, 5, "jiazhu_b", "b")]
    a1 = [("2", None, "臣"), ("3", None, "等"), ("4", "a", "浙"), ("4", "b", "江"),
          ("5", "a", "採"), ("5", "b", "進")]
    # 列 2：「謹」、阙文、墨污（排除·非字）、单行小注「瀛」、「按」
    c2 = [_cell(2, 1), _cell(2, 2), _cell(2, 3), _cell(2, 4, "jiazhu_solo"), _cell(2, 5)]
    cells = PageCells(page=PAGE, period=ROW, ref_w=200.0, columns=[
        ColumnCells(col=1, ok=True, n_body_slots=5, n_raised=1, cells=c1),
        ColumnCells(col=2, ok=True, n_body_slots=5, cells=c2)])

    def admit(col, slot, sub, ch, **kw):
        return AdmitRec(id=f"{BOOK}:{PAGE}:{col}:{slot}{sub or ''}", slot=slot, sub=sub,
                        admit=kw.pop("admit", True), channel=kw.pop("channel", "match_ref"),
                        char=ch, **kw)
    col1 = [admit(1, int(s), sub, ch, channel="human" if ch == "臣" else "match_ref")
            for s, sub, ch in a1]
    col2 = [admit(2, 1, None, "謹"),
            admit(2, 2, None, None, admit=False, channel=None),
            admit(2, 3, None, None, admit=False, channel=None, doubts=["excluded"],
                  evidence={"excluded": "not_a_char"}),
            admit(2, 4, None, "瀛"), admit(2, 5, None, "按")]
    seed = PageAdmit(page=PAGE, columns=[ColumnAdmit(col=1, chars=col1), ColumnAdmit(col=2, chars=col2)])

    def ch_rec(col, c):
        q = c.quad_page
        bb = (q[0][0] + 10, q[0][1] + 10, q[2][0] - 10, q[2][1] - 10)    # 收紧 10px 的字框
        cid = f"{BOOK}:{PAGE}:{col}:{c.slot}{c.sub or ''}"
        return CharRec(id=cid, slot=c.slot, pos=c.slot, idx=c.slot - 1, sub=c.sub,
                       cell_type="char", bbox_col=(0, 0, 0, 0), bbox_page=bb)
    chars = PageChars(page=PAGE, columns=[
        ColumnChars(col=1, ok=True, chars=[ch_rec(1, c) for c in c1 if c.kind != "blank"]),
        ColumnChars(col=2, ok=True, chars=[ch_rec(2, c) for c in c2])])

    borders = Borders(width=W, height=H, expected_cols=2,
                      top=HLineRec(y_at_right=TOP, slope=0.0, kind="top"),
                      bottom=HLineRec(y_at_right=TOP + 5 * ROW, slope=0.0, kind="bottom"),
                      verticals=[VLineRec(x_at_top=x, slope=0.0) for x in (700.0, 500.0, 300.0)])
    lines = [{"col": c, "kind": "body", "x0": x0, "x1": x1, "y0": TOP, "y1": TOP + 5 * ROW}
             for c, (x0, x1) in COL_X.items()]
    key = f"p{PAGE:04d}"
    store.write(BOOK, "row_segment", key, {"cells": cells})
    store.write(BOOK, "cell_shrink", key, {"char_index": chars})
    store.write(BOOK, "seed_admit", key, {"seed_admit": seed})
    p = store.path(BOOK, "border_detect", key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"borders": borders.model_dump(), "line_index": {"lines": lines}}),
                 encoding="utf-8")


@pytest.fixture
def store(tmp_path):
    st = ProductStore(tmp_path / "products")
    _write(st)
    return st


@pytest.fixture
def page(store):
    return from_cv_products(store, BOOK, PAGE, META)


def test_export_passes_schema_and_structure(page):
    assert gp.check(page) == []
    errs = gp.validate_schema(page)
    assert errs == [] or errs == ["jsonschema 未安装"]
    assert page["page_id"] == "testbook01/2/5"


def test_text_stream_lanes_and_marks(page):
    # 排除·非字不进文本流；阙文（v0.2）是可见的「□」占位、下标记在页上 lacuna
    assert page["text"] == ["臣", "等", "浙", "採", "江", "進", "謹", "□", "瀛", "按"]
    assert page["lacuna"] == [7]
    c1, c2 = page["regions"][0]["columns"]
    assert (c1["raised"], c1["lead_blank"]) == (1, 1)
    assert [r["lane"] for r in c1["runs"]] == ["main", "jz_r", "jz_l"]
    assert [r["lane"] for r in c2["runs"]] == ["main", "solo", "main"]
    kinds = sorted(m["kind"] for m in page["marks"])
    assert kinds == ["blank", "excluded", "seal"]
    g = {x["cv_id"]: x for x in page["glyphs"]}
    assert g[f"{BOOK}:{PAGE}:1:2"]["review"] == "human"
    assert g[f"{BOOK}:{PAGE}:1:3"]["method"] == "cv:match_ref"
    assert g[f"{BOOK}:{PAGE}:2:2"]["lacuna"] == "unreadable"
    assert all(x["glyph_id"] is None for x in page["glyphs"])   # 不拿字位 id 冒充刻例 id


def test_box_is_top_left_xywh(page):
    """列 1 第 2 格：右上原点 x∈[710,890]、y∈[210,290] → 左上原点 x = (W-1)-890 = 109。"""
    g = next(x for x in page["glyphs"] if x["cv_id"] == f"{BOOK}:{PAGE}:1:2")
    assert g["box"] == [109, 210, 180, 80]
    seal = next(m for m in page["marks"] if m["kind"] == "seal")
    assert g["id"] in seal["occludes"]


def test_markdown_matches_step9_renderer(store, page):
    """本格式出的 guji-markdown 必须与 Step9 现役渲染逐字相同。"""
    md = gp.to_guji_markdown(page, page_comment=False)
    assert md == render_page(store, BOOK, PAGE, [])
    assert md == "^.臣等<浙採|江進>\n謹[[]]:jz[瀛]{type=单行}按"


def test_norm_layer_only_overrides_listed_positions(page):
    page["norm"] = [{"i": 0, "t": "臣X"}]
    assert gp.to_guji_markdown(page, page_comment=False, layer="norm").startswith("^.臣X等")
    assert gp.to_guji_markdown(page, page_comment=False).startswith("^.臣等")


def test_map_box_crop_and_scale():
    leaf = {"width": 4000, "height": 6000}
    crop_a = {"width": 2000, "height": 3000, "region": [1900, 2700, 2000, 3000], "source": leaf}
    crop_b = {"width": 1800, "height": 2800, "region": [2000, 2800, 1800, 2800], "source": leaf}
    box = [500, 600, 100, 120]
    assert gp.map_box(box, crop_a, crop_b) == [400, 500, 100, 120]
    assert gp.map_box(box, crop_a, {"width": 4000, "height": 6000}) == [2400, 3300, 100, 120]
    tier = gp.scaled_image(crop_a, 1000)
    assert tier["height"] == 1500
    assert gp.map_box(box, crop_a, tier) == [250, 300, 50, 60]


def test_iiif_annotation_targets(page):
    canvas = "https://img.example/iiif/testbook01/2/5"
    ann = gp.to_iiif_annotations(page, canvas)
    assert ann["type"] == "AnnotationPage"
    first = ann["items"][0]
    assert first["motivation"] == "supplementing"
    assert first["body"]["value"] == "臣"
    assert first["target"] == f"{canvas}#xywh=109,210,180,80"


def test_carry_ids_after_resegment(page):
    import copy
    new = copy.deepcopy(page)
    for g in new["glyphs"]:
        g["id"] = "tmp-" + g["id"]
    # 第一个框只挪 2px（同一块像素）；第二个框切成上下两半（切开）
    new["glyphs"][0]["box"][1] += 2
    g2 = new["glyphs"][1]
    x, y, w, h = g2["box"]
    g2["box"] = [x, y, w, h // 2]
    st = gp.carry_ids(page, new)
    assert new["glyphs"][0]["id"] == page["glyphs"][0]["id"]
    assert new["glyphs"][1]["id"].startswith("tmp-") and new["glyphs"][1]["prev"] == [page["glyphs"][1]["id"]]
    assert st["kept"] == len(page["glyphs"]) - 1
    # 换了图（sha 不同）一律不承接
    other = copy.deepcopy(page)
    other["image"]["sha256"] = "0" * 64
    assert gp.carry_ids(page, other)["kept"] == 0


def test_check_catches_gaps_and_out_of_range(page):
    page["regions"][0]["columns"][0]["runs"][0]["text"][1] -= 1
    page["glyphs"][0]["text"] = [0, 99]
    errs = gp.check(page)
    assert any("不接续" in e for e in errs)
    assert any("越界" in e for e in errs)


def test_multi_char_box_and_multi_box_char(page):
    """一框多字（合文）与一字多框（切坏）都只是区间的事，不改结构。"""
    g = page["glyphs"]
    g[0]["text"] = [0, 2]                  # 「臣等」合在一框
    g[1]["text"] = [0, 2]                  # 原「等」那框也指向同一区间 → 两框一字段
    assert gp.check(page) == []
    assert gp.unboxed_tokens(page) == []
