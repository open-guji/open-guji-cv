# -*- coding: utf-8 -*-
"""guji-page ↔ guji-format（lines.md + pages/proof/norm/zi/punct/entity.json）双向转换。F3，overview#398。

全部自造数据：CV 页沿用 `test_guji_page_format._write` 那一页（抬头、行首留白、双行夹注、单行小注、阙文、
列中排除格），再手工造第二页（未收字、规范层、单行小注里的阙文）。钉住：
- 往返一致：guji-page → guji-format → guji-page 等于 `strip_ext(原页)`（文本、阙文、组字、规范层、锚点、坐标、
  候选与通道一样不丢）；guji-format → guji-page → guji-format 逐文件相同；
- lines.md 与 Step9 9.1 的导出逐字相同；
- pages.json 的锚点 = CV 格 id 去册前缀；数 lines.md 推出来的锚点在排除格之后对不上（只做校验，不当真源）；
- `derive_anchors` 相对 `build_anchor_map` 的三处修正（抬头跳 0、`:zi` 一字、夹注里的 `[[]]` 一字）；
- punct/entity 按锚点重挂：文本前面多出字时偏移跟着走，锚点失效时退到偏移 + 字校验，都不对的报出来不猜。
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from open_guji_cv.formats import guji_format as gf
from open_guji_cv.formats import guji_page as gp
from open_guji_cv.formats.guji_page_cv import from_cv_products
from open_guji_cv.products.store import ProductStore
from test_guji_page_format import BOOK, META, PAGE, _write


@pytest.fixture
def page(tmp_path):
    st = ProductStore(tmp_path / "products")
    _write(st)
    p = from_cv_products(st, BOOK, PAGE, META)
    p["glyphs"][0]["cand"] = {"lib": "巨", "ref": "臣"}       # 记录先行字段也要走 proof.json 回来
    return p


def _second_page(p: dict) -> dict:
    """同一页挪成第 6 页：加未收字、规范层、单行小注里的阙文（md 里写成「□」，靠 lacuna_extra 补）。"""
    q = copy.deepcopy(p)
    q["page"]["index"] = PAGE + 1
    q["page_id"] = q["page_id"].rsplit("/", 1)[0] + f"/{PAGE + 1}"
    for g in q["glyphs"]:
        g["id"] = "g2" + g["id"][2:]
        g["cv_id"] = g["cv_id"].replace(f":{PAGE}:", f":{PAGE + 1}:")
    for m in q["marks"]:
        m["id"] = "m2" + m["id"][2:]
        if m.get("cv_id"):
            m["cv_id"] = m["cv_id"].replace(f":{PAGE}:", f":{PAGE + 1}:")
    i_solo = next(r["text"][0] for r in q["regions"][0]["columns"][1]["runs"] if r["lane"] == "solo")
    q["text"][i_solo] = gp.LACUNA_CHAR
    q["lacuna"] = sorted(set(q["lacuna"]) | {i_solo})
    q["zi"] = [{"i": 9, "ids": "⿰扌安", "rel": "异体"}]                # text[9]「按」是近似字
    q["norm"] = [{"i": 6, "t": "謹", "by": "manual", "why": "异体"}]
    return q


def _legacy_build_anchor_map():
    path = Path(__file__).resolve().parents[1] / "scripts" / "test_vol02_extract.py"
    spec = importlib.util.spec_from_file_location("_tv02", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build_anchor_map


def test_roundtrip_page_format_page(page):
    pages = [page, _second_page(page)]
    for p in pages:
        assert gp.check(p) == []
    files = gf.to_guji_format(pages, chapter="002")
    assert set(files) == {f"002.{k}" for k in ("lines.md", "pages.json", "proof.json", "norm.json", "zi.json")}
    back, extras = gf.from_guji_format(files)
    assert extras == {}
    for orig, got in zip(pages, back):
        assert gp.check(got) == []
        assert got == gp.strip_ext(orig)


def test_roundtrip_format_page_format_bytes(page, tmp_path):
    pages = [page, _second_page(page)]
    punct = {"punctuations": [{"mark": "，", "kind": "point", "pos": "after", "char_offset": 1, "pre_char": "等",
                               "anchor": f"{PAGE}:1:3", "source": "test"}]}
    entity = {"entities": [{"id": "e1", "type": "people", "text": "臣等", "anchor": {"start": f"{PAGE}:1:2",
                            "end": f"{PAGE}:1:3"}, "span": {"start_offset": 0, "end_offset": 2}}]}
    files = gf.to_guji_format(pages, chapter="002", punct=punct, entity=entity)
    paths = gf.write_files(files, tmp_path / "a")
    back, extras = gf.from_guji_format(gf.read_files(paths))
    assert extras["punct"] == punct and extras["entity"] == entity        # 原样挂回
    files2 = gf.to_guji_format(back, chapter="002", **extras)
    paths2 = gf.write_files(files2, tmp_path / "b")
    assert [p.read_bytes() for p in paths] == [p.read_bytes() for p in paths2]


def test_lines_md_is_step9_markdown_and_carries_lacuna_zi(page):
    pages = [page, _second_page(page)]
    md = gf.to_guji_format(pages, chapter="002")["002.lines.md"]
    assert md == "\n".join(gp.to_guji_markdown(p) for p in pages) + "\n"
    p6 = md.split(f"<!-- p{PAGE + 1} -->")[1]
    assert ":zi[⿰扌安]" in p6 and "[[]]" in p6
    assert ":jz[□]{type=单行}" in p6          # Step9 记法的已知例外：单行小注里的阙文写「□」
    pj = gf.to_guji_format(pages, chapter="002")["002.pages.json"]
    assert pj["pages"][1]["lacuna_extra"] == [len(page["text"]) + 8]


def test_anchors_are_cv_ids_and_derived_only_checks(page):
    files = gf.to_guji_format([page], chapter="002")
    cells = files["002.pages.json"]["pages"][0]["cells"]
    assert [c["a"] for c in cells] == [gf.anchor_of(g["cv_id"]) for g in page["glyphs"]]
    assert all(f"{BOOK}:{c['a']}" == g["cv_id"] for c, g in zip(cells, page["glyphs"]))
    der = {d["o"]: d["a"] for d in gf.derive_anchors(files["002.lines.md"])}
    by_char = {c["c"]: (c["a"], der[c["o"]]) for c in cells}
    assert by_char["謹"] == (f"{PAGE}:2:1", f"{PAGE}:2:1")
    # 列 2 第 3 格是排除格（墨污），md 不留痕：之后的「瀛」「按」数出来少一格
    assert by_char["瀛"] == (f"{PAGE}:2:4", f"{PAGE}:2:3")
    assert by_char["按"] == (f"{PAGE}:2:5", f"{PAGE}:2:4")


def test_derive_anchors_fixes_over_build_anchor_map():
    md = "<!-- p3 -->\n^^經部\n..洛<[[]]王|柏>:zi[⿰扌安]也\n"
    legacy_chars, legacy = _legacy_build_anchor_map()(md)
    assert [legacy[k] for k in range(2)] == ["3:1:-2", "3:1:-1"]
    assert len(legacy_chars) > 8                                # `[[]]` 在夹注里、`:zi[…]` 都被逐符号当成字
    got = [(d["t"]["t"] or ":zi", d["a"]) for d in gf.derive_anchors(md)]
    assert got == [("經", "3:1:-2"), ("部", "3:1:-1"), ("洛", "3:2:3"), ("□", "3:2:4a"), ("王", "3:2:5a"),
                   ("柏", "3:2:4b"), (":zi", "3:2:6"), ("也", "3:2:7")]
    md1 = "<!-- p3 -->\n^經部總\n"
    assert [d["a"] for d in gf.derive_anchors(md1)] == ["3:1:-1", "3:1:1", "3:1:2"]   # 没有第 0 格
    assert _legacy_build_anchor_map()(md1)[1][1] == "3:1:0"


def test_reattach_follows_anchor_after_text_shift(page):
    files = gf.to_guji_format([page], chapter="002")
    i = page["text"].index("瀛")
    punct = {"punctuations": [
        {"mark": "。", "char_offset": i, "pre_char": "瀛", "anchor": f"{PAGE}:2:4"},
        {"mark": "，", "char_offset": i + 1, "pre_char": "按", "anchor": "9:9:9"},     # 锚点失效 → 退到偏移
        {"mark": "、", "char_offset": 0, "pre_char": "按", "anchor": "9:9:9"}]}       # 两条路都不对
    # 前面多一页 → 全章偏移整体后移，锚点不变
    q = copy.deepcopy(page)
    q["page"]["index"] = PAGE - 1
    q["page_id"] = q["page_id"].rsplit("/", 1)[0] + f"/{PAGE - 1}"
    for g in q["glyphs"]:
        g["id"] = "g0" + g["id"][2:]
        g["cv_id"] = g["cv_id"].replace(f":{PAGE}:", f":{PAGE - 1}:")
    files2 = gf.to_guji_format([q, page], chapter="002")
    new, rep = gf.reattach(punct, gf.anchor_index(files2["002.pages.json"]), files2["002.lines.md"])
    n = len(q["text"])
    assert new["punctuations"][0]["char_offset"] == n + i
    # 失效锚点退到旧偏移：旧偏移 i+1 现在落在新插进来的那页上，碰巧也是「按」——字校验拦不住这种同字误挂，
    # 所以退偏移的条目要进报告（by_offset）交人看，锚点才是正路
    assert rep["by_anchor"] == 1 and rep["by_offset"] == 1 and len(rep["lost"]) == 1
    same, rep1 = gf.reattach(punct, gf.anchor_index(files["002.pages.json"]), files["002.lines.md"])
    assert [p["char_offset"] for p in same["punctuations"][:2]] == [i, i + 1]
    assert rep1["by_offset"] == 1 and len(rep1["lost"]) == 1


def test_mismatched_files_raise(page):
    files = gf.to_guji_format([page], chapter="002")
    bad = dict(files)
    bad["002.lines.md"] = files["002.lines.md"].replace("瀛", "瀛也")
    with pytest.raises(ValueError, match="不是同一版"):
        gf.from_guji_format(bad)
    bad["002.lines.md"] = files["002.lines.md"].replace("瀛", "海")
    with pytest.raises(ValueError, match="pages.json 记「瀛」"):
        gf.from_guji_format(bad)


def test_pages_json_shape(page):
    pj = gf.to_guji_format([page], chapter="002")["002.pages.json"]
    assert pj["schema"] == gf.PAGES_SCHEMA and pj["n_chars"] == len(page["text"])
    p = pj["pages"][0]
    assert p["canvas"]["id"].endswith(f"/canvas/02/{PAGE:04d}")
    assert all(len(c["box"]) == 4 for c in p["cells"] if c.get("box"))
    assert not any(k in c for c in p["cells"] for k in ("method", "review", "channel", "cand", "ext"))
    proof = gf.to_guji_format([page], chapter="002")["002.proof.json"]
    assert proof["cells"][0]["cand"] == {"lib": "巨", "ref": "臣"}
    json.dumps(pj, ensure_ascii=False)
