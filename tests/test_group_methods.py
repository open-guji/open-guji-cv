# -*- coding: utf-8 -*-
"""字组方法数组（`groups/methods.py`，sheldon 2026-10-22 定）：八类方法的接口、置信度 0–1、子数组、复合、注册表里的数组。自造数据。"""
from __future__ import annotations

import numpy as np
import pytest

from open_guji_cv.groups import GROUPS
from open_guji_cv.groups import methods as M
from open_guji_cv.groups.flow import FlowConfig, check_groups
from open_guji_cv.groups.protocol import GroupVerdict


def _inp(g="zhi", members=None, cands=(), cfg=None, patch=None, left=None, right=None):
    return M.MethodInput(group=g, members=frozenset(members or GROUPS[g].members), cell_id="v:1:1:1",
                         cands=list(cands), ref=None, cfg=cfg or FlowConfig(groups=(g,)), left=left, right=right,
                         patch_fn=(lambda cid: patch) if patch is not None else None)


def test_every_group_has_method_array_of_known_kinds():
    check_groups(tuple(GROUPS))
    for g, s in GROUPS.items():
        assert s.flow is not None and s.flow.methods, g
        for m in (*s.flow.methods, *s.flow.form_methods):
            assert isinstance(m, M.Method) and m.kind in (*M.KINDS, "chain"), (g, m)
            for sub in getattr(m, "steps", ()):
                assert sub.kind in M.KINDS


def test_registry_kinds_match_ids_specs():
    """整字判法的组是 hog，登记了取框的是「取框→hog」复合，其余看图组是 ids；留痕名都沿用 `ids`。"""
    from open_guji_cv.groups.ids_online import SPECS
    img = {g: next(m for m in s.flow.methods if m.name == "ids") for g, s in GROUPS.items() if "ids" in s.flow.solvers}
    img = {g: (m.inner if isinstance(m, M.Only) else m) for g, m in img.items()}   # zy 的 HOG 包在入口限定里（2026-10-24）
    kinds = {g: m.kind for g, m in img.items()}
    for g in ("lv", "qik", "zy", "sy", "sz", "gm", "xb", "yh", "js", "yr"):
        assert kinds[g] == "hog", g
    for g in ("lih", "rr", "ts", "ly", "wj", "zh", "yt", "em", "fc"):   # lih 10-22 改下半框；文意组字形第二路 10-22
        assert kinds[g] == "composite", g
        m = img[g]
        assert isinstance(m.op, M.Crop) and m.op.region == tuple(SPECS[g].region)
    for g in ("can", "xu", "jiao", "jue", "yi_560", "ce"):          # 叙敘／教敎／絕絶 10-22 改通用 IDS 判法
        assert kinds[g] == "ids", g
    assert GROUPS["zhi"].flow.methods[1].kind == "hog"


def test_ctx_is_rule_then_llm_chain():
    m = GROUPS["jys"].flow.methods[0]
    assert m.name == "ctx" and [s.kind for s in m.steps] == ["ctx_rule", "llm"]
    assert GROUPS["ry"].flow.describe() == "[ctx_rule → llm] ＋ custom:ry_shape"


def test_chain_first_release_wins_and_skips_inapplicable():
    calls = []

    def mk(name, ch):
        def fn(inp):
            calls.append(name)
            return GroupVerdict(ch, conf=0.5 if ch else None, why="agree" if ch else "abstain:x", via=name)
        return M.Custom(name, fn=fn)

    c = M.Chain("c", steps=(mk("a", None), mk("b", "㫖"), mk("c", "旨")))
    v = c.run(_inp())
    assert v.char == "㫖" and calls == ["a", "b"] and 0.0 <= v.conf <= 1.0
    calls.clear()
    v = M.Chain("c", steps=(mk("a", None), mk("b", None))).run(_inp())
    assert v.char is None and v.why == "abstain:x" and calls == ["a", "b"]
    # LLM 方法这册没给表 → 跳过，结论是固定匹配的
    assert not M.Llm().applies(_inp("jys"))


def test_confidence_is_clipped_to_unit_interval():
    m = M.Custom("big", fn=lambda inp: GroupVerdict("旨", conf=3.7, why="agree", via="big"))
    assert m.run(_inp()).conf == 1.0
    m = M.Custom("none", fn=lambda inp: GroupVerdict(None, conf=None, why="abstain:x", via="none"))
    assert m.run(_inp()).conf == 0.0
    assert M.unit(-0.2) == 0.0 and M.unit(0.3) == 0.3


def test_codepoint_gives_book_choice():
    cfg = FlowConfig(groups=("zhi",), canon=lambda c: {"巻": "卷"}.get(c, c))
    v = M.CODEPOINT.run(_inp(members="巻卷", cfg=cfg))
    assert v.char == "卷" and v.conf == 1.0
    assert M.CODEPOINT.run(_inp(members="旨㫖", cfg=cfg)).char is None          # 这套书没定这一对
    assert M.CODEPOINT.run(_inp(members="巻卷")).why == "abstain:no_codepoints"


