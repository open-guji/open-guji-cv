"""candidates.py 单测：多来源融合的纯函数逻辑。"""

from open_guji_cv.clustering.candidates import Proposal, fuse_candidates
from open_guji_cv.clustering.variants import VariantMap

VM = VariantMap({"逰": "遊"})


def test_variants_not_merged():
    """异体字独立计票，绝不合并；semantic 注记正确。"""
    out = fuse_candidates([
        Proposal("逰", 0.6, "glyph_knn"),
        Proposal("遊", 0.5, "ocr", surface_uncertain=True),
    ], VM)
    chars = {c["char"]: c for c in out}
    assert set(chars) == {"逰", "遊"}          # 两个字形都在
    assert chars["逰"]["semantic"] == "遊"
    assert chars["遊"]["semantic"] == "遊"


def test_source_weighting():
    """字形库来源权重高于 prior：同分输入时字形库候选排前。"""
    out = fuse_candidates([
        Proposal("甲", 0.5, "prior", surface_uncertain=True),
        Proposal("乙", 0.5, "glyph_knn"),
    ], VM)
    assert out[0]["char"] == "乙"


def test_surface_uncertain_cleared_by_confident_source():
    """任一"字形确定"来源命中后，该候选不再标 surface_uncertain。"""
    out = fuse_candidates([
        Proposal("通", 0.5, "ocr", surface_uncertain=True),
        Proposal("通", 0.8, "glyph_knn", surface_uncertain=False),
    ], VM)
    assert out[0]["char"] == "通"
    assert out[0]["surface_uncertain"] is False
    assert set(out[0]["sources"]) == {"ocr", "glyph_knn"}


def test_probabilities_normalized():
    out = fuse_candidates([
        Proposal("甲", 0.9, "ocr"),
        Proposal("乙", 0.3, "ocr"),
    ], VM)
    assert abs(sum(c["p"] for c in out) - 1.0) < 0.01
    assert out[0]["p"] > out[1]["p"]


def test_empty_input():
    assert fuse_candidates([], VM) == []
