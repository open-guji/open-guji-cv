# -*- coding: utf-8 -*-
"""页型「正文/非正文」模型闸：关着不改产物、信号口径、模型读写、弃权不拦。自造数据，不依赖仓外。"""
import numpy as np
import pytest

from open_guji_cv.gates.border_detect_gate import BorderDetectGateParams
from open_guji_cv.pagetype_model import signals as S
from open_guji_cv.products.kinds.border_detect_gate import BorderDetectGateManifest


def _page(h=1200, w=900, text=True):
    g = np.full((h, w), 255, np.uint8)
    xs = [50 + i * 90 for i in range(10)]
    for x in xs:
        g[:, x:x + 3] = 0                        # 界行
    if text:
        for i in range(9):
            for r in range(100, 1100, 100):
                g[r:r + 60, xs[i] + 20:xs[i] + 70] = 0
    return g, {"verticals": [{"x_at_top": float(w - x), "slope": 0.0} for x in xs], "width": w,
               "head_raise": [], "bend_w80_med": 3.0, "bend_w80_max": 4.0,
               "top_outer_offset": -30.0, "bottom_outer_offset": 30.0,
               "top_frame_kind": "double", "bottom_frame_kind": "double"}


def test_params_off_dump_unchanged():
    d = BorderDetectGateParams().model_dump(mode="json")
    assert not any(k.startswith("pagetype_model") for k in d)
    on = BorderDetectGateParams(pagetype_model=True).model_dump(mode="json")
    assert on["pagetype_model"] is True and on["pagetype_model_fingerprint"]


def test_manifest_none_not_in_dump():
    m = BorderDetectGateManifest(page=1, admitted=True, n_cols=9, expected_cols=9)
    assert "pagetype_model" not in m.model_dump(mode="json")
    m2 = BorderDetectGateManifest(page=1, admitted=False, n_cols=9, expected_cols=9, pagetype_model={"reason": "nonbody"})
    assert m2.model_dump(mode="json")["pagetype_model"]["reason"] == "nonbody"


def test_signals_full_and_gray_only():
    g, b = _page()
    f = S.extract(g, b)
    assert set(S.FEATURES) <= set(f)
    assert f["n_cols"] == 9 and f["col_empty_n"] == 0 and f["col_ink_mean"] > 0
    f0 = S.extract(g, None)
    assert np.isnan(f0["n_cols"]) and f0["ink"] == f["ink"]


def test_signals_empty_columns_counted():
    g, b = _page(text=False)
    assert S.extract(g, b)["col_empty_n"] == 9


def test_model_roundtrip_and_gate_abstain(tmp_path):
    pytest.importorskip("sklearn")
    from sklearn.ensemble import HistGradientBoostingClassifier
    import pandas as pd
    from open_guji_cv.pagetype_model.gate import PageTypeGate
    from open_guji_cv.pagetype_model.model import file_fingerprint, load_model, save_model
    g1, b1 = _page(); g0, b0 = _page(text=False)
    rows = [S.extract(g1, b1)] * 20 + [S.extract(g0, b0)] * 20
    X = pd.DataFrame(rows)[list(S.FEATURES)]
    y = [0] * 20 + [1] * 20
    clf = HistGradientBoostingClassifier(max_iter=20).fit(X, y)
    p = tmp_path / "m.joblib"
    fp = save_model(p, [{"name": "a", "clf": clf, "features": list(S.FEATURES), "thr": 0.5}], {"model_id": "t"})
    assert fp == file_fingerprint(p) and p.with_suffix(".json").exists()
    gate = PageTypeGate(load_model(p))
    assert gate.judge(g0, b0).nonbody and not gate.judge(g1, b1).nonbody
    v = gate.judge(g0, None)                           # 无 Step1 产物 → 弃权，不拦
    assert not v.nonbody and v.reason.startswith("abstain")
    assert not gate.judge(None, b0).nonbody            # 异常 → 弃权
