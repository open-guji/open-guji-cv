"""seed_admit 越界防护：variant_form fused 为空时不崩。"""
from open_guji_cv.clustering.variant_form import decide_form
from open_guji_cv.variant_ledger import BookLedger


def test_empty_fused_does_not_crash():
    ledger = BookLedger.load_or_empty("wuyingdian_zongmu")
    # 构造一个需要走 image_ranks 的场景：forms ≥2，align 命中，且 lib 未定
    # 手动造一个有 2 形的组：用已知的异体对 髪/髮
    # 若没有该组，用 semantic 相同的占位
    forms = ["髪", "髮"]
    # lib 候选为空，触发 image 分支
    image_ranks = {"hog": [("髪", 0.9), ("髮", 0.8)], "cls": [], "emb": []}
    # HOG 权重为 0，会导致 rrf 空
    fd = decide_form("髮", forms, [], ledger, image_ranks)
    assert fd.state == "open"
    assert fd.char is None
    assert fd.evidence.get("fused") == []
