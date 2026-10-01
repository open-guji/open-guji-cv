# -*- coding: utf-8 -*-
"""影子放行闸（overview#305 第一阶段）：信号口径、只降不升、弃权、模型文件与参数指纹。全部自造数据。"""
from __future__ import annotations

import pytest

from open_guji_cv.shadow import signals as S
from open_guji_cv.shadow.gate import ShadowGate
from open_guji_cv.shadow.model import ShadowModel, ShadowModelError, file_fingerprint, load_model, save_model


class _VM:
    def semantic(self, c):
        return {"體": "体", "体": "体"}.get(c, c)


def _ctx(human=None, lib_ids=()):
    return S.SignalContext(vm=_VM(), partners={"曰": frozenset("日"), "日": frozenset("曰")},
                           human_ids=human or {}, lib_ids=frozenset(lib_ids))


class _StubModel:
    """按 `table[候选字]` 给分；没列的候选 0.01。"""
    def __init__(self, table):
        self.table = table
        self.meta = {"signal_version": S.SIGNAL_VERSION, "model_id": "stub"}
        self.version = "stub@0"

    def scores(self, rows):
        return [self.table.get(r["cand"], 0.01) for r in rows]


def _gate(table, conf=0.9, low=0.0, ctx=None):
    return ShadowGate(_StubModel(table), ctx or _ctx(), conf, low)


def test_candidates_merge_jiyisi_and_order():
    ev = S.CellEvidence("v:1:1:1", lib=[("已", .9), ("己", .95), ("日", .5)], rare=[("曰", .3)], ref="巳", cur="已")
    cands, lib, _ = S.candidates(ev)
    assert lib["己"] == .95                       # 己已巳合并取最大
    assert cands == ["己", "日", "曰"]            # 己（库 top1、整理本、现字合并）、日、曰


def test_build_rows_features():
    ev = S.CellEvidence("v:1:1:1", lib=[("曰", .99), ("日", .98)], rare=[], ref="日", cur="曰")
    rows = {r["cand"]: r for r in S.build_rows(ev, _ctx())}
    assert set(rows) == {"曰", "日"}
    assert rows["曰"]["lib_top1"] == 1 and rows["日"]["lib_top1"] == 0
    assert rows["曰"]["lib_margin"] == pytest.approx(.01) and rows["日"]["lib_margin"] == pytest.approx(-.01)
    assert rows["日"]["ref_eq"] == 1 and rows["曰"]["ref_eq"] == 0 and rows["曰"]["confusable"] == 1
    assert set(S.FEATURES) <= set(rows["曰"])


def test_human_n_excludes_self_both_prefixes():
    ctx = _ctx(human={"曰": {"vol03:1:1:1", "vol03:9:9:9"}})
    ev = S.CellEvidence("v2:vol03:1:1:1", lib=[("曰", .9)], cur="曰")
    assert S.build_rows(ev, ctx)[0]["human_n"] == 1
    ev2 = S.CellEvidence("vol03:1:1:1", lib=[("曰", .9)], cur="曰")
    assert S.build_rows(ev2, ctx)[0]["human_n"] == 1


def test_no_candidates_no_rows():
    assert S.build_rows(S.CellEvidence("x:1:1:1"), _ctx()) == []


def test_veto_only_when_different_and_confident():
    ev = S.CellEvidence("v:1:1:1", lib=[("曰", .9), ("日", .8)], cur="曰")
    v = _gate({"日": .95, "曰": .02}).judge(ev)
    assert v.veto and v.reason == "differs" and v.pick == "日" and v.conf > .9
    v = _gate({"日": .95, "曰": .02}, conf=0.999).judge(ev)         # 把握不够 → 不降
    assert not v.veto and v.reason == "differs_below_thr"
    v = _gate({"曰": .95, "日": .02}).judge(ev)                      # 影子同意现字 → 不降
    assert not v.veto and v.reason == "agree"


def test_jiyisi_same_class_is_not_veto():
    ev = S.CellEvidence("v:1:1:1", lib=[("已", .9), ("巳", .8)], cur="已")
    assert not _gate({"己": .9}).judge(ev).veto


def test_abstain_cases():
    ev = S.CellEvidence("v:1:1:1", lib=[("曰", .9)], cur="曰")
    assert _gate({"日": 1}, ctx=_ctx(lib_ids={"v:1:1:1"})).judge(ev).reason == "abstain:self_in_lib"
    assert _gate({}, ctx=_ctx(lib_ids={"v:1:1:1"})).judge(S.CellEvidence("v2:v:1:1:1", lib=[("曰", .9)], cur="曰")).reason == "abstain:self_in_lib"
    assert _gate({}).judge(S.CellEvidence("v:1:1:1", lib=[("曰", .9)], cur=None)).reason == "abstain:no_cur"
    assert _gate({}).judge(S.CellEvidence("v:1:1:1", cur="曰")).veto is False  # 只有现字一个候选：影子同意


def test_model_error_abstains_never_vetoes():
    class Boom(_StubModel):
        def scores(self, rows):
            raise ValueError("坏了")
    g = ShadowGate(Boom({}), _ctx(), 0.5)
    v = g.judge(S.CellEvidence("v:1:1:1", lib=[("曰", .9)], cur="曰"))
    assert not v.veto and v.reason.startswith("abstain:error")


def test_low_conf_option_default_off():
    ev = S.CellEvidence("v:1:1:1", lib=[("曰", .9), ("日", .8)], cur="曰")
    even = {"曰": .5, "日": .5}
    assert not _gate(even).judge(ev).veto
    assert _gate(even, low=0.6).judge(ev).reason == "low_conf"


