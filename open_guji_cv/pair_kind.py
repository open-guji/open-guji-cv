# -*- coding: utf-8 -*-
"""字对关系表 `config/dicts/variants.pairkind.tsv`：形近字的两种关系，只在这里定（sheldon 2026-11-21）。

- **V 同义异体**：同一个字的不同写法（衛/衞、䜿/豎）。算同一个字：语义表归一、关系图有边；刻本录刻形，文意帮不上。
- **C 纯形近**：意思不同、只是像（土/士、兩/雨），或只是通假。不算同一个字：语义表不并、关系图无边；文意是主要判据。

每行 `字甲<TAB>字乙<TAB>V|C<TAB>来源<TAB>备注`（`#` 开头为注释）。来源：`never_group`（人审定永不并组）、`人定`（用户审阅页）、
`A31初判`（按字义自动定）、`auto:强源`（关系图有 Unihan／yitizi／本书刻例边）。不在表里的对照旧办法：语义表与关系图各管各。

表由 `scripts/build_pair_kind.py` 生成；人定的行优先，改了重生成不会丢（脚本读已有「人定」行原样保留）。
语义表（`clustering.variants.VariantMap.load`）和关系图（`variants.VariantGraph.load`）加载默认文件时都套用这张表，
所以第 5、7 步、manager 凡是问「是不是异体」的地方答案一致。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PAIR_KIND_PATH = Path(__file__).resolve().parents[1] / "config" / "dicts" / "variants.pairkind.tsv"
V, C = "V", "C"
TAG = "local:pairkind"          # 关系图里这类边的来源标签（算异体来源、高置信）


@lru_cache(maxsize=4)
def _load(path: str) -> dict[frozenset[str], str]:
    p = Path(path)
    out: dict[frozenset[str], str] = {}
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        f = line.split("\t")
        if len(f) >= 3 and f[0] and f[1] and f[0] != f[1] and f[2] in (V, C):
            out[frozenset((f[0], f[1]))] = f[2]
    return out


def load_pair_kinds(path: str | Path | None = None) -> dict[frozenset[str], str]:
    """{无序字对: "V"|"C"}。文件缺失 → 空。"""
    return _load(str(path or PAIR_KIND_PATH))


def pair_kind(a: str, b: str, path: str | Path | None = None) -> str | None:
    """这对字的人定／自动类别：`"V"` 同义异体、`"C"` 纯形近、不在表里 `None`。"""
    return load_pair_kinds(path).get(frozenset((a, b)))
