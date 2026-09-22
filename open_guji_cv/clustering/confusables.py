# -*- coding: utf-8 -*-
"""形近对表（`config/ids/confusable_pairs_v1.tsv`）的读取与查询。

表由 IDS 关系（同结构只差一槽 / 同部件异布局）+ 字体模板 embedding 余弦闸 + 纯视觉近邻
三路合成，怎么算、阈值怎么标定见表头与 `ccr_rare_char_literature_review.md` §6 N2。
用途只有三个：形近靶子抽样、训练硬负例、审字卡片的「存在形近字 X，差在 R 槽」提示。
**永远不进放行**——形近关系是提醒人看哪里，不是判据。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
DEFAULT_TABLE = _REPO / "config" / "ids" / "confusable_pairs_v1.tsv"


@lru_cache(maxsize=2)
def load_pairs(path: str | Path = DEFAULT_TABLE) -> dict[str, list[tuple[str, str, float, str]]]:
    """→ {字: [(形近字, kind, cos, detail), …]}，每个字按 cos 降序。文件不存在 → 空表（面板照常）。"""
    p = Path(path)
    out: dict[str, list[tuple[str, str, float, str]]] = {}
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or line.startswith("a\t"):
            continue
        a, b, kind, cos, detail = (line.split("\t") + [""] * 5)[:5]
        c = float(cos)
        out.setdefault(a, []).append((b, kind, c, detail))
        out.setdefault(b, []).append((a, kind, c, detail))
    for v in out.values():
        v.sort(key=lambda t: -t[2])
    return out


def near_forms(ch: str, k: int = 3, within: set[str] | None = None,
               path: str | Path = DEFAULT_TABLE) -> list[dict]:
    """`ch` 的形近字前 k 个（可限定在 `within` 字集内），面板用的字典形。"""
    rows = load_pairs(path).get(ch, [])
    out = []
    for b, kind, c, detail in rows:
        if within is not None and b not in within:
            continue
        out.append({"char": b, "kind": kind, "cos": round(c, 3), "detail": detail})
        if len(out) >= k:
            break
    return out


def is_pair(a: str, b: str, path: str | Path = DEFAULT_TABLE) -> bool:
    return any(x[0] == b for x in load_pairs(path).get(a, []))
