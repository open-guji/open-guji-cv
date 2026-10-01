"""Step 基类、注册表、RunContext。

Step 是薄适配层：`run_page` 里调现有算法函数，把结果装进产物 schema 返回；
图像只经 `ctx.cache` 走缓存，Step 自己不写图像产物（设计 §3.8）。
注册方式沿用 `clustering/context_step.py` 的 STRATEGIES：模块级字典 + 装饰器。
"""

from __future__ import annotations

import dataclasses
from abc import ABC, abstractmethod
from collections import OrderedDict
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
    for k, _f in inst.spec.optional_consumes_when:
        if k not in inst.spec.optional_consumes:
            raise ValueError(f"Step {sid}: optional_consumes_when 的 {k!r} 不在 optional_consumes 里")
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


def resolve_step_id(name: str) -> str:
    """人查产物时常把 kind_id 和 step_id 搞混——多数步骤两者同名，
    `context_decide`（step_id）产 `context_decision`（kind_id）这种**不同名**的
    是例外，按名字直查目录（`ProductStore.step_dir` 用 step_id）会悄悄查到
    空目录、0 条，不报错（任务卡 #54 第21条）。

    `name` 既可能是 step_id 也可能是 kind_id：是 step_id 原样返回；
    是 kind_id 就解到产出它的 step_id；两者都不是就报错，报错里列出
    已注册的 kind_id 供对照（截了前 30 个，免得刷屏）。
    """
    if name in STEPS:
        return name
    if name in KINDS:
        return producer_of(name).spec.id
    valid = sorted(KINDS.keys())
    raise KeyError(
        f"{name!r} 既不是已知的 step_id，也不是已知的产物种类(kind_id)。"
        f"已注册的产物种类（前 30 个）: {valid[:30]}"
    )


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



def _with_book_params(p: BaseModel, step: "Step", ctx: "RunContext") -> BaseModel:
    """书 yaml 顶层 `params:` 段（`BookSpec.params`，2026-09-27，D-书级admit覆盖）
    覆盖**这一步**的参数——形状与管线 yaml 的 `params:` 一样 `{step_id: {字段: 值}}`，
    取的是 `ctx.book.params.get(step.spec.id)`。设计初衷：全唐文一直靠命令行
    `--params '{"seed_admit": {"use_context": false}}'` 临时挡住 `context` 通道
    的错放行，漏带一次这个参数这一整轮就白挡——书级 yaml 能把这个决定钉死，
    不必每次跑批都记得带命令行参数。

    只把**仍是 Step 构造默认值**的字段替换成书里配的值，跟 `_with_book_corpus`
    走同一个限制：显式传了 CLI `--params` 的字段已经不等于默认值，这里不碰；
    管线 yaml 若也配了同一个字段，效果上跟 CLI 一样「已经不是默认值」，也会被
    这里放过、书 yaml 那份对该字段不生效——**这一点与任务书写的「管线 yaml <
    书 yaml」字面顺序不完全一致**，是与另外四个 `_with_book_*` 函数共享的同一个
    近似（它们全都只能补「仍是默认值」的字段，分不清「从没设过」与「设成了
    跟默认值一样的值」，也分不清是管线 yaml 设的还是 CLI 设的）。目前没有任何
    管线 yaml 给 `seed_admit` 配过参数，这条边界情形不会真的发生；真出现那天，
    应该跟这几个既有函数一起换一套更精确的机制，不在这一个函数里单独精确到位。

    `ctx.book.params` 没有这个 Step 的条目、或条目是空字典时原样返回，逐字节
    行为不变——书 yaml 没写 `params:` 这一段的册，加这个函数前后产物指纹相同。
    **必须重新构造**，不能 `model_copy`：跟 `_with_book_corpus` 一样，某些参数类
    在 `model_post_init` 里按字段算派生指纹，只有重新构造才会触发。

    放在 `params_for` 参数链的最前面（先于 `_with_book_corpus` 等四个函数）：
    书 yaml 里显式配的字段是用户的明确决定，应该压过那几个函数算的「按本书
    convenience 默认值」，不能反过来被它们先占了「仍是默认值」这个判据的位置。
    """
    book_kv = (getattr(ctx.book, "params", None) or {}).get(step.spec.id)
    if not book_kv:
        return p
    default = step.spec.params()
    overrides = {k: v for k, v in book_kv.items()
                 if getattr(p, k, object()) == getattr(default, k, object())}
    if not overrides:
        return p
    return type(p)(**{**p.model_dump(), **overrides})


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


