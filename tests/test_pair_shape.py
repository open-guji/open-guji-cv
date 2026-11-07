"""书级两字刻形二选一（`groups.pair_shape`）：两字分得开、组外护栏、分差门槛、模型 schema、补放只认「整理本字或库首位」。数据全在测试里造。"""
import cv2
import numpy as np
import pytest

from open_guji_cv.groups import pair_shape
from open_guji_cv.groups.rr_shape import features


def _canvas():
    return np.full((120, 120), 255, np.uint8)


def a_img():
    g = _canvas()
    cv2.line(g, (60, 8), (12, 110), 0, 7)
    cv2.line(g, (40, 55), (110, 110), 0, 7)
    return g


def b_img():
    g = _canvas()
    cv2.line(g, (8, 40), (112, 40), 0, 7)
    cv2.line(g, (60, 8), (60, 112), 0, 7)
    return g


def _shift(g, dx):
    return np.roll(g, dx, axis=1)


def _model(*, guard=1e9, thr=0.5):
    As = [_shift(a_img(), d) for d in (-3, 0, 3)]
    Bs = [_shift(b_img(), d) for d in (-3, 0, 3)]
    F = np.array([features(g)[0] for g in As + Bs])
    pm = F.mean(0)
    _, _, vt = np.linalg.svd(F - pm, full_matrices=False)
    pc = vt[:3]
    mu, sd = F.mean(0), np.maximum(F.std(0), 1e-3)
    y = np.array([0] * len(As) + [1] * len(Bs))
    w = ((F[y == 1] - mu) / sd).mean(0) - ((F[y == 0] - mu) / sd).mean(0)
    b = -float((((F - mu) / sd) @ w).mean())
    return {"schema": pair_shape.SCHEMA, "chars": ["之", "矣"], "mean": mu, "scale": sd, "coef": w, "intercept": b,
            "pca_mean": pm, "pca": pc, "bank": (F - pm) @ pc.T, "thr": thr, "guard": guard}


def test_judge_two_chars():
    m = _model()
    assert pair_shape.judge(a_img(), m)["char"] == "之"
    assert pair_shape.judge(b_img(), m)["char"] == "矣"


def test_guard_and_margin_abstain():
    assert pair_shape.judge(a_img(), _model(guard=0.0))["why"] == "abstain:out_of_group"
    assert pair_shape.judge(a_img(), _model(thr=1e9))["why"] == "abstain:low_margin"
    assert pair_shape.judge(_canvas(), _model())["why"] == "abstain:no_ink"


def test_load_checks_schema(tmp_path):
    p = tmp_path / "m.json"
    p.write_text('{"schema": "other/1"}', encoding="utf-8")
    with pytest.raises(ValueError):
        pair_shape.load(str(p))


def test_fingerprint_empty_when_missing(tmp_path):
    assert pair_shape.fingerprint(None) == ""
    assert pair_shape.fingerprint(str(tmp_path / "none.json")) == ""


# ── pair_shape/2：墨量图＋组外判别（全唐文 大太／王玉／還遺，2026-11-07）──────────────────────────────

def da_img(dot=False, dx=0):
    """「大」：一横一撇一捺；dot=True 在撇捺之间加一点成「太」。"""
    g = _canvas()
    cv2.line(g, (15, 45), (105, 45), 0, 7)
    cv2.line(g, (60, 10), (60, 50), 0, 7)
    cv2.line(g, (60, 50), (15, 110), 0, 7)
    cv2.line(g, (60, 50), (105, 110), 0, 7)
    if dot:
        cv2.circle(g, (55, 92), 6, 0, -1)
    return _shift(g, dx)


def tian_img():
    """组外字「天」：上多一横。"""
    g = da_img()
    cv2.line(g, (25, 12), (95, 12), 0, 7)
    return g


def _pix_model(*, other=True, thr=0.5):
    def feat(g):
        return pair_shape.pix_features(pair_shape.pix_ink(g))
    A = np.array([feat(da_img(False, d)) for d in (-3, 0, 3)])
    B = np.array([feat(da_img(True, d)) for d in (-3, 0, 3)])
    O = np.array([feat(tian_img())])
    X = np.vstack([A, B])
    mu, sd = X.mean(0), np.ones(X.shape[1], np.float32)
    w = B.mean(0) - A.mean(0)
    b = -float(((X - mu) @ w).mean())
    m = {"schema": pair_shape.SCHEMA_PIX, "chars": ["大", "太"], "size": 32, "thr": thr, "other_thr": 0.0, "veto_thr": 0.5,
         "ab": {"mu": mu, "sd": sd, "coef": w, "b": b}}
    if other:
        wo = O.mean(0) - X.mean(0)
        bo = -float((((O.mean(0) + X.mean(0)) / 2) @ wo))
        m["other"] = {"mu": np.zeros_like(mu), "sd": sd, "coef": wo, "b": bo}
    return m


