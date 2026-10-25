"""日曰（ry）＋日目（rm）A24 2026-10-24：L2 表逐格细读复核（`ctx_l2.add_verify`）、单遍文意拗坐标对位不补放、
文意与整理本相反的待审格记 `group_flow_ctx_contra`、ry／rm L1 规则修订。自造数据。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.groups import flow
from open_guji_cv.groups.ctx_l1 import CtxL1Backend
from open_guji_cv.groups.ctx_l2 import CtxL2Backend, add_verify, merge_runs
from open_guji_cv.groups.flow import FlowConfig, group_flow_pass
from open_guji_cv.groups.protocol import GroupVerdict, JudgeInput, window_from_text
from open_guji_cv.groups.registry import GROUPS
from open_guji_cv.steps.seed_admit import _LANE_HARD

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Rec:
    id: str
    char: str | None = None
    admit: bool = False
    channel: str | None = None
    provenance: str = ""
    doubts: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


def _table(**cells):
    """cells: id → (haiku 字, 置信)。"""
    runs = {"haiku": {k: {"char": c, "conf": f} for k, (c, f) in cells.items()}}
    return merge_runs("ry", "日曰", "ry-l2-t", runs, {k: ("左" + k, "右") for k in cells})


# —— add_verify ——

def test_verify_vetoes_rescues_and_marks_strong():
    t = _table(a=("曰", "high"), b=("日", "high"), c=("曰", "low"), d=("曰", "mid"))
    n = add_verify(t, "opus", {"a": {"char": "日", "conf": "high"},    # 单遍 high 与细读 high 相反 → 弃权
                               "b": {"char": "日", "conf": "high"},    # 同字两遍都 high → strong
                               "c": {"char": "日", "conf": "high"},    # 主表低把握、细读 high → 用细读的字
                               "d": {"char": "日", "conf": "mid"}}, "日曰")
    cs = t["cells"]
    assert (cs["a"]["char"], cs["a"]["why"]) == (None, "disagree:verify") and not cs["a"].get("strong")
    assert (cs["b"]["char"], cs["b"]["why"], cs["b"].get("strong")) == ("日", "agree", True)
    assert (cs["c"]["char"], cs["c"]["why"]) == ("日", "agree:verify") and not cs["c"].get("strong")
    assert (cs["d"]["char"], cs["d"]["why"]) == (None, "disagree:verify")      # 细读 mid 也能否掉表里的字
    assert cs["a"]["votes"] == {"haiku": ["曰", "high"], "opus": ["日", "high"]}
    assert n == dict(verify=1, other=0, veto=2, new=0, strong=1) and t["models"] == ["haiku", "opus"]


def test_verify_mid_single_vote_wins_over_mid_and_other():
    t = _table(a=("曰", "mid"), b=("曰", "high"))
    add_verify(t, "opus", {"a": {"char": "日", "conf": "high"}, "b": {"char": "其他", "conf": "high"}}, "日曰")
    assert (t["cells"]["a"]["char"], t["cells"]["a"]["why"]) == ("日", "agree:verify")   # 另一遍只是 mid：细读 high 说了算
    assert (t["cells"]["b"]["char"], t["cells"]["b"]["why"]) == (None, "disagree:verify")   # 另一遍 high 给组内字：不算「其他」


def test_verify_creates_missing_cells_and_backend_reports_runs():
    t = _table(a=("曰", "high"))
    n = add_verify(t, "opus", {"z": {"char": "其他", "conf": "high"}, "y": {"char": "日", "conf": "high"},
                               "x": {"char": "日", "conf": "high"}}, "日曰", ctxs={"z": ("甲", "乙"), "y": ("丙", "丁")})
    assert "x" not in t["cells"] and n["new"] == 2                   # 没给窗口的格不建
    assert (t["cells"]["z"]["char"], t["cells"]["z"]["why"]) == (None, "abstain:other")
    be = CtxL2Backend(t)
    v = be.judge(GROUPS["ry"], JudgeInput("z", None, window_from_text("甲", "乙")))
    assert v.char is None and v.extra["other_conf"] == "high"
    v = be.judge(GROUPS["ry"], JudgeInput("y", None, window_from_text("丙", "丁")))
    assert v.char == "日" and v.extra["runs"] == 1 and not v.extra.get("strong")
    add_verify(t, "haiku#2", {"a": {"char": "曰", "conf": "mid"}}, "日曰")
    v = be.judge(GROUPS["ry"], JudgeInput("a", None, window_from_text("左a", "右")))
    assert v.char == "曰" and v.extra["runs"] == 2 and not v.extra.get("strong")


# —— 流程：坐标对位是组里另一个字 ——

def _patch(monkeypatch, ctx_extra: dict, shape=None):
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(
        "日" if name == "ctx" else shape, via="ctx_l2" if name == "ctx" else name,
        extra=dict(ctx_extra) if name == "ctx" else {}))


@pytest.mark.parametrize("extra,shape,lifted", [
    ({"runs": 1}, None, False),                    # 单遍 haiku（vol13 63:5:18）：不补放
    ({"runs": 2}, None, True),                     # 两遍同字
    ({"runs": 2, "strong": True}, None, True),
    ({"runs": 1}, "日", True),                     # 字形也给日
])
def test_lift_coord_dissent_inside_group(monkeypatch, extra, shape, lifted):
    _patch(monkeypatch, extra, shape)
    cands = lambda cid: [("日", 0.99), ("曰", 0.98)]
    r = Rec("x")
    group_flow_pass([r], {}, cands, lambda r: False, FlowConfig(groups=("ry",)), veto_refs={"x": "曰"})
    assert r.admit is lifted
    if not lifted:
        assert {"group_flow_coord_dissent", "group_flow_ctx_contra"} <= set(r.doubts)
    r = Rec("x")
    group_flow_pass([r], {}, cands, lambda r: False, FlowConfig(groups=("ry",), lift_ref_guard=False), veto_refs={"x": "曰"})
    assert r.admit and r.char == "日"


def test_l1_answer_passes_coord_dissent(monkeypatch):
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(
        "日" if name == "ctx" else None, via="ctx:ctx_l1" if name == "ctx" else name))
    r = Rec("x")
    group_flow_pass([r], {}, lambda cid: [("日", 0.99), ("曰", 0.98)], lambda r: False, FlowConfig(groups=("ry",)),
                    veto_refs={"x": "曰"})
    assert r.admit and r.char == "日"


def test_review_cell_with_ctx_against_ref_is_marked(monkeypatch):
    """共字组没表态（joint）而文意给了与整理本不同的字：记 `group_flow_ctx_contra`，后面的补放遍不碰；文意没给字不记。"""
    monkeypatch.setattr(flow, "_solve", lambda name, g, r, *a, **k: GroupVerdict(
        "日" if (g, name) == ("ry", "ctx") else None, via=name))
    cands = lambda cid: [("日", 0.99), ("目", 0.985)]
    cfg = FlowConfig(groups=("ry", "rm"), joint=True)
    a, b = Rec("a"), Rec("b")
    group_flow_pass([a, b], {"a": ("曰", "equal"), "b": ("日", "equal")}, cands, lambda r: False, cfg)
    assert not a.admit and {"group_flow_joint", "group_flow_ctx_contra"} <= set(a.doubts)
    assert not b.admit and b.doubts == ["group_flow_abstain"]        # 整理本是日 → 进日目组，文意弃权
    assert "group_flow_ctx_contra" in _LANE_HARD


# —— L1 规则 ——

@pytest.mark.parametrize("g,left,right,want", [
    ("ry", "分十八門又分子", "四百九十有四", None), ("ry", "釐爲子", "以理其緒", None),       # 子目
    ("ry", "侍孔子坐子", "參先王有至德", "曰"),
    ("ry", "語見黄氏", "鈔故今之所錄", None), ("ry", "讀易", "鈔", "日"),
    ("ry", "名字爵號", "月及會之類", None), ("ry", "論語義疏", "本尙有全帙", None),
    ("ry", "萬厯乙卯", "序言夫子", None), ("ry", "辛巳", "奉", "日"),
    ("ry", "故", "干祿其例", None),
    ("ry", "曲禮曰喪事先遠", "註曰葬與練祥", None), ("ry", "曰易", "書曰詩", "曰"),
    ("rm", "侍孔子坐子", "句下註曰", None), ("rm", "而改題", "五經名實", None), ("rm", "故名", "孔義", None),
    ("rm", "別標他", "一兩字", None), ("rm", "擬題數", "有單句題", None), ("rm", "分別爲十九", "久無傳本", None),
    ("rm", "四庫全書總", "", "目"), ("rm", "存", "", "目"), ("rm", "終", "", "日"), ("rm", "", "月之行", "日"),
    ("rm", "談一", "月令夏小正", None), ("rm", "下曰素", "曰藉", None),
])
def test_ry_rm_rules_1024(g, left, right, want):
    spec = GROUPS[g]
    be = CtxL1Backend(ROOT / spec.config_dir / "rules.yaml", spec.members)
    assert be.decide(left, right)[0] == want
