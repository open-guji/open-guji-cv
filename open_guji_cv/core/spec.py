"""Step / ProductKind 的声明，以及单位键的编码。

**存储粒度 = 页。** `unit` 只描述语义（这一步的最小重跑单位），P0 的产物文件与
指纹都按页落（column / cell 单位的产物是页文件里的列表）。要更细的粒度，
改 engine 的 key 选择即可，Step 接口不用动。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

Storage = Literal["numeric", "image_cache", "image_keep"]
Unit = Literal["book", "page", "column", "cell"]

# 坐标空间标识（见 anchor.py）
RAW_TR = "raw_page_px@top-right"   # 规范空间：右上原点，x 向左，y 向下
RAW_TL = "raw_page_px@top-left"    # OpenCV / 旧 v1 产物
COLUMN_PX = "column_px"            # Step2 矫正后的列图坐标


@dataclass(frozen=True)
class ProductKindSpec:
    """一种产物。numeric 的必须给 pydantic schema；图像类不用。"""
    id: str
    title: str
    storage: Storage
    unit: Unit
    schema: type[BaseModel] | None = None
    coord_space: str | None = None
    ext: str = "png"          # 图像类的文件扩展名

    def __post_init__(self) -> None:
        if self.storage == "numeric" and self.schema is None:
            raise ValueError(f"numeric 产物 {self.id!r} 必须声明 schema")


@dataclass(frozen=True)
class GateLevel:
    """闸的一层判据，只做文档/查询展示用——执行体仍在闸自己的 `run_page` 里，
    这里不驱动执行，纯重组阶段不把判据拆成逐层可插拔的函数（那是改算法，不是这一轮的事）。"""
    id: str
    """层号，如 `L1` / `L1c` / `L2b`。**只表示「第几道关卡」，不是可读的名字**：
    L0 版式层面本来就不该走这条链 · L1 结构性硬指标（多为 block）·
    L2 几何质量（多为 flag）· L3 人裁准入 · L4 更细粒度的内容质量；
    后缀字母是同一层里的不同判据（`L1c` = L1 的列级版本，`L2b` = L2 的第二条）。

    **新判据请同时给 `name`**，产物消息里印的是 name 而不是这个号——
    用户 2026-09-18：「所有 gate、裁决的名字，还是用英文单词 2-3 个比较直观」。
    层号保留是因为它表达「拦截的严重程度顺序」，那是 name 表达不了的。"""
    unit: Unit                       # 这一层判到哪个粒度
    desc: str = ""                   # 一句话判据，别写具体阈值数字（那些在 Params 里，写两处会漂）
    name: str = ""
    """机器可读的短名，2~3 个英文单词、`snake_case`，如 `column_count`、
    `frame_residue`。产物里的 reject/flag 消息以 `<name>：…` 开头，
    前端与下游按它分类，不必查层号表。空 = 尚未命名的老判据（沿用层号）。"""

    @property
    def tag(self) -> str:
        """产物消息该用的前缀：有 name 用 name，没有就退回层号。"""
        return self.name or self.id


@dataclass(frozen=True)
class GateSpec:
    """挂在某个 Step 出口的闸。`id` 是这道闸自己的 Step id——它仍然是一个正常
    注册进 `STEPS` 的 `Step`（有自己的 `consumes`/`produces`/落盘目录/指纹），
    只是不出现在任何 pipeline yaml 的 `steps:` 列表里；引擎跑完被挂的 Step 后
    自动接着跑它（见 `core.step.attach_gate` 与 `core.engine.Engine.run`）。"""
    id: str
    unit: Unit
    levels: tuple[GateLevel, ...] = ()
    on_fail: Literal["block", "flag", "degrade"] = "block"


@dataclass(frozen=True)
class StepSpec:
    id: str
    title: str
    version: str                     # 输出语义变了才升；参与指纹
    unit: Unit
    consumes: tuple[str, ...]        # 产物种类 id（**硬依赖**：缺一个就阻塞整步）
    produces: tuple[str, ...]
    params: type[BaseModel]          # 参数 schema，默认值 = 生产配置
    when: str | None = None          # 单位级条件，P0 只记录不求值
    optional_consumes: tuple[str, ...] = field(default=())
    """**可选上游**：缺了照跑，只是这一路证据没有，`run_page` 自己兜住（拿到 None）。

    与 `consumes` 的区别只在**缺席时怎么办**：硬依赖缺席 → `upstream_shas` 返回
    None、整步阻塞；可选上游缺席 → 不阻塞，只是不进指纹（在的时候照常进，改了
    照样让下游过期）。

    2026-09-13 加：`ocr_candidates`（Step5-c）是书级开关 `BookSpec.ocr_candidates`
    控制的可选步骤（默认关），关掉时 `Engine._enabled` 直接把它从 steps 里滤掉。
    但 `align_ref`/`context_decide`/`seed_admit` 当初把它写进了 `consumes`，于是
    指纹层 `upstream_shas` 认它是硬依赖、短路返回 None，**三步全部阻塞**——而这
    三步的 `run_page` 其实早就写好了容错（`seed_admit._opt` docstring 直说"可选
    上游：缺了就 None，不炸"；`align_ref` 只在 match 和 ocr 都缺时才报错），那些
    代码根本没机会跑到。声明与实现对不上，这个字段就是用来把实现的意图表达出来的。"""
    code_deps: tuple[str, ...] = field(default=())
    """参与指纹的模块名（算法所在模块）。Step 自己的模块总是参与。"""
    book_deps: tuple[str, ...] = field(default=())
    """参与指纹的 **`BookSpec` 字段名**。

    指纹只认 `params` + `code` + `upstream`，**册配置不在其中**——于是「改了
    `books/<id>.yaml` 里一个影响输出的字段，已有产物却照报『新鲜』」。
    参数的默认值写 `None`（"None = 用 Book 的 X"）也救不了：`None` 在两本书上
    哈希出来一模一样。

    2026-09-15 `leaf_layout` 踩到（改成 `folio` 后 Step1 该把版心标 `margin`，
    却整页跳过）。凡是 `run_page` 里读了 `ctx.book.X` 且 X 会改变产物的，
    都要在这里声明 X。"""
    soft_params: tuple[str, ...] = field(default=())
    """**软参数**：参数模型里这些字段**不进指纹**（`params_hash` / `self_hash` 都剔掉），
    只把当时的值记进 manifest 条目的 `soft`，`status` 另报「漂移」、不报过期。

    2026-09-25 加，给 `glyph_match` 的 `db_fingerprint` 用（用户定）：字形库是外部
    可变状态，人裁每进一批字形库指纹就变，按硬参数算就是全书 Step5-a 过期、且格级
    复用第一道闸（`self_hash`）也跟着失效——一页半分钟，一册一个多小时，而新进的
    几个字形绝大多数格的判决根本不动。改成软参数之后：

    - 库变了**不自动**重跑；`guji status` 在「漂移」一列告诉你有多少页是对旧库判的；
    - 要吃新库的红利、或确知某些字形有问题，用 `guji recheck` 点名格
      （按字 / 按判档 / 命中的库条目已撤）→ 只重算点名的格，其余格照旧复用；
    - `--force` 仍是整页全算的最后手段（配 `GUJI_NO_REUSE=1`）。

    只适合「值变了、但绝大多数产物仍然成立」的外部状态。代码、阈值、checkpoint
    这类一变就整体失效的东西**不许**放这里（cv-pipeline-ops §2.2）。"""
    needs: tuple[str, ...] = field(default=())
    """跑得起来的**外部**前提，控制台据此把跑不了的步骤置灰而不是让人点了才失败。
    口径与 `eval/registry.py` 的 `needs` 一致：

        engine    要 OCR 引擎 / GPU（rapidocr 等）
        corpus    要语料文件
        db        要 GlyphDB
        heavy     分钟级以上

    只是**声明**，不参与指纹——同一份代码在装了引擎的机器上跑出来的产物，
    跟没装的机器上的空产物不是一回事，但那个差别由参数（如引擎名）和产物
    内容自己体现，不该混进 Step 指纹。"""
    gate: GateSpec | None = None
    """这个 Step 出口挂的闸（P0 只有 Step2 有），由 `core.step.attach_gate` 事后
    挂上——不需要在这里手写，写在这里只是给类型看。"""
    parallel_safe: bool = False
    """`run_page` 页间互不依赖、无跨页累积状态、不写非按页隔离的共享文件，可以
    安全地用页级 `ProcessPoolExecutor` 并行跑（`Engine.run(jobs=N)`）。**默认 False**
    ——没审查过的 Step 一律当不安全，标 True 前必须逐行确认：没有跨页计数器/
    集合、没有依赖执行顺序的一次性初始化（会被每个子进程重复触发）、写的都是
    `store.write(..., page_key(pg), ...)` 这种按页隔离的产物，数据库/字形库连接
    （若有）能在子进程里各自新建而非跨进程共享。标错的代价是静默数据错误，
    不是报错——宁可漏标（退化成串行）也不要错标。"""


# ── 单位键 ───────────────────────────────────────────────────────────
# p0042 / p0042c03 / p0042c03s17 —— 页从 1 起、列从右到左从 1 起、slot 见 Step3

_KEY_RE = re.compile(r"^p(\d{4})(?:c(\d{2}))?(?:s(-?\d+))?$")


def page_key(page: int) -> str:
    return f"p{page:04d}"


def column_key(page: int, col: int) -> str:
    return f"p{page:04d}c{col:02d}"


def cell_key(page: int, col: int, slot: int) -> str:
    return f"p{page:04d}c{col:02d}s{slot}"


def parse_key(key: str) -> tuple[int, int | None, int | None]:
    m = _KEY_RE.match(key)
    if not m:
        raise ValueError(f"非法单位键: {key!r}")
    page = int(m.group(1))
    col = int(m.group(2)) if m.group(2) else None
    slot = int(m.group(3)) if m.group(3) else None
    return page, col, slot


def page_of(key: str) -> int:
    return parse_key(key)[0]
