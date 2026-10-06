# -*- coding: utf-8 -*-
"""`guji cache build-rare-index --jobs N`：把 Step5-b embedding 模板表分片多进程建（overview#429）。

## 为什么

`cnn_candidates.build_emb_matrix` 是逐字的：每个字把各套字体渲染成 64² 图、前向一次、
取均值再单位化，字与字之间没有任何耦合。单进程单核（模块 import 时就把 torch/BLAS
线程钉成 1，见 `cnn_candidates` 模块头的反活锁说明），四庫 vol04 两档 29,689 + 42,438 字
在云端 4 核会话里约 25 字/秒，**整整 45–50 分钟**，而其余三个核闲着。

## 做法

字表按原顺序切成 `jobs` 段连续分片，每个子进程各自起一份 `CnnCandidates`，对自己那段调
**同一个** `build_emb_matrix`，主进程按分片顺序把 `(mat, names)` 拼回去、用同一个
`_save_emb_index` 落盘。每个字的向量只取决于它自己的那几张图，与在哪个进程、前后是谁
无关，所以拼出来与单进程建的逐位相同（vol04 基集前 1,000 字实测 `np.array_equal`，2 进程 34.5s → 16.7s）。

不改 `cnn_candidates`（它是 `rare_candidates` 的 `code_deps`，一动各书 5-b 产物全判过期），
只在外面套一层调度。内存是每个子进程各一份网络 + 自己那段的堆积（`_emb_index` 模块头
实测约 5–9 KB/字），合计峰值见 overview#429 交单的实测。
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor


def shards(cs: tuple[str, ...], n: int) -> list[tuple[str, ...]]:
    """按原顺序切成至多 `n` 段连续分片（拼回去顺序不变），空段不出。"""
    n = max(1, min(n, len(cs)))
    step, extra = divmod(len(cs), n)
    out, i = [], 0
    for j in range(n):
        size = step + (1 if j < extra else 0)
        if size:
            out.append(cs[i:i + size])
        i += size
    return out


def _build_shard(args) -> tuple[object, list[str]]:
    """子进程：自建一份网络，对一段字表调产线同一个 `build_emb_matrix`。"""
    ckpt, shard, extra, tag = args
    from ..clustering import cnn_candidates as cc
    from ..clustering.synth import render_char

    inst = cc.CnnCandidates(ckpt=ckpt)
    if not inst._ensure():
        raise RuntimeError(f"checkpoint 不可用：{ckpt}")
    log = (lambda s: print(f"[{tag}] {s}", flush=True))
    return cc.build_emb_matrix(inst._net, inst._dev, shard, extra, render_char, log=log)


def build_parallel(inst, cs: tuple[str, ...], jobs: int, build_shard=_build_shard):
    """→ `(mat, names)`，与 `build_emb_matrix(inst._net, …, cs, …)` 逐位相同。

    `build_shard` 可注入（单测用假的，不必装 torch/读 checkpoint）。"""
    import numpy as np

    _key, _f, extra = inst.emb_index_key(cs)
    parts = shards(tuple(cs), jobs)
    tasks = [(str(inst.ckpt), p, {c: extra[c] for c in p if c in extra}, f"{i + 1}/{len(parts)}")
             for i, p in enumerate(parts)]
    if len(tasks) == 1:
        results = [build_shard(tasks[0])]
    else:
        with ProcessPoolExecutor(max_workers=len(tasks)) as ex:
            results = list(ex.map(build_shard, tasks))
    mats = [m for m, _ in results if len(m)]
    names = [c for _, ns in results for c in ns]
    mat = np.concatenate(mats).astype(np.float32) if mats else np.zeros((0, 256), np.float32)
    return mat, names


def default_jobs() -> int:
    return max(1, os.cpu_count() or 1)
