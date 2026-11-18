"""形近字对的按书分类器（`groups.pair_clf`，5a.3）：建档、定字条件、归文意、配置与指纹。数据自己造。"""
import json

import numpy as np
import pytest

from open_guji_cv.groups import pair_clf as PC
from open_guji_cv.steps import glyph_stages as GS


def _data(n_a, n_b, sep, seed=0, dim=16):
    """两形各一团高斯点，中心沿第一维隔开 `sep`；返回 (X 归一, y, fold)。"""
    r = np.random.default_rng(seed)
    X = r.normal(0, 0.15, (n_a + n_b, dim))
    X[:, 1] += 1.0
    X[n_a:, 0] += sep
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    y = np.arange(n_a + n_b) >= n_a
    return X, y, r.integers(0, 3, n_a + n_b)


def test_tiers_follow_exemplar_counts():
    X, y, f = _data(60, 0, 2.0)
    assert PC.build_pair("甲", "乙", X, y, f)["tier"] == 0
    X, y, f = _data(60, 2, 2.0)
    p = PC.build_pair("甲", "乙", X, y, f)
    assert p["tier"] == 1 and len(p["w"]) == X.shape[1]
    X, y, f = _data(8, 8, 2.0)                      # 够训、留出给字不到 30 → 档 2
    assert PC.build_pair("甲", "乙", X, y, f)["tier"] == 2
    X, y, f = _data(80, 60, 2.0)
    p = PC.build_pair("甲", "乙", X, y, f)
    assert p["tier"] == 3 and p["held"]["err"] == 0 and p["held"]["give"] >= PC.FINAL_MIN_GIVE


def test_inseparable_pair_goes_to_context():
    X, y, f = _data(80, 80, 0.05)                   # 两团几乎重合：刻例够了仍分不开
    p = PC.build_pair("甲", "乙", X, y, f)
    assert p["tier"] == "context"


