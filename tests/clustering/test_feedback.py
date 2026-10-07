"""feedback.py 单测：事件流重放的确定性 + 簇号重绑。"""

from open_guji_cv.clustering.feedback import remap_events, replay_events


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


def test_remap_requires_quorum():
    """重绑法定人数：得票不足原成员半数 → 保留原簇号（事件失效）。"""
    ev = {"op": "flag", "cluster": "cOLD", "flag": "impure",
          "members": ["a", "b", "c", "d", "e", "f"]}
    # 6 成员只有 2 个还在，且都落在大簇 cBIG → 不足半数，拒绑
    out, n = remap_events([ev], {"a": "cBIG", "b": "cBIG"})
    assert n == 0 and out[0]["cluster"] == "cOLD"
    # 4/6 落在同簇 → 过半，重绑
    out, n = remap_events([ev], {m: "cNEW" for m in "abcd"})
    assert n == 1 and out[0]["cluster"] == "cNEW"
