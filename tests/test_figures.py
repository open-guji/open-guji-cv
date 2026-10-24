# -*- coding: utf-8 -*-
"""图片格与插图块（GUJI-740）：人裁 → 排除名单 → 字位流 → guji-page → pages.json → char v0.3／cord v0.2／fig v0.1 与裁图。

设计 book-text `docs/design/2026-10-图片格与插图设计.md` §五，格式 guji-format spec 09。全部自造数据：
沿用 `test_guji_page_format` 那一页（两列），把列 2 第 5 格「按」判成图片格，列 1 画成插图块。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from PIL import Image
from test_guji_page_format import BOOK, META, PAGE, W, H, _write

from open_guji_cv.feedback.consumers import crop_exclude
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
from open_guji_cv.feedback.figures import figure_cells, region_key, resolved_figure_regions
from open_guji_cv.feedback.lookup import human_chars
from open_guji_cv.feedback.web_votes import latest_votes, triage
from open_guji_cv.formats import guji_char_cord as cc
from open_guji_cv.formats import guji_format as gf
from open_guji_cv.formats import guji_page as gp
from open_guji_cv.formats.guji_page_cv import from_cv_products
from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit, PageAdmit
from open_guji_cv.products.kinds.cells import CellRec
from open_guji_cv.products.store import ProductStore
from open_guji_cv.report.slots import _to_slot

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

FIG_ID = f"{BOOK}:{PAGE}:2:5"


def _confirm(key, payload, seq=1, ts="2026-10-24T00:00:00Z"):
    pg, col, slot = (int(x) for x in key.split(":")[1:])
    return make_event("b", seq, "confirm", EventTarget(step="seed_admit", unit="cell", key=key,
                                                        book=key.split(":")[0], page=pg, col=col, slot=slot),
                      payload, source_format="server", ts=ts)


def _region_event(book, page, regions, seq=1, ts="2026-10-24T00:00:00Z"):
    return make_event("b", seq, "figure_region", EventTarget(step="export", unit="page", key=region_key(book, page)),
                      {"regions": regions}, source_format="server", ts=ts)


# ───────────────────────── 人裁 ─────────────────────────

def test_crop_exclude_figure_keeps_alt(tmp_path):
    lst = tmp_path / "crop_exclusions.jsonl"
    res = crop_exclude([(_confirm("vol05:148:2:14", {"v": "figure", "alt": "左半圈连一实点"}), None)],
                       list_path=str(lst))
    assert res.added == 1
    row = json.loads(lst.read_text(encoding="utf-8"))
    assert row["reason"] == "figure" and row["origin"] == "human"
    assert "alt=左半圈连一实点" in row["evidence"]
    assert figure_cells("vol05", lst, log=EventLog(tmp_path / "fb")) == {"vol05:148:2:14": "左半圈连一实点"}


def test_figure_cells_alt_from_latest_event(tmp_path):
    lst = tmp_path / "crop_exclusions.jsonl"
    crop_exclude([(_confirm("vol05:148:2:14", {"v": "figure"}), None)], list_path=str(lst))
    log = EventLog(tmp_path / "fb")
    log.append([_confirm("vol05:148:2:14", {"v": "figure"}),
                _confirm("vol05:148:2:14", {"v": "figure", "alt": "后补的说明"}, seq=2, ts="2026-10-25T00:00:00Z")])
    assert figure_cells("vol05", lst, log=log) == {"vol05:148:2:14": "后补的说明"}
    assert figure_cells("vol04", lst, log=log) == {}


def test_human_chars_dropped_by_later_figure(tmp_path):
    log = EventLog(tmp_path / "fb")
    log.append([_confirm("bk:1:1:1", {"v": "confirm", "shape": "王"}, ts="2026-10-01T00:00:00Z")])
    assert human_chars("bk", log, stale={}, bind=False) == {"bk:1:1:1": "王"}
    log.append([_confirm("bk:1:1:1", {"v": "figure"}, seq=2, ts="2026-10-02T00:00:00Z")])
    assert human_chars("bk", log, stale={}, bind=False) == {}
    log.append([_confirm("bk:1:1:1", {"v": "confirm", "shape": "玉"}, seq=3, ts="2026-10-03T00:00:00Z")])
    assert human_chars("bk", log, stale={}, bind=False) == {"bk:1:1:1": "玉"}


def test_resolved_figure_regions_latest_per_page(tmp_path):
    log = EventLog(tmp_path / "fb")
    r1 = {"box": [10, 20, 300, 400], "col": 3, "span": 2, "alt": "河圖"}
    log.append([_region_event("vol05", 52, [r1]),
                _region_event("vol05", 53, [{"box": [1, 2, 3, 4], "col": 1}], seq=2),
                _region_event("vol05", 53, [], seq=3, ts="2026-10-25T00:00:00Z"),          # 撤掉
                _region_event("vol04", 52, [r1], seq=4)])
    assert resolved_figure_regions("vol05", log) == {52: [{**r1}]}
    log.append([_region_event("vol05", 52, [{"box": [0, 0, 5, 5]}], seq=5, ts="2026-10-26T00:00:00Z")])
    with pytest.raises(ValueError):                                    # 没有 col 不收
        resolved_figure_regions("vol05", log)


def test_web_vote_figure():
    BOOKID, REV = "96mid1ogzk", "005-r1"

    def vote(a, choice, char="", voter="v1", ts=1, **kw):
        return {"book": BOOKID, "rev": REV, "a": a, "choice": choice, "char": char, "voter": voter, "ts": ts, **kw}
    votes, _ = latest_votes([vote("148:2:14", "figure", alt="左半圈连一实点"),
                             vote("148:2:14", "figure", voter="v2", ts=2),
                             vote("148:2:15", "figure", "形"),
                             vote("148:2:16", "figure")], BOOKID, REV)
    t = triage(votes, "vol05", {})
    assert [(d.a, d.payload) for d in t.ready] == [("148:2:14", {"v": "figure", "alt": "左半圈连一实点"}),
                                                    ("148:2:16", {"v": "figure"})]
    assert [d.a for d in t.held] == ["148:2:15"] and t.held[0].held.startswith("说是图形又给了字")

    class H:                                                           # 已有人裁也是图：只是说明不同，不算推翻
        id, payload = "evt_x", {"v": "figure", "alt": "旧说明"}
    t = triage(votes, "vol05", {"vol05:148:2:14": H()})
    assert ("148:2:14", "与已有人裁 evt_x 一致") in t.skipped


# ───────────────────────── 字位流 ─────────────────────────

def test_slot_figure_occupies_and_wins_over_old_char():
    rec = AdmitRec(id=FIG_ID, slot=5, sub=None, admit=False, char=None, reading=None, channel=None,
                   doubts=["excluded"], evidence={"excluded": "human:figure", "human_char": "按"})
    s = _to_slot(BOOK, PAGE, 2, rec, CellRec(slot=5, pos=5, y0=0, y1=0, x0=0, x1=0, kind="char", sub=None, order=5))
    assert s.figure and s.char == "□" and s.is_text and s.human
    assert not s.excluded and not s.unreadable and not s.defect


# ───────────────────────── 导出 ─────────────────────────

def _store_with_figure(tmp_path) -> ProductStore:
    st = ProductStore(tmp_path / "products")
    _write(st)
    key = f"p{PAGE:04d}"
    seed: PageAdmit = st.read(BOOK, "seed_admit", key, "seed_admit")
    cols = []
    for c in seed.columns:
        chars = [AdmitRec(id=r.id, slot=r.slot, sub=r.sub, admit=False, char=None, reading=None, channel=None,
                          doubts=["excluded"], evidence={"excluded": "human:figure"}) if r.id == FIG_ID else r
                 for r in c.chars]
        cols.append(ColumnAdmit(col=c.col, chars=chars))
    st.write(BOOK, "seed_admit", key, {"seed_admit": PageAdmit(page=PAGE, columns=cols)})
    return st


def _page_image() -> Image.Image:
    im = Image.new("L", (W, H), 255)
    im.paste(0, (520, 1000, 680, 1080))
    return im


def test_export_inline_and_block_figures(tmp_path):
    st = _store_with_figure(tmp_path)
    pg = from_cv_products(st, BOOK, PAGE, META, figure_alts={FIG_ID: "一个圈"})
    assert gp.check(pg) == []
    g = next(x for x in pg["glyphs"] if x["cv_id"] == FIG_ID)
    assert g["fig"] == {"alt": "一个圈"} and g["review"] == "human" and "lacuna" not in g
    assert pg["text"][g["text"][0]] == "□"
    files = gf.to_guji_format([pg], chapter="002")
    back, _ = gf.from_guji_format(files)
    assert back == [gp.strip_ext(pg)]                                   # 往返不丢 fig
    pj = files["002.pages.json"]

    # 只有图片格
    out, rep = cc.from_pages_json(pj, zi=files["002.zi.json"], norm=files["002.norm.json"], chapter="002")
    char, cord, fig = out["002.char.json"], out["002.cord.json"], out["002.fig.json"]
    assert char["$schema"] == cc.CHAR_SCHEMA_URL_V03 and cord["$schema"] == cc.CORD_SCHEMA_URL
    cell = next(c for p in char["pages"] for col in p["columns"] for c in col["cells"] if c["a"] == f"{PAGE}:2:5")
    assert cell == {"a": f"{PAGE}:2:5", "c": "□", "fig": f"f{PAGE}-2-5"}
    assert rep["figures"]["inline"] == 1
    assert cc.check_fig(char, cord, fig) == [f"图 f{PAGE}-2-5 还没裁（sha256／width／height 空）"]
    assert cc.crop_figures(fig, cord, lambda page, sha: _page_image(), tmp_path / "out") == []
    f = fig["figures"][0]
    assert f["alt"] == "一个圈" and f["file"] == f"fig/002/f{PAGE}-2-5.png" and f["source"] == "crop"
    assert (tmp_path / "out" / f["file"]).exists() and f["width"] == f["box"][2] + 4
    for kind, obj in (("char", char), ("cord", cord), ("fig", fig)):
        assert cc.validate(obj, kind) == [], kind
    assert cc.check(char, cord, out["002.norm.json"]) == [] and cc.check_fig(char, cord, fig) == []
    assert cc.char_to_lines_md(char, guess_c_as_qz=True) == files["002.lines.md"]     # 9.1 往返：图片格是 □
    assert f":tu[一个圈]{{id=f{PAGE}-2-5}}" in cc.char_to_lines_md(char, fig=fig)

    # 加插图块：列 1 整列是图
    reg = {PAGE: [{"box": [700, 200, 200, 500], "col": 1, "span": 1, "alt": "河圖"}]}
    out2, rep2 = cc.from_pages_json(pj, zi=files["002.zi.json"], norm=files["002.norm.json"], chapter="002",
                                    figure_regions=reg, prev_fig=fig)
    char2, cord2, fig2 = out2["002.char.json"], out2["002.cord.json"], out2["002.fig.json"]
    assert cord2["$schema"] == cc.CORD_SCHEMA_URL_V02
    cols = char2["pages"][0]["columns"]
    assert cols[0] == {"col": 1, "kind": "figure", "fig": f"p{PAGE}-fig1", "cells": []}
    assert not any(c["a"].startswith(f"{PAGE}:1:") for c in cord2["pages"][0]["cells"])
    assert [m for m in cord2["pages"][0]["marks"] if m["kind"] == "figure"] == [
        {"kind": "figure", "id": f"mfig-p{PAGE}-fig1", "fig": f"p{PAGE}-fig1", "col": 1, "box": [700, 200, 200, 500]}]
    assert len(rep2["figures"]["dropped_cells"]) == 6
    assert cc.crop_figures(fig2, cord2, lambda page, sha: _page_image(), tmp_path / "out2") == []
    blk = next(x for x in fig2["figures"] if x["kind"] == "block")
    assert blk["mime"] == "image/webp" and blk["alt"] == "河圖"
    for kind, obj in (("char", char2), ("cord", cord2), ("fig", fig2)):
        assert cc.validate(obj, kind) == [], kind
    assert cc.check(char2, cord2, out2["002.norm.json"]) == [] and cc.check_fig(char2, cord2, fig2) == []
    md = cc.char_to_lines_md(char2, fig=fig2)
    assert md.splitlines()[1] == f"::tu[河圖]{{id=p{PAGE}-fig1}}"


def test_export_keeps_ids_and_redraw(tmp_path):
    """id 不跟格位变：旧 fig.json 里同页、框重叠的图沿用旧 id；重绘图原样保留（spec 09 §五）。"""
    st = _store_with_figure(tmp_path)
    files = gf.to_guji_format([from_cv_products(st, BOOK, PAGE, META, figure_alts={FIG_ID: ""})], chapter="002")
    pj = files["002.pages.json"]
    out, _ = cc.from_pages_json(pj, chapter="002")
    box = out["002.fig.json"]["figures"][0]["box"]
    prev = {"figures": [{"id": "quan", "kind": "inline", "page": PAGE, "box": [box[0] + 3, box[1], box[2], box[3]],
                         "alt": "圈", "file": "fig/002/quan.svg", "sha256": "0" * 64, "mime": "image/svg+xml",
                         "width": 10, "height": 10, "source": "redraw", "by": "human:Sheldon"}]}
    out, rep = cc.from_pages_json(pj, chapter="002", prev_fig=prev)
    f = out["002.fig.json"]["figures"][0]
    assert f["id"] == "quan" and f["source"] == "redraw" and f["file"] == "fig/002/quan.svg" and f["box"] == box
    assert rep["figures"]["kept"] == 1
    assert cc.crop_figures(out["002.fig.json"], out["002.cord.json"], lambda *_: None, tmp_path) == []   # 重绘不裁
    cell = next(c for p in out["002.char.json"]["pages"] for col in p["columns"] for c in col["cells"] if c.get("fig"))
    assert cell["fig"] == "quan"
    # 没写说明：导出写「图形符号」
    out, _ = cc.from_pages_json(pj, chapter="002")
    assert out["002.fig.json"]["figures"][0]["alt"] == cc.FIG_DEFAULT_ALT


def test_no_figures_byte_identical(tmp_path):
    """没用到图的册：不出 fig.json，char／cord 的 $schema 照旧（逐字节不变）。"""
    st = ProductStore(tmp_path / "products")
    _write(st)
    files = gf.to_guji_format([from_cv_products(st, BOOK, PAGE, META)], chapter="002")
    out, rep = cc.from_pages_json(files["002.pages.json"], chapter="002")
    assert set(out) == {"002.char.json", "002.cord.json", "002.norm.json"}
    assert out["002.char.json"]["$schema"] == cc.CHAR_SCHEMA_URL and out["002.cord.json"]["$schema"] == cc.CORD_SCHEMA_URL
    assert rep["figures"] == {"inline": 0, "block": 0, "kept": 0, "dropped_cells": []}


def test_exporter_script_writes_fig(tmp_path, monkeypatch):
    from export_guji_format import main
    _store_with_figure(tmp_path)
    lst = tmp_path / "crop_exclusions.jsonl"
    crop_exclude([(_confirm(FIG_ID, {"v": "figure", "alt": "一个圈"}), None)], list_path=str(lst))
    monkeypatch.setenv("GUJI_EXCLUSIONS", str(lst))
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(tmp_path / "feedback"))
    EventLog(tmp_path / "feedback").append([_region_event(BOOK, PAGE, [{"box": [700, 200, 200, 500], "col": 1}])])
    imgs = tmp_path / "imgs"
    imgs.mkdir()
    _page_image().save(imgs / f"{PAGE}.png")
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"defaults": META}, ensure_ascii=False), encoding="utf-8")
    base = ["--products", str(tmp_path / "products"), "--book", BOOK, "--chapter", "002", "--meta", str(meta),
            "--pages", str(PAGE), "--format", "char-cord", "--text-version", "0.1.3", "--no-fetch"]
    assert main(base + ["--out", str(tmp_path / "new"), "--page-images", str(imgs)]) == 0
    fig = json.loads((tmp_path / "new" / "002.fig.json").read_text(encoding="utf-8"))
    assert sorted(f["id"] for f in fig["figures"]) == [f"f{PAGE}-2-5", f"p{PAGE}-fig1"]
    assert (tmp_path / "new" / "fig" / "002" / f"f{PAGE}-2-5.png").exists()
    assert (tmp_path / "new" / "fig" / "002" / f"p{PAGE}-fig1.webp").exists()
    # 不读事件：插图块没了，图片格照 Step7 产物出、说明写缺省
    assert main(base + ["--out", str(tmp_path / "plain"), "--no-figures", "--page-images", str(imgs)]) == 0
    fig = json.loads((tmp_path / "plain" / "002.fig.json").read_text(encoding="utf-8"))
    assert [(f["id"], f["alt"]) for f in fig["figures"]] == [(f"f{PAGE}-2-5", cc.FIG_DEFAULT_ALT)]
