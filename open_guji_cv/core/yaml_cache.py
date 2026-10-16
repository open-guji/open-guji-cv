"""按文件 mtime 缓存 yaml 解析结果（`load_book` / `load_pipeline` 在绑定表、定字裁决载入里被每页调一遍，
全书 173 页解析 500+ 次共 6.5 秒；GUJI-525）。

只缓存**解析出的 dict**，每次返回深拷贝——调用方照旧拿到自己的一份，改了不会串；
文件改了（mtime_ns 或大小变）自动重读。缓存键是绝对路径，换工作区不会串。
"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

_CACHE: dict[str, tuple[tuple[int, int], object]] = {}


def load_yaml_cached(path: Path):
    p = Path(path)
    st = p.stat()
    sig = (st.st_mtime_ns, st.st_size)
    key = str(p.resolve())
    hit = _CACHE.get(key)
    if hit is None or hit[0] != sig:
        with open(p, encoding="utf-8") as f:
            hit = (sig, yaml.safe_load(f) or {})
        _CACHE[key] = hit
    return copy.deepcopy(hit[1])
