# -*- coding: utf-8 -*-
"""绑定缓存键带算法哈希（2026-11-26，GM2／CV0）：缓存里 algo 不是本版就重算。"""
from open_guji_cv.feedback import bindings as B


def test_algo_hash_stable_and_short():
    a = B._algo_hash()
    assert a == B._algo_hash() and len(a) == 16


def test_cache_with_other_algo_is_recomputed(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(B, "_bindings_dir", lambda book: tmp_path)
    calls = []
    monkeypatch.setattr(B, "compute_page", lambda *a, **k: calls.append(1) or [{"event": "e1", "status": "valid"}])
    monkeypatch.setattr(B, "_sig", lambda *a, **k: "S")
    f = tmp_path / "p0001.json"
    f.write_text(json.dumps({"v": B._VERSION, "algo": "other", "cells_sha": "C", "sig": "S", "rows": []}), encoding="utf-8")
    rows = B.page_bindings("tb", 1, [], store=object(), backfill={}, cells_sha="C")
    assert calls and rows == [{"event": "e1", "status": "valid"}]
    calls.clear()
    assert B.page_bindings("tb", 1, [], store=object(), backfill={}, cells_sha="C") == [{"event": "e1", "status": "valid"}]
    assert not calls                     # 本版写回的缓存命中
