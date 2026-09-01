"""feedback.py 单测：事件流重放的确定性 + 阈值标定。"""

import numpy as np
import pytest

from open_guji_cv.clustering.feedback import (calibrate_threshold,
                                              replay_events)


def test_confirm_and_relabel_precedence():
    state = replay_events([
        {"op": "confirm", "cluster": "c1", "char": "通"},
        {"op": "relabel", "instance": "b:1:1:5", "char": "遇"},
    ])
    assert state.label_of("b:1:1:0", "c1") == "通"
    assert state.label_of("b:1:1:5", "c1") == "遇"   # 改判优先于簇标签


def test_split_removes_member():
    state = replay_events([
        {"op": "confirm", "cluster": "c1", "char": "通"},
        {"op": "split", "cluster": "c1", "moved": ["b:1:1:9"]},
    ])
    assert state.label_of("b:1:1:0", "c1") == "通"
    assert state.label_of("b:1:1:9", "c1") is None   # 被移出，标签不再适用
    assert state.diff_pairs   # 产生了异类对证据


def test_merge_inherits_label():
    state = replay_events([
        {"op": "confirm", "cluster": "c2", "char": "查"},
        {"op": "merge", "clusters": ["c1", "c2"]},
    ])
    # c2 并入 c1，标签由代表簇继承
    assert state.label_of("x", "c1") == "查"
    assert state.label_of("x", "c2") == "查"


def test_later_confirm_overrides():
    state = replay_events([
        {"op": "confirm", "cluster": "c1", "char": "日"},
        {"op": "confirm", "cluster": "c1", "char": "曰"},
    ])
    assert state.label_of("x", "c1") == "曰"


def test_mark():
    state = replay_events([
        {"op": "mark", "instance": "b:1:1:3", "flag": "damaged"},
    ])
    assert state.marks["b:1:1:3"] == "damaged"


def test_calibrate_threshold_separable():
    """same/diff 分布可分时，选出的阈值应落在两分布之间且满足纯度。"""
    rng = np.random.default_rng(0)
    same = np.clip(rng.normal(0.9, 0.03, 500), 0, 1)
    diff = np.clip(rng.normal(0.5, 0.08, 500), 0, 1)
    result = calibrate_threshold(same, diff, max_impurity=0.01)
    theta = result["theta_high"]
    assert 0.6 < theta < 0.9
    assert result["same_recall"] > 0.8
    # 验证纯度约束确实满足
    accepted_diff = np.count_nonzero(diff >= theta)
    accepted = accepted_diff + np.count_nonzero(same >= theta)
    assert accepted_diff / accepted <= 0.01


def test_calibrate_threshold_inseparable_rejects_all():
    """完全重叠的分布 → theta=1.0（拒绝一切合并），绝不牺牲纯度。"""
    same = np.full(100, 0.7)
    diff = np.full(100, 0.7)
    result = calibrate_threshold(same, diff, max_impurity=0.001)
    assert result["theta_high"] == 1.0


def test_calibrate_requires_same_samples():
    with pytest.raises(ValueError):
        calibrate_threshold(np.array([]), np.array([0.5]))
