# -*- coding: utf-8 -*-
"""yolo_tool project.json ↔ guji-page v0 往返一致性（`open_guji_cv/formats/guji_page_yolo.py`）。

三类数据：
1. `fixtures/yolo_tool/001_project_p0.json`——yolo_tool 仓 pdfs_demo/diff/001_project.json 的第 0 页
   （真实工程文件，11 位框、没有 source_text / sort_mode；冻结在本仓，见 fixtures/README）；
2. 自造工程：8/10/11/12 位框混排、手动序、source_text 比框多（待框溢出）、比框少（空框）、
   夹注列（subText/subText2）、孤框（不落在任何版面框里）；
3. CV 导出的页（自造产物，抬头、双行夹注、单行小注、阙文、排除、印章，与
   `test_guji_page_format.py` 同一份），走 guji → yolo → guji。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from open_guji_cv.formats import guji_page_yolo as gp
from open_guji_cv.formats.guji_page import check

FIX = Path(__file__).resolve().parent / "fixtures" / "yolo_tool"


def _norm(x):
    """JSON 层面比较（int/float 1 与 1.0 在 json.dumps 里会不同，所以连类型一起比）。"""
    return json.dumps(x, ensure_ascii=False, sort_keys=False)


def _crafted():
    t = lambda x, y, w, h, cls, i: [x, y, w, h, cls, 0.9, "type", i, "", 0.0, i]  # noqa: E731
    return {
        "0": {
            "type": [t(800.5, 100.0, 100.0, 900.0, "text", 1),
                     t(700.0, 100.0, 48.0, 500.0, "subText", 2),
                     t(650.0, 100.0, 48.0, 500.0, "subText2", 3)],
            "slide": [
                [810.0, 110.25, 80.0, 80.0, "text", 0.8, "slide", 1],                   # 8 位
                [810.0, 210.0, 80.0, 80.0, "text", 0.8, "slide", 2, "等", 0.97],         # 10 位
                [810.0, 310.0, 80.0, 80.0, "text", 1.0, "slide", 3, "謹", 2.0, 3],       # 11 位，人工
                [702.0, 110.0, 44.0, 44.0, "text", 0.7, "slide", 4, "浙", 0.6, 1, "淅"],  # 12 位
                [652.0, 110.0, 44.0, 44.0, "text", 0.7, "slide", 5, "江", 0.6, 1, ""],
                [50.0, 50.0, 30.0, 30.0, "text", 0.5, "slide", 6, "", 0.0, 1, ""],        # 孤框
            ],
            "sort_mode": {"type": "auto", "slide": "manual"},
            "source_text": ["臣", "等", "謹", "浙", "江", "按", "語"],                     # 比框多 → 待框
        },
        "1": {"type": [t(800.0, 100.0, 100.0, 900.0, "text", 1)],
              "slide": [[810.0, 110.0, 80.0, 80.0, "text", 0.8, "slide", 1, "一", 0.9, 1, ""],
                        [810.0, 210.0, 80.0, 80.0, "text", 0.8, "slide", 2, "二", 0.9, 2, ""]],
              "sort_mode": {"type": "auto", "slide": "auto"},
              "source_text": ["一"]},                                                     # 比框少 → 空框
        "2": {"type": [], "slide": [], "source_text": ["缺", "頁"]},                     # 插入的缺页
    }


def _check_page(pg):
    """不依赖 cv 仓：runs 首尾相接铺满 text、区间不越界。"""
    pos = 0
    for reg in pg["regions"]:
        for c in reg["columns"]:
            for r in c["runs"]:
                assert r["text"][0] == pos, (pg["page_id"], c["id"], r, pos)
                pos = r["text"][1]
    assert pos == len(pg["text"]), (pg["page_id"], pos, len(pg["text"]))
    for g in pg["glyphs"]:
        s, e = g["text"]
        assert 0 <= s <= e <= len(pg["text"])
    assert check(pg) == []


def test_real_project_roundtrip_exact():
    proj = json.loads((FIX / "001_project_p0.json").read_text(encoding="utf-8"))
    pages = gp.project_to_pages(proj, book_id="testbook", volume=1)
    assert len(pages) == 1
    for pg in pages:
        _check_page(pg)
    back = gp.pages_to_project(json.loads(json.dumps(pages)))     # 经过一次真正的 JSON 序列化
    assert _norm(back) == _norm(proj)


def test_real_project_text_is_reading_order():
    proj = json.loads((FIX / "001_project_p0.json").read_text(encoding="utf-8"))
    pg = gp.project_to_pages(proj, book_id="testbook", volume=1)[0]
    order, _ = gp.reading_order(proj["0"])
    want = [proj["0"]["slide"][si][8] for _, sis in order for si in sis if proj["0"]["slide"][si][8]]
    assert pg["text"] == want
    assert len(pg["text"]) > 150


def test_crafted_project_roundtrip_exact():
    proj = _crafted()
    pages = gp.project_to_pages(proj, book_id="testbook", volume=1)
    for pg in pages:
        _check_page(pg)
    back = gp.pages_to_project(json.loads(json.dumps(pages)))
    assert _norm(back) == _norm(proj)


def test_crafted_semantics():
    p0, p1, p2 = gp.project_to_pages(_crafted(), book_id="testbook", volume=1)
    # 待框：source_text 7 字、在列内的框 5 个 → 最后两个字无框，挂在末列
    assert p0["text"] == ["臣", "等", "謹", "浙", "江", "按", "語"]
    boxed = {k for g in p0["glyphs"] for k in range(*g["text"])}
    assert boxed == {0, 1, 2, 3, 4}
    lanes = [c["runs"][0]["lane"] for c in p0["regions"][0]["columns"] if c["runs"]]
    assert lanes[:3] == ["main", "jz_r", "jz_l"]
    g = {g["ext"]["yolo"]["index"]: g for g in p0["glyphs"]}
    assert g[2]["review"] == "human" and g[2]["method"] == "yolo:human"
    assert g[1]["method"] == "ocr" and g[1]["conf"] == 0.97
    assert "orphan" in g[5]["flags"] and g[5]["text"][0] == g[5]["text"][1]
    # 空框：source_text 只 1 字，第二个框区间为空
    assert [x["text"] for x in p1["glyphs"]] == [[0, 1], [1, 1]]
    # 缺页：无框，字照样在
    assert p2["text"] == ["缺", "頁"] and p2["glyphs"] == []


def test_edit_in_guji_reaches_yolo():
    """在 guji 一侧改字、挪框，回到 yolo 要体现出来（且改字记成人工哨兵 2.0）。"""
    pages = gp.project_to_pages(_crafted(), book_id="testbook", volume=1)
    pg = pages[0]
    g0 = next(g for g in pg["glyphs"] if g["ext"]["yolo"]["index"] == 0)
    pg["text"][g0["text"][0]] = "巨"
    g0["review"] = "human"
    g0["box"] = [g0["box"][0] + 5, g0["box"][1], g0["box"][2], g0["box"][3]]
    back = gp.pages_to_project(pages)
    s0 = back["0"]["slide"][0]
    assert s0[8] == "巨" and s0[9] == 2.0
    assert s0[0] == 815.0
    assert back["0"]["source_text"][0] == "巨"


def test_cv_page_to_yolo_and_back(tmp_path):
    """CV 导出的页（抬头 + 夹注 + 印章）→ yolo → guji：文本、字框、读序、夹注左右都保住。

    丢掉的是 yolo 表达不了的：抬头级数/行首留白、阙文与「框里还没字」的区别、印章与排除标记、
    来源通道（规范 §9.3 损失表）。"""
    from open_guji_cv.formats.guji_page_cv import from_cv_products
    from open_guji_cv.products.store import ProductStore
    from test_guji_page_format import BOOK, META, PAGE, _write

    st = ProductStore(tmp_path / "products")
    _write(st)
    cv = from_cv_products(st, BOOK, PAGE, META)
    key, ypage = gp.page_to_yolo(cv)
    assert key == str(PAGE - 1)
    assert ypage["sort_mode"]["slide"] == "manual"
    proj = {key: ypage}
    back = gp.project_to_pages(json.loads(json.dumps(proj)), book_id=cv["book"]["id"],
                               volume=cv["volume"]["index"],
                               sizes={PAGE - 1: (cv["image"]["width"], cv["image"]["height"])})[0]
    _check_page(back)
    assert back["text"] == cv["text"]
    assert back["page_id"] == cv["page_id"]
    boxed_cv = [(g["text"], g["box"]) for g in cv["glyphs"] if g.get("box")]
    boxed_back = [(g["text"], g["box"]) for g in back["glyphs"]]
    assert boxed_back == boxed_cv
    lane = lambda pg: [g.get("lane") for g in sorted(pg["glyphs"], key=lambda g: g["text"])]  # noqa: E731
    # 单行小注在 yolo 里没有专门类别，回来是夹注右（损失表里有）
    assert [x if x != "solo" else "jz_r" for x in lane(cv)] == lane(back)
    # 第二圈：yolo → guji → yolo 已经是不动点
    assert json.dumps(gp.pages_to_project([copy.deepcopy(back)]), ensure_ascii=False) == \
        json.dumps(proj, ensure_ascii=False)
