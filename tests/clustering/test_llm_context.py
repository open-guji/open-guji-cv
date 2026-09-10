"""llm_context 单测：不发网络请求（urlopen 全 monkeypatch），覆盖：

- 回答解析（JSON / 单字 / 引号提取 / 候选唯一命中 / 候选歧义 / 无法解析）
- 没 key 显式抛异常，不许静默退化
- 真调用层的缓存（同一 prompt 第二次不再发请求）与重试
- prompt 两版都不泄漏 gold
- MockJudge 能跑通「调用→解析→打分」全链路（任务书完成判据 #2）
"""

from __future__ import annotations

import json

import pytest

from open_guji_cv.clustering.llm_context import (LLMContextJudge, MockJudge,
                                                  NoAPIKeyError, parse_answer,
                                                  prompt_direct,
                                                  prompt_with_candidates)


# ── parse_answer ──────────────────────────────────────────────────────

def test_parse_answer_json():
    assert parse_answer('{"char": "根"}') == ("根", True)


def test_parse_answer_json_with_reason_ignored():
    assert parse_answer('{"char": "根", "reason": "上下文提到根源"}') == ("根", True)


def test_parse_answer_plain_single_char():
    assert parse_answer("根") == ("根", True)


def test_parse_answer_quoted_char_in_sentence():
    assert parse_answer("根据上下文，我认为这里应该是「根」字。") == ("根", True)


def test_parse_answer_quoted_char_ascii_quotes():
    assert parse_answer('这里应该填 "檢" 字') == ("檢", True)


def test_parse_answer_quote_extraction_beats_boilerplate_cjk():
    """回归用例：踩过的坑——boilerplate「根据上下文」本身含「根」字，
    通用首字兜底会把它误当成答案，即便真正答案是候选表里完全不同的字。"""
    text = "根据上下文，我认为这里应该是「檢」字。"
    assert parse_answer(text) == ("檢", True)
    assert parse_answer(text, candidates=["檢", "校", "類"]) == ("檢", True)


def test_parse_answer_candidates_unique_hit_no_quotes():
    assert parse_answer("我选校", candidates=["檢", "校", "類"]) == ("校", True)


def test_parse_answer_candidates_ambiguous_fails():
    # 复述了不止一个候选字，判解析失败，不瞎猜
    text = "候选有檢和校，我选校"
    assert parse_answer(text, candidates=["檢", "校", "類"]) == (None, False)


def test_parse_answer_empty_fails():
    assert parse_answer("") == (None, False)
    assert parse_answer(None) == (None, False)


def test_parse_answer_no_cjk_fails():
    assert parse_answer("I don't know", candidates=["檢", "校"]) == (None, False)


# ── prompt 不泄漏 gold ──────────────────────────────────────────────

_ITEM = {
    "context_before": "前文十字前文十字",
    "context_after": "后文十字后文十字",
    "candidates_chars": ["檢", "校", "類"],
    "gold": "驥",   # 真答案：两版 prompt 都不许把它拼进去
    # ⚠️ 别挑「根」这类常见字当测试用的 gold——prompt_direct 模板本身的
    # 「只根据上下文…」措辞就含「根」字，会把这条断言坑成假阳性
    # （2026-09-10 实测踩过，非解析逻辑的 bug，是测试夹具选字选到了坑里）。
}


def test_prompt_direct_no_candidates_no_gold():
    p = prompt_direct(_ITEM, "欽定四庫全書總目")
    assert _ITEM["gold"] not in p      # gold 不出现
    assert _ITEM["context_before"] in p
    assert _ITEM["context_after"] in p
    assert "欽定四庫全書總目" in p


def test_prompt_with_candidates_lists_options_not_gold():
    p = prompt_with_candidates(_ITEM, "欽定四庫全書總目")
    for c in _ITEM["candidates_chars"]:
        assert c in p
    assert _ITEM["gold"] not in p
    assert "json" in p.lower() or "JSON" in p


def test_prompt_with_candidates_reason_variant_differs():
    p1 = prompt_with_candidates(_ITEM, "书名", with_reason=False)
    p2 = prompt_with_candidates(_ITEM, "书名", with_reason=True)
    assert p1 != p2
    assert "reason" in p2


# ── 没 key：显式抛异常，不许静默退化 ──────────────────────────────────

