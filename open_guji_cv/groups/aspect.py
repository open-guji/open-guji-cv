"""日曰 字形宽高比（只作证据）：日窄长、曰扁宽。

字块主体外框 宽/高 ≤ `LOW` → 日；≥ `HIGH` → 曰；中间弃权。阈值取自殿本 vol02–10 的字块图：
整理本字为日的格 宽/高 中位 0.69、为曰的 0.84；人裁格日 0.68–0.80、曰 0.76–0.90（日少、两头有重叠，所以取两头、中间弃权）。
质量闸沿用入人八分类器（散斑、贴边长线、贴边墨多 → 不给字）。
只在 `group_flow` 的 ry 组里当「第二路」：文意给字、字形强烈指向另一个字 → 冲突降审；单独不许补放（`lift_needs=("ctx",)`）。
"""
from __future__ import annotations

import numpy as np

from ..utils import rr_clf

LOW = 0.68
HIGH = 0.88


def aspect(gray: np.ndarray) -> float | None:
    """主体外框 宽/高；没有可用字形、或质量闸不过 → None。"""
    if rr_clf.gated(rr_clf.quality(gray)):
        return None
    b = rr_clf.binarize(gray)
    if b is None:
        return None
    m, _ = rr_clf.main_body(b)
    if m is None or m.shape[0] < 8 or m.shape[1] < 8:
        return None
    return m.shape[1] / m.shape[0]


def judge(gray: np.ndarray) -> tuple[str | None, float | None]:
    """→ (日|曰|None, 宽高比)。"""
    r = aspect(gray)
    if r is None:
        return None, None
    return ("日" if r <= LOW else "曰" if r >= HIGH else None), r
