# -*- coding: utf-8 -*-
"""第四步 4d `group_decision`（CV4 P3c，2026-11-28）：只出原料；收尾读产物与自己现算逐格相同；GM3 要求的次序／位置不变。自造数据。"""
from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace

import pytest

import open_guji_cv.feedback.lookup as lookup
import open_guji_cv.steps  # noqa: F401
from helpers import make_book, page_align_ref, page_match, patch_seed_admit, write_product
from open_guji_cv.core.step import STEPS, RunContext
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.kinds.chars import CharRec, ColumnChars, PageChars
from open_guji_cv.products.kinds.group_decision import (GroupDecisionRec, MODEL_KEYED, PAIR_KEYED, PageGroupDecision, pack_near)
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps import group_decision as gd
from open_guji_cv.steps import seed_admit_shapes as shapes
from open_guji_cv.steps.seed_admit import SeedAdmitParams

BOOK, PAGE, COL = "tbook", 1, 1


def test_default_off_and_registered():
    spec = STEPS["group_decision"].spec
    assert spec.enabled_by == "enabled" and gd.GroupDecisionParams().enabled is False
    assert spec.produces == ("group_decision",)
    assert "group_decision" in STEPS["char_decide"].spec.optional_consumes
    from open_guji_cv.core.pipeline import load_pipeline
    steps = load_pipeline("keben_body_v2").steps
    assert steps.index("group_decision") < steps.index("char_decide")


def test_seed_fields_exist_and_cover_group_flow():
    fields = set(SeedAdmitParams.model_fields)
    sf = set(gd.seed_fields())
    assert sf <= fields, f"seed_fields 列了不存在的字段：{sf - fields}"
    assert {f for f in fields if f.startswith("group_flow")} <= sf


def test_entry_config_matches_flow_config_on_entry_fields():
    """`entry` 读的 cfg 字段（组、分差、min_cov、joint、provisional、ref_free_groups、tolerate_extra、coord_outside_skip）两个配置必须一致。"""
    from open_guji_cv.steps.seed_admit_groups import _entry_config, _flow_config
    p = SeedAdmitParams(group_flow=("ry", "rm"), group_flow_ref_free=("ry",), group_flow_tolerate_extra={"ry": "目"})
    a, b = _entry_config(p), _flow_config(p, None, 1)
    for k in ("groups", "delta", "min_cov", "joint", "provisional", "ref_free_groups", "tolerate_extra", "coord_outside_skip",
              "ref_alias", "provisional_to", "pv_ref_gap", "pv_ref_cov", "lift_shape_ref", "top1_cov"):
        assert getattr(a, k) == getattr(b, k), k


def test_pack_near_roundtrip_all_key_shapes():
    assert "part_shape" in PAIR_KEYED and {"pair_shape", "book_knn", "near_knn", "stroke_veto"} <= MODEL_KEYED
    ev = {"char": "八", "why": "x", "score": 0.5}
    cases = {"rr_shape": {"a:1:1:2": ev}, "part_shape": {("a:1:1:3", ("剌", "刺")): ev},
             "pair_shape": {("a:1:1:4", "pair_shape=abc"): ev}, "near_knn": {("a:1:1:5", "near_knn=zz"): ev}, "stroke_veto": {("a:1:1:6", "stroke_veto=q"): ev}}
    st = PageGroupDecision(page=1, near={m: pack_near(m, g) for m, g in cases.items()}, ran=[f"near:{m}" for m in cases])
    back = PageGroupDecision.model_validate_json(st.model_dump_json())
    for m, g in cases.items():
        assert back.near_map(m) == g
    assert back.near_map("book_knn") == {}


def test_wh_map_roundtrip():
    st = PageGroupDecision(page=1, wh={"a:1:1:1": [92.0, 100.5]}, ran=["wh"])
    back = PageGroupDecision.model_validate_json(st.model_dump_json())
    assert back.wh_map() == {"a:1:1:1": (92.0, 100.5)}


class _Ctx:
    """只给 `shapes._near_from_3b` 用的假 ctx：group_decision 有就给，glyph_near 一律没有。"""

    def __init__(self, gdp=None):
        self.gdp = gdp

    def product(self, kind, page):
        if kind == "group_decision" and self.gdp is not None:
            return self.gdp
        raise KeyError(kind)