def test_no_api_key_raises(monkeypatch):
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(NoAPIKeyError):
        LLMContextJudge("glm")
    with pytest.raises(NoAPIKeyError):
        LLMContextJudge("qwen")


def test_unknown_provider_raises_keyerror(monkeypatch):
    monkeypatch.setenv("GLM_API_KEY", "fake-key")
    with pytest.raises(KeyError):
        LLMContextJudge("not-a-real-provider")


# ── 真调用层：urlopen 全 mock，验证请求体、解析、缓存、重试 ────────────

class _FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _ok_response(char: str = "校"):
    return _FakeResponse({"choices": [{"message": {"content": char}}]})


def test_llm_context_judge_ask_parses_and_caches(monkeypatch, tmp_path):
    monkeypatch.setenv("GLM_API_KEY", "fake-key")
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(json.loads(req.data.decode("utf-8")))
        return _ok_response("校")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    judge = LLMContextJudge("glm", cache_path=tmp_path / "cache.json")

    ans1 = judge.ask("item-1", "随便一个 prompt")
    assert ans1.parsed_char == "校" and ans1.parse_ok and not ans1.cached
    assert len(calls) == 1
    assert calls[0]["model"] == "glm-4-plus"
    assert calls[0]["messages"][0]["content"] == "随便一个 prompt"

    # 同一 prompt 第二次：缓存命中，不再发请求
    ans2 = judge.ask("item-1", "随便一个 prompt")
    assert ans2.parsed_char == "校" and ans2.cached
    assert len(calls) == 1

    # 缓存落了盘，换一个 judge 实例也能读到
    judge2 = LLMContextJudge("glm", cache_path=tmp_path / "cache.json")
    ans3 = judge2.ask("item-1", "随便一个 prompt")
    assert ans3.cached and ans3.parsed_char == "校"


def test_llm_context_judge_different_prompts_not_conflated(monkeypatch, tmp_path):
    monkeypatch.setenv("GLM_API_KEY", "fake-key")

    def fake_urlopen(req, timeout=None):
        body = json.loads(req.data.decode("utf-8"))
        char = "甲" if "A" in body["messages"][0]["content"] else "乙"
        return _ok_response(char)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    judge = LLMContextJudge("glm", cache_path=tmp_path / "cache.json")
    assert judge.ask("a", "prompt A").parsed_char == "甲"
    assert judge.ask("b", "prompt B").parsed_char == "乙"


def test_llm_context_judge_retries_then_succeeds(monkeypatch, tmp_path):
    import urllib.error

    monkeypatch.setenv("DASHSCOPE_API_KEY", "fake-key")
    monkeypatch.setattr("time.sleep", lambda *_: None)  # 别真的睡
    attempts = {"n": 0}

    def flaky_urlopen(req, timeout=None):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise urllib.error.URLError("boom")
        return _ok_response("類")

    monkeypatch.setattr("urllib.request.urlopen", flaky_urlopen)
    judge = LLMContextJudge("qwen", cache_path=tmp_path / "cache.json",
                            max_retries=2)
    ans = judge.ask("item-1", "prompt")
    assert ans.parsed_char == "類"
    assert attempts["n"] == 2


def test_llm_context_judge_gives_up_after_max_retries(monkeypatch, tmp_path):
    import urllib.error

    monkeypatch.setenv("GLM_API_KEY", "fake-key")
    monkeypatch.setattr("time.sleep", lambda *_: None)

    def always_fails(req, timeout=None):
        raise urllib.error.URLError("boom")

    monkeypatch.setattr("urllib.request.urlopen", always_fails)
    judge = LLMContextJudge("glm", cache_path=tmp_path / "cache.json",
                            max_retries=1)
    ans = judge.ask("item-1", "prompt")
    assert ans.parsed_char is None and not ans.parse_ok
    assert ans.error is not None


# ── MockJudge：没 key 也能跑通全链路 ───────────────────────────────────

def test_mock_judge_full_pipeline():
    judge = MockJudge(responder=lambda item_id, prompt: "「校」")
    ans = judge.ask("item-1", "无所谓的 prompt")
    assert ans.provider == "mock"
    assert ans.parsed_char == "校" and ans.parse_ok
    assert judge.calls == ["item-1"]


def test_mock_judge_default_responder_fails_to_parse():
    judge = MockJudge()   # 默认 responder 返回空字符串
    ans = judge.ask("item-1", "prompt")
    assert ans.parsed_char is None and not ans.parse_ok
