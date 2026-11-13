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
    monkeypatch.setenv(ctx_llm.ENV_ONLINE, "1")
    monkeypatch.delenv(ctx_llm.ENV_KEY, raising=False)
    assert j(None, None).why == "abstain:no_api_key"


def test_default_offline_records_ask(monkeypatch):
    """缺省不调 API（2026-11-05）：有密钥也不问，弃权 llm_pending 并记下这一问给对话统一审。"""
    monkeypatch.delenv(ctx_llm.ENV_ONLINE, raising=False)
    monkeypatch.setenv(ctx_llm.ENV_KEY, "k")
    ctx_llm._CLIENT.clear()
    v = j(None, None)
    assert v.why == "abstain:llm_pending" and v.extra["ask"] == {"ver": "ry-l2-2", "l": "子", "r": "學而時習之"}
    assert not ctx_llm._CLIENT


def test_ctx_out_keeps_ask():
    """留痕口径 `_ctx_out` 要把 extra.ask 带进 seed_admit 产物，否则 llm_queue 导出恒为空（2026-11-05 史記重放发现）。"""
    from open_guji_cv.groups.methods import _ctx_out
    from open_guji_cv.groups.protocol import GroupVerdict
    ask = {"ver": "ry-l2-2", "l": "子", "r": "學而"}
    out = _ctx_out(GroupVerdict(None, why="abstain:llm_pending", via="ctx_llm", extra={"ask": ask, "llm_model": "m"}))
    assert out.extra["ask"] == ask


def test_key_without_anthropic_abstains(monkeypatch):
    """机器有密钥却没装 anthropic：弃权（不抛 ImportError 拖垮整页）。"""
    import builtins
    real = builtins.__import__

    def no_anthropic(name, *a, **k):
        if name == "anthropic":
            raise ImportError(name)
        return real(name, *a, **k)
    monkeypatch.setenv(ctx_llm.ENV_KEY, "k")
    monkeypatch.setenv(ctx_llm.ENV_ONLINE, "1")
    monkeypatch.setattr(builtins, "__import__", no_anthropic)
    ctx_llm._CLIENT.clear()
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


def test_ruling_cache_roundtrip_and_layout_independent(tmp_path):
    """裁定库当缓存：问过的窗口存成 ctx_ruling 事件（来源 llm、不算人裁），换格号也命中，提示词换版本才重问。"""
    from open_guji_cv.feedback.events import counts_as_human
    from open_guji_cv.feedback.rulings import RulingCache, RulingLog, RulingStore
    fc = FakeClient()
    rc = RulingCache(RulingStore(tmp_path))
    v = j(rc, fc, cell="vol01:1:1:1")
    assert v.char == "曰" and len(fc.calls) == 1
    evs = list(RulingLog(tmp_path).iter_all(raw=True))
    assert len(evs) == 1 and evs[0].kind == "ctx_ruling" and evs[0].actor == "model" and not counts_as_human(evs[0])
    assert evs[0].payload["cell"] == "vol01:1:1:1" and (tmp_path / "rulings").is_dir() and not (tmp_path / "events").exists()
    v = j(RulingCache(RulingStore(tmp_path)), fc, cell="vol99:7:7:7")        # 新进程、换格号
    assert v.char == "曰" and v.extra.get("cached") and len(fc.calls) == 1
    ctx_llm.judge("ry", "提示詞", "ry-l2-3", "子", "學而時習之", frozenset("日曰"), cache=RulingCache(RulingStore(tmp_path)),
                  client=fc)                                                  # 提示词换版本
    assert len(fc.calls) == 2


def test_ruling_abstain_is_recorded(tmp_path):
    from open_guji_cv.feedback.rulings import RulingCache, RulingStore
    fc = FakeClient({"char": "曰", "conf": "low", "why": "不确定"})
    rc = RulingCache(RulingStore(tmp_path))
    assert j(rc, fc).why == "abstain:low_conf"
    assert j(RulingCache(RulingStore(tmp_path)), fc).why == "abstain:low_conf" and len(fc.calls) == 1


def test_ruling_other_is_recorded(tmp_path):
    from open_guji_cv.feedback.rulings import RulingCache, RulingStore
    fc = FakeClient({"char": "其他", "conf": "high", "why": "窠臼"})
    j(RulingCache(RulingStore(tmp_path)), fc)
    v = j(RulingCache(RulingStore(tmp_path)), fc)
    assert v.why == "abstain:other" and v.extra["other_conf"] == "high" and len(fc.calls) == 1


