"""scripts/eval_oracle_llm.py 的核心逻辑单测：不依赖真实数据集/语料。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import eval_oracle_llm as eol  # noqa: E402
from open_guji_cv.clustering.context_step import build_strategy  # noqa: E402


def _write_report(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "report.json"
    p.write_text(json.dumps({
        "provider": "qwen", "model": "qwen-plus", "prompt_version": "candidates",
        "n": len(rows), "llm_accuracy": 0.5, "rows": rows,
    }, ensure_ascii=False), encoding="utf-8")
    return p


def test_load_answer_table_skips_parse_fail_and_out_of_candidates(tmp_path):
    rows = [
        {"id": "a:1", "llm_parse_ok": True, "llm_answer_in_candidates": True,
         "llm_parsed_char": "甲"},
        {"id": "a:2", "llm_parse_ok": False, "llm_answer_in_candidates": False,
         "llm_parsed_char": None},
        {"id": "a:3", "llm_parse_ok": True, "llm_answer_in_candidates": False,
         "llm_parsed_char": "乙"},   # 解析出字但不在候选内——铁律 1，不收
    ]
    path = _write_report(tmp_path, rows)
    answers, meta = eol.load_answer_table(path)
    assert answers == {"a:1": "甲"}
    assert meta["answers_usable"] == 1
    assert meta["provider"] == "qwen"


def _sample(slots: list[dict]) -> dict:
    return {"page": 1, "source_item": "test",
           "columns": [{"column_id": "c1", "slots": slots}]}


def test_run_oracle_uses_answer_table_and_falls_back_when_missing():
    """答案表命中的槽位按 LLM 答案判；缺席的槽位行为与纯 gated_ngram 一致。"""
    from open_guji_cv.clustering.lm import UniformLM
    from open_guji_cv.clustering.variants import VariantMap

    lm = UniformLM()
    vm = VariantMap.load(None)

    slots = [
        {"instance_id": "s:0", "candidates": [{"char": "甲", "prob": 0.6},
                                              {"char": "乙", "prob": 0.4}],
         "gold": "乙", "origin": "align"},   # 基线答错，答案表能救
        {"instance_id": "s:1", "candidates": [{"char": "丙", "prob": 0.6},
                                              {"char": "丁", "prob": 0.4}],
         "gold": "丙", "origin": "align"},   # 基线本来就对，答案表没有这题
    ]
    samples = [_sample(slots)]
    answers = {"s:0": "乙"}

    decider = build_strategy("oracle_llm", answers=answers,
                             semantic_fn=vm.semantic, lm=lm, lam=0.55)
    result = eol.run_oracle(samples, decider, margin=0.70)

    assert result["n"] == 2
    assert result["oracle_hits"] == 1
    assert result["rescued"] == 1
    assert result["harmed"] == 0
    assert result["glyph_layer_immutability"] is True
    # s:1 没有答案表条目，OracleLLM 弃权 margin=0，不满足 gate → 保持基线 top1（丙），不算翻转
    assert result["flips"] == 1
