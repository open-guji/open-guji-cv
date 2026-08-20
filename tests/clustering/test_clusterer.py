"""clusterer.py 单测 + 合成集纯度回归。"""

import numpy as np

from open_guji_cv.clustering.clusterer import (ClusterParams,
                                               ConservativeClusterer)
from open_guji_cv.clustering.features import get_feature
from open_guji_cv.clustering.synth import fragmentation, make_dataset, purity


def _run(patches: np.ndarray, feature: str = "raw",
         params: ClusterParams | None = None):
    params = params or ClusterParams(feature=feature)
    feats = get_feature(feature).extract(patches)
    hw = np.ones(len(patches))
    ink = np.array([p.mean() for p in patches])
    return ConservativeClusterer(params).cluster(patches, feats, hw, ink)


def test_synthetic_purity():
    """合成集（20 字 × 8 份 + 磨损）：purity 必须 100%——保守聚类硬指标。"""
    patches, labels = make_dataset(n_chars=20, n_per_char=8, seed=42, wear=0.4)
    result = _run(patches)
    members = [c.members for c in result.clusters]
    p = purity(members, labels)
    assert p >= 0.999, f"purity={p:.4f}"
    # 碎片率是软指标，但完全不聚也能 purity=100%，故加个宽松下限防退化
    frag = fragmentation(members, labels)
    assert frag < 4.0, f"fragmentation={frag:.2f}（几乎没聚起来）"
    # 至少形成一些多成员簇
    assert any(len(m) >= 4 for m in members)


def test_all_identical_single_cluster():
    """完全相同的图块必须聚成一簇。"""
    patches, _ = make_dataset(n_chars=1, n_per_char=6, seed=1, wear=0.0)
    result = _run(patches)
    assert len(result.clusters) == 1
    assert len(result.clusters[0].members) == 6


def test_singletons_preserved():
    """彼此不同的字形应各自成簇（不强行合并）。"""
    patches, labels = make_dataset(n_chars=8, n_per_char=1, seed=5, wear=0.0)
    result = _run(patches)
    members = [c.members for c in result.clusters]
    assert purity(members, labels) >= 0.999
    assert len(result.clusters) == 8


def test_cluster_result_invariants():
    """成员不重不漏；reps ⊆ members；cluster_id 唯一。"""
    patches, _ = make_dataset(n_chars=10, n_per_char=5, seed=9, wear=0.3)
    result = _run(patches)
    seen: set[int] = set()
    ids: set[str] = set()
    for c in result.clusters:
        assert c.cluster_id not in ids
        ids.add(c.cluster_id)
        for m in c.members:
            assert m not in seen
            seen.add(m)
        assert set(c.reps).issubset(set(c.members))
        assert 1 <= len(c.reps) <= result.params.n_reps
    assert len(seen) == len(patches)


def test_deterministic():
    """同参数同输入 → 结果完全一致（seed 固定）。"""
    patches, _ = make_dataset(n_chars=6, n_per_char=4, seed=3, wear=0.3)
    r1 = _run(patches)
    r2 = _run(patches)
    m1 = sorted(tuple(c.members) for c in r1.clusters)
    m2 = sorted(tuple(c.members) for c in r2.clusters)
    assert m1 == m2
