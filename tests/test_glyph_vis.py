"""3e 看图大模型 `glyph_vis`（2026-11-28，CV3；接口草案 CV4 审定）：触发、缓存键、离线 ask、在线（打桩）、
收尾 `vis`／`evidence.v`、没开时收尾逐字节不变、`vis_glyph` 事件种类、rekey 脚本。

全部自造数据；大模型一律打桩（假 client），不调任何外部服务，不读真书。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from open_guji_cv.feedback.vis_glyph import KIND, SUBDIR, TARGET_UNIT, VisGlyphStore
from open_guji_cv.groups import vis_img as V
from open_guji_cv.products.kinds.read import NearMethodOut, NearRec, VisRec
from open_guji_cv.steps import glyph_vis as GV
from open_guji_cv.steps.glyph_analyzer import merge_cell
from open_guji_cv.steps.glyph_vis import GlyphVisParams, cell_trigger, group_marks

from helpers import make_book, make_ctx, page_chars, page_match, run_steps, write_product

ZY = {"chars": ["于", "千", "子", "干"]}
GONG = {"chars": ["宫", "宮", "官"], "fold": {"宮": "宫"}}
P = GlyphVisParams(skip_half=False)


def _rec(**kw):
    return page_match(recs=[{"slot": 1, "verdict": "unsure", **kw}]).columns[0].chars[0]


def _nr(group="zy", methods=(), cid="tbook:1:1:1"):
    return NearRec(id=cid, slot=1, group=group, trigger="cands", methods=list(methods))


def _mo(name, sims=None, **ev):
    return NearMethodOut(method=name, sims=sims or {}, evidence=ev)


# ── 缺省、提示词、键 ─────────────────────────────────────────────────

def test_default_groups_are_live_vis_groups():
    from open_guji_cv.groups.registry import VIS_GROUPS
    assert tuple(GlyphVisParams().groups) == VIS_GROUPS
    assert GlyphVisParams().enabled is False and GlyphVisParams().model == ""


def test_bad_params_rejected():
    with pytest.raises(ValueError):
        GlyphVisParams(prompt="nope")
    with pytest.raises(ValueError):
        GlyphVisParams(patch="bin")
    with pytest.raises(ValueError):
        GlyphVisParams(groups="zy")


def test_prompt_is_image_and_candidates_only():
    sys_, _ = V.PROMPTS["vis-img-1"]
    assert "四庫" not in sys_ and "殿本" not in sys_ and "前后文" not in sys_
    content = V.user_content(np.full((30, 20), 255, np.uint8), ["千", "于", "于", V.OTHER], "vis-img-1")
    assert [b["type"] for b in content] == ["image", "text"]
    assert content[1]["text"] == "候选字：于、千、其他"                      # 码位排序、去重、其他只在末尾一次


def test_img_sha_includes_shape():
    a = np.zeros((4, 6), np.uint8)
    assert V.img_sha(a) != V.img_sha(a.reshape(6, 4))
    assert V.img_sha(a) == V.img_sha(np.zeros((4, 6), np.uint8))
    assert V.img_sha(np.dstack([a, a, a])) == V.img_sha(a)                 # 三通道先转灰度
    assert len(V.prompt_sha("vis-img-1")) == 16


# ── 触发 ─────────────────────────────────────────────────────────────

def test_marks_abstain_split_margin():
    r = _rec(candidates=[("于", 0.9), ("言", 0.5)])
    assert group_marks(_nr(), r, ZY, P) == ["near_abstain"]                 # 组没挂方法：全弃权
    assert group_marks(_nr(methods=[_mo("rr_shape:zy", char=None)]), r, ZY, P) == ["near_abstain"]
    assert group_marks(_nr(methods=[_mo("x:zy", error="patch_missing")]), r, ZY, P) == ["near_abstain"]
    two = [_mo("rr_shape:zy", char="于"), _mo("book_knn:zy", char="千")]
    assert group_marks(_nr(methods=two), r, ZY, P) == ["near_split"]
    near = [_mo("cnn_small:zy", {"于": 0.55, "千": 0.45})]
    assert group_marks(_nr(methods=near), r, ZY, P) == ["near_margin"]
    far = [_mo("cnn_small:zy", {"于": 0.9, "千": 0.1})]
    assert group_marks(_nr(methods=far), r, ZY, P) == []
    knn = [_mo("book_knn:zy", {"于": 0.5, "千": 0.49}, char="于")]          # 非概率口径：不看分差
    assert group_marks(_nr(methods=knn), r, ZY, P) == []
    assert group_marks(_nr(methods=near), r, ZY, GlyphVisParams(skip_half=False, trig_near_margin=0)) == []


def test_margin_folds_variants():
    r = _rec(candidates=[("宫", 0.9)])
    mo = [_mo("cnn_small:gong", {"宫": 0.8, "宮": 0.8, "官": 0.2})]         # 宮 归 宫，不算两字相持
    assert group_marks(_nr("gong", mo), r, GONG, P) == []


def test_a_margin_needs_both_in_group_and_not_same():
    far = [_mo("cnn_small:zy", {"于": 0.9, "千": 0.1})]
    assert group_marks(_nr(methods=far), _rec(candidates=[("于", 0.90), ("千", 0.89)]), ZY, P) == ["a_margin"]
    assert group_marks(_nr(methods=far), _rec(candidates=[("于", 0.90), ("言", 0.89)]), ZY, P) == []
    assert group_marks(_nr(methods=far), _rec(candidates=[("于", 0.90), ("千", 0.80)]), ZY, P) == []


def test_p_low_uses_first_calibrated_method():
    class Cal:
        def calibrate(self, sims):
            return {"于": 0.6, "千": 0.4}
    far = [_mo("cnn_small:zy", {"于": 0.9, "千": 0.1})]
    r = _rec(candidates=[("于", 0.9)])
    assert group_marks(_nr(methods=far), r, ZY, P, {"cnn_small:zy": Cal()}) == []          # 缺省 trig_p_min=0 不看
    q = GlyphVisParams(skip_half=False, trig_p_min=0.7)
    assert group_marks(_nr(methods=far), r, ZY, q, {"cnn_small:zy": Cal()}) == ["p_low"]


def test_cell_trigger_excludes_same_agreeing_and_unlisted_groups():
    allowed = {"zy"}
    agree = [_mo("rr_shape:zy", char="于")]
    same = _rec(verdict="same", char="于", cov=0.95)
    assert cell_trigger(same, [_nr(methods=agree)], {"zy": ZY}, P, allowed) is None        # 3a 有把握、3b 不反对
    assert cell_trigger(same, [_nr()], {"zy": ZY}, P, allowed) is None                     # 全弃权也不反对
    dis = [_mo("rr_shape:zy", char="千"), _mo("book_knn:zy", char="于")]
    assert cell_trigger(same, [_nr(methods=dis)], {"zy": ZY}, P, allowed)["trigger"] == ["near_split"]   # 有方法反对：照常看记号
    r = _rec(candidates=[("于", 0.9), ("言", 0.5)])
    assert cell_trigger(r, [_nr("gong")], {"gong": GONG}, P, allowed) is None              # 组不在 groups 里


def test_cell_trigger_candidates_and_multi_group():
    r = _rec(candidates=[("于", 0.9), ("言", 0.5), ("文", 0.4)])
    t = cell_trigger(r, [_nr("zy"), _nr("yz", [_mo("rr_shape:yz", char="予")])],
                     {"zy": ZY, "yz": {"chars": ["予", "子"]}}, GlyphVisParams(skip_half=False, cand_topk=2), {"zy", "yz"})
    assert t["group"] == "zy" and t["groups"] == ["zy"] and t["trigger"] == ["near_abstain"]   # yz 方法有字、不触发
    assert t["cands"] == V.sort_cands(["于", "千", "子", "干", "言"])                         # 组字 ∪ 3a 前 2 名
    t2 = cell_trigger(r, [_nr("zy"), _nr("yz")], {"zy": ZY, "yz": {"chars": ["予", "子"]}}, P, {"zy", "yz"})
    assert t2["group"] == "yz" and t2["groups"] == ["yz", "zy"] and "予" in t2["cands"]


def test_guard_group_only_when_guard_on():
    r = _rec(candidates=[("己", 0.9), ("已", 0.89)])
    g = [_nr("_guard", [_mo("near_knn:_guard", char="已")])]
    assert cell_trigger(r, g, {"_guard": {}}, P, set(P.groups)) is None
    # 一个方法给了字：不弃权、不分歧；近邻分不是概率口径 → 没有记号
    assert cell_trigger(r, g, {"_guard": {}}, P, set(P.groups) | {"_guard"}) is None
    g2 = [_nr("_guard")]
    t = cell_trigger(r, g2, {"_guard": {}}, P, {"_guard"})
    assert t["trigger"] == ["near_abstain"] and t["cands"] == V.sort_cands(["已", "己"])


# ── 管线：离线、缓存、在线（打桩） ─────────────────────────────────────

class FakeClient:
    def __init__(self, ans=None, err=None):
        self.ans, self.err, self.calls = ans, err, []

    def ask(self, system, user, members, model, effort):
        self.calls.append({"system": system, "user": user, "members": list(members), "model": model, "effort": effort})
        if self.err:
            return None, {"in": 10}, self.err
        return dict(self.ans), {"in": 100, "out": 20, "model": "served"}, None


def _patch(seed):
    g = np.full((40, 36), 255, np.uint8)
    g[5 + seed:30, 10:20 + seed] = 0
    return g


@pytest.fixture
def fb(tmp_path, monkeypatch):
    d = tmp_path / "feedback"
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(d))
    return d


def _page(tmp_path, vis_params: dict, *, near: dict | None = None, slots=(1, 2, 3), missing=(), analyzer=True):
    """一页：格 1 3b 全弃权、格 2 3b 两法分歧、格 3（夹注 a 半格）3b 全弃权；3a 都是于／千相持。"""
    from open_guji_cv.products.kinds.read import ColumnNear, PageNear
    params = {"glyph_near": {"groups": {"zy": ZY}}, "glyph_vis": {"enabled": True, **vis_params}}
    if analyzer:
        params["glyph_analyzer"] = {"enabled": True}
    book = make_book("tbook", params=params)
    ctx = make_ctx(tmp_path, book)
    recs = [{"slot": s, "verdict": "unsure", "candidates": [("于", 0.90), ("千", 0.80)]} for s in slots]
    write_product(ctx, "glyph_match", 1, glyph_match=page_match(recs=recs))
    write_product(ctx, "cell_shrink", 1, char_index=page_chars(recs=[
        {"slot": s, "bbox_page": (30.0, 10.0 + 50 * s, 70.0, 50.0 + 50 * s), "patch_key": f"p0001c01s{s}"} for s in slots]))
    for s in slots:
        if s not in missing:
            ctx.cache.put("tbook", "char_patch", f"p0001c01s{s}", _patch(s))
    near = near or {1: [], 2: [_mo("rr_shape:zy", char="于"), _mo("book_knn:zy", char="千")], 3: []}
    chars = [NearRec(id=f"tbook:1:1:{s}", slot=s, group="zy", trigger="cands", methods=near.get(s, [])) for s in slots]
    write_product(ctx, "glyph_near", 1, glyph_near=PageNear(page=1, columns=[ColumnNear(col=1, chars=chars)]))
    return ctx


def test_offline_pending_with_ask(tmp_path, fb):
    ctx = _page(tmp_path, {"skip_half": False})
    out = run_steps(ctx, 1, ["glyph_vis"])["glyph_vis"]
    by = out.by_id()
    assert list(by) == ["tbook:1:1:1", "tbook:1:1:2", "tbook:1:1:3"]
    a = by["tbook:1:1:1"]
    assert a.status == "pending" and a.trigger == ["near_abstain"] and a.group == "zy"
    assert a.ask == {"img_sha": V.img_sha(_patch(1)), "prompt": "vis-img-1", "prompt_sha": V.prompt_sha("vis-img-1"),
                     "cands": V.sort_cands(["于", "千", "子", "干"]), "model": ""}
    assert by["tbook:1:1:2"].trigger == ["near_split"]
    assert out.usage == {"pending": 3} and out.cache_pin == "" and out.model == "glyph-vis/0"
    assert not (fb / SUBDIR).exists()                                          # 离线不写缓存


def test_model_set_but_offline_still_pending(tmp_path, fb, monkeypatch):
    monkeypatch.delenv("GUJI_LLM_ONLINE", raising=False)
    ctx = _page(tmp_path, {"skip_half": False, "model": "cfg-model"})
    by = run_steps(ctx, 1, ["glyph_vis"])["glyph_vis"].by_id()
    assert {v.status for v in by.values()} == {"pending"} and by["tbook:1:1:1"].ask["model"] == "cfg-model"


def test_cap_skip_half_patch_missing(tmp_path, fb):
    ctx = _page(tmp_path, {"skip_half": True, "max_per_page": 1}, slots=(1, 2, 4), missing=(4,),
                near={1: [_mo("rr_shape:zy", char="于"), _mo("book_knn:zy", char="千")], 2: [], 4: []})
    by = run_steps(ctx, 1, ["glyph_vis"])["glyph_vis"].by_id()
    assert by["tbook:1:1:2"].status == "pending"                               # near_abstain 排前，占了唯一名额
    assert by["tbook:1:1:1"].status == "skipped:cap"
    assert by["tbook:1:1:4"].status == "skipped:patch_missing" and "p0001c01s4" in by["tbook:1:1:4"].why
    # 夹注半格
    from open_guji_cv.products.kinds.read import PageVis  # noqa: F401
    rec = _rec(candidates=[("于", 0.9)])
    rec.sub = "a"
    assert cell_trigger(rec, [_nr()], {"zy": ZY}, P, {"zy"}) is not None      # 触发照算，跳不跳在 run_page


def test_skip_half_follows_seed_admit(tmp_path, fb):
    from open_guji_cv.core.step import STEPS
    book = make_book("tbook", params={"glyph_vis": {"enabled": True}, "seed_admit": {"group_flow_llm_skip_half": True}})
    ctx = make_ctx(tmp_path, book)
    assert ctx.params_for(STEPS["glyph_vis"]).skip_half is True
    ctx2 = make_ctx(tmp_path / "b", make_book("tbook", params={"glyph_vis": {"enabled": True}}))
    assert ctx2.params_for(STEPS["glyph_vis"]).skip_half is False


def test_star_groups_expand_to_book_near_groups(tmp_path):
    from open_guji_cv.core.step import STEPS
    book = make_book("tbook", params={"glyph_near": {"groups": {"zy": ZY, "gong": GONG}},
                                      "glyph_vis": {"enabled": True, "groups": "*", "skip_half": False}})
    assert make_ctx(tmp_path, book).params_for(STEPS["glyph_vis"]).groups == ["gong", "zy"]


def _seed(fb, slot, *, cands=("于", "千", "子", "干"), model="cfg-model", char="千", conf="high", legacy=False):
    st = VisGlyphStore(fb)
    st.put(img_sha=V.img_sha(_patch(slot)), img_shape=(40, 36), patch="char_patch", prompt="vis-img-1",
           prompt_sha="old" if legacy else V.prompt_sha("vis-img-1"), cands=cands, char=char, conf=conf, why="横短",
           model=model, cell=f"tbook:1:1:{slot}", legacy=legacy)
    return st


def test_cache_hit_needs_same_cands_and_model(tmp_path, fb):
    _seed(fb, 1)                                              # 命中
    _seed(fb, 2, cands=("于", "千"))                           # 候选集合不同
    _seed(fb, 3, model="other-model")                         # 模型不同
    by = run_steps(_page(tmp_path, {"skip_half": False, "model": "cfg-model"}), 1, ["glyph_vis"])["glyph_vis"].by_id()
    a = by["tbook:1:1:1"]
    assert (a.status, a.char, a.conf, a.cache_hit, a.model) == ("hit", "千", "high", True, "cfg-model")
    assert by["tbook:1:1:2"].status == "pending" and by["tbook:1:1:3"].status == "pending"


def test_accept_models_and_empty_model_reads_only_accepted(tmp_path, fb):
    _seed(fb, 1, model="session:A24")
    by = run_steps(_page(tmp_path, {"skip_half": False}), 1, ["glyph_vis"])["glyph_vis"].by_id()
    assert by["tbook:1:1:1"].status == "pending"                               # 缺省不混对话判
    by = run_steps(_page(tmp_path / "b", {"skip_half": False, "accept_models": ["session:A24"]}), 1,
                   ["glyph_vis"])["glyph_vis"].by_id()
    assert by["tbook:1:1:1"].status == "hit" and by["tbook:1:1:1"].model == "session:A24"


def test_legacy_off_by_default(tmp_path, fb):
    _seed(fb, 1, legacy=True, model="old-model", char="于")
    by = run_steps(_page(tmp_path, {"skip_half": False}), 1, ["glyph_vis"])["glyph_vis"].by_id()
    assert by["tbook:1:1:1"].status == "pending"
    by = run_steps(_page(tmp_path / "b", {"skip_half": False, "accept_legacy": True}), 1, ["glyph_vis"])["glyph_vis"].by_id()
    a = by["tbook:1:1:1"]
    assert (a.status, a.legacy, a.char, a.prompt_sha) == ("hit", True, "于", "old")


def test_cache_pin_recorded(tmp_path, fb):
    _seed(fb, 1)
    out = run_steps(_page(tmp_path, {"skip_half": False}), 1, ["glyph_vis"])["glyph_vis"]
    pin = out.cache_pin
    assert pin and pin == VisGlyphStore(fb).cache_pin()
    _seed(fb, 2)
    assert VisGlyphStore(fb).cache_pin() != pin


def test_online_asks_writes_cache_then_hits(tmp_path, fb, monkeypatch):
    fake = FakeClient({"char": "千", "conf": "high", "why": "竖笔出头"})
    monkeypatch.setattr(GV, "_client", lambda: fake)
    out = run_steps(_page(tmp_path, {"skip_half": False, "model": "cfg-model", "effort": "low"}), 1, ["glyph_vis"])["glyph_vis"]
    by = out.by_id()
    assert {v.status for v in by.values()} == {"asked"} and len(fake.calls) == 3
    c = fake.calls[0]
    assert c["model"] == "cfg-model" and c["effort"] == "low" and c["members"] == V.sort_cands(ZY["chars"])
    assert c["user"][0]["type"] == "image" and "前文" not in c["user"][1]["text"]
    assert out.usage == {"calls": 3, "in": 300, "out": 60}
    rows = [json.loads(x) for f in sorted((fb / SUBDIR).glob("*.jsonl")) for x in f.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 3 and {r["kind"] for r in rows} == {KIND}
    r0 = rows[0]
    assert r0["actor"] == "model" and r0["target"]["unit"] == TARGET_UNIT and r0["target"]["key"] == r0["payload"]["img_sha"]
    assert r0["target"]["book"] is None and r0["payload"]["model"] == "cfg-model"          # 写配置值，不写服务端回的型号
    assert r0["payload"]["cell"].startswith("tbook:1:1:") and r0["payload"]["legacy"] is False
    assert not (fb / "rulings").exists() and not (fb / "events").exists()
    fake.calls.clear()
    by = run_steps(_page(tmp_path / "b", {"skip_half": False, "model": "cfg-model"}), 1, ["glyph_vis"])["glyph_vis"].by_id()
    assert {v.status for v in by.values()} == {"hit"} and fake.calls == []


def test_online_error_and_bad_answer_not_cached(tmp_path, fb, monkeypatch):
    monkeypatch.setattr(GV, "_client", lambda: FakeClient(err="refusal"))
    by = run_steps(_page(tmp_path, {"skip_half": False, "model": "m"}), 1, ["glyph_vis"])["glyph_vis"].by_id()
    assert {(v.status, v.why) for v in by.values()} == {("error", "refusal")}
    monkeypatch.setattr(GV, "_client", lambda: FakeClient({"char": "言", "conf": "high", "why": ""}))   # 不在候选里
    by = run_steps(_page(tmp_path / "b", {"skip_half": False, "model": "m"}), 1, ["glyph_vis"])["glyph_vis"].by_id()
    assert {(v.status, v.why) for v in by.values()} == {("error", "bad_answer")}
    assert not (fb / SUBDIR).exists()


def test_online_other_is_cached_as_abstain(tmp_path, fb, monkeypatch):
    monkeypatch.setattr(GV, "_client", lambda: FakeClient({"char": V.OTHER, "conf": "low", "why": "残"}))
    by = run_steps(_page(tmp_path, {"skip_half": False, "model": "m"}), 1, ["glyph_vis"])["glyph_vis"].by_id()
    assert by["tbook:1:1:1"].other and by["tbook:1:1:1"].char is None
    p = VisGlyphStore(fb).lookup(V.img_sha(_patch(1)), V.prompt_sha("vis-img-1"), ZY["chars"], ["m"])
    assert p["other"] is True and p["char"] is None


# ── 收尾 ─────────────────────────────────────────────────────────────

def _vrec(**kw):
    base = dict(id="tbook:1:1:1", slot=1, group="zy", trigger=["near_split"], cands=["于", "千"], img_sha="abc",
                status="hit", char="千", conf="high", why="w", model="m", prompt_sha="ps", cache_hit=True)
    return VisRec(**{**base, **kw})


def test_merge_cell_vis_and_evidence_v_no_p():
    m = _rec(candidates=[("于", 0.9), ("千", 0.8)])
    base = merge_cell(m, None, {}, 5, "elastic")
    got = merge_cell(m, None, {}, 5, "elastic", vis_rec=_vrec())
    assert [c.char for c in got.cands] == [c.char for c in base.cands]           # 排序不变
    assert all(c.p is None for c in got.cands) and got.p_src == base.p_src == ""
    by = {c.char: c for c in got.cands}
    assert by["千"].evidence["v"] == {"conf": "high", "model": "m", "prompt_sha": "ps", "cache_hit": True, "legacy": False}
    assert "v" not in by["于"].evidence
    assert got.vis == {"group": "zy", "trigger": ["near_split"], "status": "hit", "char": "千", "other": False, "conf": "high",
                       "why": "w", "model": "m", "prompt_sha": "ps", "cache_hit": True, "legacy": False, "img_sha": "abc"}


def test_merge_cell_vis_char_not_in_cands_appended_last():
    got = merge_cell(_rec(candidates=[("于", 0.9)]), None, {}, 5, "elastic", vis_rec=_vrec(char="干", groups=["yz", "zy"]))
    assert [c.char for c in got.cands] == ["于", "干"] and got.cands[1].p is None and "v" in got.cands[1].evidence
    assert got.vis["groups"] == ["yz", "zy"]


@pytest.mark.parametrize("kw", [{"char": None, "other": True}, {"status": "pending", "char": None, "conf": None},
                                {"status": "skipped:cap", "char": None}])
def test_merge_cell_other_pending_only_in_vis(kw):
    got = merge_cell(_rec(candidates=[("于", 0.9), ("千", 0.8)]), None, {}, 5, "elastic", vis_rec=_vrec(**kw))
    assert all("v" not in c.evidence for c in got.cands) and got.vis["status"] == kw.get("status", "hit")


def test_merge_cell_keeps_near_p():
    class Cal:
        merge: dict = {}

        def calibrate(self, sims):
            return {"于": 0.7, "千": 0.3}
    nr = _nr(methods=[_mo("cnn_small:zy", {"于": 0.7, "千": 0.3})])
    m = _rec(candidates=[("于", 0.9), ("千", 0.8)])
    a = merge_cell(m, [nr], {"cnn_small:zy": Cal()}, 5, "elastic")
    b = merge_cell(m, [nr], {"cnn_small:zy": Cal()}, 5, "elastic", vis_rec=_vrec())
    assert [(c.char, c.p) for c in a.cands] == [(c.char, c.p) for c in b.cands] and a.p_src == b.p_src


#: 加 3e 之前（origin/dev 5910584e）的 `merge_cell` 在下面这格上的输出，逐字节冻结：没开 3e 时收尾产物必须与它相同
#: （B3 11-28 起 `evidence.b` 不再记 group，冻结串同步去掉；其余逐字节不变）
_FROZEN = ('{"id":"tbook:1:1:1","slot":1,"sub":null,"cands":[{"char":"于","p":0.7,"evidence":{"a":{"sim":0.9,"algo":"elastic"},'
           '"b":{"cnn_small:zy":0.7}}},{"char":"千","p":0.3,"evidence":{"a":{"sim":0.8,"algo":"elastic"},'
           '"b":{"cnn_small:zy":0.3}}},{"char":"言","p":null,"evidence":{"a":{"sim":0.5,"algo":"elastic"}}}],'
           '"p_map":{},"p_src":"near:cnn_small:zy","near":{"zy":{"trigger":"cands","methods":{"cnn_small":{"method":"cnn_small",'
           '"fold":"fold1","model":"m1"}},"p":{"于":0.7,"千":0.3},"p_src":"near:cnn_small:zy"}}}')


def test_merge_cell_without_vis_byte_identical_to_before():
    class Cal:
        merge: dict = {}

        def calibrate(self, sims):
            return {"于": 0.7, "千": 0.3}
    nr = _nr(methods=[_mo("cnn_small:zy", {"于": 0.7, "千": 0.3}, fold="fold1")])
    m = _rec(candidates=[("于", 0.9), ("千", 0.8), ("言", 0.5)])
    got = merge_cell(m, [nr], {"cnn_small:zy": Cal()}, 5, "elastic", near_models={"cnn_small:zy": "m1"})
    assert got.model_dump_json() == _FROZEN


def test_analyzer_end_to_end_reads_glyph_vis(tmp_path, fb):
    _seed(fb, 1)
    ctx = _page(tmp_path, {"skip_half": False, "model": "cfg-model"})
    out = run_steps(ctx, 1, ["glyph_vis", "glyph_analyzer"])
    fin = out["glyph_analyzer"].by_id()
    assert fin["tbook:1:1:1"].vis["status"] == "hit" and fin["tbook:1:1:1"].vis["char"] == "千"
    assert {c.char: c.evidence.get("v") for c in fin["tbook:1:1:1"].cands}["千"]["model"] == "cfg-model"
    assert fin["tbook:1:1:2"].vis["status"] == "pending"


def test_analyzer_without_glyph_vis_has_no_vis_key(tmp_path, fb):
    ctx = _page(tmp_path, {"skip_half": False})
    fin = run_steps(ctx, 1, ["glyph_analyzer"])["glyph_analyzer"]
    s = fin.model_dump_json()
    assert '"vis"' not in s and '"v"' not in s


def test_new_step_off_by_default_and_ordered(tmp_path):
    from open_guji_cv.core.engine import Engine
    from open_guji_cv.core.pipeline import load_pipeline
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore
    pl = load_pipeline("keben_body_v2")
    steps = pl.stages["read"]
    assert steps.index("glyph_near") < steps.index("glyph_vis") < steps.index("glyph_analyzer") == len(steps) - 1
    e = Engine(make_book(), pl, store=ProductStore(tmp_path / "p"), cache=ImageCache(tmp_path / "c"), log=lambda s: None)
    assert "glyph_vis" not in e._enabled(pl.steps)


# ── 事件种类 ─────────────────────────────────────────────────────────

def test_vis_glyph_kind_not_pin_gate_exempt_not_in_ruling_index(tmp_path):
    from open_guji_cv.core.event_files import GATE_EXEMPT_KINDS
    from open_guji_cv.feedback.events import EventTarget, counts_as_pin, event_level, make_event
    from open_guji_cv.feedback.rulings import RulingStore
    ev = make_event("b", 1, "vis_glyph", EventTarget(step="glyph_vis", unit=TARGET_UNIT, key="abc"),
                    {"source": "llm", "char": "千"}, actor="model")
    assert ev.kind == "vis_glyph" and event_level(ev) is None and not counts_as_pin(ev)
    assert "vis_glyph" in GATE_EXEMPT_KINDS
    st = _seed(tmp_path, 1)
    assert st.dir == tmp_path / SUBDIR and any(st.dir.glob("*.jsonl"))
    assert RulingStore(tmp_path)._load() == {}                                 # 裁定库不读、也不在 rulings/ 里


# ── rekey 脚本 ───────────────────────────────────────────────────────

def _rekey_mod():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("rekey_vis1", root / "scripts" / "rekey_vis1_to_glyph_vis.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _vis1_event(seq, cell, patch, **kw):
    import hashlib

    from open_guji_cv.feedback.events import EventTarget, make_event
    ver = "vis1:" + hashlib.sha1(np.ascontiguousarray(patch).tobytes()).hexdigest()[:12]
    p = {"source": "llm", "group": "zy", "char": "千", "other": False, "conf": "high", "why": "图文皆千", "model": "old-m",
         "prompt_ver": ver, "cell": cell, "tok": {}, "ctx": {"left": "", "right": "", "hash": "h"}, **kw}
    return make_event("llm-ctx-x", seq, "ctx_ruling", EventTarget(step="seed_admit", unit="cell", key=cell or "ctx:h"),
                      p, actor="model")


def test_rekey_matches_current_patch_only(tmp_path):
    m = _rekey_mod()
    same, moved = _patch(1), _patch(2)
    evs = [_vis1_event(1, "tbook:1:1:1", same), _vis1_event(2, "tbook:1:1:2", same),   # 格 2 现在是别的图
           _vis1_event(3, None, same), _vis1_event(4, "tbook:1:1:9", same)]
    cur = {1: same, 2: moved}
    patch_of = lambda b, pg, c, s, sub: cur.get(s)                               # noqa: E731
    st = VisGlyphStore(tmp_path)
    rep = m.rekey(evs, patch_of, st, write=False)
    assert rep == {"total": 4, "matched": 1, "written": 0, "already": 0, "no_cell": 1, "no_patch": 1, "changed": 1}
    assert not st.dir.exists()                                                  # dry-run 不写
    rep = m.rekey(evs, patch_of, st, write=True)
    assert rep["written"] == 1
    p = VisGlyphStore(tmp_path).lookup_legacy(V.img_sha(same))
    assert p["legacy"] is True and p["prompt"] == "vis1-legacy" and p["model"] == "old-m" and p["char"] == "千"
    assert p["source_event"] == evs[0].id and p["cell"] == "tbook:1:1:1" and "于" in p["cands"]
    assert VisGlyphStore(tmp_path).lookup(V.img_sha(same), p["prompt_sha"], p["cands"], ["old-m"]) is None   # 不进常规索引
    rep = m.rekey(evs, patch_of, VisGlyphStore(tmp_path), write=True)
    assert rep["written"] == 0 and rep["already"] == 1                          # 可重复跑


def test_rekey_parse_cell():
    m = _rekey_mod()
    assert m.parse_cell("vol35:152:2:4") == ("vol35", 152, 2, 4, None)
    assert m.parse_cell("vol35:152:2:4a") == ("vol35", 152, 2, 4, "a")
    assert m.parse_cell("ctx:abc") is None and m.parse_cell(None) is None