def test_freq_and_top1():
    cfg = FlowConfig(groups=("zhi",), freq_table={"zhi": {"㫖": 30, "旨": 0}}, freq_vols={"zhi": {"㫖": 3}})
    v = M.FREQ.run(_inp(cfg=cfg))
    assert v.char == "㫖" and v.conf == 1.0
    assert M.TOP1.run(_inp(cands=[("旨", 0.99)])).char == "旨"
    assert M.TOP1.run(_inp(cands=[("旨", 0.90)])).char is None
    assert M.FORM_TOP1.run(_inp(members="會㑹", cands=[("㑹", 0.95), ("會", 0.90)])).char == "㑹"


def test_image_methods_without_patch_are_pending():
    assert M.BARS.run(_inp("ts")).why == "abstain:no_patch"
    assert M.RY_SHAPE.needs_patch and not M.CTX.needs_patch and not M.FREQ.needs_patch
    assert GROUPS["jiao"].flow.needs_patch and not GROUPS["jys"].flow.needs_patch
    assert GROUPS["zh"].flow.needs_patch            # 两段判第二段有 IDS


def test_composite_crop_equals_registered_region(monkeypatch):
    """取框→HOG 与直接按 SPECS 的取框调整字判法结果一致（教敎）。"""
    from open_guji_cv.groups import ids_online
    if not ids_online.has_bank("jiao"):
        pytest.skip("没有教敎模板库")
    rng = np.random.default_rng(0)
    img = np.full((60, 60), 255, np.uint8)
    img[10:50, 10:50] = (rng.random((40, 40)) > 0.6) * 255
    v1 = GROUPS["jiao"].flow.methods[-1].run(_inp("jiao", patch=img))
    v2 = ids_online.judge("jiao", img)
    assert (v1.char, v1.why, v1.extra) == (v2.char, v2.why, v2.extra)
    with pytest.raises(ValueError):
        M.Composite("x", op=M.Crop((0, 1, 0, 1)), inner=M.FREQ).run(_inp("jiao", patch=img))


def test_codepoint_groups_flow_only():
    """码位归一组只进字组流程（`FLOW_GROUPS`），不进 `GROUPS`（glyph_match、rare_ref_coord 的全局字组集合不变）。"""
    from open_guji_cv.groups.registry import CODEPOINT_GROUPS, FLOW_GROUPS, SHAPE_GROUPS
    old = {"nei", "chu", "juan", "wan", "huo", "kui", "lie", "lei", "cuan", "lang", "zheng", "cek"}
    assert set(CODEPOINT_GROUPS) >= old and all(g.startswith("cp_") for g in set(CODEPOINT_GROUPS) - old)
    assert not set(CODEPOINT_GROUPS) & set(GROUPS) and set(FLOW_GROUPS) == set(GROUPS) | set(CODEPOINT_GROUPS) | set(SHAPE_GROUPS)
    check_groups(tuple(CODEPOINT_GROUPS))
    for g, s in CODEPOINT_GROUPS.items():
        assert s.flow.methods == (M.CODEPOINT,) and not s.flow.review and 2 <= len(s.members) <= 3, g
    assert "chu" in FLOW_GROUPS["sy"].overlaps and "sy" in FLOW_GROUPS["chu"].overlaps
    # 放宽了进入（tolerate 组外繁复字）的组，补放必须与整理本同字
    for g, s in CODEPOINT_GROUPS.items():
        assert bool(s.flow.tolerate) == s.flow.lift_ref_agree, g
        assert not s.flow.tolerate & s.members, g
    assert {g for g, s in CODEPOINT_GROUPS.items() if s.flow.tolerate} == {"huo", "kui", "lie"}
    # 库首位与整理本同组即进（2026-10-26）：出岀 除外（与 sy 共字，分差内有 山由 归 sy 按文意判）
    assert {g for g, s in CODEPOINT_GROUPS.items() if not s.flow.ref_top_enter} == {"chu"}


