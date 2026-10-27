# -*- coding: utf-8 -*-
"""把本机算好的派生缓存存上 R2（manager 一侧；原在 `clustering/font_pack.py`，2026-10-27 拆分 M3 挪来）。"""

from __future__ import annotations

from ..clustering import font_pack as FP


def push_packs(src=None) -> list[str]:
    """本机 `cache_root()/fontdb/*.sqlite` 里 R2 还没有的，存上去（gzip）。要正式令牌，手动跑。"""
    from ..datastore import packs as P
    src = src or P._client()
    have = {r["key"].rsplit("/", 1)[0] for r in
            src._call("GET", "/v1/packs", query={"bucket": P._bucket(src), "prefix": f"derived/{FP.R2_DIR}/"})["packs"]
            if r["key"].endswith("/manifest.json")}
    done = []
    for f in sorted(FP.local_dir().glob("*.sqlite")):
        key = f"derived/{FP.R2_DIR}/{f.name}"
        if key not in have:
            P.push_file(key, f, src=src, gzip_level=1)
            done.append(key)
    return done
