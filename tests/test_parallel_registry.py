# -*- coding: utf-8 -*-
"""页级并行登记（`core/parallel.py`）与并行时的缓存戳（2026-10-20）。

- 登记在 Step 模块之外，改登记不动任何 Step 的代码指纹；
- 进程数按可用内存压；
- 几个进程同时给同一种类的不同页记戳：不丢戳、不因共用临时文件名而失败。"""

from __future__ import annotations

import multiprocessing as mp

import numpy as np
import pytest

import open_guji_cv.steps  # noqa: F401  —— 注册全部 Step
from open_guji_cv.core import parallel
from open_guji_cv.core.engine import _longest_first
from open_guji_cv.core.step import STEPS
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.manifest import ManifestEntry


def test_audited_steps_exist_and_count_as_safe():
    for sid in parallel.AUDITED:
        assert sid in STEPS, sid
        assert parallel.is_parallel_safe(STEPS[sid])
    assert parallel.is_parallel_safe(STEPS["border_detect"])     # 标在 Step 上的照旧认
    assert not parallel.is_parallel_safe(STEPS["context_decide"])    # 没登记的一律串行


def test_registry_is_not_a_code_dep():
    """登记表要是进了某步的 code_deps，改登记就会让那一步各书产物整体过期——正是放在这里要躲开的。"""
    for sid, st in STEPS.items():
        mods = {type(st).__module__, *st.spec.code_deps}
        assert "open_guji_cv.core.parallel" not in mods, sid
        assert "open_guji_cv.core.engine" not in mods, sid


def test_effective_jobs_caps_by_memory(monkeypatch):
    step = STEPS["glyph_match"]
    gb = parallel.AUDITED["glyph_match"].mem_gb
    monkeypatch.setattr(parallel.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(parallel, "available_memory_gb", lambda: gb * 3.5)
    n, why = parallel.effective_jobs(step, 8)
    assert n == 2 and "内存" in why                  # 3 份装得下，留 1 份给主进程
    monkeypatch.setattr(parallel, "available_memory_gb", lambda: None)
    assert parallel.effective_jobs(step, 8) == (8, None)
    assert parallel.effective_jobs(step, 1) == (1, None)
    monkeypatch.setattr(parallel, "available_memory_gb", lambda: 0.1)
    assert parallel.effective_jobs(step, 8)[0] == 1


def test_worker_threads_split_cores(monkeypatch):
    monkeypatch.setattr(parallel.os, "cpu_count", lambda: 8)
    assert parallel.worker_threads(4) == 2
    assert parallel.worker_threads(16) == 1


def test_longest_first_orders_by_last_elapsed(tmp_path):
    from open_guji_cv.products.store import ProductStore
    m = ProductStore(tmp_path).manifest("b", "s")
    for pg, el in ((1, 2.0), (2, 30.0), (3, 5.0)):
        m.put(ManifestEntry(key=f"p{pg:04d}", fingerprint="x", elapsed=el))
    assert _longest_first([1, 2, 3, 4], m) == [4, 2, 3, 1]     # 没记过耗时的当最难


def _stamp_many(root, pages):
    c = ImageCache(root)
    img = np.zeros((4, 4), np.uint8)
    for pg in pages:
        c.put("b", "char_patch", f"p{pg:04d}_c01_s01", img, stamp=f"sha{pg}")


@pytest.mark.skipif("fork" not in mp.get_all_start_methods(), reason="要 fork")
def test_concurrent_stamps_not_lost(tmp_path):
    ctx = mp.get_context("fork")
    procs = [ctx.Process(target=_stamp_many, args=(tmp_path, range(i, 200, 4))) for i in range(4)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
        assert p.exitcode == 0
    c = ImageCache(tmp_path)
    got = c._read_stamps("b", "char_patch")
    assert got == {f"p{pg:04d}": f"sha{pg}" for pg in range(200)}
    # 锁文件、戳文件不算缓存图：整种类清空不删锁、LRU 不淘汰它们
    assert c.usage()[1] == 200
    c.invalidate("b", "char_patch")
    assert (tmp_path / "b" / "char_patch" / ".stamps.lock").exists()


def test_set_blas_threads_reaches_bundled_openblas():
    """fork 出的 worker 里设环境变量不生效，必须能调到轮子自带 OpenBLAS 的运行期接口。"""
    n = parallel.set_blas_threads(1)
    try:
        if n == 0:
            pytest.skip("这台机器的 numpy 不带 OpenBLAS（如 MKL 版）")
        assert n >= 1
    finally:
        parallel.set_blas_threads(parallel.os.cpu_count() or 1)


def test_cgroup_memory_limit_caps_available_memory(tmp_path):
    """容器里 /proc/meminfo 看到整台宿主；按 cgroup 余量（上限 − 已用 + 文件页）算才不会高估。"""
    from open_guji_cv.core.parallel import _cgroup_available_bytes
    G = 1 << 30
    # v1
    pc = tmp_path / "cg1"
    pc.write_text("4:memory:/a/b\n3:cpuset:/\n", encoding="ascii")
    d = tmp_path / "root" / "memory" / "a" / "b"
    d.mkdir(parents=True)
    (d / "memory.limit_in_bytes").write_text(str(12 * G))
    (d / "memory.usage_in_bytes").write_text(str(5 * G))
    (d / "memory.stat").write_text(f"cache 1\ninactive_file 5\ntotal_active_file {G}\ntotal_inactive_file {G}\n")
    assert _cgroup_available_bytes(str(pc), str(tmp_path / "root")) == 9 * G
    (d / "memory.limit_in_bytes").write_text(str(9223372036854771712))        # 没设上限
    assert _cgroup_available_bytes(str(pc), str(tmp_path / "root")) is None
    # v2
    pc2 = tmp_path / "cg2"
    pc2.write_text("0::/s\n", encoding="ascii")
    d2 = tmp_path / "root2" / "s"
    d2.mkdir(parents=True)
    (d2 / "memory.max").write_text(str(8 * G))
    (d2 / "memory.current").write_text(str(7 * G))
    (d2 / "memory.stat").write_text(f"anon 1\nactive_file {G // 2}\ninactive_file {G // 2}\n")
    assert _cgroup_available_bytes(str(pc2), str(tmp_path / "root2")) == 2 * G
    (d2 / "memory.max").write_text("max\n")
    assert _cgroup_available_bytes(str(pc2), str(tmp_path / "root2")) is None
    assert _cgroup_available_bytes(str(tmp_path / "nope"), str(tmp_path)) is None