def test_codepoint_group_lifts_book_choice():
    from dataclasses import dataclass, field
    from open_guji_cv.groups.flow import group_flow_pass

    @dataclass
    class Rec:
        id: str
        char: str | None = None
        admit: bool = False
        channel: str | None = None
        provenance: str = ""
        doubts: list = field(default_factory=list)
        evidence: dict = field(default_factory=dict)

    book = {"巻": "卷", "內": "内"}
    canon = lambda c: book.get(c, c)                     # noqa: E731
    cfg = FlowConfig(groups=("juan", "nei"), canon=canon)
    a, b, c = Rec("a"), Rec("b"), Rec("c")
    cands = {"a": [("巻", 0.97), ("卷", 0.96)], "b": [("內", 0.95)], "c": [("巻", 0.97), ("券", 0.96)]}
    res = group_flow_pass([a, b, c], {"a": ("巻", "eq")}, lambda cid: cands[cid], lambda r: False, cfg, canon=canon)
    assert a.admit and a.char == "卷" and a.channel == "group_flow"
    assert a.evidence["group"]["solvers"][0]["solver"] == "codepoint"
    assert b.admit and b.char == "内"
    assert not c.admit and "group" not in c.evidence             # 组外字紧咬、没有整理本字，不进
    assert res.lifted == 2
    # 库首位与整理本（缺位时坐标对位）字同在组里：分差内的组外字不拦（`ref_top_enter`）；库 cov 不到 0.91 码位法弃权
    e, f, h = Rec("e"), Rec("f"), Rec("h")
    cands = {"e": [("巻", 0.97), ("券", 0.96)], "f": [("巻", 0.95), ("春", 0.94)], "h": [("巻", 0.90), ("春", 0.89)]}
    res = group_flow_pass([e, f, h], {"e": ("卷", "replace")}, lambda cid: cands[cid], lambda r: False, cfg, canon=canon,
                          veto_refs={"f": "巻", "h": "巻"})
    assert e.admit and e.char == "卷" and f.admit and f.char == "卷"
    assert not h.admit and "group_flow_abstain" in h.doubts
    # 整理本是组外字：不走这条
    k = Rec("k")
    group_flow_pass([k], {"k": ("春", "replace")}, lambda cid: [("巻", 0.97), ("春", 0.96)], lambda r: False, cfg, canon=canon)
    assert not k.admit and "group" not in k.evidence
    # 这套书没定码位 → 待定送审
    d = Rec("d")
    group_flow_pass([d], {}, lambda cid: [("巻", 0.97)], lambda r: False, FlowConfig(groups=("juan",)))
    assert not d.admit and "group_flow_abstain" in d.doubts


def test_ctx_glyph2_groups():
    """文意组字形第二路（2026-10-22）：排在文意之后、清碎墨；象𧰼 形判只在族内、𧰼 不足 20 例永不自动给；曾會 族的會㑹 形判不用整字库。"""
    from open_guji_cv.groups.ids_online import SPECS
    from open_guji_cv.groups.registry import GLYPH2
    for g in GLYPH2:
        assert GROUPS[g].flow.solvers[0] == "ctx" and "ids" in GROUPS[g].flow.solvers, g
        assert SPECS[g].whole == "hog" and SPECS[g].clean and SPECS[g].min_margin >= 0.4, g
    assert "ids" not in GROUPS["xz"].flow.solvers and "ids" in GROUPS["xz"].flow.form_solvers
    assert SPECS["xz"].min_class == 20
    assert "ids" not in GROUPS["zh"].flow.form_solvers
    assert "wxs" not in GLYPH2 and "dt" not in GLYPH2


def test_clean_patch_drops_border_specks():
    import numpy as np
    from open_guji_cv.groups import ids_whole
    g = np.full((60, 50), 255, np.uint8)
    g[10:50, 20:30] = 0          # 主体竖笔
    g[0:3, 0:3] = 0              # 贴边碎墨
    g[30:32, 46:50] = 0          # 贴右边的小块
    c = ids_whole.clean_patch(g)
    assert (c[10:50, 20:30] == 0).all() and c[0:3, 0:3].min() == 255 and c[30:32, 46:50].min() == 255
    assert ids_whole.aspect_ok(g, (0.45, 2.2)) and not ids_whole.aspect_ok(np.zeros((10, 40)), (0.45, 2.2))


def test_near_family_groups():
    """码位已定、库在形近字间拿不准的族（2026-10-26）：整字 HOG 一对多、两码位并一类、陪衬进库；须与整理本同字、库首位是陪衬也按整理本进。"""
    from open_guji_cv.groups.ids_online import SPECS, bank_path
    from open_guji_cv.groups.registry import SHAPE_GROUPS, _NEAR_FAMILY
    gs = [g for g, *_ in _NEAR_FAMILY]
    assert set(gs) == {"xiang", "weim", "bie", "zhen"}
    check_groups(tuple(gs))
    for g in gs:
        f = SHAPE_GROUPS[g].flow
        assert f.solvers == ("ids",) and f.lift_ref_agree and f.ref_enter and not f.review, g
        assert not f.tolerate & SHAPE_GROUPS[g].members and len(SHAPE_GROUPS[g].members) == 2, g
        assert SPECS[g].whole == "hog" and SPECS[g].min_margin >= 0.4 and bank_path(g) is not None, g
    assert "卿" in SHAPE_GROUPS["xiang"].flow.tolerate and {"徵", "徴"} <= SHAPE_GROUPS["weim"].flow.tolerate
    assert "刖" in SHAPE_GROUPS["bie"].flow.tolerate
