# -*- coding: utf-8 -*-
"""控制台用到的几个 Store 的**进程内实例**，以及它们的注入口。

## 为什么单独一个文件

`app.py` 原先在模块顶层写死 `runner = JobRunner()`、`_log = EventLog()`、
`_batches = BatchStore()`、`_gold = GoldStore()`，用的全是默认根目录
（控制台重构方案 §四·1）。四个类**本来就都收 `root` 参数**，注入能力早就有，
只是控制台没用。路由拆成 11 个 router 之后，它们总得有个共同的家——就是这里。

## 单例 vs 每次新建：两类，别混

- **单例**（`runner()` / `event_log()` / `batch_store()` / `gold_store()`）：
  它们**本来就是**模块级单例，`JobRunner` 更是自带队列与后台 worker 线程，
  一个进程只能有一个。
- **每次新建**（`product_store()` / `image_cache()`）：`app.py` 里原本就是
  `ProductStore()` 现建现用。**这个不能改成单例**——`ProductStore` 按实例缓存
  manifest（`self._manifests`），做成进程级单例的话，跑完一轮管线再刷控制台
  会读到**上一轮的 manifest**，产物看着还是旧的。这是行为差异，不是风格问题。

## 注入口

`set_roots()` 用于测试或将来的多工作区：换根之后重建单例。
不传就各按各自的默认（`GUJI_FEEDBACK_DIR` / `GUJI_BATCHES_DIR` /
`GUJI_DATASET_DIR` 等环境变量仍然生效，解析在各 Store 自己那边）。
"""
from __future__ import annotations

from pathlib import Path

from ..feedback.events import EventLog
from ..gold.store import GoldStore
from ..products.cache import ImageCache
from ..products.store import ProductStore
from ..review.batches import BatchStore
from .jobs import JobRunner

_roots: dict[str, Path | None] = {"feedback": None, "batches": None, "dataset": None,
                                  "products": None, "cache": None}
_runner: JobRunner | None = None
_log: EventLog | None = None
_batches: BatchStore | None = None
_gold: GoldStore | None = None


def set_roots(*, feedback: Path | None = None, batches: Path | None = None,
              dataset: Path | None = None, products: Path | None = None,
              cache: Path | None = None) -> None:
    """换根并重建单例。只传要换的那个，其余保持原样。"""
    global _log, _batches, _gold
    for k, v in (("feedback", feedback), ("batches", batches), ("dataset", dataset),
                 ("products", products), ("cache", cache)):
        if v is not None:
            _roots[k] = Path(v)
    _log = _batches = _gold = None


def runner() -> JobRunner:
    """任务队列。自带单 worker 线程，一个进程只能有一个。"""
    global _runner
    if _runner is None:
        _runner = JobRunner()
    return _runner


def event_log() -> EventLog:
    global _log
    if _log is None:
        _log = EventLog(_roots["feedback"])
    return _log


def batch_store() -> BatchStore:
    global _batches
    if _batches is None:
        _batches = BatchStore(_roots["batches"])
    return _batches


def gold_store() -> GoldStore:
    global _gold
    if _gold is None:
        _gold = GoldStore(_roots["dataset"])
    return _gold


def product_store() -> ProductStore:
    """**每次新建**——manifest 是按实例缓存的，见模块 docstring。"""
    return ProductStore(_roots["products"])


def image_cache() -> ImageCache:
    """每次新建（与 `app.py` 原来的 `ImageCache()` 现建现用一致）。"""
    return ImageCache(_roots["cache"])
