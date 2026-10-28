"""文意 L3 在线（`groups/ctx_llm`）：按窗口内容缓存、只收 high、没密钥弃权、方法数组里只问前面各层都没给字的格。
客户端用假的，不连网。"""
import json

from open_guji_cv.groups import ctx_l2, ctx_llm
from open_guji_cv.groups.methods import Chain, CtxModel, CtxOnline, CtxRule, Llm, MethodInput, _L3C


class FakeClient:
    def __init__(self, ans=None, err=None):
        self.ans, self.err, self.calls = ans or {"char": "曰", "conf": "high", "why": "引語"}, err, []

    def ask(self, system, user, members, model, effort):
        self.calls.append(user)
        return (None if self.err else dict(self.ans)), {"in": 900, "out": 40, "cache_read": 0, "model": model}, self.err


def j(cache, client, left="子", right="學而時習之", **kw):
    return ctx_llm.judge("ry", "提示詞", "ry-l2-2", left, right, frozenset("日曰"), cache=cache, client=client, **kw)


def test_cache_by_window_content(tmp_path):
    ctx_llm.usage_summary(reset=True)
    c = ctx_llm.AnswerCache(tmp_path / "ry.jsonl")
    fc = FakeClient()
    v = j(c, fc)
    assert (v.char, v.via, v.extra["tok"]["in"]) == ("曰", "ctx_llm", 900)
    v = j(ctx_llm.AnswerCache(tmp_path / "ry.jsonl"), fc)          # 新进程读同一个文件：不再问
    assert v.char == "曰" and v.extra.get("cached") and len(fc.calls) == 1
    j(c, fc, right="學而時習")                                       # 窗口变了：重问
    assert len(fc.calls) == 2
    u = ctx_llm.usage_summary()
    assert u["calls"] == 2 and u["hits"] == 1 and u["input_tokens"] == 1800
    assert ctx_llm.cache_usage([tmp_path / "ry.jsonl"])["answers"] == 2


def test_only_high_member():
    assert j(None, FakeClient({"char": "曰", "conf": "mid", "why": ""})).why == "abstain:low_conf"
    v = j(None, FakeClient({"char": "其他", "conf": "high", "why": "窠臼"}))
    assert v.char is None and v.why == "abstain:other" and v.extra["other_conf"] == "high"


def test_errors_not_cached(tmp_path):
    c = ctx_llm.AnswerCache(tmp_path / "ry.jsonl")
    assert j(c, FakeClient(err="refusal")).why == "abstain:llm_refusal"
    assert not (tmp_path / "ry.jsonl").exists()


def test_no_api_key(monkeypatch):
    monkeypatch.delenv(ctx_llm.ENV_KEY, raising=False)
    assert j(None, None).why == "abstain:no_api_key"


def test_chain_asks_only_when_lower_layers_abstain(tmp_path, monkeypatch):
    """L2 模型给了字 → 不问；L2 低于门槛 → 问，L2 首选字记 `l2_top`；开 need_l2_agree 时不同就弃权。"""
    from tests.test_groups_ctx_l2 import FakeEnc, head
    monkeypatch.setattr(ctx_l2, "_encoder", lambda n, r: FakeEnc())
    fc = FakeClient({"char": "日", "conf": "high", "why": "x"})
    monkeypatch.setattr(ctx_llm, "_client", lambda: fc)
    _L3C.clear()

    def cfg(thr, agree=False):
        hp = tmp_path / f"ry{thr}.json"
        hp.write_text(json.dumps(head(thr=thr), ensure_ascii=False), encoding="utf-8")

        class Cfg:
            l2_tables, l2_models, canon, l2_drift = {}, {"ry": str(hp)}, None, 0
            l3_online = {"ry": {"system": "提示詞", "ver": "t", "cache": ""}}
            l3_model, l3_effort, l3_need_l2_agree = "m", "low", agree
        return Cfg()

    chain = Chain("ctx", steps=(CtxRule(), Llm(), CtxModel(), CtxOnline()))

    def run(c):
        return chain.run(MethodInput(group="ry", members=frozenset("日曰"), cell_id="v:1:1:1", cands=[], ref=None,
                                     cfg=c, left="某乙", right="云"))
    v = run(cfg(0.99))
    assert v.char == "曰" and v.via == "ctx:ctx_l2" and not fc.calls
    v = run(cfg(0.999999999999))
    assert v.char == "日" and v.via == "ctx:ctx_llm" and v.extra["l2_top"] == "曰" and len(fc.calls) == 1
    _L3C.clear()
    v = run(cfg(0.999999999999, agree=True))
    assert v.char is None and v.why == "disagree:l2"