def _with_book_real_proto(p: BaseModel, ctx: "RunContext") -> BaseModel:
    """`RareCandidatesParams.model_fingerprint` 换成**按这册书**算的那份（5-b 转正二，
    2026-09-27）。只对 `RareCandidatesParams` 生效，别的参数类原样返回，跟
    `_with_book_corpus` 同一个坑、同一个补法。

    `model_post_init` 造实例时没有 `ctx.book`，只能填模块级默认（`REAL_PROTO_ENABLED`
    缺省关那份）；此前只靠 `StepSpec.book_deps=("font",)` 兜底整本 `font` 字典的文本
    （yaml 改了会让 self_hash 变，但 `params_hash` 里那格仍是常量，与产物体
    `PageRare.model_fingerprint` 实际用的值对不上）。这里在 `params_for` 里用
    `book_real_proto(ctx.book.font)` 重算，让 `params_hash` 与 `run_page` 算的
    是同一份——顺带补上 `book_deps` 没兜住的那格：`real_proto_fingerprint` 本来就是
    内容指纹（`instances/*.jsonl` 的名字:大小:mtime），`glyph_store` 长内容而 yaml
    文本不动时，这里重算也会跟着变，不必再等 `book_deps`。

    ⚠️ 必须**重新构造**，不能 `model_copy`：同 `_with_book_corpus` 的道理——
    `model_post_init` 只在字段为空串时才填，`model_copy` 不会重新触发这段判断。

    只在「当前值仍是构造时的模块级默认」时才换——跟 `_with_book_corpus` 用
    `p.corpus != DEFAULT_CORPUS` 判断「已经不是缺省值」是同一个道理，这里换成比
    对不带 `ctx.book` 时 `model_post_init` 会填的那份，显式传了 `model_fingerprint`
    的（`GlyphMatchParams.db_fingerprint` 那条注释说的「按某个历史指纹重放」）
    才不会被这里覆盖。`ctx.book` 没有 `font` 属性（旧结构 / 测试用的壳对象）按
    `None` 处理，等价于关。
    """
    from ..steps.rare_candidates import RareCandidatesParams
    if not isinstance(p, RareCandidatesParams):
        return p

    def _fp(real_proto) -> str:
        fp = full_fingerprint(real_proto=real_proto)
        if p.struct_probe:
            import hashlib
            pp = Path(p.struct_probe)
            fp += ":probe=" + (hashlib.sha1(pp.read_bytes()).hexdigest()[:12] if pp.exists() else "missing")
        return fp

    from ..clustering.cnn_candidates import book_real_proto, full_fingerprint
    if p.model_fingerprint != _fp(None):
        return p  # 显式传值，或已经按某本书算过（幂等，见下）
    fp = _fp(book_real_proto(getattr(ctx.book, "font", None)))
    if fp == p.model_fingerprint:
        return p
    return type(p)(**{**p.model_dump(), "model_fingerprint": fp})


def _with_witness_fingerprint(p: BaseModel, ctx: "RunContext") -> BaseModel:
    """`AlignRefParams.witness_fingerprint` 按**这册书的 `references` 文件**算
    （2026-09-27，任务书-D-多证人对齐策略）。只对 `witness_strategy != "legacy"`
    生效——legacy 策略只用单一 `corpus`，继续吃 `_with_book_corpus` 那份指纹，
    不需要这里再算一遍。

    同 `_with_book_corpus`／`_with_book_real_proto` 一个坑：`model_post_init`
    造实例时没有 `ctx.book`，只能留空；这里在 `params_for` 里补，让
    `Engine.fingerprint()` 与 `run_page` 拿到同一份。只在字段仍是空串（未算过）
    时才填，显式传值的不动。
    """
    if not hasattr(p, "witness_strategy") or not hasattr(p, "witness_fingerprint"):
        return p
    if getattr(p, "witness_strategy") == "legacy" or getattr(p, "witness_fingerprint"):
        return p
    from ..core.workspace import corpus_path
    from ..steps.align_ref import book_corpus
    from ..steps.context_decide import corpus_fingerprint
    refs = getattr(ctx.book, "references", None) or []
    names = [r.get("file", "") for r in refs if r.get("file")]
    if not names:
        names = [Path(book_corpus(ctx.book.id)).name]
    fp = corpus_fingerprint([str(corpus_path(n)) for n in names])
    return type(p)(**{**p.model_dump(), "witness_fingerprint": fp})