def _tiny_clf():
    from sklearn.ensemble import HistGradientBoostingClassifier
    import numpy as np
    import pandas as pd
    X = pd.DataFrame(np.random.RandomState(0).rand(60, len(S.FEATURES)), columns=list(S.FEATURES))
    return HistGradientBoostingClassifier(max_iter=5).fit(X, (X["lib_cov"] > .5).astype(int))


def test_model_roundtrip_fingerprint_and_version_guard(tmp_path):
    p = tmp_path / "m.joblib"
    fp = save_model(p, _tiny_clf(), {"model_id": "t", "train_books": {"a": 1}})
    assert fp == file_fingerprint(p) and (tmp_path / "m.json").exists()
    m = load_model(p)
    assert m.version == f"t@{fp}" and m.meta["features"] == list(S.FEATURES)
    assert len(m.scores([{f: 0.5 for f in S.FEATURES}])) == 1
    import joblib
    doc = joblib.load(p)
    doc["meta"]["signal_version"] = "999"
    joblib.dump(doc, p)
    with pytest.raises(ShadowModelError):
        load_model(p)
    with pytest.raises(ShadowModelError):
        load_model(tmp_path / "nope.joblib")


def test_seed_admit_params_off_is_invisible(tmp_path):
    """关着时五个影子字段不进 dump → params_hash 与加字段前逐位相同；开着时路径不进指纹、内容进。"""
    from open_guji_cv.core.engine import params_hash
    from open_guji_cv.steps.seed_admit import SeedAdmitParams, SeedAdmitStep
    db = tmp_path / "g.db"
    off = SeedAdmitParams(db_path=str(db))
    assert not any(k.startswith("shadow") for k in off.model_dump())
    assert "shadow_model" in SeedAdmitStep.spec.path_params
    m1, m2 = tmp_path / "a.joblib", tmp_path / "sub" / "b.joblib"
    m2.parent.mkdir()
    save_model(m1, _tiny_clf(), {"model_id": "t"})
    m2.write_bytes(m1.read_bytes())
    sp, pt = SeedAdmitStep.spec.soft_params, SeedAdmitStep.spec.path_params
    h = lambda p: params_hash(p, sp, pt)  # noqa: E731
    on1 = SeedAdmitParams(db_path=str(db), shadow_veto=True, shadow_model=str(m1))
    on2 = SeedAdmitParams(db_path=str(db), shadow_veto=True, shadow_model=str(m2))
    assert h(on1) == h(on2) != h(off)                          # 同内容换路径：指纹不变
    save_model(m2, _tiny_clf(), {"model_id": "t2"})            # 内容变
    assert h(SeedAdmitParams(db_path=str(db), shadow_veto=True, shadow_model=str(m2))) != h(on1)


def test_seed_admit_shadow_veto_only_demotes(tmp_path, monkeypatch):
    """端到端（造数据）：开关关 = 与不带该参数逐字一致；开 = 只把放行格降回待审，evidence 留痕，人裁格不动。"""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from test_approx_labels import _png, _run_seed
    from open_guji_cv.clustering.glyph_db import GlyphDB
    from open_guji_cv.products.kinds.recog import MatchRec
    from open_guji_cv.steps import seed_admit as sa

    p = tmp_path / "lib.db"
    g = GlyphDB(p)
    for k, ch in ((1, "衡"), (2, "衡"), (3, "乃")):
        g.admit_instance(f"v2:lib:1:1:{k}", ch, _png(k), provenance="human", page="1", col=1, idx=k)
    g.conn.commit()
    g.close()
    recs = [
        MatchRec(id="tbook:1:3:1", slot=1, verdict="same", char="衡", matched_id="v2:lib:1:1:1",
                 cov=0.999, candidates=[("衡", 0.999), ("乃", 0.9)]),
        MatchRec(id="tbook:1:3:2", slot=2, verdict="same", char="衡", matched_id="v2:lib:1:1:2",
                 cov=0.999, candidates=[("衡", 0.999)]),
        MatchRec(id="tbook:1:3:3", slot=3, verdict="same", char="乃", matched_id="v2:lib:1:1:9",
                 cov=0.999, candidates=[("乃", 0.999), ("衡", 0.5)]),
    ]
    base = _run_seed(tmp_path, monkeypatch, p, recs)
    off = _run_seed(tmp_path, monkeypatch, p, recs, shadow_veto=False)
    assert {k: v.model_dump() for k, v in base.items()} == {k: v.model_dump() for k, v in off.items()}
    assert all(r.admit for r in base.values())

    gate = ShadowGate(_StubModel({"乃": .95, "衡": .02}), _ctx(), 0.9)
    monkeypatch.setattr(sa, "_shadow_gate", lambda _p: gate)
    on = _run_seed(tmp_path, monkeypatch, p, recs, shadow_veto=True, shadow_model_fingerprint="x")
    assert not on[1].admit and "shadow_veto" in on[1].doubts
    ev = on[1].evidence["shadow_veto"]
    assert ev["pick"] == "乃" and ev["model"] == "stub@0" and ev["conf"] >= 0.9
    assert on[1].char == "衡"                                   # 字不改，只降级
    assert on[2].admit and on[3].admit                           # 单候选 / 影子同意：不动
    assert all("shadow_veto" not in r.evidence for r in (on[2], on[3]))
