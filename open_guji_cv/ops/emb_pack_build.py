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

from ..clustering.emb_pack import (
    EMB_DIR,
    FILES,
    PRECISIONS,
    REPO,
    current_spec,
    encode,
    version_of,
)


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


#: 每片向量的行数：32,768 行 × 256 维 × 4 字节 ＝ 32 MB。整份 104 MB 经 Worker 上传被拒（10-20 实测 413，
#: 单次请求上限约 100 MB），所以切片，每片单独按 sha 存取。
SHARD_ROWS = 32768


def write_pack(out: Path, mat: np.ndarray, names: list[str], failed: list[str], spec: dict, meta: dict,
               emb_dir: Path = EMB_DIR) -> dict:
    """`(mat, names)` → `out/<精度>/vectors-NN.npy`（int8 另有 `scale.npy`）、`chars.txt`、`failed.txt`，
    三种精度一起写；清单写进 `emb_dir/<版本>.json`，文件同时放进本机 blob 缓存（本机取用不用再下）。"""
    import shutil

    from ..hanzi.pack import blob_cache_path
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rel: list[str] = []
    for prec in PRECISIONS:
        d = out / prec
        if d.exists():
            shutil.rmtree(d)
        d.mkdir()
        arrays = encode(mat, prec)
        for k, i in enumerate(range(0, max(len(mat), 1), SHARD_ROWS)):
            buf = io.BytesIO()
            np.save(buf, arrays["vectors"][i:i + SHARD_ROWS], allow_pickle=False)
            (d / f"vectors-{k:02d}.npy").write_bytes(buf.getvalue())
            rel.append(f"{prec}/vectors-{k:02d}.npy")
        if "scale" in arrays:
            buf = io.BytesIO()
            np.save(buf, arrays["scale"], allow_pickle=False)
            (d / "scale.npy").write_bytes(buf.getvalue())
            rel.append(f"{prec}/scale.npy")
    (out / "chars.txt").write_text("".join(c + "\n" for c in names), encoding="utf-8")
    (out / "failed.txt").write_text("".join(c + "\n" for c in failed), encoding="utf-8")
    m = {"version": version_of(spec), **spec, "dim": int(mat.shape[1]), "precisions": list(PRECISIONS),
         "n_chars": len(names), "n_failed": len(failed), "charset": "hanzi chars ∪ ids_lv1", **meta,
         "files": {n: {"sha256": hashlib.sha256((out / n).read_bytes()).hexdigest(),
                       "bytes": (out / n).stat().st_size} for n in [*rel, *FILES]}}
    for n, f in m["files"].items():
        bp = blob_cache_path(f["sha256"])
        if not bp.exists():
            bp.parent.mkdir(parents=True, exist_ok=True)
            bp.write_bytes((out / n).read_bytes())
    Path(emb_dir).mkdir(parents=True, exist_ok=True)
    (Path(emb_dir) / f"{m['version']}.json").write_text(
        json.dumps(m, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return m


def build(out: Path, chars: tuple[str, ...] | None = None, jobs: int = 4, emb_dir: Path = EMB_DIR,
          log=print) -> dict:
    """在本机建一版（要 torch 与 checkpoint），写进 `out/` 与 `emb_dir/<版本>.json`（`write_pack`）。"""
    import time

    from ..clustering import cnn_candidates as cc
    from ..clustering.synth import render_char
    from .rare_index_build import build_parallel
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
    ok = set(names)
    m = write_pack(out, mat, names, [c for c in cs if c not in ok], spec,
                   {"build_seconds": round(secs), "jobs": jobs}, emb_dir)
    log(f"建好 {m['version']}：{len(names)} 字，失败 {m['n_failed']}，{secs:.0f} 秒")
    return m