def _with_book_gw(p: BaseModel, ctx: "RunContext") -> BaseModel:
    """`RareCandidatesParams.model_fingerprint` 再叠一层书级开关：`font.gw_variant.enabled`
    （T4 变体形模板，2026-09-27）。跟在 `_with_book_real_proto` 之后跑，`params_for` 里
    两个开关依次生效——与它同一个坑、同一个补法（`model_post_init` 造实例时没有
    `ctx.book`，只能填模块级默认 `GW_ENABLED` 缺省关那份）。

    这里的「构造时默认值」基准**必须带上 `_with_book_real_proto` 已经生效的
    `real_proto`**，不能直接对 `full_fingerprint()`（两个开关都不传，即两个都按
    模块级）比——那样若某本书只开了 `real_proto` 没开 `gw_variant`，
    `p.model_fingerprint` 在这一步一进来就已经不等于「两者皆模块级」那份，会被
    误判成「显式传值/已经算过」而跳过，`gw_variant` 那半开关就失效了。
    做法：重算一次同一份 `real_proto`（纯读 yaml，无 IO 开销），拿它当基准的固定项，
    只比较 gw 那一维「是否还是构造时的模块级默认」。

    ⚠️ 同样必须**重新构造**，不能 `model_copy`（理由同 `_with_book_real_proto`）。
    """
    from ..steps.rare_candidates import RareCandidatesParams
    if not isinstance(p, RareCandidatesParams):
        return p

    from ..clustering.cnn_candidates import book_gw_variant, book_real_proto, full_fingerprint
    font = getattr(ctx.book, "font", None)
    real_proto = book_real_proto(font)

    def _fp(gw_enabled) -> str:
        fp = full_fingerprint(real_proto=real_proto, gw_enabled=gw_enabled)
        if p.struct_probe:
            import hashlib
            pp = Path(p.struct_probe)
            fp += ":probe=" + (hashlib.sha1(pp.read_bytes()).hexdigest()[:12] if pp.exists() else "missing")
        return fp

    if p.model_fingerprint != _fp(None):
        return p  # 显式传值，或已经按某本书算过（幂等，见下）
    fp = _fp(book_gw_variant(font))
    if fp == p.model_fingerprint:
        return p
    return type(p)(**{**p.model_dump(), "model_fingerprint": fp})