def test_pix_judge_dot():
    m = _pix_model()
    assert pair_shape.judge(da_img(), m)["char"] == "大"
    assert pair_shape.judge(da_img(True), m)["char"] == "太"


def test_pix_other_guard_and_margin():
    assert pair_shape.judge(tian_img(), _pix_model())["why"] == "abstain:out_of_group"
    assert pair_shape.judge(da_img(), _pix_model(thr=1e9))["why"] == "abstain:low_margin"
    assert pair_shape.judge(_canvas(), _pix_model())["why"] == "abstain:no_ink"


def test_pix_ink_drops_edge_rule_line():
    g = da_img(True)
    g[:, :3] = 0                                     # 贴左边的界行
    ink = pair_shape.pix_ink(g)
    assert ink is not None and ink.shape[1] < 100     # 紧框只跟字身走


def test_pix_load_roundtrip(tmp_path):
    m = _pix_model()
    js = {k: v for k, v in m.items() if k not in ("ab", "other")}
    js["ab"] = {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in m["ab"].items()}
    js["other"] = {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in m["other"].items()}
    p = tmp_path / "dt.json"
    p.write_text(__import__("json").dumps(js, ensure_ascii=False), encoding="utf-8")
    pair_shape.load.cache_clear()
    d = pair_shape.load(str(p))
    assert pair_shape.judge(da_img(True), d)["char"] == "太"


def _admit_page(recs):
    from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit
    return [ColumnAdmit(col=1, chars=[AdmitRec(**r) for r in recs])]


def test_pass_lifts_pending_and_vetoes_admitted(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from open_guji_cv.steps import seed_admit as sa
    m = _pix_model()
    js = {k: v for k, v in m.items() if k not in ("ab", "other")}
    js["ab"] = {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in m["ab"].items()}
    js["other"] = {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in m["other"].items()}
    p = tmp_path / "dt.json"
    p.write_text(__import__("json").dumps(js, ensure_ascii=False), encoding="utf-8")
    pair_shape.load.cache_clear()
    imgs = {1: da_img(True), 2: da_img(False), 3: da_img(True), 4: tian_img(), 5: da_img(True)}
    monkeypatch.setattr(sa, "_page_patch", lambda ctx, page, col, slot, sub: imgs[slot])
    out = _admit_page([
        {"id": "b:1:1:1", "slot": 1, "char": "太", "doubts": ["group_flow_disagree"]},          # 打架格：刻形＝库首位 → 放
        {"id": "b:1:1:2", "slot": 2, "char": "太", "doubts": ["group_flow_disagree"]},          # 刻形说大，库首位太、整理本太 → 不放
        {"id": "b:1:1:3", "slot": 3, "char": "大", "admit": True, "channel": "match_ref", "provenance": "match"},  # 已放行大，刻形太 → veto
        {"id": "b:1:1:4", "slot": 4, "char": "天", "doubts": []},                               # 组外字，整理本说大 → 护栏挡
        {"id": "b:1:1:5", "slot": 5, "char": "大", "admit": True, "channel": "human", "provenance": "human"},      # 人裁不碰
    ])
    amap = {"b:1:1:1": ("太",), "b:1:1:2": ("太",), "b:1:1:3": ("大",), "b:1:1:4": ("大",), "b:1:1:5": ("大",)}
    params = SimpleNamespace(patch_missing="raise", group_flow_pair_shape="")
    d = sa._pair_shape_pass(params, out, amap, model_path=str(p), veto=False)
    r = {x.id: x for x in out[0].chars}
    assert d == 1 and r["b:1:1:1"].admit and r["b:1:1:1"].channel == "pair_shape"
    assert not r["b:1:1:2"].admit and r["b:1:1:3"].admit and not r["b:1:1:4"].admit
    d = sa._pair_shape_pass(params, out, amap, model_path=str(p), veto=True)
    assert d == -1 and not r["b:1:1:3"].admit and "pair_shape_veto" in r["b:1:1:3"].doubts
    assert r["b:1:1:3"].evidence["demoted_from"]["by"] == "pair_shape_veto"
    assert r["b:1:1:5"].admit
