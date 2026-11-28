"""收尾直接写的送审原因（P3a-2，2026-11-28）：enum 副本与 manager 一致，判法与 manager `classify` 的单格行为一致。

真源是 guji-manager `review/pending_reasons.yaml`；cv 存精简副本 `open_guji_cv/ops/pending_reasons.json`。
manager 没装就跳过对账那条（其余不依赖 manager）。副本由 `python -m guji_manager.review.pending_reason --json` 精简得来，
改了 manager 的 yaml 后重新导出并更新副本。
"""
from __future__ import annotations

import json

import pytest

from open_guji_cv.core.decide_names import FINAL_PENDING_REASONS
from open_guji_cv.products.kinds.recog import AdmitRec
from open_guji_cv.steps import char_decide_reasons as R

_KEYS = ("code", "category", "route", "owner", "reviewer", "priority")


def test_copy_matches_manager_export():
    pr = pytest.importorskip("guji_manager.review.pending_reason")
    exp = pr.export()
    mine = R.spec()
    assert mine["version"] == exp["version"]
    assert mine["renamed"] == exp["renamed"]
    assert list(mine["reasons"]) == list(exp["reasons"]), "原因名或顺序与 manager 不同：重新导出副本"
    for k, v in exp["reasons"].items():
        assert {f: v[f] for f in _KEYS} == mine["reasons"][k], k


def test_final_set_is_owner_cv4():
    assert set(FINAL_PENDING_REASONS) == R.final_reasons_set()
    assert len(set(FINAL_PENDING_REASONS)) == len(FINAL_PENDING_REASONS)


def test_rules_only_name_known_reasons():
    assert set(R.RULES) <= set(R.reason_names())


def test_admit_rec_none_not_serialized_and_roundtrip():
    d = AdmitRec(id="b:1:1:1", slot=1).model_dump(mode="json")
    assert not ({"pending_reason", "pending_reason_detail", "form_src"} & set(d))
    d = AdmitRec(id="b:1:1:1", slot=1, pending_reason="hard_pair", pending_reason_detail="日/曰", form_src="lib").model_dump(mode="json")
    assert (d["pending_reason"], d["pending_reason_detail"], d["form_src"]) == ("hard_pair", "日/曰", "lib")
    assert AdmitRec.model_validate(d).pending_reason == "hard_pair"


def _ctx(**kw):
    return R.build_context([], **kw)


def _cell(**kw):
    return R.Cell(id=kw.pop("id", "b:1:1:1"), **kw)


@pytest.mark.parametrize("cell,want", [
    # 极难形近（己已巳日曰全在内）
    (dict(char="日", ref="曰", cands=[["日", 0.9]]), "hard_pair"),
    # 参校本缺字
    (dict(char="x", ref="〓", cands=[["x", 0.9]]), "ref_lacuna"),
    # 整理本没字、不是设计
    (dict(char="x", ref=None, cands=[["x", 0.9]]), "ref_gap"),
    # 库里没有（需要库计数：没给库＝按老办法 L01）
    (dict(char="x", ref="y", cands=[["z", 0.5]], doubts=["库里没有这个字"]), "lib_missing"),
    # 文本对位 replace 段
    (dict(char="x", ref="y", ref_op="replace", cands=[["x", 0.99]]), "ref_ocr_diff"),
    # 机器字≠整理本字，别的都不中
    (dict(char="x", ref="y", ref_op="equal", cands=[["x", 0.99]]), "ref_final_diff"),
    # 机器字＝整理本字：库认不出（L04，不归第四步）
    (dict(char="y", ref="y", ref_op="equal", cands=[["y", 0.9]]), "lib_unrecognized"),
    # 乱码闸
    (dict(char="x", ref="y", cands=[["x", 0.5]], doubts=["ctx_garble_shape"]), "garble_gate"),
    # 裁定冲突优先于一切
    (dict(char="x", ref="y", doubts=["src_code_conflict", "occluded"]), "ruling_conflict"),
    # 形近护栏
    (dict(char="x", ref="y", cands=[["x", 0.9]], evidence={"guard": "conflict"}), "near_form_guard"),
])
def test_classify_basic(cell, want):
    assert R.classify(_cell(**cell), _ctx()) == want


def test_classify_variant_and_sparse():
    av = lambda a, b: {a, b} == {"體", "体"}   # noqa: E731
    x = _ctx(are_variants=av)
    assert R.classify(_cell(char="体", ref="體", cands=[["体", 0.9]]), x) == "variant_pair"
    # 通假／形近来源的 T3 边不算异体：落到后面的 ref_final_diff
    x = _ctx(are_variants=av, edge_tier=lambda a, b: "T3")
    assert R.classify(_cell(char="体", ref="體", cands=[["体", 0.9]]), x) == "ref_final_diff"
    x = _ctx(lib_own=lambda ch: 1)
    assert R.classify(_cell(char="x", ref="y", cands=[["x", 0.9]], doubts=["库里没有这个字"]), x) == "lib_sparse_dissent"
    x = _ctx(lib_own=lambda ch: 0)
    assert R.classify(_cell(char="x", ref="y", cands=[["x", 0.9]]), x) == "lib_missing"   # 刻例 0：第一次进库


def test_classify_group_kinds():
    g = lambda **k: {"group": {"id": "wu", **k}}   # noqa: E731
    base = dict(char="x", ref="y", cands=[["x", 0.9]])
    assert R.classify(_cell(**base, evidence=g(why="abstain", solvers=[])), _ctx()) == "group_abstain"
    two = [{"char": "a"}, {"char": "b"}]
    assert R.classify(_cell(**base, evidence=g(why="conflict", solvers=two)), _ctx()) == "group_conflict"
    assert R.classify(_cell(**base, evidence=g(why="x", decision="demote", solvers=[{"char": "a"}])), _ctx()) == "group_demoted"
    assert R.classify(_cell(**base, evidence=g(why="weak", solvers=[{"char": "a"}])), _ctx()) == "group_unconfirmed"
    assert R.classify(_cell(**base, evidence=g(why="ref_dissent", solvers=[{"char": "a"}])), _ctx()) == "group_ref_dissent"


def test_other_owners_win_by_priority():
    # 遮挡（D01，GM4）先于 P02：归别人，cv 不写
    r = R.classify(_cell(char="x", ref="y", cands=[["x", 0.9]], doubts=["occluded"]), _ctx())
    assert r == "occluded_with_ref" and r not in R.final_reasons_set()
    # 切坏碎片
    assert R.classify(_cell(char="x", ref=None, frag=True), _ctx()) == "seg_defect"


def test_detail_formats():
    c = _cell(char="日", ref="曰", cands=[["己", 0.9]])
    assert R.detail_of("hard_pair", c) == "己/日/曰"
    assert R.detail_of("ref_final_diff", c) == "曰>日"
    gc = _cell(char="x", ref="y", evidence={"group": {"id": "wu", "mode": "lift"}})
    assert R.detail_of("group_abstain", gc) == "wu:lift"
