"""Step 基类、注册表、RunContext。

Step 是薄适配层：`run_page` 里调现有算法函数，把结果装进产物 schema 返回；
图像只经 `ctx.cache` 走缓存，Step 自己不写图像产物（设计 §3.8）。
注册方式沿用 `clustering/context_step.py` 的 STRATEGIES：模块级字典 + 装饰器。
"""

from __future__ import annotations

import dataclasses
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import numpy as np
from pydantic import BaseModel

from .spec import GateSpec, ProductKindSpec, StepSpec, page_key
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
    for k in (*inst.spec.consumes, *inst.spec.optional_consumes, *inst.spec.produces):
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


def attach_gate(step_id: str, gate: GateSpec) -> None:
    """把一道闸挂到某个已注册 Step 的 spec 上——只覆盖这一个实例的 `spec`
    （`dataclasses.replace` 出一份新的、其余字段原样复制），不改该 Step 自己的
    源文件。挂闸的 Step 与被挂的 Step 是两个不同的 `StepSpec.id`：闸自己按它
    的 `id` 正常注册、正常落盘（见 `register_step`），这里只是让引擎知道
    「跑完这个 Step 之后，接着自动跑那道闸」（见 `core.engine.Engine.run`）。

    调用时机：闸模块（`gates/`）在 import 时调用，必须晚于它要挂的 Step 被
    `register_step` 注册——`steps/__init__.py` 末尾 `import ..gates` 保证这个顺序。
    """
    step = STEPS[step_id]
    step.spec = dataclasses.replace(step.spec, gate=gate)



def _with_book_corpus(p: BaseModel, ctx: "RunContext") -> BaseModel:
    """参数里的整理本语料没显式指定时，换成**这册书自己的**（`references[0].file`）。

    只对带 `corpus` 字段的参数类生效（`align_ref` / `context_decide`），别的步原样返回。
    显式传了 `--params corpus=…` 的照用不误——只在「用的还是缺省值」时替换。

    ⚠️ 必须**重新构造**，不能 `model_copy`：`corpus_fingerprint` 是在 `model_post_init`
    里填的，而 `model_copy` 不触发它——那样换了语料指纹却还是旧的，产物不会 stale，
    等于换语料不生效。

    2026-09-21 从 `steps/align_ref.py` 搬到这里：原先它只在 `run_page` 里调，
    `Engine.fingerprint()` 拿到的是没换过的参数，两边算出不同的指纹（见 `params_for`）。
    """
    if not hasattr(p, "corpus"):
        return p
    from ..steps.align_ref import DEFAULT_CORPUS, book_corpus
    if p.corpus != DEFAULT_CORPUS:
        return p
    want = book_corpus(ctx.book.id)
    if want == p.corpus:
        return p
    return type(p)(**{**p.model_dump(), "corpus": want, "corpus_fingerprint": ""})

