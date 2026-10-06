# -*- coding: utf-8 -*-
"""先纯按形聚类、每类标一次（`group=cluster`，2026-10-01）：键恒定时分簇只由形状决定。"""
import numpy as np

from open_guji_cv.console.routers.review_cluster import cluster_tiles


def _unit(v):
    v = np.asarray(v, np.float32)
    return v / np.linalg.norm(v)


def test_constant_key_merges_by_shape_regardless_of_first_pick():
    # a1/a2 形状相同但「首选字」不同（整理本/AI 一个说今、一个说令）：分字种键下永远不同簇，键恒定则并成一簇
    e = {"a1": _unit([1, 0, 0]), "a2": _unit([0.99, 0.05, 0]), "b": _unit([0, 1, 0])}
    tiles = [{"id": "a1", "pick": "今"}, {"id": "a2", "pick": "令"}, {"id": "b", "pick": "大"}]
    by_char = cluster_tiles(tiles, lambda t: e[t["id"]], lambda t: t["pick"], 0.95)
    by_shape = cluster_tiles(tiles, lambda t: e[t["id"]], lambda t: 0, 0.95)
    assert sorted(c["n"] for c in by_char) == [1, 1, 1]
    assert sorted(c["n"] for c in by_shape) == [1, 2]
    two = next(c for c in by_shape if c["n"] == 2)
    assert {m["id"] for m in two["members"]} == {"a1", "a2"}