def test_client_missing_anthropic_warns_once(monkeypatch, caplog):
    """有密钥却没装 anthropic：按无密钥弃权，但要大声报一次（2026-10-31，worker 上 1.7 万格静默丢成 no_api_key）。"""
    import logging
    from open_guji_cv.groups import ctx_llm
    monkeypatch.setenv(ctx_llm.ENV_KEY, "k-test-missing-pkg")
    monkeypatch.setenv(ctx_llm.ENV_ONLINE, "1")

    def no_pkg(*a, **k):
        raise ImportError("No module named 'anthropic'")
    monkeypatch.setattr(ctx_llm, "Client", no_pkg)
    ctx_llm._IMPORT_WARNED.discard("k-test-missing-pkg")
    with caplog.at_level(logging.WARNING, logger="open_guji_cv.groups.ctx_llm"):
        assert ctx_llm._client() is None
        assert ctx_llm._client() is None
    assert sum("anthropic" in r.getMessage() for r in caplog.records) == 1


class ModelClient:
    """按模型给答案的假客户端：{模型: (char, conf)}，记每次 (模型, effort)。"""

    def __init__(self, by_model):
        self.by, self.calls = by_model, []

    def ask(self, system, user, members, model, effort):
        self.calls.append((model, effort))
        ch, conf = self.by[model]
        return {"char": ch, "conf": conf, "why": "x"}, {"in": 100, "out": 20, "cache_read": 0, "model": model}, None


PANEL = ("A:high", "B:high")


def jp(client, cache=None, **kw):
    return ctx_llm.judge("ry", "提示词", "ry-l2-2", "子", "學而時習之", frozenset("日曰"), model="M", effort="low",
                         cache=cache, client=client, panel=PANEL, **kw)


def test_panel_confirms_unsure_first_pass():
    """首问 mid → 二审小组两家高 effort 同字（≥mid）→ 给字且 strong；首问的 token 与小组的合并记账。"""
    fc = ModelClient({"M": ("曰", "mid"), "A": ("曰", "high"), "B": ("曰", "mid")})
    v = jp(fc)
    assert v.char == "曰" and v.extra["strong"] and v.extra["panel"] == "char:曰h曰m"
    assert sorted(fc.calls) == sorted([("M", "low"), ("A", "high"), ("B", "high")])
    assert v.extra["tok"]["in"] == 300


def test_panel_split_or_low_keeps_first_pass():
    v = jp(ModelClient({"M": ("曰", "mid"), "A": ("曰", "high"), "B": ("日", "high")}))
    assert v.char is None and v.why == "abstain:low_conf" and v.extra["panel"].startswith("split")
    v = jp(ModelClient({"M": ("曰", "mid"), "A": ("曰", "high"), "B": ("曰", "low")}))
    assert v.char is None and v.extra["panel"].startswith("split")


def test_panel_other_hands_over():
    v = jp(ModelClient({"M": ("其他", "low"), "A": ("其他", "mid"), "B": ("其他", "high")}))
    assert v.char is None and v.why == "abstain:other" and v.extra["other_conf"] == "high"


def test_panel_skipped_when_first_pass_solid_and_agrees_with_ref():
    fc = ModelClient({"M": ("曰", "high"), "A": ("日", "high"), "B": ("日", "high")})
    v = jp(fc, ref="曰")
    assert v.char == "曰" and not v.extra.get("strong") and fc.calls == [("M", "low")]
    # 首问 high 但与整理本不同 → 小组复核；小组推翻首问（同说日）→ 给日，strong
    v = jp(fc, ref="日")
    assert v.char == "日" and v.extra["strong"]


def test_panel_cached_per_member(tmp_path):
    c = ctx_llm.AnswerCache(tmp_path / "ry.jsonl")
    fc = ModelClient({"M": ("曰", "mid"), "A": ("曰", "high"), "B": ("曰", "high")})
    jp(fc, cache=c)
    n = len(fc.calls)
    v = jp(fc, cache=ctx_llm.AnswerCache(tmp_path / "ry.jsonl"))       # 新进程：三条都从缓存取
    assert v.char == "曰" and v.extra["strong"] and len(fc.calls) == n


def test_panel_member_error_falls_back():
    class Err(ModelClient):
        def ask(self, system, user, members, model, effort):
            if model == "B":
                return None, {}, "refusal"
            return super().ask(system, user, members, model, effort)
    v = jp(Err({"M": ("曰", "mid"), "A": ("曰", "high")}))
    assert v.char is None and v.why == "abstain:low_conf" and v.extra["panel"].startswith("fail")


def test_panel_needs_one_high():
    """两家都只有 mid → 不算数（宁可送审）。"""
    v = jp(ModelClient({"M": ("曰", "low"), "A": ("曰", "mid"), "B": ("曰", "mid")}))
    assert v.char is None and v.extra["panel"].startswith("split")


def test_credit_exhausted_gets_own_error_code():
    """额度用完的 400 单独记 api_credit（2026-11-02 r2 整套 llm_api_400 实为没额度）；别的 400 照旧。"""
    from open_guji_cv.groups import ctx_llm
    assert ctx_llm.api_error_code(400, "Error code: 400 - {'message': 'Your credit balance is too low to access the Anthropic API.'}") == "api_credit"
    assert ctx_llm.api_error_code(400, "invalid model") == "api_400"
    assert ctx_llm.api_error_code(401, "") == "api_401"


