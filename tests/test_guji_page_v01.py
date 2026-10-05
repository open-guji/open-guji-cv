# -*- coding: utf-8 -*-
"""guji-page v0.1：网站总管的 IIIF 约定 + 文本总管的文本口径（overview#357 / #361）。

v0.2 起导出器出 0.2；本文件的文本口径用例改用 `_v01()` 造出的 v0.1 页，钉「v0.1 文件照样能读、能检查、能导出」。
v0.2 自己的用例在 `test_guji_page_v02.py`。

全部自造数据（产物沿用 `test_guji_page_format._write` 那一页：两列、抬头、夹注、阙文、排除、印章）。
钉住：
- canvas：页序换算（拆点前同号、拆块 a–d、拆点后 −3）、canvas id、`source.selector` 与 `image.region` 一一对应、
  CV 跑批的图与 canvas 不同时几何整体搬到 canvas、IIIF 注释 target = `<canvas id>#xywh=`；
- 文本：每个阙文一个 `[[]]` 不合并、「□」是真字、`norm.why` 只许「异体」、组字 `zi` 导出 `:zi[…]`、
  来源站点组字式原样；
- 去掉 ext 后导出的 md 不变；旧 v0 文件照样能检查、导出、升级；册级索引过 schema。
"""
from __future__ import annotations

import copy
import json

import pytest

from open_guji_cv.formats import guji_page as gp
from open_guji_cv.formats.guji_page_cv import from_cv_products
from open_guji_cv.products.store import ProductStore
from test_guji_page_format import BOOK, META, PAGE, W, H, _write

LEAF = (4000, 6000)
# 一张合扫原叶拆成 4 块，工作区页号 5–8；本页（PAGE=5）是第一块「右上」
SPLIT = [
    {"vol": BOOK, "ia_leaf": 5, "canvas_seq": "0005a", "ws_page": 5, "pos": "右上", "xywh": [2500, 0, W, H], "orig_size": list(LEAF)},
    {"vol": BOOK, "ia_leaf": 5, "canvas_seq": "0005b", "ws_page": 6, "pos": "左上", "xywh": [0, 0, W, H], "orig_size": list(LEAF)},
    {"vol": BOOK, "ia_leaf": 5, "canvas_seq": "0005c", "ws_page": 7, "pos": "右下", "xywh": [2500, 3000, W, H], "orig_size": list(LEAF)},
    {"vol": BOOK, "ia_leaf": 5, "canvas_seq": "0005d", "ws_page": 8, "pos": "左下", "xywh": [0, 3000, W, H], "orig_size": list(LEAF)},
]


@pytest.fixture
def store(tmp_path):
    st = ProductStore(tmp_path / "products")
    _write(st)
    return st


def _meta(**kw):
    m = copy.deepcopy(META)
    m["volume"]["ia_item"] = "test0001.cn"
    m.update(kw)
    return m


@pytest.fixture
def page(store):
    return from_cv_products(store, BOOK, PAGE, _meta())


def _v01(p):
    """v0.2 页 → v0.1 写法（阙文回到空串、组字原形回到 text），钉 v0.1 文件照样能读、能导出。"""
    p = copy.deepcopy(p)
    for i in p.pop("lacuna", []):
        p["text"][i] = ""
    for z in p.get("zi", []):
        form = "ids" if "ids" in z else "desc"
        p["text"][z["i"]] = z[form]
        for k in ("ids", "desc", "rel"):
            z.pop(k, None)
        z["form"] = form
    for g in p["glyphs"]:
        g.pop("cand", None)
        g.pop("channel", None)
    p["schema"] = gp.SCHEMA_V01
    return p


def _ok(p):
    assert gp.check(p) == []
    errs = gp.validate_schema(p)
    assert errs == [] or errs == ["jsonschema 未安装"], errs


# ───────────── canvas ─────────────

def test_seq_mapping_follows_split_table():
    assert gp.seq_for_ws_page(4, SPLIT)[0] == "0004"
    assert gp.seq_for_ws_page(7, SPLIT)[0] == "0005c"
    assert gp.seq_for_ws_page(9, SPLIT)[0] == "0006"           # 拆点后 −3
    assert gp.seq_for_ws_page(12, None)[0] == "0012"