def _with_book_step6_ai(p: BaseModel, ctx: "RunContext") -> BaseModel:
    """`ContextDecideParams.ai_evidence` 缺省时按书级配置 `step6_ai:` 填（2026-09-27，
    D-Step6 导回管线）。同 `_with_book_corpus` 一个道理：要在 `params_for` 里填，
    指纹（`params_hash`）与 `run_page` 才拿到同一份；必须**重新构造**以触发
    `model_post_init` 算内容指纹。相对路径锚工作区根（没有工作区则锚 cwd）。
    书没配 `step6_ai`、或调用方显式传了 `ai_evidence` 的，原样返回。"""
    if not hasattr(p, "ai_evidence") or p.ai_evidence:
        return p
    rel = getattr(ctx.book, "step6_ai", "") or ""
    if not rel:
        return p
    from .workspace import workspace_root
    path = Path(rel)
    if not path.is_absolute():
        path = (workspace_root() or Path.cwd()) / path
    return type(p)(**{**p.model_dump(), "ai_evidence": str(path), "ai_evidence_fingerprint": ""})


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
        self._raw: "OrderedDict[int, np.ndarray]" = OrderedDict()
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

        2026-09-27 补 `_with_book_real_proto()`：`RareCandidatesParams.model_fingerprint`
        同一个坑（见该函数文档）——`rare_candidates` 的开关/来源转正二。

        2026-09-27 又补 `_with_witness_fingerprint()`：`AlignRefParams.witness_fingerprint`
        同一个坑，`witness_strategy != "legacy"` 时按 `references` 全部文件算（任务书
        D-多证人对齐策略）。
        `_with_book_gw()`（同日，T4 变体形）跟在它后面再叠一层——两个书级开关各自
        对 `RareCandidatesParams.model_fingerprint` 生效，顺序不能换（见 `_with_book_gw`
        文档「基准要带上 real_proto」那段）。

        2026-09-27 再补 `_with_book_params()`（D-书级admit覆盖）：书 yaml 顶层
        `params:` 段按字段通用覆盖任意 Step 的参数（`BookSpec.params`），放在**最前面**
        ——它是用户在书 yaml 里的明确配置，不该被下面几个"按本书 convenience
        默认值"的函数抢先占了"仍是默认值"这个判据的位置（见该函数文档）。
        """
        p = self.params.get(step.spec.id)
        if p is None:
            p = step.spec.params()
        p = _with_book_params(p, step, self)
        p = _with_book_corpus(p, self)
        p = _with_book_real_proto(p, self)
        p = _with_witness_fingerprint(p, self)
        p = _with_book_gw(p, self)
        p = _with_book_step6_ai(p, self)
        return p

    #: `_raw` 最多留几页（见 `raw_page`）。引擎按 step-major 顺序跑——
    #: 一个 Step 对全书每一页依次调用一次，同一个 `RunContext`／`self._raw`
    #: 贯穿整本书——**不是**只处理当前页那一刻才存在。留 2 页给相邻页偶尔
    #: 互相借用的场景（目前没有这种调用，纯防御）。
    _RAW_MAX = 2

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

        ⚠️ **`_raw` 必须有界**（2026-09-27，R-rare-mem 急件）：这里此前是无界
        `dict`，注释写着「同一页只读一次」，实现却是「每一页都留一份，一本书
        跑到底」——引擎按 step-major 顺序跑（一个 Step 对全书每页各调一次），
        188 页 × 每页原图 ~7MB，实测一遍 `border_detect`（`raw_page` 的调用方
        之一）跑下来 `_raw` 自己就攒到 1.4GB，且这份状态跨步骤持续存在
        （border_detect 那一遍攒的页，column_warp/rare_candidates 那几遍也不
        会释放，同一个 `RunContext` 全程共用）。四庫 vol03 服务器上
        `rare_candidates` 单进程涨破 3G 被杀，这是主要分量之一：轮到
        `rare_candidates` 跑时，`_raw` 早已被它前面那几个读原图的 Step
        （border_detect / column_warp / line_detect）攒满了整本书。改成 LRU
        （`_RAW_MAX` 页），没有任何调用点会跨页借用原图（`grep -rn "raw_page("`
        实测全部传的是 `run_page` 自己收到的那个 `page` 参数），所以留 2 页
        纯防御、行为不变；实测同样跑一遍 `border_detect` 全书，RSS 从
        72MB→1410MB（改前）变成 72MB→146MB 就不再涨（改后）。
        """
        if page in self._raw:
            self._raw.move_to_end(page)
            return self._raw[page]
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
        while len(self._raw) > self._RAW_MAX:
            self._raw.popitem(last=False)
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
    def cache_stamp(self, kind_id: str, key: str) -> str | None:
        """这张缓存图该对着的产物版本：产出它的那一步、这一页产物的 sha（见 `products/cache.py` 页戳）。
        那一页还没有 ok 的产物 → None（不验）。"""
        import re as _re
        m = _re.match(r"^p\d{4}", key)
        if not m:
            return None
        try:
            ent = self.store.manifest(self.book.id, self.producer(kind_id).spec.id).get(m.group(0))
        except Exception:                      # noqa: BLE001 —— 戳只是护栏，取不到不挡出图
            return None
        return ent.sha256 if ent is not None and ent.status == "ok" and ent.sha256 else None

    def materialize(self, kind_id: str, key: str) -> Path:
        step = self.producer(kind_id)
        return self.cache.materialize(
            self.book.id, kind_id, key,
            lambda: step.render(self, kind_id, key),
            stamp=self.cache_stamp(kind_id, key))

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
