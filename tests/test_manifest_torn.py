# -*- coding: utf-8 -*-
"""manifest 追加写被杀留下半行时，读表不抛异常、该页按没记过处理（续跑用）。"""
from __future__ import annotations

from open_guji_cv.products.manifest import Manifest, ManifestEntry


def test_torn_last_line_is_skipped(tmp_path):
    p = tmp_path / "manifest.jsonl"
    m = Manifest(p)
    m.put(ManifestEntry(key="p0001", fingerprint="a"))
    m.put(ManifestEntry(key="p0002", fingerprint="b"))
    with open(p, "a", encoding="utf-8") as f:
        f.write('{"key": "p0003", "fingerprint": "c", "sha2')     # 写到一半被杀
    got = Manifest(p)
    assert got.get("p0001").fingerprint == "a"
    assert got.get("p0002").fingerprint == "b"
    assert got.get("p0003") is None
    got.put(ManifestEntry(key="p0003", fingerprint="c"))          # 补跑后能继续追加
    assert Manifest(p).get("p0003").fingerprint == "c"
