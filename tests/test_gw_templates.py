# -*- coding: utf-8 -*-
"""GlyphWiki 变体形模板档（`CnnCandidates._gw_index` + `emb_topk_batch` 的 max 融合）的契约。

装了 torch 且仓里有 checkpoint 才跑。造一个两张图的临时目录：把字体渲染的「甲」形挂成
「乙」的变体——拿同一张图去查，融合后「乙」必须以余弦 ≈1 顶到第一，且 `last_gw_prov`
记下是哪张形赢的；目录缺席 / 关掉总开关时结果与原来逐位相同。**不测效果**（那在
设计稿 §13 ⑤）。
"""

from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")


def _catalog(tmp_path, img, related: str, name="zihai-000001", src="zihai"):
    f = tmp_path / "catalog_64.npz"
    np.savez_compressed(f, names=np.array([name]), related=np.array([related]), source=np.array([src]),
                        imgs=img[None].astype(np.uint8), charset="test")
    return f


def test_gw_max_fusion_and_provenance(tmp_path, monkeypatch):
    from open_guji_cv.clustering import cnn_candidates as cc
    from open_guji_cv.clustering.font_candidates import _font_files
    from open_guji_cv.clustering.synth import render_char
    if not cc.DEFAULT_CKPT.exists() or not _font_files():
        pytest.skip("没有 checkpoint / 字体")
    img = render_char("諭", _font_files()[0], size=64).astype(np.uint8)
    charset = ("諭", "論", "俞")
    cnn = cc.CnnCandidates(cc.DEFAULT_CKPT)
    monkeypatch.setattr(cc, "GW_CATALOG", tmp_path / "nope.npz")
    base = cnn.emb_topk_batch([img], charset, k=3)[0]
    assert base[0][0] == "諭" and cnn.last_gw_prov == [{}]

    monkeypatch.setattr(cc, "GW_ENABLED", True)          # 缺省关（见 cnn_candidates.GW_ENABLED），这里显式开
    monkeypatch.setattr(cc, "GW_CATALOG", _catalog(tmp_path, img, related="論"))
    monkeypatch.setattr(cnn, "ckpt", tmp_path / "ckpt" / "best.pt")     # 落盘缓存写到临时目录
    (tmp_path / "ckpt").mkdir()
    monkeypatch.setattr(cc, "fingerprint", lambda p=None: "testfp")
    cnn._gw = cnn._gw_cs = None
    fused = cnn.emb_topk_batch([img], charset, k=3)[0]
    assert fused[0][0] == "論" and fused[0][1] > 0.999            # 同一张图当模板 → 余弦 1
    assert set(cnn.last_gw_prov[0]) == {"論"}
    name, src, cos = cnn.last_gw_prov[0]["論"]
    assert name == "zihai-000001" and src == "zihai" and cos > 0.999
    assert any(p.name.startswith("gw_") for p in (tmp_path / "ckpt").iterdir())   # embedding 落了盘

    monkeypatch.setattr(cc, "GW_ENABLED", False)
    cnn._gw_cs = None
    assert cnn.emb_topk_batch([img], charset, k=3)[0] == base and cnn.last_gw_prov == [{}]