def test_plain_page_canvas_is_whole_leaf(page):
    _ok(page)
    c = page["canvas"]
    assert c["id"] == "https://data.kaiyuanguji.com/iiif/testbook01/canvas/02/0005"
    assert (c["width"], c["height"]) == (W, H) and "source" not in c
    ann = gp.to_iiif_annotations(page)
    assert ann["items"][0]["target"] == f"{c['id']}#xywh=109,210,180,80"


def test_split_block_canvas_selector_matches_region(store):
    p = from_cv_products(store, BOOK, PAGE, _meta(split_rows=SPLIT))
    _ok(p)
    c = p["canvas"]
    assert c["id"].endswith("/canvas/02/0005a") and c["seq"] == "0005a"
    assert c["source"]["selector"] == {"type": "FragmentSelector", "value": f"xywh=2500,0,{W},{H}"}
    assert "test0001.cn_0005.tif" in c["source"]["id"]
    # CV 跑批的图就是这一块：image.region 与 selector 一一对应，坐标不动
    assert p["image"]["region"] == [2500, 0, W, H]
    g = next(x for x in p["glyphs"] if x["cv_id"] == f"{BOOK}:{PAGE}:1:2")
    assert g["box"] == [109, 210, 180, 80]
    cv = gp.to_iiif_canvas(p)
    assert cv["type"] == "Canvas" and (cv["width"], cv["height"]) == (W, H)
    assert cv["source"]["selector"]["value"] == f"xywh=2500,0,{W},{H}"
    # 换回原叶像素：加裁剪框偏移
    assert gp.map_box(g["box"], gp.coord_frame(p), {"width": LEAF[0], "height": LEAF[1]}) == [2609, 210, 180, 80]


def test_stale_image_is_remapped_into_canvas(store):
    """CV 跑批用的是旧裁法（原叶上 xywh=2480,10,W,H），canvas 是新裁法 → 几何整体平移 (−20, +10)。"""
    m = _meta(split_rows=SPLIT)
    m["image"] = {"path": "raw/5.png", "region": [2480, 10, W, H],
                  "source": {"kind": "ia", "item": "test0001.cn", "leaf": 5, "width": LEAF[0], "height": LEAF[1]}}
    p = from_cv_products(store, BOOK, PAGE, m)
    _ok(p)
    g = next(x for x in p["glyphs"] if x["cv_id"] == f"{BOOK}:{PAGE}:1:2")
    assert g["box"] == [109 - 20, 210 + 10, 180, 80]
    assert any("换到 canvas" in w for w in p["warnings"])
    assert gp.to_iiif_annotations(p)["items"][0]["target"].endswith("#xywh=89,220,180,80")


def test_canvas_size_must_equal_selector(page):
    page["canvas"]["source"] = {"id": None, "width": 4000, "height": 6000,
                                "selector": {"type": "FragmentSelector", "value": "xywh=0,0,10,10"}}
    assert any("应等于裁剪框" in e for e in gp.check(page))


# ───────────── 文本口径 ─────────────

def test_each_lacuna_is_its_own_marker(page):
    page = _v01(page)
    i = page["text"].index("謹")
    page["text"][i] = ""                          # 「謹」也认不出 → 与后面那个阙文相邻
    md = gp.to_guji_markdown(page, page_comment=False)
    assert "[[]][[]]" in md and "[[凡二字]]" not in md


def test_box_char_is_a_real_character(page):
    page = _v01(page)
    i = page["text"].index("謹")
    page["text"][i] = "□"                          # 底本刻的「□」/ 来源站点的「□」：真字照录
    assert gp.to_guji_markdown(page, page_comment=False).split("\n")[1].startswith("□[[]]")
    g = next(x for x in page["glyphs"] if x["text"] == [i, i + 1])
    g["guess"] = "謹"                              # 原刻残、人给了「最像」
    assert gp.to_guji_markdown(page, page_comment=False).split("\n")[1].startswith("□{guess=謹}[[]]")


def test_norm_only_variants(page):
    page["norm"] = [{"i": 0, "t": "臣", "why": "异体"}]
    _ok(page)
    page["norm"] = [{"i": 0, "t": "巨", "why": "讹"}]
    assert any("why" in e for e in gp.check(page))
    page["norm"] = [{"i": 0, "t": "巨"}]
    assert any("why" in e for e in gp.check(page))


