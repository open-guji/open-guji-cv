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
