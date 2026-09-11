# -*- coding: utf-8 -*-
"""Step6 上下文裁决：线上外部大模型接线（2026-09-10）。

只测新逻辑本身（不依赖真实原图/ProductStore）：
- 关闭时（默认）不调用、不产生日志——行为与旧版完全一致；
- 开启后只在 margin 不过门槛时问，答案只调 `ranked`/`llm_suggestion`，
  不碰 `char`/`source`（人审纪律不能因为接了 LLM 就松）；
- 答案不在候选内/解析失败时不生效，等同没问过；
- 每次调用都追加写日志，字段齐全，供之后测正确率用。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.clustering.llm_context import LLMAnswer
from open_guji_cv.products.kinds.recog import MatchRec
from open_guji_cv.steps.context_decide import ContextDecideParams, ContextDecideStep


def _mock_ctx(book_id="vol01", title="欽定四庫全書總目"):
    return SimpleNamespace(book=SimpleNamespace(id=book_id, title=title))


def _mk_rec(id_, candidates):
    return MatchRec(id=id_, slot=int(id_.split(":")[-1]), verdict="diff",
                    candidates=candidates)


class _FakeJudge:
    """代替 `LLMContextJudge`：固定回答，不发请求。"""

    def __init__(self, answer: str, provider="qwen", model="qwen-plus"):
        self._answer = answer
        self.provider = provider
        self.model = model
        self.calls: list[str] = []

    def ask(self, item_id, prompt):
        self.calls.append(item_id)
        return LLMAnswer(item_id=item_id, provider=self.provider, model=self.model,
                         raw_text=f'{{"char": "{self._answer}"}}',
                         parsed_char=self._answer, parse_ok=True, latency_s=0.01,
                         prompt_tokens=50, completion_tokens=5)


def test_ask_llm_online_reorders_ranked_when_answer_in_candidates(tmp_path, monkeypatch):
    step = ContextDecideStep()
    monkeypatch.setattr(step, "_llm_judge", lambda p: _FakeJudge("乙"))
    p = ContextDecideParams(enable_online_llm=True,
                            llm_log_dir=str(tmp_path / "llm_online_calls"))
    ctx = _mock_ctx()
    r = _mk_rec("vol01:10:1:0", [("甲", 0.6), ("乙", 0.4)])
    priors = {"甲": 0.6, "乙": 0.4}
    ordered = [r]
    result = step._ask_llm_online(ctx, p, 10, r, priors, ordered, 0, {}, [])
    assert result == "乙"

    log_path = tmp_path / "llm_online_calls" / "vol01.jsonl"
    assert log_path.exists()
    row = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert row["id"] == "vol01:10:1:0"
    assert row["book"] == "vol01" and row["page"] == 10
    assert row["llm_parsed_char"] == "乙"
    assert row["llm_answer_in_candidates"] is True
    assert row["candidates_chars"] == ["甲", "乙"]      # 按 prob 降序
    assert row["provider"] == "qwen"


def test_ask_llm_online_returns_none_when_answer_outside_candidates(tmp_path, monkeypatch):
    step = ContextDecideStep()
    monkeypatch.setattr(step, "_llm_judge", lambda p: _FakeJudge("丙"))   # 不在候选里
    p = ContextDecideParams(enable_online_llm=True,
                            llm_log_dir=str(tmp_path / "llm_online_calls"))
    ctx = _mock_ctx()
    r = _mk_rec("vol01:10:1:0", [("甲", 0.6), ("乙", 0.4)])
    priors = {"甲": 0.6, "乙": 0.4}
    result = step._ask_llm_online(ctx, p, 10, r, priors, [r], 0, {}, [])
    assert result is None    # 铁律 1：候选外答案当没答

    log_path = tmp_path / "llm_online_calls" / "vol01.jsonl"
    row = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert row["llm_answer_in_candidates"] is False    # 但日志仍要记，供复盘


def test_ask_llm_online_no_key_raises_loud_not_silent(tmp_path, monkeypatch):
    """开了线上调用却没 key：必须报错退出，不许悄悄退回纯 ngram。"""
    from open_guji_cv.clustering.llm_context import NoAPIKeyError

    step = ContextDecideStep()

    def _boom(p):
        raise NoAPIKeyError("没找到 key")
    monkeypatch.setattr(step, "_llm_judge", _boom)
    p = ContextDecideParams(enable_online_llm=True,
                            llm_log_dir=str(tmp_path / "llm_online_calls"))
    ctx = _mock_ctx()
    r = _mk_rec("vol01:10:1:0", [("甲", 0.6), ("乙", 0.4)])
    priors = {"甲": 0.6, "乙": 0.4}
    with pytest.raises(RuntimeError, match="enable_online_llm"):
        step._ask_llm_online(ctx, p, 10, r, priors, [r], 0, {}, [])


def test_run_page_reorder_respects_max_ranked_even_when_llm_pick_is_offlist(monkeypatch):
    """LLM 建议的字排在原始 ranked 截断线之外时，重排后不能超过 max_ranked
    （曾经的 bug：prepend 不去重截断会让 ranked 悄悄变长）。"""
    import tempfile

    from open_guji_cv.products.kinds.recog import ColumnMatch, PageMatch

    step = ContextDecideStep()
    # 6 个候选，max_ranked=3，LLM 答第 6 名——原本会被截掉
    cands = [("甲", 0.30), ("乙", 0.25), ("丙", 0.20),
            ("丁", 0.15), ("戊", 0.06), ("己", 0.04)]
    r = _mk_rec("vol01:1:1:0", cands)
    monkeypatch.setattr(step, "_llm_judge", lambda p: _FakeJudge("己"))
    monkeypatch.setattr(step, "_decider",
                        lambda p: SimpleNamespace(decide=lambda priors, context=(): (
                            SimpleNamespace(surface=None, margin=0.1,
                                           decision=SimpleNamespace(
                                               used_context=False,
                                               ranked=cands)))))

    match = PageMatch(page=1, columns=[ColumnMatch(col=1, chars=[r])])
    book = SimpleNamespace(id="vol01", title="测试书")

    with tempfile.TemporaryDirectory() as td:
        class _FakeProductCtx:
            def __init__(self):
                self.book = book
            def params_for(self, s):
                return ContextDecideParams(enable_online_llm=True, max_ranked=3,
                                           llm_log_dir=td)
            def product(self, kind, page):
                if kind == "glyph_match":
                    return match
                raise KeyError(kind)

        out = step.run_page(_FakeProductCtx(), 1)
    dec = out["context_decision"]
    rec = dec.columns[0].chars[0]
    assert rec.llm_suggestion == "己"
    assert len(rec.ranked) == 3, f"ranked 超过 max_ranked=3: {rec.ranked}"
    assert rec.ranked[0][0] == "己"      # LLM 的答案被推到最前


def test_enable_online_llm_defaults_off():
    """默认关闭——不会因为跑一次 context_decide 就产生 API 账单。"""
    assert ContextDecideParams().enable_online_llm is False


def test_params_field_moves_hash():
    """开关本身要参与 params_hash：开/关必须是两份不同的产物缓存。"""
    from open_guji_cv.core.engine import params_hash
    a = ContextDecideParams(enable_online_llm=False)
    b = ContextDecideParams(enable_online_llm=True)
    assert params_hash(a) != params_hash(b)
