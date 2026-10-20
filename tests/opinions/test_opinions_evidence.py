# -*- coding: utf-8 -*-
"""意见池 C1：证据包的裁切坐标（自造小图＋自造 cord＋假 IIIF），不连网。"""
from __future__ import annotations

import io
import json

from booktext_fixture import BOOK, CANVAS_H, CANVAS_W, SEAL_BOX, char, cord
from PIL import Image, ImageDraw

from open_guji_cv.opinions import evidence as E
from open_guji_cv.opinions.schema import Opinion, make_id

TARGET_BOX = [300, 150, 60, 48]          # 3:1:3 「卷」
RED, BLUE = (255, 0, 0), (0, 0, 255)


def _page(scale: float = 1.0) -> bytes:
    im = Image.new("RGB", (int(CANVAS_W * scale), int(CANVAS_H * scale)), "white")
    d = ImageDraw.Draw(im)
    x, y, w, h = TARGET_BOX
    d.rectangle([x * scale, y * scale, (x + w) * scale - 1, (y + h) * scale - 1], fill=RED)
    x, y, w, h = SEAL_BOX
    d.rectangle([x * scale, y * scale, (x + w) * scale - 1, (y + h) * scale - 1], fill=BLUE)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _fake_get(scale: float, calls: list):
    canvas = f"https://iiif.test/iiif/{BOOK}/canvas/02/0003"
    manifest = {"items": [{"id": canvas, "width": CANVAS_W, "height": CANVAS_H, "items": [{"items": [{"body": {
        "type": "Choice", "items": [{"id": f"https://iiif.test/iiif/{BOOK}/02/0003/full/1200,/0/default.png"}, {"id": "x"}]}}]}]}]}

    def get(url):
        calls.append(url)
        if url.endswith("manifest.json"):
            assert url == f"https://iiif.test/iiif/{BOOK}/02/manifest.json"
            return json.dumps(manifest).encode()
        assert f"/full/{CANVAS_W},/" in url          # 原图档：宽度换成 canvas 宽
        return _page(scale)
    return get


def _op():
    return Opinion(id=make_id("span", "x"), book=BOOK, vol="002", channel="span", raw_id="r", ts="t",
                   target={"start": "3:1:3", "end": "3:1:3", "text_version": "1.0.1", "check": "卷"},
                   category="missing", proposal={"text": "卷一"})


def _colors(path):
    return {c for _n, c in Image.open(path).convert("RGB").getcolors(1 << 20)}


def test_crop_coordinates_and_next_unit(tmp_path):
    calls = []
    f = E.ImageFetcher(tmp_path / "cache", get=_fake_get(1.0, calls))
    ev = E.build(_op(), char(), cord(), f, tmp_path / "out", pad=0)
    d = tmp_path / "out" / _op().id
    tgt = [u for u in ev["units"] if u["target"]]
    assert [u["a"] for u in tgt] == ["3:1:3"]
    assert tgt[0]["crop"] == [300, 150, 360, 198]
    assert _colors(d / tgt[0]["file"]) == {RED}                       # 裁到的正好是那一格
    nx = ev["next_after_target"]
    assert nx["kind"] == "excluded" and nx["mark_id"] == "mseal1" and nx["note"].startswith("排除名单")
    assert _colors(d / nx["file"]) == {BLUE}
    assert [u["label"] for u in ev["units"]] == ["3:1:1", "3:1:2", "3:1:3", "excluded@3", "blank@6"]
    assert ev["context"] == "欽定【卷】御製甲乙丙□文"
    assert (d / "strip.png").is_file() and (d / "strip_marked.png").is_file()
    png, md = E.sheet([ev], tmp_path / "out")
    assert png.is_file() and "排除名单" in md.read_text(encoding="utf-8")
    # 第二次走缓存，不再下载整页
    n = len(calls)
    E.build(_op(), char(), cord(), E.ImageFetcher(tmp_path / "cache", get=_fake_get(1.0, calls)), tmp_path / "out2", pad=0)
    assert not any("default.png" in u for u in calls[n:])


def test_scaled_image(tmp_path):
    """下载到的图只有 canvas 一半宽时，框按比例换算。"""
    f = E.ImageFetcher(tmp_path / "cache", get=_fake_get(0.5, []))
    ev = E.build(_op(), char(), cord(), f, tmp_path / "out", pad=0)
    tgt = next(u for u in ev["units"] if u["target"])
    assert ev["image"]["scale"] == 0.5 and tgt["crop"] == [150, 75, 180, 99]
    assert _colors(tmp_path / "out" / _op().id / tgt["file"]) == {RED}


def test_column_units_jiazhu_order():
    pg = cord()["pages"][2]
    seq = [c["a"] for p in char()["pages"] for col in p["columns"] for c in col["cells"]]
    us = E.column_units(pg, {}, 2, seq)
    # 读序：抬头、正文、夹注右列、左列；排除名单那格（y=150）插在第一个比它低的字格之前
    assert [u.label for u in us] == ["3:2:-1", "3:2:1", "3:2:2a", "3:2:3a", "3:2:2b", "excluded@3", "3:2:4", "3:2:5"]
