# -*- coding: utf-8 -*-
"""5a.2 字形判定（groups/shape_stage.py）：只取注册表里吃字块图的方法、不给整理本和文意、只出字形判定。"""

from dataclasses import dataclass

import numpy as np
import pytest

from open_guji_cv.groups import shape_stage as S
from open_guji_cv.groups.methods import Chain, Method
from open_guji_cv.groups.protocol import GroupVerdict
from open_guji_cv.groups.registry import FLOW_GROUPS, FlowSpec, GroupSpec


@dataclass(frozen=True)
class _Fixed(Method):
    """测试用方法：给定字；记下收到的输入，好查没把整理本和文意传进来。"""
    char: str | None = None
    patch: bool = True
    seen: tuple = ()

    @property
    def needs_patch(self):            # type: ignore[override]
        return self.patch

    def _run(self, inp):
        assert inp.ref is None and inp.left is None and inp.right is None and inp.coord is None and inp.cur is None
        return GroupVerdict(self.char, conf=0.9 if self.char else 0.0, why="agree" if self.char else "abstain:test", via="image")


def _group(monkeypatch, gid, members, methods, **flow):
    base = next(iter(FLOW_GROUPS.values()))
    spec = GroupSpec(id=gid, name=gid, members=members, backends=base.backends, note="", kind="near_form", solvers=(),
                     config_dir=base.config_dir, flow=FlowSpec(methods=methods, **flow))
    monkeypatch.setitem(FLOW_GROUPS, gid, spec)


IMG = np.zeros((8, 8), np.uint8)


def test_only_patch_methods_run(monkeypatch):
    ctx = _Fixed("ctx", char="乙", patch=False)                      # 不吃图的方法（文意）不该被调
    _group(monkeypatch, "t1", "甲乙", (Chain("ctx", steps=(ctx,)), _Fixed("a", char="甲"), _Fixed("b", char=None)))
    assert [m.name for m in S.shape_methods("t1")] == ["a", "b"]
    v = S.judge("t1", "c1", [("甲", 0.99)], lambda _id: IMG)
    assert (v.char, v.why, v.final) == ("甲", "agree", False)         # 组里还有文意方法：只当证据，不单独定字
    assert [(r[0], r[1]) for r in v.solvers] == [("a", "甲"), ("b", None)]


def test_final_needs_all_shape_and_no_ref_policy(monkeypatch):
    _group(monkeypatch, "t2", "甲乙", (_Fixed("a", char="乙"),))
    assert S.final("t2") and S.judge("t2", "c", [], lambda _id: IMG).final
    _group(monkeypatch, "t3", "甲乙", (_Fixed("a", char="乙"),), lift_ref_veto=True)   # 要整理本互证的组
    v = S.judge("t3", "c", [], lambda _id: IMG)
    assert v.char == "乙" and not v.final


def test_conflict_abstain_no_method_no_patch(monkeypatch):
    _group(monkeypatch, "t4", "甲乙", (_Fixed("a", char="甲"), _Fixed("b", char="乙")))
    assert S.judge("t4", "c", [], lambda _id: IMG).why == "conflict"
    _group(monkeypatch, "t5", "甲乙", (_Fixed("a", char=None),))
    assert S.judge("t5", "c", [], lambda _id: IMG).why == "abstain"
    _group(monkeypatch, "t6", "甲乙", (_Fixed("a", char="甲", patch=False),))
    assert S.judge("t6", "c", [], lambda _id: IMG).why == "no_method" and not S.final("t6")
    assert S.judge("t4", "c", [], lambda _id: None).why == "no_patch"
    assert S.judge("没有这个组", "c", [], lambda _id: IMG).why == "no_method"


def test_inventory_covers_registry():
    inv = S.inventory()
    assert sum(len(v) for v in inv.values()) == len(FLOW_GROUPS)
    assert "ss" in inv["final"] or "ss" in inv["evidence"]           # 十士：量横，纯字形
    assert "jys" in inv["none"]                                       # 己已巳：只有文意
    assert "ry" in inv["evidence"]                                    # 日曰：宽高比＋文意