def test_skip_half_cells_bypass_l3_steps():
    """group_flow_llm_skip_half：夹注 a/b 半格不走 Llm／CtxOnline／二审小组；整格照常。"""
    from types import SimpleNamespace as NS

    from open_guji_cv.groups import methods as M
    inp = lambda cid, on: NS(cfg=NS(l3_skip_half=on), cell_id=cid)           # noqa: E731
    assert M._skip_half(inp("vol06:12:5:12a", True)) and M._skip_half(inp("vol06:12:5:12b", True))
    assert not M._skip_half(inp("vol06:12:5:12", True))
    assert not M._skip_half(inp("vol06:12:5:12a", False))
    from open_guji_cv.steps.seed_admit import SeedAdmitParams
    assert "group_flow_llm_skip_half" not in SeedAdmitParams(db_path="x").model_dump()
    assert SeedAdmitParams(db_path="x", group_flow_llm_skip_half=True).model_dump()["group_flow_llm_skip_half"] is True
    # group_flow_llm_half_groups：这几组的半格不受 skip_half 限制（A24 11-08，SJ 史記 H01 半格要记 L3 问）
    hg = lambda cid, g: NS(cfg=NS(l3_skip_half=True, l3_half_groups=frozenset({"ry", "jys"})), cell_id=cid, group=g)   # noqa: E731
    assert not M._skip_half(hg("01:12:5:12a", "ry")) and M._skip_half(hg("01:12:5:12a", "men"))
    assert "group_flow_llm_half_groups" not in SeedAdmitParams(db_path="x").model_dump()
    assert SeedAdmitParams(db_path="x", group_flow_llm_half_groups=["ry"]).model_dump()["group_flow_llm_half_groups"] == ["ry"]


def test_dt_wyu_sb_have_ids_method_that_abstains_without_bank():
    """大太、王玉、十卜（QTW 全唐文 11-05）声明了 IDS 解法；没有本书模板库时 abstain:no_bank，不改变输出。"""
    from types import SimpleNamespace as NS

    from open_guji_cv.groups import ids_online
    from open_guji_cv.groups.flow import check_groups
    from open_guji_cv.groups.methods import IDS
    from open_guji_cv.groups.registry import FLOW_GROUPS
    check_groups(["dt", "wyu", "sb"])
    for g in ("dt", "wyu", "sb"):
        assert "ids" in FLOW_GROUPS[g].flow.solvers and g in ids_online.SPECS
    v = IDS._run(NS(group="dt_no_such_bank", patch=lambda: None))
    assert v.char is None and v.why == "abstain:no_bank"


def test_ruling_first_overrides_lower_layers(tmp_path, monkeypatch):
    """`FlowConfig.ruling_first`（全唐文 11-13 己已巳按文意＋AI）：本组先查裁定库，命中就照裁定给字（L2 小头让位）；
    没命中照常走各层；不在名单的组不受影响。"""
    from tests.test_groups_ctx_l2 import FakeEnc, head
    monkeypatch.setattr(ctx_l2, "_encoder", lambda n, r: FakeEnc())
    monkeypatch.delenv(ctx_llm.ENV_ONLINE, raising=False)
    _L3C.clear()
    hp = tmp_path / "ry.json"
    hp.write_text(json.dumps(head(thr=0.99), ensure_ascii=False), encoding="utf-8")
    cp = tmp_path / "cache.jsonl"
    ctx_llm.judge("ry", "提示詞", "t", "某乙", "云", frozenset("日曰"), model="m", effort="low",
                  cache=ctx_llm.AnswerCache(cp), client=FakeClient({"char": "日", "conf": "high", "why": "x"}))

    def cfg(first):
        class Cfg:
            l2_tables, l2_models, canon, l2_drift = {}, {"ry": str(hp)}, None, 0
            l3_online = {"ry": {"system": "提示詞", "ver": "t", "cache": str(cp)}}
            l3_model, l3_effort, l3_need_l2_agree = "m", "low", False
            ruling_first = first
        return Cfg()

    chain = Chain("ctx", steps=(CtxRule(), Llm(), CtxModel(), CtxOnline()))

    def run(c, right="云"):
        return chain.run(MethodInput(group="ry", members=frozenset("日曰"), cell_id="v:1:1:1", cands=[], ref=None,
                                     cfg=c, left="某乙", right=right))
    assert run(cfg(frozenset())).char == "曰"                                  # 缺省：L2 小头先给字
    assert run(cfg(frozenset({"jys"}))).char == "曰"                            # 别的组开着不影响
    v = run(cfg(frozenset({"ry"})))
    assert v.char == "日" and v.via == "ctx:ctx_llm" and v.extra["ruling_first"]
    v = run(cfg(frozenset({"ry"})), right="云云")                                # 没有裁定：照常 L2
    assert v.char == "曰" and not v.extra.get("ruling_first")
