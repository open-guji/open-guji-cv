"""Step 基类、注册表、RunContext。

Step 是薄适配层：`run_page` 里调现有算法函数，把结果装进产物 schema 返回；
图像只经 `ctx.cache` 走缓存，Step 自己不写图像产物（设计 §3.8）。
注册方式沿用 `clustering/context_step.py` 的 STRATEGIES：模块级字典 + 装饰器。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import numpy as np
from pydantic import BaseModel

from .spec import ProductKindSpec, StepSpec, page_key
from ..utils.image_io import imread

if TYPE_CHECKING:
    from .book import BookSpec
    from ..products.cache import ImageCache
    from ..products.store import ProductStore


# ── 注册表 ───────────────────────────────────────────────────────────
STEPS: dict[str, "Step"] = {}
KINDS: dict[str, ProductKindSpec] = {}


def register_kind(kind: ProductKindSpec) -> ProductKindSpec:
    if kind.id in KINDS and KINDS[kind.id] is not kind:
        raise ValueError(f"产物种类重复注册: {kind.id}")
    KINDS[kind.id] = kind
    return kind


def register_step(cls: type["Step"]) -> type["Step"]:
    inst = cls()
    sid = inst.spec.id
    if sid in STEPS and type(STEPS[sid]) is not cls:
        raise ValueError(f"Step 重复注册: {sid}")
    for k in (*inst.spec.consumes, *inst.spec.produces):
        if k not in KINDS:
            raise ValueError(f"Step {sid} 引用了未注册的产物种类 {k!r}")
    STEPS[sid] = inst
    return cls


def kind_of(kind_id: str) -> ProductKindSpec:
    try:
        return KINDS[kind_id]
    except KeyError:
        raise KeyError(f"未注册的产物种类: {kind_id}") from None


def producer_of(kind_id: str) -> "Step":
    for s in STEPS.values():
        if kind_id in s.spec.produces:
            return s
    raise KeyError(f"没有 Step 产出 {kind_id!r}")


# ── 运行上下文 ───────────────────────────────────────────────────────
class RunContext:
    """一次运行里 Step 看到的全部环境。Step 通过它读上游产物、拿原图、走图像缓存。"""

    def __init__(self, book: "BookSpec", store: "ProductStore", cache: "ImageCache",
                 params: dict[str, BaseModel] | None = None,
                 log: Callable[[str], None] | None = None):
        self.book = book
        self.store = store
        self.cache = cache
        self.params: dict[str, BaseModel] = params or {}
        self.log = log or (lambda s: print(s, flush=True))
        self._raw: dict[int, np.ndarray] = {}

    # 参数
    def params_for(self, step: "Step") -> BaseModel:
        p = self.params.get(step.spec.id)
        return p if p is not None else step.spec.params()

    # 原图（灰度 uint8）。同一页只读一次。
    def raw_page(self, page: int) -> np.ndarray:
        if page not in self._raw:
            path = self.book.raw_path(page)
            img = imread(str(path), 0) if path.exists() else None
            if img is None:
                raise FileNotFoundError(f"原图缺失: {path}")
            if img.ndim == 3:
                import cv2
                img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            self._raw[page] = img
        return self._raw[page]

    def raw_size(self, page: int) -> tuple[int, int]:
        h, w = self.raw_page(page).shape[:2]
        return w, h

    # 上游数值产物
    def product(self, kind_id: str, page: int) -> Any:
        step = producer_of(kind_id)
        obj = self.store.read(self.book.id, step.spec.id, page_key(page), kind_id)
        if obj is None:
            raise FileNotFoundError(f"上游产物缺失: {kind_id} {page_key(page)}（先跑 {step.spec.id}）")
        return obj

    def has_product(self, kind_id: str, page: int) -> bool:
        step = producer_of(kind_id)
        return self.store.exists(self.book.id, step.spec.id, page_key(page))

    # 派生图像：查缓存，没有就让产出它的 Step 现算
    def materialize(self, kind_id: str, key: str) -> Path:
        step = producer_of(kind_id)
        return self.cache.materialize(
            self.book.id, kind_id, key,
            lambda: step.render(self, kind_id, key))

    def image(self, kind_id: str, key: str) -> np.ndarray:
        img = imread(str(self.materialize(kind_id, key)), 0)
        if img is None:
            raise FileNotFoundError(f"缓存图像读不出来: {kind_id} {key}")
        return img


# ── Step 基类 ─────────────────────────────────────────────────────────
class Step(ABC):
    spec: StepSpec

    @abstractmethod
    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        """处理一页，返回 {numeric 产物种类 id: schema 实例}。
        图像类产物在这里顺手 `ctx.cache.put(...)`，并实现 `render` 以便缓存丢失时再生。"""

    def render(self, ctx: RunContext, kind_id: str, key: str) -> np.ndarray:
        raise NotImplementedError(f"{self.spec.id} 不会再生 {kind_id}")

    def describe(self) -> dict:
        s = self.spec
        return {
            "id": s.id, "title": s.title, "version": s.version, "unit": s.unit,
            "consumes": list(s.consumes), "produces": list(s.produces),
            "params": s.params.model_json_schema(), "when": s.when,
        }