def test_near_readers_prefer_group_decision_snapshot():
    ev = {"char": "鳴", "why": "p", "p": 0.97}
    snap = PageGroupDecision(page=1, ran=["near:wu_shape", "near:book_knn"],
                             near={"wu_shape": pack_near("wu_shape", {"a:1:1:2": ev}),
                                   "book_knn": pack_near("book_knn", {("a:1:1:3", "book_knn=f"): ev})})
    ctx = _Ctx(snap)
    assert shapes._near_from_3b(ctx, 1, "wu_shape", "m.json") == {"a:1:1:2": ev}
    assert shapes._near_by_model_from_3b(ctx, 1, "book_knn") == {("a:1:1:3", "book_knn=f"): ev}
    # 这页没算这个方法／没开 4d／4d 步自己取快照（use_gd=False）：都不读快照，退回读 3b（这里 3b 也没有 → 空）
    assert shapes._near_from_3b(ctx, 1, "rr_shape", "m.json") == {}
    assert shapes._near_from_3b(_Ctx(), 1, "wu_shape", "m.json") == {}
    assert shapes._near_from_3b(ctx, 1, "wu_shape", "m.json", use_gd=False) == {}
    assert shapes._near_by_model_from_3b(ctx, 1, "book_knn", use_gd=False) == {}
    assert shapes._near_from_3b(None, 1, "wu_shape", "m.json") == {}


# ── 端到端：收尾读产物与自己现算逐格相同 ────────────────────────────────────
def _box(slot, w=92, h=100):
    return CharRec(id=f"{BOOK}:{PAGE}:{COL}:{slot}", slot=slot, pos=slot, idx=slot - 1, cell_type="char",
                   bbox_col=(0, 100 * (slot - 1), w, 100 * (slot - 1) + h), bbox_page=(0, 100 * (slot - 1), w, 100 * (slot - 1) + h),
                   height=h, width=w, flags=[])


def _ctx2(tmp_path, monkeypatch, sa_params, gd_params=None):
    products, cache = tmp_path / "products", tmp_path / "cache"
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(products))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(cache))
    monkeypatch.setattr(lookup, "human_chars", lambda book, log=None, stale=None, bind=None, lost=None: {})
    params = {"char_decide": sa_params}
    if gd_params is not None:
        params["group_decision"] = gd_params
    return RunContext(make_book(BOOK), ProductStore(products), ImageCache(cache), params=params, log=lambda s: None)


CHARS = {1: "日", 2: "曰", 3: "山"}


def _fill(ctx):
    recs = [dict(slot=s, verdict="review", cov=0.9, wmax=0.0, char=c, candidates=[(c, 0.95), ("曰" if c == "日" else "日", 0.5)])
            for s, c in CHARS.items()]
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, recs=recs, col=COL))
    write_product(ctx, "align_ref", PAGE, align_ref=page_align_ref(
        PAGE, BOOK, recs=[dict(slot=s, align_char=c) for s, c in CHARS.items()], col=COL))
    boxes = [_box(1, w=80), _box(2, w=110), _box(3)]
    write_product(ctx, "cell_shrink", PAGE, char_index=PageChars(page=PAGE, columns=[
        ColumnChars(col=COL, ok=True, n_instances=len(boxes), chars=boxes)]))


def _cells(page):
    return {r.id: r.model_dump() for cc in page.columns for r in cc.chars}


