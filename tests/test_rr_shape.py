"""入人八 书级刻形判法（`groups.rr_shape`）：几何判 八、组外字护栏、分差门槛、NaN 不误判。数据全在测试里造。"""
import cv2
import numpy as np

from open_guji_cv.groups import rr_shape

PARAMS = {"ba_rtop_max": 0.05, "ba_ltop_min": 0.2, "ba_rh_min": 0.8, "ba_lh_min": 0.5, "ba_ratio_min": 0.3,
          "ren_rtop_min": 0.3}


def _canvas():
    return np.full((120, 120), 255, np.uint8)


def ba():
    """八：右笔从顶上起、左笔起点低，两笔不相连。"""
    g = _canvas()
    cv2.line(g, (62, 8), (110, 110), 0, 7)
    cv2.line(g, (50, 40), (12, 110), 0, 7)
    return g


def ren():
    """人：左撇从顶上起，右捺从左撇中段出，一笔连着。"""
    g = _canvas()
    cv2.line(g, (60, 8), (12, 110), 0, 7)
    cv2.line(g, (40, 55), (110, 110), 0, 7)
    return g


def ru():
    """入：右捺从顶上起，左撇短、连在顶上。"""
    g = _canvas()
    cv2.line(g, (50, 8), (110, 110), 0, 7)
    cv2.line(g, (55, 25), (12, 110), 0, 7)
    return g


def _model(bank_imgs, ren_imgs, ru_imgs, *, guard=1e9, thr=0.5):
    F = np.array([rr_shape.features(g)[0] for g in bank_imgs])
    pm = F.mean(0)
    _, _, vt = np.linalg.svd(F - pm, full_matrices=False)
    pc = vt[:3]
    X = np.array([rr_shape.features(g)[0] for g in ren_imgs + ru_imgs])
    y = np.array([0] * len(ren_imgs) + [1] * len(ru_imgs))
    mu, sd = X.mean(0), np.maximum(X.std(0), 1e-3)
    w = ((X[y == 1] - mu) / sd).mean(0) - ((X[y == 0] - mu) / sd).mean(0)
    b = -float((((X - mu) / sd) @ w).mean())
    return {"schema": rr_shape.SCHEMA, "mean": mu, "scale": sd, "coef": w, "intercept": b,
            "pca_mean": pm, "pca": pc, "bank": (F - pm) @ pc.T, "params": PARAMS, "thr": thr, "guard": guard}


def _shift(g, dx):
    return np.roll(g, dx, axis=1)


def test_geometry_ba_vs_ren():
    gb = rr_shape.features(ba())[1]
    assert gb["n"] == 2 and rr_shape.is_ba(gb, PARAMS)
    assert rr_shape.features(ren())[1]["n"] == 1


def test_judge_three_chars():
    rens = [_shift(ren(), d) for d in (-3, 0, 3)]
    rus = [_shift(ru(), d) for d in (-3, 0, 3)]
    m = _model(rens + rus + [ba()], rens, rus)
    assert rr_shape.judge(ba(), m)["char"] == "八"
    assert rr_shape.judge(ren(), m)["char"] == "人"
    assert rr_shape.judge(ru(), m)["char"] == "入"


def test_guard_and_margin_abstain():
    rens = [_shift(ren(), d) for d in (-3, 0, 3)]
    rus = [_shift(ru(), d) for d in (-3, 0, 3)]
    m = _model(rens + rus, rens, rus, guard=0.0)
    assert rr_shape.judge(ren(), m)["why"] == "abstain:out_of_group"
    m = _model(rens + rus, rens, rus, thr=1e9)
    assert rr_shape.judge(ren(), m)["why"] == "abstain:low_margin"


def test_blank_and_nan_abstain():
    rens = [_shift(ren(), d) for d in (-3, 0, 3)]
    rus = [_shift(ru(), d) for d in (-3, 0, 3)]
    m = _model(rens + rus, rens, rus)
    assert rr_shape.judge(_canvas(), m)["char"] is None
    m["scale"] = np.zeros_like(m["scale"])           # 导出时 scale 被四舍五入成 0：不能落成「人」
    assert rr_shape.judge(ren(), m)["char"] is None
