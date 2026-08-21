"""RapidOcrSource / VlmSeedSource 单测。"""

import json

import numpy as np
import pytest

from open_guji_cv.clustering.candidates import (RapidOcrSource, VlmSeedSource,
                                                fuse_candidates)
from open_guji_cv.clustering.variants import VariantMap

CJK_FONT = "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf"


def test_clean_strips_noise():
    """OCR 常见噪声：标点、拉丁字母数字 —— 取首个 CJK 字符。"""
    clean = RapidOcrSource._clean
    assert clean("書") == "書"
    assert clean("“臣") == "臣"        # 前置引号
    assert clean("1") == ""            # "一"被误识为数字 → 丢弃
    assert clean("a文b") == "文"
    assert clean("") == ""
    assert clean("，。") == ""


def test_rapidocr_recognizes_rendered_char(tmp_path):
    """端到端：渲染汉字 → RapidOCR 识别正确。"""
    pytest.importorskip("rapidocr_onnxruntime")
    from PIL import Image, ImageDraw, ImageFont
    import os
    if not os.path.exists(CJK_FONT):
        pytest.skip("无 CJK 字体")

    img = Image.new("L", (96, 96), 255)
    ImageDraw.Draw(img).text((10, 4), "文", fill=0,
                             font=ImageFont.truetype(CJK_FONT, 72))
    src = RapidOcrSource(votes=1)
    props = src.propose([np.asarray(img)], [])
    assert props, "应给出候选"
    assert props[0].char == "文"
    assert props[0].source == "ocr"
    assert props[0].surface_uncertain is True   # 字表未必含异体字形


def test_vlm_seed_source(synth_book, tmp_path):
    """VlmSeedSource 按簇成员反查识别结果。"""
    from open_guji_cv.clustering.vlm_assist import make_sheets
    from open_guji_cv.clustering.extractor import load_index

    seed = tmp_path / "seed"
    mapping = make_sheets(synth_book, seed, min_size=2)
    b1 = mapping["batch_01"]
    (seed / "recognitions.json").write_text(
        json.dumps({"batch_01": {"1": "甲|乙~"}}, ensure_ascii=False),
        encoding="utf-8")

    clusters_json = synth_book / "phase5_clusters" / "clusters.json"
    src = VlmSeedSource(seed, clusters_json)
    with open(clusters_json, encoding="utf-8") as f:
        cl = {c["cluster_id"]: c for c in json.load(f)["clusters"]}
    inst = {i.id: i for i in load_index(synth_book / "phase4_chars")}

    target = cl[b1["1"]["cluster"]]
    props = src.propose([], [inst[m] for m in target["members"]])
    assert [p.char for p in props] == ["甲", "乙"]
    assert all(p.source == "vlm" and p.surface_uncertain for p in props)

    # 未识别的簇 → 无候选
    other = next(c for cid, c in cl.items()
                 if cid != target["cluster_id"] and c["members"])
    if other["cluster_id"] not in {v["cluster"] for v in b1.values()}:
        assert src.propose([], [inst[m] for m in other["members"]]) == []


def test_fusion_prefers_agreement():
    """双来源一致 → 该候选得分显著高于任一单来源候选。"""
    from open_guji_cv.clustering.candidates import Proposal
    vm = VariantMap({})
    out = fuse_candidates([
        Proposal("內", 0.9, "vlm"),
        Proposal("丙", 0.6, "ocr", surface_uncertain=True),
        Proposal("內", 0.4, "ocr", surface_uncertain=True),
    ], vm)
    assert out[0]["char"] == "內"
    assert set(out[0]["sources"]) == {"vlm", "ocr"}
    assert out[0]["p"] > out[1]["p"]


def test_traditional_variants():
    """简→繁扩展：刻本不可能有简体，OCR 简体输出应扩展为繁体候选。"""
    pytest.importorskip("opencc")
    from open_guji_cv.clustering.candidates import traditional_variants as tv
    assert tv("内") == ["內"]
    assert tv("为") == ["爲"]        # 刻本用"爲"而非"為"
    assert tv("万") == ["萬"]        # 一简多繁只取非自身项
    assert tv("書") == []            # 本身是繁体
    assert tv("之") == []            # 简繁同形


def test_rapidocr_s2t_expansion(monkeypatch):
    """OCR 输出简体时，繁体候选权重高于原简体输出。"""
    pytest.importorskip("opencc")
    src = RapidOcrSource(s2t=True, votes=1)

    class FakeEngine:
        def __call__(self, img, **kw):
            return [["内", 0.9]], None

    src._engine = FakeEngine()
    props = src.propose([np.zeros((32, 32), np.uint8)], [])
    chars = [p.char for p in props]
    assert chars[0] == "內"                 # 繁体首选
    assert "内" in chars                    # 原输出保留为低权候选
    assert props[0].p > props[-1].p
    assert all(p.surface_uncertain for p in props)

    # 关闭时原样输出
    src2 = RapidOcrSource(s2t=False, votes=1)
    src2._engine = FakeEngine()
    assert [p.char for p in src2.propose([np.zeros((32, 32), np.uint8)], [])] == ["内"]
