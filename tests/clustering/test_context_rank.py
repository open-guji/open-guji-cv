"""context_rank.py + lm.py 单测：微型语料上的确定性行为。"""

from open_guji_cv.clustering.context_rank import (Slot, SlotCandidate,
                                                  beam_search,
                                                  check_cluster_consistency)
from open_guji_cv.clustering.lm import CharNgramLM, UniformLM
from open_guji_cv.clustering.variants import VariantMap


def _slot(iid, cid, cands):
    return Slot(instance_id=iid, cluster_id=cid,
                candidates=[SlotCandidate(c, s, p) for c, s, p in cands])


def test_lm_prefers_seen_bigram():
    lm = CharNgramLM(order=2)
    lm.train(["天下太平", "天下大同"])
    assert lm.logp("下", ("天",)) > lm.logp("上", ("天",))


def test_beam_uses_context():
    """OCR 弱分歧 + LM 明确偏好 → LM 翻盘。"""
    lm = CharNgramLM(order=2)
    lm.train(["天下太平"] * 5)
    slots = [
        _slot("b:1:1:0", "c0", [("天", "天", 0.9)]),
        # OCR 略偏"卜"，但语料只见过"天下"
        _slot("b:1:1:1", "c1", [("卜", "卜", 0.55), ("下", "下", 0.45)]),
    ]
    results = beam_search(slots, lm, lam=0.3)
    assert results[1].best == "下"
    assert "lm_ocr_conflict" in results[1].suspect_reasons


def test_variant_surface_preserved():
    """字形层输出保留异体字：LM 在语义层无差别时，字形证据（p_ocr）裁决。"""
    lm = CharNgramLM(order=2)
    lm.train(["雲遊四海"] * 3)   # 语料是语义层（正字）
    slots = [
        _slot("b:1:1:0", "c0", [("雲", "雲", 0.9)]),
        # 两个候选映射到同一语义"遊"——字形层"逰"的 OCR 分更高
        _slot("b:1:1:1", "c1", [("逰", "遊", 0.6), ("遊", "遊", 0.4)]),
    ]
    results = beam_search(slots, lm, lam=0.5)
    assert results[1].best == "逰"          # 精确异体字形保留
    assert results[1].best_semantic == "遊"  # 语义层注记正确


def test_low_margin_flagged():
    lm = UniformLM()
    slots = [_slot("b:1:1:0", "c0", [("甲", "甲", 0.5), ("乙", "乙", 0.5)])]
    results = beam_search(slots, lm)
    assert "low_margin" in results[0].suspect_reasons


def test_cluster_consistency_check():
    lm = UniformLM()
    slots = [
        _slot("b:1:1:0", "cX", [("甲", "甲", 0.99)]),
        _slot("b:1:1:1", "cX", [("乙", "乙", 0.99)]),
    ]
    results = beam_search(slots, lm)
    check_cluster_consistency(results)
    assert all("cluster_inconsistent" in r.suspect_reasons for r in results)


def test_empty_candidates_unk():
    lm = UniformLM()
    results = beam_search([_slot("b:1:1:0", None, [])], lm)
    assert results[0].best == "<unk>"


def test_variant_map():
    vm = VariantMap({"逰": "遊", "為": "爲"})
    assert vm.semantic("逰") == "遊"
    assert vm.semantic("天") == "天"
    assert vm.normalize_text("逰天為") == "遊天爲"
    assert "逰" in vm.variants_of("遊")
    assert "遊" in vm.variants_of("遊")


def test_ngram_save_load(tmp_path):
    lm = CharNgramLM(order=3)
    lm.train(["天下太平"])
    p = tmp_path / "lm.json"
    lm.save(p)
    lm2 = CharNgramLM.load(p)
    assert lm2.logp("下", ("天",)) == lm.logp("下", ("天",))