@pytest.mark.usefixtures("seed_admit_switches_off")
def test_finale_fold_wh_same_with_and_without_group_decision(tmp_path, monkeypatch):
    p = SeedAdmitParams(group_flow=("ry",), fold_groups=("ry",), fold_aspect=(0.85, 1.0), patch_missing="skip")
    seen: dict = {}

    def spy_factory(store):
        from open_guji_cv.steps import seed_admit as sa
        orig = sa._fold_pass

        def spy(*a, **k):
            store["wh"] = k.get("wh")
            return orig(*a, **k)
        return spy

    ctx = _ctx2(tmp_path / "a", monkeypatch, p)
    _fill(ctx)
    inline_seen: dict = {}
    patch_seed_admit(monkeypatch, "_fold_pass", spy_factory(inline_seen))
    inline = STEPS["char_decide"].run_page(ctx, PAGE)["char_decide"]

    ctx2 = _ctx2(tmp_path / "b", monkeypatch, p, gd.GroupDecisionParams(enabled=True))
    _fill(ctx2)
    st = STEPS["group_decision"].run_page(ctx2, PAGE)["group_decision"]
    assert "wh" in st.ran and "entry" in st.ran
    write_product(ctx2, "group_decision", PAGE, group_decision=st)
    via_seen: dict = {}
    patch_seed_admit(monkeypatch, "_fold_pass", spy_factory(via_seen))
    via = STEPS["char_decide"].run_page(ctx2, PAGE)["char_decide"]
    assert _cells(via) == _cells(inline)
    assert (via.n_auto, via.n_review) == (inline.n_auto, inline.n_review)
    assert inline_seen, "夹具要走到 fold 遍"
    if inline_seen:
        assert via_seen["wh"] == inline_seen["wh"]
    by = st.by_id()
    assert by[f"{BOOK}:{PAGE}:{COL}:1"].aspect == {"ry": 80 / 100}
    assert by[f"{BOOK}:{PAGE}:{COL}:2"].aspect == {"ry": 110 / 100}
    assert by[f"{BOOK}:{PAGE}:{COL}:3"].aspect == {"ry": 92 / 100}   # 证据只是比值，窄宽判与门槛在收尾


@pytest.mark.usefixtures("seed_admit_switches_off")
def test_finale_reads_entry_and_aspect_from_group_decision(tmp_path, monkeypatch):
    """A2：4d 产物在时，收尾 group_flow 的待审格入口、fold 的宽高比都读产物；逐格结果与现算相同。"""
    import open_guji_cv.groups.flow as flow
    from open_guji_cv.steps import seed_admit as sa
    p = SeedAdmitParams(group_flow=("ry",), fold_groups=("ry",), fold_aspect=(0.85, 1.0), patch_missing="skip")
    calls = {"entry": 0, "pre": [], "aspect": []}
    orig_entry, orig_gfp, orig_fold = flow.entry, flow.group_flow_pass, sa._fold_pass

    def entry_spy(*a, **k):
        calls["entry"] += 1
        return orig_entry(*a, **k)

    def gfp_spy(*a, **k):
        calls["pre"].append(k.get("pre_entry"))
        return orig_gfp(*a, **k)

    def fold_spy(*a, **k):
        calls["aspect"].append(k.get("aspect"))
        return orig_fold(*a, **k)
    monkeypatch.setattr(flow, "entry", entry_spy)
    monkeypatch.setattr("open_guji_cv.groups.flow.group_flow_pass", gfp_spy)
    patch_seed_admit(monkeypatch, "_fold_pass", fold_spy)

    ctx = _ctx2(tmp_path / "a", monkeypatch, p)
    _fill(ctx)
    inline = STEPS["char_decide"].run_page(ctx, PAGE)["char_decide"]
    n_inline, pre_inline, asp_inline = calls["entry"], list(calls["pre"]), list(calls["aspect"])
    assert pre_inline and all(x is None for x in pre_inline) and all(a is None for a in asp_inline)

    calls.update(entry=0, pre=[], aspect=[])
    ctx2 = _ctx2(tmp_path / "b", monkeypatch, p, gd.GroupDecisionParams(enabled=True))
    _fill(ctx2)
    write_product(ctx2, "group_decision", PAGE, group_decision=STEPS["group_decision"].run_page(ctx2, PAGE)["group_decision"])
    calls["entry"] = 0
    via = STEPS["char_decide"].run_page(ctx2, PAGE)["char_decide"]
    assert _cells(via) == _cells(inline) and (via.n_auto, via.n_review) == (inline.n_auto, inline.n_review)
    assert calls["pre"] and all(isinstance(x, dict) and x for x in calls["pre"])
    assert calls["aspect"] and all(isinstance(a, dict) and a for a in calls["aspect"])
    assert calls["entry"] <= n_inline          # 待审格不再现算入口；放行格的复核入口仍现算


