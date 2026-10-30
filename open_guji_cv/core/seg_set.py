"""套书（seg_set）登记：一册书的切分代码归哪一套（2026-10-30，Sheldon 定）。

一套书 = `open_guji_cv/books/<套书>/` 下自管的切分代码。册 yaml 写 `seg_set:` 指定；不写按管线推：
keben_body_v2 → siku_zongmu，keben_free → zengguang_youxue，modern_body → beixing。
shiji_wyg（史記文淵閣本，写本）从殿本分叉，必须在册 yaml 里显式写。

## 指纹

`SERIES_MODULES[(套书, 步 id)]` 是这套书在这一步额外参与产物指纹的模块（`books/<套书>/…`）。
搬家前（第 1 步）全空，所以现有产物的指纹逐位不变；代码搬进套书目录后，把它们登记到这里，
指纹就按套书算：改史記的文件，殿本的产物不过期。本模块在 core，只放数据与字符串，不 import `books`。
"""

from __future__ import annotations

SEG_SETS: tuple[str, ...] = ("siku_zongmu", "shiji_wyg", "zengguang_youxue", "beixing")

PIPELINE_SEG_SET: dict[str, str] = {
    "keben_body_v2": "siku_zongmu",
    "keben_free": "zengguang_youxue",
    "modern_body": "beixing",
}

SERIES_MODULES: dict[tuple[str, str], tuple[str, ...]] = {}


def validate_seg_set(name: str | None) -> str | None:
    if name is not None and name not in SEG_SETS:
        raise ValueError(f"seg_set {name!r} 不在登记表里，可选 {list(SEG_SETS)}（core/seg_set.py）")
    return name


def seg_set_of(book) -> str:
    """这册书的套书：册 yaml 显式写的优先，否则按管线推。"""
    explicit = getattr(book, "seg_set", None)
    if explicit:
        return explicit
    return PIPELINE_SEG_SET.get(book.default_pipeline_id(), "siku_zongmu")


def series_modules(book, step_id: str) -> tuple[str, ...]:
    """本册在这一步额外参与指纹的套书模块；搬家前恒为空。"""
    return SERIES_MODULES.get((seg_set_of(book), step_id), ())