# ── 运行上下文 ───────────────────────────────────────────────────────
class RunContext:
    """一次运行里 Step 看到的全部环境。Step 通过它读上游产物、拿原图、走图像缓存。"""

    def __init__(self, book: "BookSpec", store: "ProductStore", cache: "ImageCache",
                 params: dict[str, BaseModel] | None = None,
                 log: Callable[[str], None] | None = None,
                 pipeline=None):
        self.book = book
        self.store = store
        self.cache = cache
        self.params: dict[str, BaseModel] = params or {}
        self.log = log or (lambda s: print(s, flush=True))
        self._raw: dict[int, np.ndarray] = {}
        #: 查「谁产出这种产物」按这条管线来（2026-09-14，三模式方案「地基 2」）。
        #: 不传就按册的 edition 选默认管线（`core.pipeline.default_pipeline_id`）——
        #: 控制台 / CLI 那些不经 Engine 直接建 RunContext 的调用点不用改。
        self._pipeline = pipeline
        #: 格级复用开关（`core/reuse.py`）。环境变量 `GUJI_NO_REUSE=1` 关掉——用环境
        #: 变量而不是 Step 参数，是因为参数进指纹，加一个参数会让全书产物过期；
        #: 也不走 Engine 的形参，并行 worker 自己建 ctx、拿不到 Engine。
        import os as _os
        self.reuse_enabled = _os.environ.get("GUJI_NO_REUSE") != "1"

    @property
    def pipeline(self):
        if self._pipeline is None:
            from .pipeline import default_pipeline_id, load_pipeline
            self._pipeline = load_pipeline(default_pipeline_id(self.book))
        return self._pipeline

    def producer(self, kind_id: str) -> "Step":
        """本管线里产出 `kind_id` 的 Step；同一种产物有多个产出者时（刻本链 /
        现代链各一个）以当前管线为准，别用全局的 `producer_of`。"""
        return self.pipeline.producer_of(kind_id)

    # 参数
    def params_for(self, step: "Step") -> BaseModel:
        """这一步这次跑用的参数。**指纹与 run_page 必须拿到同一份**，所以「按册换语料」
        这类改写要在这里做，不能留在 `run_page` 里。

        2026-09-21 修：`align_ref` / `context_decide` 的 `corpus` 缺省是四庫總目那份，
        `run_page` 里用 `_with_book_corpus()` 换成本册自己的整理本并重算 `corpus_fingerprint`，
        而 `Engine.fingerprint()` 走的是**没换过的**那份——两边算的不是同一个东西，于是
        这两步**永远判过期，跑多少次都洗不掉**（bxgb 实测：引擎按不存在的
        `zongmu_wenyuange_wikisource.txt` 算出 `a8c79b1a`，run_page 按
        `beixingrilu_jiaoduiben.txt` 算出 `a7729ad3`，产物里记的又是上一轮的
        `4bf07e96`，三个互不相同）。产物内容一直是对的（run_page 用的语料没错），
        坏的只是新鲜度判断——它长期显示过期，让人分不清真该重跑还是假警报。

        凡是 `references` 指向非缺省语料的书都中招；四庫總目因缺省值恰好就是它的语料，
        反而不显——**这类"只在别的书上犯"的错，不跨书验就看不见**。
        """
        p = self.params.get(step.spec.id)
        if p is None:
            p = step.spec.params()
        return _with_book_corpus(p, self)

    # 原图（灰度 uint8）。同一页只读一次。
    def raw_page(self, page: int) -> np.ndarray:
        """读序空间的「原图」。

        **横排书在这里顺时针旋转 90°**（三模式方案 §三）：转完之后原图第一行
        变成最右列、行内第一个字变成最上格，恰好落进竖排的规范空间
        `raw_page_px@top-right`，于是 Step1–4 那几百行按「列竖直」写的几何代码
        一行不用改。管线其余部分看到的永远是「竖排」。

        代价记在这里，别让后人找：**产物坐标从此是读序空间，不是原图坐标**。
        面向人的三处（控制台叠图、金标锚点、Step9 导出）要转回去，走
        `core/anchor.py` 的 `to_original()`；那部分尚未实现，所以横排书现在
        跑得了算法、叠图看着是横躺的。
        """
        if page not in self._raw:
            path = self._page_path(page)
            img = imread(str(path), 0) if path.exists() else None
            if img is None:
                raise FileNotFoundError(f"原图缺失: {path}")
            if img.ndim == 3:
                import cv2
                img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            if getattr(self.book, "writing_mode", "vertical-rl") == "horizontal-tb":
                img = np.rot90(img, -1).copy()   # -1 = 顺时针；copy 保证内存连续
            if getattr(self.book, "binarized_input", False):
                # 整页二值副本（`book.binarized_input`）。放在旋转**之后**：
                # Sauvola 的窗口是各向同性的，先转后转结果一样，但纸缘护栏
                # 按的是「转完之后」的四条边，与下游几何看到的边一致。
                from ..utils.binarized import binarize_page
                img = binarize_page(img)
            self._raw[page] = img
        return self._raw[page]

    def _page_path(self, page: int) -> "Path":
        """这一页从哪读：登记过预清理且产物已生成的，读修好的那张；否则读原图。

        逻辑见 `utils.preclean.effective_raw_path`——叠图（`render.overlay`）
        与这里必须共用同一份判断，不能各写一遍。
        """
        from ..utils.preclean import effective_raw_path
        return effective_raw_path(self.book, page, log=self.log)

    def raw_size(self, page: int) -> tuple[int, int]:
        h, w = self.raw_page(page).shape[:2]
        return w, h

    # 上游数值产物
    def product(self, kind_id: str, page: int) -> Any:
        step = self.producer(kind_id)
        obj = self.store.read(self.book.id, step.spec.id, page_key(page), kind_id)
        if obj is None:
            raise FileNotFoundError(f"上游产物缺失: {kind_id} {page_key(page)}（先跑 {step.spec.id}）")
        return obj

    def has_product(self, kind_id: str, page: int) -> bool:
        step = self.producer(kind_id)
        return self.store.exists(self.book.id, step.spec.id, page_key(page))

    # 派生图像：查缓存，没有就让产出它的 Step 现算
    def materialize(self, kind_id: str, key: str) -> Path:
        step = self.producer(kind_id)
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
        d = {
            "id": s.id, "title": s.title, "version": s.version, "unit": s.unit,
            "consumes": list(s.consumes), "optional_consumes": list(s.optional_consumes),
            "produces": list(s.produces),
            "params": s.params.model_json_schema(), "when": s.when,
        }
        if s.gate:
            d["gate"] = {
                "id": s.gate.id, "unit": s.gate.unit, "on_fail": s.gate.on_fail,
                "levels": [{"id": lv.id, "unit": lv.unit, "desc": lv.desc}
                           for lv in s.gate.levels],
            }
        return d