def test_group_flow_pass_pre_entry_only_for_pending_cells():
    """已放行格、人裁格、字组通道格不吃预算入口（它们读最终放行字）；待审格吃。"""
    import open_guji_cv.groups.flow as flow
    cfg = flow.FlowConfig(groups=("ry",), delta=0.1, min_cov=0.0, joint=True)
    mk = lambda i, **k: SimpleNamespace(id=i, char="日", admit=False, channel=None, provenance="", doubts=[], evidence={}, **k)
    pending, admitted = mk("a"), mk("b")
    admitted.admit, admitted.channel = True, "ref"
    seen = []
    orig = flow.entry
    try:
        flow.entry = lambda r, *a, **k: (seen.append(r.id), None)[1]
        flow.group_flow_pass([pending, admitted], {}, lambda i: [("日", 0.9)], lambda r: False, cfg,
                             pre_entry={"a": None, "b": ["ry", "lift"]})
    finally:
        flow.entry = orig
    assert seen == ["b"]                       # a 吃预算（None＝入不了组），b 已放行、现算


@pytest.mark.usefixtures("seed_admit_switches_off")
def test_entry_lift_group_and_switches(tmp_path, monkeypatch):
    p = SeedAdmitParams(group_flow=("ry",))
    ctx = _ctx2(tmp_path, monkeypatch, p, gd.GroupDecisionParams(enabled=True))
    _fill(ctx)
    st = STEPS["group_decision"].run_page(ctx, PAGE)["group_decision"]
    by = st.by_id()
    assert by[f"{BOOK}:{PAGE}:{COL}:3"].lift is None           # 山 不在任何点名的组
    assert st.ran == ["entry"] and st.wh == {} and st.near == {}   # 没开 fold_aspect／3b 方法：只出入口
    off = _ctx2(tmp_path / "o", monkeypatch, SeedAdmitParams(), gd.GroupDecisionParams(enabled=True))
    _fill(off)
    st2 = STEPS["group_decision"].run_page(off, PAGE)["group_decision"]
    assert st2.ran == [] and all(c.lift is None and c.aspect == {} for c in st2.cells)


def test_book_params_fills_seed_digest(tmp_path, monkeypatch):
    ctx = _ctx2(tmp_path, monkeypatch, SeedAdmitParams(group_flow=("ry",)), gd.GroupDecisionParams(enabled=True))
    p = STEPS["group_decision"].book_params(gd.GroupDecisionParams(enabled=True), ctx)
    assert list(p.seed["group_flow"]) == ["ry"] and set(p.seed) == set(gd.seed_fields())
    assert STEPS["group_decision"].book_params(gd.GroupDecisionParams(), ctx).seed == {}


def test_handling_snapshot_resolved_and_in_product(tmp_path, monkeypatch):
    from open_guji_cv.groups import near_registry as nr
    ctx = _ctx2(tmp_path, monkeypatch, SeedAdmitParams(group_flow=("ry",)), gd.GroupDecisionParams(enabled=True))
    _fill(ctx)
    step = STEPS["group_decision"]
    p = step.book_params(gd.GroupDecisionParams(enabled=True), ctx)
    base = nr.handling_of("ry")
    assert p.resolved["ry"] == {**base, "methods": list(base["methods"])}
    # 书级覆盖叠上去；覆盖一变，参数（指纹）就变
    p2 = step.book_params(gd.GroupDecisionParams(enabled=True, handling={"ry": {"aspect": not base["aspect"]}}), ctx)
    assert p2.resolved["ry"]["aspect"] is (not base["aspect"]) and p2.resolved != p.resolved
    # 非法覆盖：methods、不认识的组、坏取值都报错
    for bad in ({"ry": {"methods": ["x"]}}, {"no_such_group": {"aspect": True}}, {"ry": {"action": "zzz"}}):
        with pytest.raises(ValueError):
            step.book_params(gd.GroupDecisionParams(enabled=True, handling=bad), ctx)
    # 关着不解析（不读登记表、不报错）
    assert step.book_params(gd.GroupDecisionParams(handling={"no_such_group": {}}), ctx).resolved == {}