def _model(tmp_path, pairs, context=(), name="pair_clf.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"version": 1, "pairs": pairs, "context": list(context)}, ensure_ascii=False), encoding="utf-8")
    return path


def test_decide_final_needs_switch_tier3_and_agreement(tmp_path):
    X, y, f = _data(80, 60, 2.0)
    rec3 = PC.build_pair("甲", "乙", X, y, f)
    rec2 = {**rec3, "a": "甲", "b": "丙", "tier": 2}
    m = PC.load(_model(tmp_path, {"甲乙": rec3, "甲丙": rec2}, context=["甲丁"]))
    xa, xb = X[0], X[-1]
    rows, char, key = PC.decide(m, "乙", xb, final=True)
    assert char == "乙" and key == PC.pair_key("甲", "乙") and rows[0]["tier"] == 3 and rows[0]["p"] > 0.98
    assert PC.decide(m, "乙", xa, final=True)[1] == "甲"                     # 首位字是乙、刻形是甲：改成甲
    assert PC.decide(m, "乙", xb, final=False)[1] is None                    # 开关没开：只出证据
    assert PC.decide(m, "丙", xb, final=True)[1] is None                     # 只有档 2 的对：不终判
    rows, char, _ = PC.decide(m, "甲", xa, final=True)                       # 甲还牵着档 2 的甲丙、归文意的甲丁：不定
    assert char is None and {"pair": PC.pair_key("甲", "丁"), "tier": "context"} in rows and len(rows) == 3
    assert PC.decide(m, "戊", xb, final=True) == ([], None, None)            # 文件里没有的字：不出证据
    m0 = PC.load(_model(tmp_path, {"甲乙": rec3, "甲丙": {"a": "甲", "b": "丙", "tier": 0, "w": []}}, name="m0.json"))
    assert PC.decide(m0, "甲", xa, final=True)[1] == "甲"                    # 档 0 的对不拦
    rec2b = {**rec3, "tier": 2, "p_min": 0.9999999}
    assert PC.decide(PC.load(_model(tmp_path, {"甲乙": rec3, "甲丙": {**rec2b, "b": "丙"}}, name="m2.json")), "甲", xa, final=True)[1] is None   # 有分类器的对没给字：拦
    mid = (X[~y].mean(0) + X[y].mean(0)) / 2                                  # 两形中间的格：把握不够，不给字
    assert "char" not in PC.judge(m, PC.pair_key("甲", "乙"), mid / np.linalg.norm(mid))


def test_build_whole_book_and_context_list():
    X, y, f = _data(80, 60, 2.0)
    ids = [f"{'001' if k % 3 == 0 else '002' if k % 3 == 1 else '003'}:1:1:{k}" for k in range(len(y))]
    labels = {"甲乙": {i: ("乙" if t else "甲") for i, t in zip(ids, y)}, "己已": {ids[0]: "己"}, "子孑": {"009:1:1:1": "子"}}
    vol = {"001": 0, "002": 1, "003": 2}
    out = PC.build(labels, dict(zip(ids, X)), lambda i: vol[i.split(":")[0]], context=["己已"])
    assert out["pairs"][PC.pair_key("甲", "乙")]["tier"] == 3
    assert PC.pair_key("己", "已") not in out["pairs"] and out["context"] == [PC.pair_key("己", "已")]
    assert out["pairs"][PC.pair_key("子", "孑")]["tier"] == 0                 # 刻例没有嵌入：占位
    assert PC.tier_counts(out) == {"3": 1, "0": 1}


def test_stages_config_pair_and_fingerprint(tmp_path):
    X, y, f = _data(80, 60, 2.0)
    path = _model(tmp_path, {"甲乙": PC.build_pair("甲", "乙", X, y, f)})
    c = GS.StagesConfig.from_any({"pair": {"model": str(path)}})
    assert c.pair == str(path) and not c.pair_final
    assert GS.StagesConfig.from_any({"pair": {"model": str(path), "final": True}}).pair_final
    assert GS.StagesConfig.from_any({}).pair is None
    with pytest.raises(ValueError):
        GS.StagesConfig.from_any({"pair": {"model": str(path), "nope": 1}})
    with pytest.raises(ValueError):
        GS.StagesConfig.from_any({"pair": {"model": str(tmp_path / "没有.json")}})
    off, on, fin = (GS.stages_fingerprint(v) for v in ({}, {"pair": {"model": str(path)}}, {"pair": {"model": str(path), "final": True}}))
    assert on.startswith(off) and on != off and fin != on                     # 不写 pair 指纹不带这一段


def test_stage_pair_evidence_and_no_model_no_evidence(tmp_path):
    X, y, f = _data(80, 60, 2.0)
    path = _model(tmp_path, {"甲乙": PC.build_pair("甲", "乙", X, y, f)})
    inp = GS.StageInput("b:1:1:1", "甲", (), [("甲", 0.99)], None, X[-1])
    assert GS.stage_pair(inp, GS.StagesConfig(), None) == ({}, None, None)
    ev, char, key = GS.stage_pair(inp, GS.StagesConfig(pair=str(path), pair_final=True), None)
    assert char == "乙" and ev["pair"][0]["lean"] == "乙"
    assert GS.stage_pair(inp, GS.StagesConfig(pair=str(path)), None)[1] is None


def test_apply_unrouted_cell_only_changes_when_final_decides_other_char(tmp_path):
    """5a.1 没拦的格：`final` 关着只留证据、判决不动；开着且刻形不是首位字才改字。"""
    from open_guji_cv.clustering.match import MatchResult
    from open_guji_cv.clustering.near_route import RouteConfig, RouteDecision
    X, y, f = _data(80, 60, 2.0)
    path = _model(tmp_path, {"甲乙": PC.build_pair("甲", "乙", X, y, f)})

    def stages(emb, final):
        s = object.__new__(GS.Stages)
        s.cfg = GS.StagesConfig(RouteConfig(), frozenset(), pair=str(path), pair_final=final)
        s._m = type("M", (), {"_same_cell_rows": lambda self, i: set()})()
        s._net, s._embed, s._pos, s._flow_cfg = None, (lambda net, xs: emb[None]), {}, None
        s._lib_chars = frozenset("甲乙")
        s.router = type("R", (), {"decide": lambda self, q, exclude=(): RouteDecision(None, "甲")})()
        return s

    m, norm = MatchResult("same", "甲", "x", 0.99, 0.0, [("甲", 0.99)]), np.zeros((64, 64), np.float32)
    o = stages(X[-1], False).apply("same", m, norm, norm, "c", None)
    assert o.verdict is None and o.stage["pair"][0]["lean"] == "乙"
    o = stages(X[-1], True).apply("same", m, norm, norm, "c", None)
    assert (o.verdict, o.char, o.via, o.stage["final"], o.stage["top"]) == ("same", "乙", "pair:" + PC.pair_key("甲", "乙"), "5a.3", "甲")
    o = stages(X[0], True).apply("same", m, norm, norm, "c", None)             # 刻形就是首位字：不动判决
    assert o.verdict is None and o.stage["pair"][0]["char"] == "甲"
    s = stages(X[0], True); s.cfg = GS.StagesConfig(RouteConfig(), frozenset())
    assert s.apply("same", m, norm, norm, "c", None) == GS.StageOut()          # 没配 pair：与原来逐字相同
