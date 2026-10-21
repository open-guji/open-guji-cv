# -*- coding: utf-8 -*-
"""特殊符号表：刻本上的圈、方框、三角这类图形字符（`config/charset/symbols.tsv`，唯一登记处）。

设计见 `doc/design/特殊符号进字符候选集-设计.md`。它们不是汉字，各路只认汉字的过滤（`is_han`、
`charset_spec._cjk`）都会把它们挡掉；要让某一路收符号，从这里读，不在各处手写。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

TSV = Path(__file__).resolve().parents[2] / "config" / "charset" / "symbols.tsv"


@lru_cache(maxsize=1)
def symbols() -> dict[str, str]:
    """`{符号: 名称}`，按表里的顺序。"""
    out: dict[str, str] = {}
    for line in TSV.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        c, name, *_ = line.split("\t") + [""]
        if len(c) == 1:
            out[c] = name
    return out


def is_symbol(c: str) -> bool:
    return c in symbols()
