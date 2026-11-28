# -*- coding: utf-8 -*-
"""第四步读口改读 3c 候选（A7，2026-11-28）：cand_topk_map、read_3c 缺省关时参数哈希不变、开时 3c 进指纹而 5-b 出。"""
from open_guji_cv.core.spec import live_optional_consumes
from open_guji_cv.core.step import STEPS
from open_guji_cv.products.kinds.read import CandRec, ColumnCand, PageCand
from open_guji_cv.steps.align_ref import cand_topk_map, topk_src_map


def _cand():
    return PageCand(page=1, model="m", columns=[ColumnCand(col=1, chars=[
        CandRec(id="a", slot=1, cands=[["日", 0.9], ["曰", 0.8], ["日", 0.7], ["目", 0.6]]),
        CandRec(id="b", slot=2, ran=False),
        CandRec(id="c", slot=3, cands=[]),
    ])])


def test_cand_topk_map_rank_dedup_ran_false():
    m = cand_topk_map(_cand(), 3)
    assert m == {"a": ["日", "曰", "目"]}         # 去重、按列表顺序、ran=False／空候选不进表
    assert cand_topk_map(_cand(), 0) == {} and cand_topk_map(None, 5) == {}


def test_topk_src_map_switch(monkeypatch):
    import open_guji_cv.steps.align_ref as ar
    seen = []
    monkeypatch.setattr(ar, "_opt", lambda ctx, kind, page: (seen.append(kind), _cand() if kind == "glyph_candidate" else None)[1])
    assert topk_src_map(None, 1, 2, True) == {"a": ["日", "曰"]}
    assert topk_src_map(None, 1, 2, False) == {} and seen == ["glyph_candidate", "rare_candidates"]


def test_default_off_keeps_params_dump_and_gates():
    for sid, kw in (("align_ref", {"rare_topk": 5}), ("context_decide", {"rare_topk": 5}), ("char_decide", {})):
        spec = STEPS[sid].spec
        off = spec.params(**kw)
        assert "read_3c" not in off.model_dump(context={"hash": True}) and "read_3c" not in off.model_dump()
        on = spec.params(**kw, read_3c=True)
        assert on.model_dump(context={"hash": True}) != off.model_dump(context={"hash": True})
        assert "glyph_candidate" not in live_optional_consumes(spec, off)
        assert "glyph_candidate" in live_optional_consumes(spec, on)