def test_zi_exports_directive_and_source_forms_untouched(page):
    page = _v01(page)
    t = page["text"]
    a, b = t.index("謹"), t.index("按")
    t[a], t[b] = "⿰句員", "左句右員"
    page["zi"] = [{"i": a, "form": "ids"}, {"i": b, "form": "desc"}]
    _ok(page)
    line = gp.to_guji_markdown(page, page_comment=False).split("\n")[1]
    assert line.startswith(":zi[⿰句員][[]]") and line.endswith(":zi[左句右員]")
    t[b] = "[口*恒]"                               # 来源站点组字式：原样，不标 zi、不转 IDS
    page["zi"] = [{"i": a, "form": "ids"}]
    assert gp.to_guji_markdown(page, page_comment=False).split("\n")[1].endswith("[口*恒]")
    page["zi"] = [{"i": t.index(""), "form": "ids"}]
    assert any("阙文" in e for e in gp.check(page))


# ───────────── 入库、兼容、索引 ─────────────

def test_strip_ext_keeps_markdown(page):
    page["ext"] = {"tool": {"x": 1}}
    page["regions"][0]["columns"][0]["ext"] = {"yolo": {"raw": [1, 2]}}
    stripped = gp.strip_ext(page)
    assert "ext" not in json.dumps(stripped, ensure_ascii=False).replace('"text"', "")
    _ok(stripped)
    for kw in ({}, {"layer": "norm"}, {"keep_empty_cols": True}):
        assert gp.to_guji_markdown(stripped, **kw) == gp.to_guji_markdown(page, **kw)
    assert gp.to_iiif_annotations(stripped) == gp.to_iiif_annotations(page)


def test_v0_page_still_reads(page):
    v0 = _v01(page)
    v0["schema"] = gp.SCHEMA_V0
    for k in ("canvas", "zi"):
        v0.pop(k)
    _ok(v0)                                        # 用 v0 schema 校验
    assert gp.to_guji_markdown(v0) == gp.to_guji_markdown(page)
    cid = "https://x/iiif/c/1"
    assert gp.to_iiif_annotations(v0, cid)["items"][0]["target"] == f"{cid}#xywh=109,210,180,80"
    up = gp.upgrade(copy.deepcopy(v0))
    _ok(up)
    assert up["schema"] == gp.SCHEMA_ID and up["text"] == page["text"] and up["lacuna"] == page["lacuna"]
    assert up["canvas"]["id"] is None and up["glyphs"][0]["box"] == page["glyphs"][0]["box"]
    up2 = gp.upgrade(copy.deepcopy(v0), canvas=page["canvas"])
    _ok(up2)


def test_volume_index_reserves_chapter_mapping(page):
    idx = gp.volume_index([page])
    assert idx["schema"] == gp.INDEX_SCHEMA_ID and idx["book_text"] == {"version": None}
    row = idx["pages"][0]
    assert row["canvas_seq"] == "0005" and row["chapters"] == []
    row["chapters"] = [{"version": "v1", "chapter": "005", "text": None}]
    try:
        import jsonschema
    except ImportError:            # pragma: no cover
        return
    schema = json.loads(gp.INDEX_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(idx)
    row["chapters"] = [{"chapter": "5"}]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(idx)


def test_carry_ids_across_known_recrop(store):
    """同一 canvas、两版裁法都记了 region（重裁）→ 坐标都在 canvas 上，ID 照常承接；不知道裁剪区就不承接。"""
    m = _meta(split_rows=SPLIT)
    m["image"] = {"region": [2480, 10, W, H], "source": {"width": LEAF[0], "height": LEAF[1]}}
    old = from_cv_products(store, BOOK, PAGE, m)
    new = copy.deepcopy(old)
    new["image"] = dict(old["image"], sha256="1" * 64, region=[2500, 0, W, H])
    for g in new["glyphs"]:
        g["id"] = "tmp-" + g["id"]
    assert gp.carry_ids(old, new)["kept"] == sum(1 for g in old["glyphs"] if g.get("box"))
    new2 = copy.deepcopy(new)
    new2["image"].pop("region")
    assert gp.carry_ids(old, new2)["kept"] == 0
