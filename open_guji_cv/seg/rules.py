"""剥长直线（界行、版框横线）：只看二值墨图，不认识任何一套书。

写本连笔、再加一条贯穿整列的界行，一串字会连成一个连通块；做连通块分析（漏切块、发前清格）之前先剥掉长直线。
2026-11-12 A22（《切分三方向》第 6 步）：史記书仓 `patch_clean`、史記快筛 `ctx2.py`、cv `eval/seg_screen.strip_long_lines`
原先各抄一份同样的两次开运算（竖 200px、横 0.85 列宽且至少 40px），收成这一个原语。
"""
from __future__ import annotations

import numpy as np


def long_rule_mask(ink: np.ndarray, *, vline: int = 200, hline_frac: float = 0.85,
                   hline_min: int = 40) -> np.ndarray:
    """二值墨图（非 0 即墨）里长直线的掩膜（0/1，同形状）。

    - 竖线：竖向开运算 `vline` px（比一个字高得多才算界行）；
    - 横线：横向开运算 `max(hline_min, int(hline_frac × 图宽))` px（几乎横贯整列才算版框横线）。
    """
    import cv2
    ink = (np.asarray(ink) > 0).astype(np.uint8)
    w = ink.shape[1]
    vl = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((max(1, int(vline)), 1), np.uint8))
    hl = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, max(int(hline_min), int(hline_frac * w))), np.uint8))
    return ((vl | hl) > 0).astype(np.uint8)


def strip_long_rules(ink: np.ndarray, *, vline: int = 200, hline_frac: float = 0.85,
                     hline_min: int = 40) -> np.ndarray:
    """二值墨图剥掉长直线后的墨（0/1）。参数同 `long_rule_mask`。"""
    mask = long_rule_mask(ink, vline=vline, hline_frac=hline_frac, hline_min=hline_min)
    return ((np.asarray(ink) > 0) & (mask == 0)).astype(np.uint8)
