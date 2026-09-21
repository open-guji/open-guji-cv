"""`oracle_llm` 策略：答案表驱动的大模型裁决。

这一层刻意**不在线调 API**，理由写在 `OracleLLM` 的 docstring 里（数字要
可复现、评测不能泄漏、没验收集不许进生产）。这里只测**契约**：
只在候选内选、表里没有就弃权、弃权时可退回 n-gram。

2026-09-20：六条「复现」用例已删。它们拿 `confusable-context` 冻结的逐题
答案跑五个臂，断言准确率还是 `charset_and_lm.md §四` 记的那几个数
（76.0% / 64.3% / 66.2% / 95.5% / 98.7%）。那是**评测**，不是代码行为：

- 数据集路径写死成 `D:/workspace/open-guji-dataset/...`，除了作者那台机器
  以外哪儿都跑不了（这个绝对路径本身就是这套依赖失控的标志）；
- 算准确率那段逻辑**在测试里**，不在生产代码里——测试自己实现一遍被测
  的东西，实现变了它也跟着变，护不住任何东西。

复现照旧跑评测：`python scripts/eval_oracle_llm.py --answers <答案表>`。
结论与口径（尤其「字形层 64.3% 低于多数类基线 76.0%」这条——形近位上形状
判据比瞎猜还差，是「护栏该往宽开」的全部依据）留在 charset_and_lm.md §四。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from open_guji_cv.clustering.context_step import STRATEGIES, build_strategy



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


def test_falls_back_to_the_base_strategy_when_it_abstains():
    """弃权时可退回 n-gram：`fallback` 要写明是哪一条路——
    「拿不准就保持基线」，而不是静默给一个空结果。"""
    d = build_strategy("oracle_llm", answers={"x": "入"})
    r = d.decide({"入": 0.5, "人": 0.4}, item_id="y")
    assert r.surface is None
    assert r.decision.fallback == "no_oracle_answer"


def test_out_of_candidate_answer_never_leaks_into_the_ranking():
    """候选外的答案不但不能被选中，也不能混进 `ranked`——下游（seed_admit
    的 context 通道）是照 `ranked` 取用的，混进去等于绕过了铁律 1。

    ⚠️ 这里**不**断言「两种弃权理由分得开」：候选外与表里没有，现在共用
    同一个 `fallback="no_oracle_answer"`。诊断时分不开是个已知的小缺口，
    但那是实现现状，测试该钉现状、不该写一条描述想象中行为的断言。
    """
    d = build_strategy("oracle_llm", answers={"x": "書"})
    r = d.decide({"入": 0.5, "人": 0.4}, item_id="x")
    assert r.surface is None
    assert "書" not in dict(r.decision.ranked), r.decision.ranked
