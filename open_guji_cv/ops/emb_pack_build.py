# -*- coding: utf-8 -*-
"""建一版全字表字形向量包（hanzi 库 B2）：`guji cache build-emb-pack`。读取与版本见 `clustering/emb_pack.py`。

放在 ops（L4）是因为要复用 `ops.rare_index_build.build_parallel` 的分片多进程建法，
与 `guji cache build-rare-index` 逐位相同。
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np

from ..clustering.emb_pack import EMB_DIR, FILES, REPO, current_spec, version_of


def full_charset() -> tuple[str, ...]:
    """建包用的全字表：hanzi 库的码位全集（Unihan 统一汉字）∪ `config/ids/ids_lv1.txt` 的字头，按码位排。"""
    import sqlite3

    from ..hanzi.pack import Pack
    con = sqlite3.connect(Pack().ensure("parts"))
    cs: set[str] = {r[0] for r in con.execute("SELECT ch FROM chars")}
    con.close()
    ids = REPO / "config" / "ids" / "ids_lv1.txt"
    for line in ids.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            cs.add(line.split("\t", 1)[0])
    return tuple(sorted((c for c in cs if len(c) == 1), key=ord))


def build(out: Path, chars: tuple[str, ...] | None = None, jobs: int = 4, emb_dir: Path = EMB_DIR,
          log=print) -> dict:
    """在本机建一版（要 torch 与 checkpoint）：写三个文件到 `out/`，清单写进 `emb_dir/<版本>.json`。"""
    import time

    from ..hanzi.pack import blob_cache_path
    from ..ops.rare_index_build import build_parallel
    from . import cnn_candidates as cc
    from .synth import render_char
    spec = current_spec()
    inst = cc.CnnCandidates(ckpt=cc.DEFAULT_CKPT)
    if not inst._ensure():
        raise RuntimeError(f"checkpoint 不可用（{inst.ckpt}）或没装 torch")
    cs = chars or full_charset()
    t0 = time.time()
    log(f"建向量包：{len(cs)} 字，{jobs} 进程，规格 {spec}")
    mat, names = build_parallel(inst, cs, jobs) if jobs > 1 else cc.build_emb_matrix(
        inst._net, inst._dev, cs, {}, render_char)
    secs = time.time() - t0
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    ok = set(names)
    buf = io.BytesIO()
    np.save(buf, mat.astype(np.float32), allow_pickle=False)
    (out / "vectors.npy").write_bytes(buf.getvalue())
    (out / "chars.txt").write_text("".join(c + "\n" for c in names), encoding="utf-8")
    (out / "failed.txt").write_text("".join(c + "\n" for c in cs if c not in ok), encoding="utf-8")
    m = {"version": version_of(spec), **spec, "dim": int(mat.shape[1]), "dtype": "float32",
         "n_chars": len(names), "n_failed": len(cs) - len(names), "charset": "hanzi chars ∪ ids_lv1",
         "build_seconds": round(secs), "jobs": jobs,
         "files": {n: {"sha256": hashlib.sha256((out / n).read_bytes()).hexdigest(),
                       "bytes": (out / n).stat().st_size} for n in FILES}}
    for n, f in m["files"].items():                      # 本机 blob 缓存也放一份，本机取用不用再下
        bp = blob_cache_path(f["sha256"])
        bp.parent.mkdir(parents=True, exist_ok=True)
        bp.write_bytes((out / n).read_bytes())
    Path(emb_dir).mkdir(parents=True, exist_ok=True)
    (Path(emb_dir) / f"{m['version']}.json").write_text(
        json.dumps(m, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    log(f"建好 {m['version']}：{len(names)} 字，失败 {m['n_failed']}，{secs:.0f} 秒")
    return m
