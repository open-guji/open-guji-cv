# -*- coding: utf-8 -*-
"""己／已／巳 的上下文决策表（overview#428，N1）。

表 `config/near_form_ctx_jys.json` 由 `research/near_form/build_ctx_table.py` 从外部语料
（daizhige，与四庫总目无重叠）数「本族字 × 前后 1–2 字」的共现建成。判一格时按特异度
(2,2) > (1,1) > (2,0) > (0,2) > (1,0) > (0,1) 查键，第一个 n ≥ min_n 的键：最高字占比 ≥ purity
就定字，否则弃权（见过但不纯，不往更粗的键退）。弃权 = 交人审。

强真值格（人裁＋看图，vol02–04 共 112 格）上：purity 0.98、min_n 5 定 13 格、错 0（样本小，
0 错的 95% 上界约 20%）。日／曰、入／人／八 上同一张表当否决没有已知收益、还错判过人裁真值，
所以只做了己已巳（见 overview#428）。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[2] / "config" / "near_form_ctx_jys.json"
_ORDER = ((2, 2), (1, 1), (2, 0), (0, 2), (1, 0), (0, 1))
_FAM = "己已巳"


@lru_cache(maxsize=2)
def _table(path: str) -> dict[str, list[int]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["keys"]


def decide(prev: str, nxt: str, purity: float = 0.98, min_n: int = 5,
           path: str | None = None) -> tuple[str | None, str]:
    """→ (字 | None, 依据)。`prev` / `nxt`：本页读序紧邻的前 / 后文（只传连续已知的字，最多各取 2 字）。"""
    tab = _table(str(path or CONFIG))
    for a, b in _ORDER:
        if len(prev) < a or len(nxt) < b:
            continue
        l, r = (prev[len(prev) - a:] if a else ""), nxt[:b]
        c = tab.get(f"{a}{b}|{l}|{r}")
        if not c:
            continue
        n = sum(c)
        if n >= min_n:
            k = max(c)
            if k / n >= purity:
                return _FAM[c.index(k)], f"上下文表{a}{b}:{l}_{r} {k}/{n}"
            return None, f"上下文表不纯{a}{b}:{l}_{r} {dict(zip(_FAM, c))}"
    return None, "上下文表无键"
