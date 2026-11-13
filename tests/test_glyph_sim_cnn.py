"""5a 精验改用 CNN 相似度的开关（`glyph_match.sim_model`，`clustering.sim_cnn`）。

不开时参数 dump 与改前相同（不让各书产物过期）；开了以后匹配器的逐对分数换成嵌入余弦、
指纹带权重与代码哈希。权重用随机初始化的小网络现造，不依赖 R2 上的真模型。"""

from __future__ import annotations

import numpy as np
import pytest

from open_guji_cv.clustering.match import GlyphMatcher
from open_guji_cv.steps.glyph_match import GlyphMatchParams, _with_sim_model


def _glyph(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    a = np.zeros((64, 64), dtype=np.uint8)
    for _ in range(6):
        x0, y0 = rng.integers(8, 48, 2)
        if rng.random() < 0.5:
            a[y0:y0 + 3, x0:x0 + int(rng.integers(8, 16))] = 1
        else:
            a[y0:y0 + int(rng.integers(8, 16)), x0:x0 + 3] = 1
    return a


def test_off_by_default_dump_unchanged(tmp_path):
    p = GlyphMatchParams(db_path=str(tmp_path / "none.db"), db_fingerprint="x")
    d = p.model_dump()
    assert "sim_model" not in d and "sim_model_sha" not in d
    assert p.sim_model is None and p.sim_model_sha == ""


@pytest.fixture
def weights(tmp_path):
    torch = pytest.importorskip("torch")
    from open_guji_cv.clustering.sim_cnn import SimNet
    torch.manual_seed(0)
    net = SimNet(n_cls=5)            # 带训练用的类中心 W，加载时要丢掉
    f = tmp_path / "sim.pt"
    torch.save(net.state_dict(), f)
    return f


def test_params_fingerprint_when_on(tmp_path, weights):
    p = GlyphMatchParams(db_path=str(tmp_path / "none.db"), db_fingerprint="x",
                         sim_model={"path": str(weights), "same": 0.9})
    d = p.model_dump()
    assert d["sim_model"]["path"] == str(weights)
    sha, code = d["sim_model_sha"].split(":")
    assert len(sha) == 64 and len(code) == 16


def test_matcher_uses_cnn_scores(weights):
    from open_guji_cv.clustering.sim_cnn import CnnVerifier
    m = GlyphMatcher(k=5)
    for i, ch in enumerate("甲乙丙丁戊"):
        m.add(f"v2:001:1:{i + 1}:1", ch, _glyph(i))
    g = _with_sim_model(m, {"path": str(weights), "same": 0.9999995, "low": -1.0})
    assert g is not m and isinstance(g._verify, CnnVerifier)
    assert not isinstance(m._verify, CnnVerifier)          # 缓存里那份不动
    assert _with_sim_model(m, {"path": str(weights), "same": 0.9999995, "low": -1.0}) is g   # 整库嵌入只算一次

    # 随机初始化的网络嵌入挤在一起（别的字也到 0.99999），same 门槛只能放到「同一张图」才过
    q = _glyph(2).copy()                                    # 和库里 丙 一模一样（不同对象）
    r = g.match(q)
    assert r.verdict == "same" and r.char == "丙"
    assert r.cov == pytest.approx(1.0, abs=1e-5)
    # 分数就是嵌入余弦
    v = g._verify
    s = v.score(q, m._patches[0])
    from open_guji_cv.clustering.sim_cnn import embed
    e = embed(v.net, [q, m._patches[0]])
    assert s == pytest.approx(float(e[0] @ e[1]), abs=1e-5)


def test_config_parsing():
    from open_guji_cv.clustering.sim_cnn import SimModelConfig
    assert SimModelConfig.from_any(None) is None
    assert SimModelConfig.from_any("models/x.pt") == SimModelConfig("models/x.pt")
    c = SimModelConfig.from_any({"path": "a.pt", "same": 0.8, "low": 0.4})
    assert (c.same, c.low) == (0.8, 0.4)
    with pytest.raises(ValueError):
        SimModelConfig.from_any({"same": 0.8})


def test_calib_maps_scores_and_fingerprint(tmp_path, weights):
    """权重旁有 calib.json：分数按节点分段线性映射到 cov 尺度，same／low 缺省 0.996／0.85，表进指纹。"""
    import json
    from open_guji_cv.clustering.sim_cnn import CnnVerifier, SimModelConfig, embed, sim_fingerprint
    fp0 = sim_fingerprint(str(weights))
    (weights.parent / "calib.json").write_text(json.dumps({"knots": [[-1, 0], [0.5, 0.9], [1, 1]]}), encoding="utf-8")
    fp1 = sim_fingerprint(str(weights))
    assert fp1.startswith(fp0 + ":") and len(fp1.split(":")) == 3
    a, b = _glyph(0), _glyph(1)
    v = CnnVerifier(SimModelConfig(str(weights)), [b])
    assert (v.same, v.low) == (0.996, 0.85)
    e = embed(v.net, [a, b])
    raw = float(e[0] @ e[1])
    assert v.score(a, b) == pytest.approx(float(np.interp(raw, [-1, 0.5, 1], [0, 0.9, 1])), abs=1e-5)
    (weights.parent / "calib.json").write_text(json.dumps({"knots": [[0, 1], [1, 0.5]]}), encoding="utf-8")
    with pytest.raises(ValueError):
        CnnVerifier(SimModelConfig(str(weights)), [b])


def test_no_calib_defaults(weights):
    from open_guji_cv.clustering.sim_cnn import CnnVerifier, SimModelConfig
    v = CnnVerifier(SimModelConfig(str(weights)), [_glyph(1)])
    assert v.calib is None and (v.same, v.low) == (0.90, 0.50)
    v = CnnVerifier(SimModelConfig(str(weights), same=0.7, low=0.3), [_glyph(1)])
    assert (v.same, v.low) == (0.7, 0.3)


def test_fuse_mean_averages_with_cov(tmp_path, weights):
    """fuse: mean：逐对分＝（校准后 CNN 分＋覆盖分）/2；没校准表拒绝。"""
    import json
    from open_guji_cv.clustering.sim_cnn import CnnVerifier, SimModelConfig
    from open_guji_cv.clustering.verify import verify_pair_elastic
    a, b = _glyph(0), _glyph(1)
    with pytest.raises(ValueError):
        CnnVerifier(SimModelConfig(str(weights), fuse="mean"), [b])
    (weights.parent / "calib.json").write_text(json.dumps({"knots": [[-1, 0], [1, 1]]}), encoding="utf-8")
    v = CnnVerifier(SimModelConfig.from_any({"path": str(weights), "fuse": "mean"}), [b])
    r = v(a, b, cov_high=0.996, miss_wmax=12.0, wmax_floor=0.5)
    cov = verify_pair_elastic(a, b, cov_high=0.996, miss_wmax=12.0).f1
    assert r.f1 == pytest.approx((v.score(a, b) + cov) / 2, abs=1e-6)
    s = v(a, a.copy(), cov_high=0.996, miss_wmax=12.0)
    assert s.f1 == pytest.approx(1.0, abs=1e-5) and s.verdict == "same"
    with pytest.raises(ValueError):
        SimModelConfig.from_any({"path": "x.pt", "fuse": "max"})
