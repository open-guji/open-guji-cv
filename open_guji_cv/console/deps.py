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
_verdicts: GoldStore | None = None


def set_roots(*, feedback: Path | None = None, batches: Path | None = None,
              dataset: Path | None = None, products: Path | None = None,
              cache: Path | None = None) -> None:
    """换根并重建单例。只传要换的那个，其余保持原样。"""
    global _log, _batches, _gold, _verdicts
    for k, v in (("feedback", feedback), ("batches", batches), ("dataset", dataset),
                 ("products", products), ("cache", cache)):
        if v is not None:
            _roots[k] = Path(v)
    _log = _batches = _gold = _verdicts = None


def reset_roots() -> None:
    """把四个根清回「按环境变量解析」并重建单例——**热切工作区**用（2026-09-15）。

    与 `set_roots()` 的区别：那个是「显式指定某个根」，这个是「忘掉显式指定，
    回去问 `core/workspace.py`」。切工作区改的是 `GUJI_WORKSPACE`，而这几个
    Store 构造时就把根算进了实例，不重建就还拿着上一个工作区的路径——
    产物、人裁批次、裁决表会安静地读错地方。

    `runner()` 不重建：worker 线程带着队列，重建等于把在跑/排队的任务丢了。
    切换入口（routers/workspace.py）在有任务跑的时候直接拒绝，不走到这里。"""
    global _log, _batches, _gold, _verdicts
    for k in _roots:
        _roots[k] = None
    _log = _batches = _gold = _verdicts = None
    _by_root.clear()


def runner() -> JobRunner:
    """任务队列。自带单 worker 线程，一个进程只能有一个。"""
    global _runner
    if _runner is None:
        _runner = JobRunner()
    return _runner


#: 按「解析出来的根」缓存的 Store。**不能做成进程级单例**——工作区是每请求
#: 一个（`core/workspace` 的 contextvar，见 `console/middleware.py`），单例会
#: 把第一个请求那个工作区的根一直用下去，第二个标签页就读到别人的数据了。
#: 同一个工作区复用同一个实例：`EventLog`/`GoldStore` 内部有自己的缓存，
#: 每次新建会丢掉、也白读一遍盘。
_by_root: dict[tuple[str, str], object] = {}


def _cached(kind: str, root: Path, make):
    key = (kind, str(root))
    inst = _by_root.get(key)
    if inst is None:
        inst = _by_root[key] = make(root)
    return inst


def event_log() -> EventLog:
    from ..core.workspace import feedback_root
    root = _roots["feedback"] or feedback_root()
    return _cached("feedback", root, EventLog)          # type: ignore[return-value]


def batch_store() -> BatchStore:
    from ..core.workspace import batches_root
    root = _roots["batches"] or batches_root()
    return _cached("batches", root, BatchStore)         # type: ignore[return-value]


def gold_store() -> GoldStore:
    """**测试集仓**（open-guji-dataset）——只给金标管理视图（分片表 / 迁移 / 漂移）用。
    事件消费**不能**用它，用 `verdict_store()`（2026-09-13 三仓边界）。

    测试集仓不随工作区走（它是独立的第三个仓），但根仍可能由 `set_roots` 指定，
    所以一样按根缓存。"""
    if _roots["dataset"] is not None:
        return _cached("dataset", _roots["dataset"], GoldStore)   # type: ignore[return-value]
    global _gold
    if _gold is None:
        _gold = GoldStore(None)
    return _gold


def verdict_store() -> GoldStore:
    """workspace 的裁决表 `feedback/verdicts/`——事件路由消费的落点、面板去重的数据源。
    根随 `feedback` 根走（`<feedback>/verdicts`）。"""
    from ..core.workspace import verdicts_root
    root = (_roots["feedback"] / "verdicts") if _roots["feedback"] is not None else verdicts_root()
    return _cached("verdicts", root, GoldStore)         # type: ignore[return-value]


def product_store() -> ProductStore:
    """**每次新建**——manifest 是按实例缓存的，见模块 docstring。
    根不传就由 `ProductStore` 自己按本请求的工作区解析（contextvar）。"""
    return ProductStore(_roots["products"])


def image_cache() -> ImageCache:
    """每次新建（与 `app.py` 原来的 `ImageCache()` 现建现用一致）。"""
    return ImageCache(_roots["cache"])
