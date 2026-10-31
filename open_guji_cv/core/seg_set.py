"""套书（seg_set）登记：一册书的切分代码归哪一套（2026-10-30，Sheldon 定）。

一套书 = `open_guji_cv/books/<套书>/` 下自管的切分代码。册 yaml 写 `seg_set:` 指定；不写按管线推：
keben_body_v2 → siku_zongmu，keben_free → zengguang_youxue，modern_body → beixing。
shiji_wyg（史記文淵閣本，写本）从殿本分叉，必须在册 yaml 里显式写。

## 套书各自的实现

套书之间不互相 import，但共用同一个 Step 壳：壳问 `resolve(book, 缺省实现模块)`，这套书有自己的实现就用它，
没有就用缺省（殿本）的。`OVERRIDES[套书]` 登记「缺省模块 → 这套书自己的模块」。同一张表也进指纹
（`engine.code_hash` 把 Step 的 `code_deps` 里被覆盖的模块换成这套书的），所以改史記的模块只让史記的产物过期，
改殿本的同名模块也不会牵动史記。本模块在 core，只放数据与字符串，不 import `books`。
"""

from __future__ import annotations

SEG_SETS: tuple[str, ...] = ("siku_zongmu", "shiji_wyg", "zengguang_youxue", "beixing")

PIPELINE_SEG_SET: dict[str, str] = {
    "keben_body_v2": "siku_zongmu",
    "keben_free": "zengguang_youxue",
    "modern_body": "beixing",
}

_SIKU = "open_guji_cv.books.siku_zongmu."
_SJ = "open_guji_cv.books.shiji_wyg."

#: 套书 → {缺省实现模块: 这套书自己的模块}。史記是从殿本分叉出来的写本：先只分叉职名页（臣行拆分等写本专用逻辑），
#: 别的步骤仍走缺省实现；以后哪一步要为写本改，就把那个模块复制进 books/shiji_wyg/ 再登记在这里。
OVERRIDES: dict[str, dict[str, str]] = {
    "shiji_wyg": {
        _SIKU + "roster_segment": _SJ + "roster_segment",
        _SIKU + "roster_glyph": _SJ + "roster_glyph",
    },
}


def validate_seg_set(name: str | None) -> str | None:
    if name is not None and name not in SEG_SETS:
        raise ValueError(f"seg_set {name!r} 不在登记表里，可选 {list(SEG_SETS)}（core/seg_set.py）")
    return name


def seg_set_of(book) -> str:
    """这册书的套书：册 yaml 显式写的优先，否则按管线推。"""
    explicit = getattr(book, "seg_set", None)
    if explicit:
        return explicit
    pid = getattr(book, "pipeline", None)
    if not pid:
        f = getattr(book, "default_pipeline_id", None)
        pid = f() if callable(f) else None
    return PIPELINE_SEG_SET.get(pid, "siku_zongmu")


def resolve(book, default_module: str) -> str:
    """这册书在 `default_module` 这个位置该用哪个模块：套书有覆盖用覆盖，否则用缺省。"""
    ov = OVERRIDES.get(seg_set_of(book))
    return ov.get(default_module, default_module) if ov else default_module


def replace_deps(book, mods: list[str]) -> list[str]:
    """指纹用：把 Step 的模块表里被这册套书覆盖的模块换成套书自己的（顺序不变）。"""
    if not OVERRIDES:
        return mods
    return [resolve(book, m) for m in mods]
