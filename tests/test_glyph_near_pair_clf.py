"""3b `glyph_near` 的 pair_clf 方法（3a `glyph_match.stages.pair` 的 5a.3 按书字对分类器搬进 3b，结构拆分 A4，2026-11-28）。

一致性：同一张图、同一个相似度模型与分类器文件，走 3a（`normalize_patch` → `sim_cnn.embed` → `pair_clf.judge`）与走 3b 方法，
证据同键同值。相似度网络随机初始化现造，分类器文件现写，不依赖 R2。
"""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import numpy as np
import pytest

from open_guji_cv.groups import near_methods as NM
from open_guji_cv.groups import pair_clf
import open_guji_cv.steps  # noqa: F401  —— 注册 glyph_match（方法按它的参数取 norm_stroke／sim_model）

torch = pytest.importorskip("torch")
cv2 = pytest.importorskip("cv2")


@pytest.fixture
def files(tmp_path):
    from open_guji_cv.clustering.sim_cnn import SimNet, model_sha256
    torch.manual_seed(0)
    sim = tmp_path / "sim.pt"
    torch.save(SimNet().state_dict(), sim)
    rng = np.random.default_rng(1)
    d = {"version": 3, "sim_model": model_sha256(str(sim))[:12],
         "pairs": {"乙甲": {"a": "甲", "b": "乙", "tier": 2, "w": rng.normal(0, 3, 128).round(4).tolist(), "bias": 0.1, "p_min": 0.6},
                   "丙甲": {"a": "甲", "b": "丙", "tier": 0, "w": []}},
         "context": ["己已"]}
    f = tmp_path / "pair_clf.json"
    f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return f, sim


def _img(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    g = np.full((70, 60), 255, np.uint8)
    for _ in range(5):
        x0, y0, x1, y1 = (int(v) for v in rng.integers(5, 55, 4))
        cv2.line(g, (x0, y0), (x1, y1), 0, 4)
    return g


def _spec(files, pair=("甲", "乙")):
    f, sim = files
    return {"path": str(f), "pair": list(pair), "sim": str(sim)}


def test_spec_and_errors(files):
    f, sim = files
    m = NM.load_method("pair_clf", _spec(files))
    assert m.patch == "char_patch" and m.key == "乙甲"
    with pytest.raises(ValueError, match="要写"):
        NM.load_method("pair_clf", str(f))
    with pytest.raises(ValueError, match="没有字对"):
        NM.load_method("pair_clf", _spec(files, ("甲", "丁")))
    with pytest.raises(ValueError, match="sim"):
        NM.parse_spec({"path": str(f), "sim": str(sim)})
    other = sim.with_name("other.pt")
    torch.save(torch.load(sim), other)
    torch.manual_seed(5)
    from open_guji_cv.clustering.sim_cnn import SimNet
    torch.save(SimNet().state_dict(), other)
    with pytest.raises(ValueError, match="对不上"):
        NM.load_method("pair_clf", {"path": str(f), "pair": ["甲", "乙"], "sim": str(other)})


@pytest.mark.parametrize("punct", [False, True])
@pytest.mark.parametrize("ns", [None, 3])
def test_same_evidence_as_3a(files, punct, ns):
    from open_guji_cv.clustering.normalize import normalize_patch
    from open_guji_cv.clustering.sim_cnn import embed, load_net
    f, sim = files
    imgs = [_img(s) for s in range(6)]
    model = pair_clf.load(f)
    ctx = NS(params_for=lambda step: NS(sim_model={"path": str(sim)}, norm_stroke=ns), book=NS(norm_stroke=None))
    m = NM.load_method("pair_clf", _spec(files))
    outs = NM.score(m, imgs, "b", ctx=ctx, cells=[{"punct": punct} for _ in imgs])
    E = embed(load_net(str(sim)), [normalize_patch(g, stroke_width=ns, isotropic=punct) for g in imgs])
    for o, e in zip(outs, E):
        want = pair_clf.judge(model, "乙甲", e)                    # 3a stage_pair／_pair_unsure 的那一行
        assert o["evidence"] == {"method": "pair_clf", **want}
        assert o["sims"] == {"乙": want["p"], "甲": round(1 - want["p"], 4)}
        assert m.calibrate(o["sims"]) is None
    assert all("p" in o["evidence"] for o in outs)


def test_book_norm_stroke_and_sim_mismatch(files, tmp_path):
    from open_guji_cv.clustering.sim_cnn import SimNet
    f, sim = files
    m = NM.load_method("pair_clf", _spec(files))
    ctx = NS(params_for=lambda step: NS(sim_model={"path": str(sim)}, norm_stroke=None), book=NS(norm_stroke=4))
    assert m._norm(ctx) == 4
    other = tmp_path / "o.pt"
    torch.manual_seed(9)
    torch.save(SimNet().state_dict(), other)
    bad = NS(params_for=lambda step: NS(sim_model={"path": str(other)}, norm_stroke=None), book=NS(norm_stroke=None))
    with pytest.raises(ValueError, match="不是同一个模型"):
        m.score([_img(0)], "b", ctx=bad, cells=[{}])


def test_context_and_tier0_pairs_give_no_sims(files):
    f, sim = files
    d = json.loads(f.read_text(encoding="utf-8"))
    d["pairs"]["已己"] = {"a": "己", "b": "已", "tier": 2, "w": [0.0] * 128}
    f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    for pair, tier in ((("甲", "丙"), 0), (("己", "已"), "context")):
        (o,) = NM.load_method("pair_clf", _spec(files, pair)).score([_img(0)], "b", cells=[{}])
        assert o["sims"] == {} and o["evidence"]["tier"] == tier


def test_fingerprint(files, tmp_path):
    f, sim = files
    fp = NM.method_fingerprint("pair_clf", _spec(files))
    assert fp == NM.method_fingerprint("pair_clf", _spec(files, ("乙", "甲")))          # 字对次序不论
    assert fp != NM.method_fingerprint("pair_clf", _spec(files, ("甲", "丙")))
    assert fp == "pair_clf=" + NM.load_method("pair_clf", _spec(files)).fingerprint()
    assert NM.load_method("pair_clf", _spec(files)).model_sha == pair_clf.fingerprint(f)
