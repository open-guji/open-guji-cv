# -*- coding: utf-8 -*-
"""真刻例多原型档（R2 / T11）的契约：`REAL_PROTO_ENABLED` 关（缺省）时结果与从前
逐位相同；开了之后同一张图当「人裁真刻例」存进 `glyph_store` 布局，查询命中该
原型、`last_real_prov` 记来源；`label_status` 白名单只认 human；留一法
（`real_exclude_ids`）摘掉之后退回字体基线；一个字 >3 条真刻例只留 <=3 个原型。

不测效果（那是评测脚本的事），只测接线对不对——同 `test_gw_templates.py` 的定位。
"""

from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

torch = pytest.importorskip("torch")


def _raw_patch(char: str, font_path: str, canvas: int = 200) -> np.ndarray:
    """造一张「原始裁块」灰度图（白底黑字，未归一化）——`glyph_store` 里
    `patches/<instance_id>.png` 的真实格式，需要 `normalize_patch` 才能进网络。"""
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(font_path, int(canvas * 0.8))
    img = Image.new("L", (canvas, canvas), 255)
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), char, font=font)
    x = (canvas - (bbox[2] - bbox[0])) // 2 - bbox[0]
    y = (canvas - (bbox[3] - bbox[1])) // 2 - bbox[1]
    draw.text((x, y), char, fill=0, font=font)
    return np.asarray(img).astype(np.uint8)


def _make_store(tmp_path, entries):
    """entries: [(char, instance_id, label_status, raw_img), ...] -> store 目录。"""
    store = tmp_path / "store"
    (store / "instances").mkdir(parents=True)
    (store / "patches").mkdir(parents=True)
    lines = []
    for ch, iid, status, raw in entries:
        cv2.imwrite(str(store / "patches" / f"{iid.replace(':', '_')}.png"), raw)
        lines.append(json.dumps({"instance_id": iid, "label": ch, "label_status": status}))
    (store / "instances" / "vol01.jsonl").write_text("\n".join(lines), encoding="utf-8")
    return store


def test_real_proto_hit_and_provenance(tmp_path, monkeypatch):
    from open_guji_cv.clustering import cnn_candidates as cc
    from open_guji_cv.clustering.font_candidates import _font_files
    from open_guji_cv.clustering.normalize import normalize_patch
    if not cc.DEFAULT_CKPT.exists() or not _font_files():
        pytest.skip("没有 checkpoint / 字体")

    raw = _raw_patch("諭", _font_files()[0])
    store = _make_store(tmp_path, [("諭", "vol01:1:1:1", "human", raw)])
    charset = ("諭", "論", "俞")
    cnn = cc.CnnCandidates(cc.DEFAULT_CKPT)

    monkeypatch.setattr(cc, "REAL_PROTO_ENABLED", False)
    query = normalize_patch(raw)
    base = cnn.emb_topk_batch([query], charset, k=3)[0]
    assert cnn.last_real_prov == [{}]

    monkeypatch.setattr(cc, "REAL_PROTO_ENABLED", True)
    monkeypatch.setattr(cc, "REAL_PROTO_SPECS", (f"store:{store}",))
    cnn._real_cs = None
    fused = cnn.emb_topk_batch([query], charset, k=3)[0]
    assert fused[0][0] == "諭" and fused[0][1] > 0.999
    assert set(cnn.last_real_prov[0]) == {"諭"}
    iid, cos = cnn.last_real_prov[0]["諭"]
    assert iid == "vol01:1:1:1" and cos > 0.999

    # 总开关关掉 -> 与最初逐位相同
    monkeypatch.setattr(cc, "REAL_PROTO_ENABLED", False)
    cnn._real_cs = None
    assert cnn.emb_topk_batch([query], charset, k=3)[0] == base
    assert cnn.last_real_prov == [{}]


def test_only_human_label_status(tmp_path, monkeypatch):
    """`align`/`match`/`context` 都是算法标的，不算真刻例——不进池子。"""
    from open_guji_cv.clustering import cnn_candidates as cc
    from open_guji_cv.clustering.font_candidates import _font_files
    if not cc.DEFAULT_CKPT.exists() or not _font_files():
        pytest.skip("没有 checkpoint / 字体")

    raw = _raw_patch("諭", _font_files()[0])
    store = _make_store(tmp_path, [("諭", "vol01:1:1:1", "align", raw)])
    pool = cc.load_real_exemplars((f"store:{store}",), charset=("諭",))
    assert pool == {}


def test_leave_one_out_by_physical_cell(tmp_path, monkeypatch):
    """留一法：评测字自己的物理格（同册同页同列、格号相差 <=2）摘掉后退回字体基线。"""
    from open_guji_cv.clustering import cnn_candidates as cc
    from open_guji_cv.clustering.font_candidates import _font_files
    from open_guji_cv.clustering.normalize import normalize_patch
    if not cc.DEFAULT_CKPT.exists() or not _font_files():
        pytest.skip("没有 checkpoint / 字体")

    raw = _raw_patch("諭", _font_files()[0])
    store = _make_store(tmp_path, [("諭", "vol01:5:2:10", "human", raw)])
    charset = ("諭", "論", "俞")
    cnn = cc.CnnCandidates(cc.DEFAULT_CKPT)
    monkeypatch.setattr(cc, "REAL_PROTO_ENABLED", True)
    monkeypatch.setattr(cc, "REAL_PROTO_SPECS", (f"store:{store}",))

    query = normalize_patch(raw)
    cnn._real_cs = None
    monkeypatch.setattr(cc, "REAL_PROTO_ENABLED", False)
    base = cnn.emb_topk_batch([query], charset, k=3)[0]
    monkeypatch.setattr(cc, "REAL_PROTO_ENABLED", True)

    # 摘一个相邻格号（漂移邻格，非精确同一 id）也要摘中
    cnn._real_cs = None
    out = cnn.emb_topk_batch([query], charset, k=3, real_exclude_ids=frozenset({"vol01:5:2:11"}))[0]
    assert out == base and cnn.last_real_prov == [{}]

    # 不相关的格（列不同）不摘
    cnn._real_cs = None
    out2 = cnn.emb_topk_batch([query], charset, k=3, real_exclude_ids=frozenset({"vol01:5:9:10"}))[0]
    assert out2[0][0] == "諭" and out2[0][1] > 0.999


def test_k_le_3_prototypes(tmp_path, monkeypatch):
    """一个字 5 条人裁真刻例 -> 聚类后 <=3 个原型。"""
    from open_guji_cv.clustering import cnn_candidates as cc
    from open_guji_cv.clustering.font_candidates import _font_files
    if not cc.DEFAULT_CKPT.exists() or not _font_files():
        pytest.skip("没有 checkpoint / 字体")

    fonts = _font_files()
    entries = []
    for i in range(5):
        raw = _raw_patch("諭", fonts[i % len(fonts)], canvas=200 + i * 4)
        entries.append(("諭", f"vol01:{i+1}:1:1", "human", raw))
    store = _make_store(tmp_path, entries)
    cnn = cc.CnnCandidates(cc.DEFAULT_CKPT)
    monkeypatch.setattr(cc, "REAL_PROTO_ENABLED", True)
    monkeypatch.setattr(cc, "REAL_PROTO_SPECS", (f"store:{store}",))
    names = ["諭", "論", "俞"]
    cnn._ensure()
    res = cnn._real_index(("諭", "論", "俞"), names)
    assert res is not None
    R, rows_idx, iids = res
    assert (rows_idx == 0).sum() <= cc.REAL_PROTO_K
