"""形近护栏格书级刻形近邻（`groups.near_knn`）：候选限定、全库同意、护栏、float16 打包。数据全在测试里造。"""
import json

import cv2
import numpy as np

from open_guji_cv.groups import near_knn, rr_shape


def _canvas():
    return np.full((120, 120), 255, np.uint8)


def box(dx=0):
    g = _canvas()
    cv2.rectangle(g, (20 + dx, 20), (100 + dx, 100), 0, 7)
    return g


def cross(dx=0):
    g = _canvas()
    cv2.line(g, (15 + dx, 60), (105 + dx, 60), 0, 7)
    cv2.line(g, (60 + dx, 10), (60 + dx, 110), 0, 7)
    return g


def bar(dx=0):
    g = _canvas()
    cv2.line(g, (15 + dx, 60), (105 + dx, 60), 0, 9)
    return g


SH = (-4, -3, -2, -1, 0, 1, 2, 3)


def _model(shapes=(("口", box), ("十", cross), ("一", bar)), **kw):
    imgs, lab = [], []
    for ch, fn in shapes:
        for d in SH:
            imgs.append(fn(d)); lab.append(ch)
    F = np.array([rr_shape.features(g)[0] for g in imgs])
    m = F.mean(0)
    _, _, vt = np.linalg.svd(F - m, full_matrices=False)
    P = vt[:6]
    d = {"schema": near_knn.SCHEMA, "k": 7, "votes_min": 7, "ratio_max": 0.8, "full_votes_min": 4, "min_n": 5,
         "guard": 1e9, "skip_chars": [], "skip_groups": [],
         "pca_mean": near_knn.pack(m), "pca": near_knn.pack(P), "bank": near_knn.pack((F - m) @ P.T), "labels": lab}
    d.update(kw)
    return d


def _load(tmp_path, d):
    p = tmp_path / "near_knn.json"
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    near_knn.load.cache_clear()
    return near_knn.load(str(p))


def test_pick_within_cands(tmp_path):
    m = _load(tmp_path, _model())
    v = near_knn.judge(box(0), m, ["十", "口"])
    assert (v["char"], v["why"]) == ("口", "agree")
    assert near_knn.judge(cross(0), m, ["口", "十"])["char"] == "十"


def test_full_bank_dissent(tmp_path):
    """候选里没有真字（刻 一、候选 口／十）：候选内近邻会挑一个，全库近邻投给 一 → 弃权。"""
    m = _load(tmp_path, _model())
    v = near_knn.judge(bar(0), m, ["口", "十"])
    assert v["char"] is None and v["full"] == "一"


def test_few_cands_and_guard(tmp_path):
    m = _load(tmp_path, _model())
    assert near_knn.judge(box(0), m, ["口"])["why"] == "abstain:few_cands"
    assert near_knn.judge(box(0), m, ["口", "鬱"])["why"] == "abstain:few_cands"     # 库里没有的字不算候选
    m = _load(tmp_path, _model(guard=0.0))
    assert near_knn.judge(box(0), m, ["口", "十"])["why"] == "abstain:out_of_book"
    assert near_knn.judge(_canvas(), m, ["口", "十"])["char"] is None


def test_pack_roundtrip():
    a = np.random.default_rng(0).normal(size=(5, 3)).astype(np.float32)
    assert np.allclose(near_knn.unpack(near_knn.pack(a)), a, atol=1e-2)
    assert near_knn.unpack([[1, 2]]).shape == (1, 2)
