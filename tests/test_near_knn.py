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


def test_witness3_knn_veto(tmp_path, monkeypatch):
    """witness3 否决：刻例近邻指向库首位才否决；指向整理本字、skip_chars、取不到字块都照旧放（返回 None）。"""
    from types import SimpleNamespace
    from open_guji_cv.steps import seed_admit as sa
    path = tmp_path / "near_knn.json"
    path.write_text(json.dumps(_model(skip_chars=["一"]), ensure_ascii=False), encoding="utf-8")
    near_knn.load.cache_clear()
    p = SimpleNamespace(group_flow_near_knn=str(path))
    monkeypatch.setattr(sa, "_page_patch", lambda ctx, page, col, slot, sub: box(0))
    veto = sa._witness3_knn_veto_fn(p, None, 1)
    rec = SimpleNamespace(slot=1, sub=None)
    v = veto(1, rec, "口", "十")                      # 图是 口＝库首位，整理本说 十 → 否决
    assert v and v["pick"] == "口"
    assert veto(1, rec, "十", "口") is None           # 图是 口＝整理本字 → 照旧放
    assert veto(1, rec, "口", "一") is None           # skip_chars
    def boom(*a):
        raise sa.PatchUnavailable("x")
    monkeypatch.setattr(sa, "_page_patch", boom)
    assert veto(1, rec, "口", "十") is None           # 取不到字块 fail-open


def test_near_knn_gap(tmp_path, monkeypatch):
    """near_knn_gap：库没把握、库首位≠整理本的格也收，候选＝本格字＋整理本＋库前三；给的字须等于整理本（或同组异体）才放。"""
    from types import SimpleNamespace as NS
    from open_guji_cv.steps import seed_admit as sa
    path = tmp_path / "near_knn.json"
    path.write_text(json.dumps(_model(), ensure_ascii=False), encoding="utf-8")
    near_knn.load.cache_clear()
    monkeypatch.setattr(sa, "_page_patch", lambda ctx, page, col, slot, sub: box(0))

    def run(gap, ref):
        r = NS(id="c1", char="十", admit=False, provenance="match", channel=None, evidence={}, doubts=["lib_unsure"],
               slot=1, sub=None)
        p = NS(group_flow_near_knn=str(path), near_knn_gap=gap, patch_missing="skip")
        m = NS(char=None, candidates=[("十", 0.9), ("口", 0.8), ("一", 0.5)])
        n = sa._near_knn_pass(p, [NS(col=1, chars=[r])], {"c1": (ref,)}, {"c1": m}, stage="gap" if gap else "near")
        return n, r
    assert run(False, "口")[0] == 0                       # 关：不在护栏／字组的格不碰
    n, r = run(True, "口")
    assert n == 1 and r.char == "口" and r.channel == "near_knn" and r.evidence["near_knn"]["via"] == "near_gap"
    n, r = run(True, "十")                                 # 库首位＝整理本：不进
    assert n == 0 and "near_knn" not in r.evidence
    n, r = run(True, "一")                                 # 给 口 ≠ 整理本 一、也非异体 → 出口闸留审
    assert n == 0 and r.evidence["near_knn"]["why"] == "abstain:ref_gate"
