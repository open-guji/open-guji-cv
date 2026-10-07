"""`guji cache build-rare-index --jobs`：分片多进程建表与单进程逐位相同（overview#429）。

不装 torch、不读 checkpoint：注入假的分片构建函数（逐字向量只取决于字本身，
与真 `build_emb_matrix` 的性质相同），只验分片与拼接的顺序。"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from open_guji_cv.ops.rare_index_build import build_parallel, shards


def _vec(ch: str) -> np.ndarray:
    rng = np.random.default_rng(ord(ch))
    return rng.standard_normal(256).astype(np.float32)


def _fake_shard(args):
    _ckpt, shard, _extra, _tag = args
    keep = [c for c in shard if c != "丟"]           # 模拟「全部字体渲染失败」的字被跳过
    return (np.stack([_vec(c) for c in keep]) if keep else np.zeros((0, 256), np.float32)), keep


class _Inst:
    ckpt = Path("best.pt")

    def emb_index_key(self, cs):
        return "k", Path("emb_k.npz"), {}


def test_shards_keep_order_and_cover_everything():
    cs = tuple("甲乙丙丁戊己庚")
    for n in (1, 2, 3, 7, 20):
        parts = shards(cs, n)
        assert sum(parts, ()) == cs and all(parts) and len(parts) == min(n, len(cs))


def test_parallel_matches_sequential_bitwise():
    cs = tuple("天地玄黃丟宇宙洪荒日月")
    seq_mat, seq_names = _fake_shard(("", cs, {}, ""))
    for jobs in (1, 3, 4):
        mat, names = build_parallel(_Inst(), cs, jobs, build_shard=_fake_shard)
        assert names == seq_names and np.array_equal(mat, seq_mat)