def test_handling_snapshot_written_to_product_and_finale_never_reads_it(tmp_path, monkeypatch):
    ctx = _ctx2(tmp_path, monkeypatch, SeedAdmitParams(group_flow=("ry",)), gd.GroupDecisionParams(enabled=True))
    _fill(ctx)
    step = STEPS["group_decision"]
    ctx.params["group_decision"] = step.book_params(ctx.params["group_decision"], ctx)   # 引擎跑前会做的这一步
    out = step.run_page(ctx, PAGE)["group_decision"]
    assert "ry" in out.handling and out.handling["ry"]["methods"] == list(out.handling["ry"]["methods"])
    import open_guji_cv.steps.seed_admit as sa, open_guji_cv.steps.seed_admit_groups as sg, open_guji_cv.steps.seed_admit_shapes as ss
    for m in (sa, sg, ss):
        assert ".handling" not in inspect.getsource(m), f"{m.__name__} 不该读 handling 快照（本版只记）"


# ── GM3 要的断言：vis_ruling 及其后的次序、vis_ctx／ask／group 的位置不变 ─────────────────
def _calls_in_order(src_func) -> list[str]:
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(src_func)))
    out = [(n.lineno, n.func.id) for n in ast.walk(tree)
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id.startswith("_") and n.func.id.endswith("_pass")]
    return [name for _, name in sorted(out)]


#: `SeedAdmitStep._run_page` 里各遍的调用先后（源码顺序；dev 2aae3bd 即 P3c 之前实测）。P3c 不许挪：`_vis_ruling_pass`（原 5c）及其后各遍
#: 的次序一动，`evidence.vis_ctx` 里记的窗口键就变，manager 终审裁定键直接用它（GM3 要求）。
_ORDER_BEFORE_P3C = [
    "_group_flow_pass", "_group_flow_pass", "_rr_shape_pass", "_wu_shape_pass", "_hou_shape_pass", "_part_shape_pass", "_pair_shape_pass",
    "_pair_shape_pass", "_book_knn_pass", "_near_knn_pass", "_p_ref_pass", "_fold_pass", "_rare_ref_pass", "_shadow_veto_pass",
    "_review_lanes_pass", "_blank_ink_pass", "_header_formula_pass", "_pua_rule_pass", "_follow_ref_pass", "_edge_pair_pass",
    "_ref_lib_coord_pass", "_ref_topk_pass", "_rare_ref_pass", "_rare_ref_sparse_pass", "_solo_5b_pass", "_ref_lib_5b_veto_pass",
    "_pua_code_pass", "_pua_code_admit_pass", "_vis_ruling_pass", "_hou_shape_pass", "_symbol_review_pass", "_symbol_ref_blank_pass",
    "_near_knn_pass", "_consensus_lib_pass", "_stroke_veto_pass", "_pair_form_pass", "_human_unbound_pass", "_evict_review_pass",
    "_jiazhu_uneven_pass", "_seg_box_pass", "_ink_mark_pass"]


def test_pass_order_unchanged():
    from open_guji_cv.steps.seed_admit import SeedAdmitStep
    assert _calls_in_order(SeedAdmitStep._run_page) == _ORDER_BEFORE_P3C


def test_vis_ctx_written_first_in_vis_ruling_loop():
    """`evidence.vis_ctx` 仍由 `_vis_ruling_pass` 在待审格循环开头写（窗口键＝此刻的邻格放行结果），键是 left／right／ref。"""
    from open_guji_cv.steps import seed_admit_groups as g
    tree = ast.parse(inspect.getsource(g._vis_ruling_pass).lstrip())
    keys = [tuple(k.value for k in n.keys if isinstance(k, ast.Constant)) for n in ast.walk(tree) if isinstance(n, ast.Dict)]
    assert ("left", "right", "ref") in keys
    assert any("vis_ctx" in (k.value for k in n.keys if isinstance(k, ast.Constant)) for n in ast.walk(tree) if isinstance(n, ast.Dict))


def test_group_evidence_still_written_by_group_flow():
    """`evidence.group`（id／mode／pick…）仍由 `groups.flow.group_flow_pass` 写进放行记录，后面各遍读它；4d 产物不替代它。"""
    from open_guji_cv.groups import flow
    src = inspect.getsource(flow.group_flow_pass)
    assert '"group": {"id": g, "mode": mode, "pick": ch' in src


def test_group_decision_step_never_mutates_cells():
    """`group_decision` 只出原料：源码里不许出现对放行记录的改动（admit／channel／provenance 赋值）。"""
    src = inspect.getsource(gd)
    for bad in (".admit =", ".channel =", ".provenance =", "_demote("):
        assert bad not in src
