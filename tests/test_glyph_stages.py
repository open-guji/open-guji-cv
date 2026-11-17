"""第 5 步分段判定（`steps.glyph_stages`）：配置、指纹、5a.2 定字条件、关着时参数与记录逐字节不变。"""
import numpy as np
import pytest

from open_guji_cv.clustering.match import MatchResult
from open_guji_cv.clustering.near_route import RouteConfig, RouteDecision
from open_guji_cv.groups import shape_stage
from open_guji_cv.products.kinds.recog import MatchRec
from open_guji_cv.steps import glyph_stages as GS


def test_config_parse_and_reject_unknown():
    assert GS.StagesConfig.from_any(None) is None and GS.StagesConfig.from_any(False) is None
    c = GS.StagesConfig.from_any(True)
    assert c.route == RouteConfig() and c.final == frozenset() and c.shape
    c = GS.StagesConfig.from_any({"route": {"knn_min": 0.9}, "final": ["xb"], "shape": False})
    assert c.route.knn_min == 0.9 and c.final == {"xb"} and not c.shape
    for bad in ({"x": 1}, {"route": {"nope": 1}}, {"final": ["没有这个组"]}):
        with pytest.raises(ValueError):
            GS.StagesConfig.from_any(bad)


def test_fingerprint_off_empty_and_final_changes_it():
    assert GS.stages_fingerprint(None) == ""
    a, b = GS.stages_fingerprint(True), GS.stages_fingerprint({"final": ["xb"]})
    assert a and b and a != b and a == GS.stages_fingerprint({})


def test_matchrec_stage_not_dumped_when_none():
    r = MatchRec(id="b:1:1:1", slot=1, verdict="same", char="天")
    assert "stage" not in r.model_dump()
    assert MatchRec(id="b:1:1:1", slot=1, verdict="unsure", stage={"route": "weak"}).model_dump()["stage"] == {"route": "weak"}


def _fake_judge(table):
    def judge(g, cell_id, cands, patch_fn, cfg=None):
        ch, why = table[g]
        return shape_stage.ShapeVerdict(g, ch, why, False, (("ids", ch, 0.9, why),))
    return judge


def test_stage_shape_final_only_from_book_list(monkeypatch):
    inp = GS.StageInput("c", "心", ("xb", "g2", "g3"), [("心", 0.99)], np.zeros((8, 8), np.uint8))
    monkeypatch.setattr(shape_stage, "judge", _fake_judge({"xb": ("必", "agree"), "g2": (None, "abstain"), "g3": (None, "no_method")}))
    ev, ch, gid = GS.stage_shape(inp, GS.StagesConfig(RouteConfig(), frozenset({"xb"})), None)
    assert (ch, gid) == ("必", "xb") and [r["group"] for r in ev["shape"]] == ["xb", "g2"]
    ev, ch, gid = GS.stage_shape(inp, GS.StagesConfig(RouteConfig(), frozenset()), None)       # 名单空：只出证据
    assert ch is None and ev["shape"][0]["char"] == "必"
    monkeypatch.setattr(shape_stage, "judge", _fake_judge({"xb": ("必", "agree"), "g2": ("心", "agree"), "g3": (None, "abstain")}))
    assert GS.stage_shape(inp, GS.StagesConfig(RouteConfig(), frozenset({"xb"})), None)[1] is None   # 两组给的字不一致：不定


class _Router:
    def __init__(self, d):
        self.d = d

    def decide(self, q, exclude=()):
        return self.d


def _stages(decision, final=()):
    s = object.__new__(GS.Stages)
    s.cfg = GS.StagesConfig(RouteConfig(), frozenset(final))
    s._m = type("M", (), {"_same_cell_rows": lambda self, i: set()})()
    s._net, s._embed, s._pos, s._flow_cfg = None, (lambda net, xs: np.zeros((1, 4), np.float32)), {}, None
    s.router = _Router(decision)
    return s


def test_apply_routes(monkeypatch):
    m = MatchResult("same", "心", "x", 0.99, 0.0, [("心", 0.99)])
    norm = np.zeros((64, 64), np.float32)
    assert _stages(RouteDecision(None, "心")).apply("same", m, norm, norm, "c", None) == GS.StageOut()
    assert _stages(RouteDecision("near_group", "心")).apply("unsure", m, norm, norm, "c", None) == GS.StageOut()   # 只管判 same 的格
    o = _stages(RouteDecision("weak", "心", knn=0.8)).apply("same", m, norm, norm, "c", None)
    assert (o.verdict, o.guard, o.stage["knn"]) == ("unsure", "weak_knn", 0.8)
    monkeypatch.setattr(shape_stage, "judge", _fake_judge({"xb": ("必", "agree")}))
    d = RouteDecision("near_group", "心", partners=("必",), groups=("xb",))
    o = _stages(d).apply("same", m, norm, norm, "c", None)                       # 缺省：全部待审，证据带走
    assert (o.verdict, o.guard, o.char) == ("unsure", "near_group", None) and o.stage["shape"][0]["char"] == "必"
    o = _stages(d, final=("xb",)).apply("same", m, norm, norm, "c", None)        # 进了书级名单：这一步定字
    assert (o.verdict, o.guard, o.char, o.via, o.stage["final"]) == ("same", None, "必", "shape:xb", "5a.2")


def test_params_dump_unchanged_when_off(tmp_path):
    from open_guji_cv.steps.glyph_match import GlyphMatchParams
    d = GlyphMatchParams(db_path=str(tmp_path / "x.db"), db_fingerprint="f").model_dump()
    assert "stages" not in d and "stages_sha" not in d
