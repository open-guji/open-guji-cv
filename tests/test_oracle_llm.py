"""`oracle_llm` 策略：答案表驱动的大模型裁决。

这一层刻意**不在线调 API**，理由写在 `OracleLLM` 的 docstring 里（数字要
可复现、评测不能泄漏、没验收集不许进生产）。所以这里的用例分两类：

- **契约**：只在候选内选、表里没有就弃权、弃权时可退回 n-gram；
- **复现**：拿 `confusable-context` 冻结的逐题答案跑一遍，五个臂的数字必须
  和 `charset_and_lm.md §四` 记的一致。这条是防「策略实现悄悄改了口径」。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from open_guji_cv.clustering.context_step import STRATEGIES, build_strategy

DS = Path(r"D:/workspace/open-guji-dataset/confusable-context")
needs_dataset = pytest.mark.skipif(
    not (DS / "answer_key.json").exists(), reason="没有 confusable-context 数据集")


def test_registered():
    assert "oracle_llm" in STRATEGIES


def test_only_picks_from_candidates():
    """答案不在候选里就当没答——绝不引入候选外的字（铁律 1）。"""
    d = build_strategy("oracle_llm", answers={"x": "書"})
    assert d.decide({"入": 0.5, "人": 0.4}, item_id="x").surface is None


def test_abstains_when_no_answer():
    """表里没有的字位弃权，margin=0——「拿不准就保持基线」。"""
    d = build_strategy("oracle_llm", answers={"x": "入"})
    r = d.decide({"入": 0.5, "人": 0.4}, item_id="y")
    assert r.surface is None and r.margin == 0.0
    assert r.decision.fallback == "no_oracle_answer"


def test_hits_answer_within_candidates():
    d = build_strategy("oracle_llm", answers={"x": "入"})
    r = d.decide({"入": 0.5, "人": 0.4}, item_id="x")
    assert r.surface == "入" and r.margin == 1.0
    assert r.decision.used_context is True


@needs_dataset
@pytest.mark.parametrize("arm,expect", [
    ("多数类基线", 0.760),
    ("字形层 top-1", 0.643),
    ("OCR", 0.662),
    ("ngram-heldout", 0.955),
    ("大模型（盲测）", 0.987),
])
def test_reproduces_frozen_baseline(arm, expect):
    """五个臂的冻结答案跑出来必须还是文档里那几个数（±0.5%）。

    尤其是**字形层 64.3% 低于多数类基线 76.0%** 这一条——形近位上形状判据
    比瞎猜还差，是「护栏该往宽开」的全部依据。哪天这个数悄悄变了，
    说明口径被动过，那 charset_and_lm.md §四 的结论就要重新算。
    """
    base = json.loads((DS / "baseline_r1.json").read_text(encoding="utf-8"))
    key = json.loads((DS / "answer_key.json").read_text(encoding="utf-8"))
    gold = {r["id"]: r["gold"] for r in key}
    opts = {r["id"]: r["options"] for r in key}
    d = build_strategy("oracle_llm", answers=base[arm])
    ok = sum(1 for cid, g in gold.items()
             if d.decide({o: 1.0 / len(opts[cid]) for o in opts[cid]},
                         item_id=cid).surface == g)
    acc = ok / len(gold)
    assert abs(acc - expect) < 0.005, f"{arm} 复现 {acc:.3f}，文档记 {expect}"


@needs_dataset
def test_llm_beats_ngram_on_hard_tier():
    """真难档才是这一层的价值所在：大模型 93.8% vs n-gram 87.5%。"""
    base = json.loads((DS / "baseline_r1.json").read_text(encoding="utf-8"))
    key = json.loads((DS / "answer_key.json").read_text(encoding="utf-8"))
    hard = [r for r in key if r["tier"].startswith("hard")]
    assert hard, "难档样本没了，这条用例就失去意义"

    def acc(arm):
        d = build_strategy("oracle_llm", answers=base[arm])
        ok = sum(1 for r in hard
                 if d.decide({o: 1.0 / len(r["options"]) for o in r["options"]},
                             item_id=r["id"]).surface == r["gold"])
        return ok / len(hard)

    assert acc("大模型（盲测）") >= acc("ngram-heldout")
