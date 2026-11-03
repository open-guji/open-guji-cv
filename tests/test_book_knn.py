"""字组书级刻形近邻判法（`groups.book_knn`）：A 档、B 档要整理本同字、组外字护栏。数据全在测试里造。"""
import cv2
import numpy as np

from open_guji_cv.groups import book_knn, rr_shape


def _canvas():
    return np.full((120, 120), 255, np.uint8)


def box(dx=0):
    """口：四边框。"""
    g = _canvas()
    cv2.rectangle(g, (20 + dx, 20), (100 + dx, 100), 0, 7)
    return g


def cross(dx=0):
    """十：一横一竖。"""
    g = _canvas()
    cv2.line(g, (15 + dx, 60), (105 + dx, 60), 0, 7)
    cv2.line(g, (60 + dx, 10), (60 + dx, 110), 0, 7)
    return g


def _model(**kw):
    imgs = [box(d) for d in (-4, -2, 0, 2, 4)] + [cross(d) for d in (-4, -2, 0, 2, 4)]
    F = np.array([rr_shape.features(g)[0] for g in imgs])
    m = F.mean(0)
    _, _, vt = np.linalg.svd(F - m, full_matrices=False)
    P = vt[:4]
    d = {"schema": book_knn.SCHEMA, "group": "t", "pca_mean": m, "pca": P, "bank": (F - m) @ P.T,
         "labels": np.array(list("口口口口口十十十十十")), "k": 5, "votes_min": 5, "ratio_max": 0.8,
         "ref_votes_min": 4, "ref_ratio_max": 1.0, "guard": 1e9}
    d.update(kw)
    return d


def test_tier_a():
    m = _model()
    assert book_knn.judge(box(1), m)["char"] == "口"
    v = book_knn.judge(cross(1), m)
    assert (v["char"], v["tier"]) == ("十", "A")


def test_tier_b_needs_ref():
    m = _model(votes_min=99)                       # A 档关掉：只剩 B 档
    assert book_knn.judge(box(1), m)["char"] is None
    v = book_knn.judge(box(1), m, ref="口")
    assert (v["char"], v["tier"]) == ("口", "B")
    assert book_knn.judge(box(1), m, ref="十")["char"] is None


def test_guard_and_blank():
    assert book_knn.judge(box(1), _model(guard=0.0))["why"] == "abstain:out_of_group"
    assert book_knn.judge(_canvas(), _model())["char"] is None
