# -*- coding: utf-8 -*-
"""跨进程写锁（H 人裁单写者任务书件 1）：N 个真进程并发写，0 丢失、0 撞号。

`multiprocessing`（fork，Linux/CI 默认）起真进程而不是线程——线程共享 GIL 与
`_EVENTS_LOCK` 那类进程内锁本来就管得住，测不出「跨进程」这个词的分量。
只有真进程才会真的去抢 `feedback/lock.py` 的 flock。

worker 之间**故意让 seq 互相碰撞**（都从 1 开始编号）——这比真实场景里两个
请求恰好读到同一个 `latest_seq()` 更极端，是对「碰撞后顺延不丢」这条修复
最直接的压力测试。
"""

from __future__ import annotations

import multiprocessing as mp
from pathlib import Path

import pytest


def _write_events(root: Path, worker: int, n: int) -> int:
    from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
    log = EventLog(Path(root))
    events = [make_event("stress", i + 1, "verdict",
                         EventTarget(step="test", unit="cell", key=f"w{worker}:{i}"),
                         {"worker": worker, "i": i}, actor="user")
              for i in range(n)]
    return log.append(events)


def _write_gold(root: Path, worker: int, n: int) -> tuple[int, int]:
    from open_guji_cv.gold.item import GoldItem
    from open_guji_cv.gold.store import GoldStore
    store = GoldStore(Path(root))
    items = [GoldItem(id=f"w{worker}:{i}", expected={"char": "測"}, label_origin="human")
             for i in range(n)]
    return store.upsert("stress-shard", items, why="concurrency test")


@pytest.mark.parametrize("n_workers,n_each", [(8, 200)])
def test_concurrent_event_append_no_loss_no_collision(tmp_path, n_workers, n_each):
    root = tmp_path / "feedback"
    ctx = mp.get_context("fork")
    with ctx.Pool(n_workers) as pool:
        pool.starmap(_write_events, [(root, w, n_each) for w in range(n_workers)])

    from open_guji_cv.feedback.events import EventLog
    log = EventLog(root)
    evs = log.read("stress")
    assert len(evs) == n_workers * n_each, f"应有 {n_workers * n_each} 条，实得 {len(evs)}（丢失）"
    seqs = [e.seq for e in evs]
    assert len(seqs) == len(set(seqs)), "存在撞号（同一 seq 出现两次）"
    # 每个 worker 的 n 个 key 都在——不是「凑够总数」但漏了某个 worker 整批
    keys = {e.target.key for e in evs}
    expect_keys = {f"w{w}:{i}" for w in range(n_workers) for i in range(n_each)}
    assert keys == expect_keys, f"缺失的 key：{sorted(expect_keys - keys)[:5]}"


@pytest.mark.parametrize("n_workers,n_each", [(8, 200)])
def test_concurrent_gold_upsert_no_loss(tmp_path, n_workers, n_each):
    root = tmp_path / "dataset"
    ctx = mp.get_context("fork")
    with ctx.Pool(n_workers) as pool:
        pool.starmap(_write_gold, [(root, w, n_each) for w in range(n_workers)])

    from open_guji_cv.gold.store import GoldStore
    store = GoldStore(root)
    items = store.list("stress-shard")
    assert len(items) == n_workers * n_each, f"应有 {n_workers * n_each} 条，实得 {len(items)}（丢失）"
    ids = {it.id for it in items}
    expect_ids = {f"w{w}:{i}" for w in range(n_workers) for i in range(n_each)}
    assert ids == expect_ids, f"缺失的 id：{sorted(expect_ids - ids)[:5]}"
