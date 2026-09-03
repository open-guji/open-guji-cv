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
class StepSpec:
    id: str
    title: str
    version: str                     # 输出语义变了才升；参与指纹
    unit: Unit
    consumes: tuple[str, ...]        # 产物种类 id
    produces: tuple[str, ...]
    params: type[BaseModel]          # 参数 schema，默认值 = 生产配置
    when: str | None = None          # 单位级条件，P0 只记录不求值
    code_deps: tuple[str, ...] = field(default=())
    """参与指纹的模块名（算法所在模块）。Step 自己的模块总是参与。"""


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
