# -*- coding: utf-8 -*-
"""统计：别把噪声当提升。

- `paired_bootstrap`：以**页**为簇的配对自助法。两个变体跑的是同一批页、同一批格，
  格与格在页内相关（同一页的版式、墨色、切分质量一起变），按格重抽会把区间算窄；按页重抽、
  两边用同一组重抽页，求「比率之差」的分位数区间。
- `mcnemar_exact`：逐格配对的二值结果（如「这格是不是放行错」），只看不一致的格，精确二项检验。
- `wilson`：单个变体比率的 Wilson 区间（标签少时比正态近似靠谱）。

全部纯 Python + 固定种子，结果可复现。
"""
from __future__ import annotations

import math
import random


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, c - h), min(1.0, c + h)


def _binom_cdf(k: int, n: int) -> float:
    """P(X ≤ k)，X ~ Bin(n, 1/2)。"""
    return sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)


def mcnemar_exact(b: int, c: int) -> float | None:
    """双侧精确 McNemar：b = A 好 B 坏，c = A 坏 B 好。没有不一致的格返回 None。"""
    n = b + c
    if n == 0:
        return None
    return min(1.0, 2 * _binom_cdf(min(b, c), n))


def paired_bootstrap(pages: list[tuple[float, float, float, float]], *, n_boot: int = 2000,
                     seed: int = 0, alpha: float = 0.05, min_valid: float = 0.9
                     ) -> tuple[float, float] | None:
    """`pages` 每页一行 (A 分子, A 分母, B 分子, B 分母)；统计量 = ΣB分子/ΣB分母 − ΣA分子/ΣA分母。

    重抽里任一边分母为 0 的那次作废；作废超过 `1-min_valid` 就认为区间不可靠，返回 None。"""
    if not pages:
        return None
    rng = random.Random(seed)
    m = len(pages)
    diffs = []
    for _ in range(n_boot):
        an = ad = bn = bd = 0.0
        for _ in range(m):
            a1, a2, b1, b2 = pages[rng.randrange(m)]
            an += a1
            ad += a2
            bn += b1
            bd += b2
        if ad > 0 and bd > 0:
            diffs.append(bn / bd - an / ad)
    if len(diffs) < min_valid * n_boot:
        return None
    diffs.sort()
    lo = diffs[int(math.floor(alpha / 2 * (len(diffs) - 1)))]
    hi = diffs[int(math.ceil((1 - alpha / 2) * (len(diffs) - 1)))]
    return lo, hi
