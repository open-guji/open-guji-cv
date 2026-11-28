"""自由版式 → 标准列图的几何（`free_to_cells` 用；2026-11-28，默认链第二期）。

两件事：
1. **列图怎么拉直**：与 `cell_cut` 同一套逐行平移（`free_cells.straighten`）——列的左右弯缝之间的像素逐行平移到左对齐。
   `column_rows` 按 `cell_cut` 的算式重算每行的起点，`free_cells` 的字框换到列图坐标逐位对得上。
2. **列图坐标 → 原图坐标**：列图 (x, y) → 拉正后的页 (x + xa + L[y], y + y0) → 原图（`layout_blocks.warp`
   的 Coons 片，`warp_points` 与 `free_rectify.warp_maps` 同一算式、逐点算，不建整页 map）。
   `steps/_warpmap.ColumnMapper.of` 见到列窗里的 `free_map` 就走这条（`FreeColumnMapper`）。

本模块不进 `cell_cut` 等已有 Step 的 code_deps；改 `free_rectify.warp_maps` 时这里要跟着改（`tests/test_free_to_cells.py` 守两边一致）。
"""

from __future__ import annotations

import numpy as np

from .free_cells import column_span, seam_rows
from .free_rectify import _coons


def column_rows(col, W: int, pad: int = 2) -> tuple[int, int, np.ndarray, np.ndarray, int]:
    """一列（`ColumnRec`）在拉正后的页上怎么裁：(xa, xb, L, R, wc)。

    xa..xb 是横向裁的范围（左上原点，`column_span`）；L、R 是逐行（相对 `int(col.y0)`）缝在 xa 起的局部 x
    （各让 `pad`，夹到 [0, xb−xa−1]）；wc 是列图宽。与 `cell_cut` 调 `straighten(src, left − xa, right − xa)` 逐位相同。"""
    left, right = seam_rows(col, W)
    xa, xb = column_span(col, W)
    w = xb - xa
    L = np.clip(left - xa - pad, 0, w - 1)
    R = np.clip(right - xa + pad, 0, w - 1)
    return xa, xb, L, R, int(np.max(R - L)) + 1


def straighten_gray(gray: np.ndarray, y0: int, y1: int, xa: int, L: np.ndarray, R: np.ndarray, wc: int,
                    keep: np.ndarray | None = None) -> np.ndarray:
    """拉正后的页灰度图 → 列图（h×wc，uint8，缝外白）。`keep`（同页大小的 bool）为假的像素抹白（框线、界栏）。"""
    h = y1 - y0
    out = np.full((h, wc), 255, np.uint8)
    for y in range(h):
        a, b = xa + int(L[y]), xa + int(R[y]) + 1
        row = gray[y0 + y, a:b]
        if keep is not None:
            row = np.where(keep[y0 + y, a:b], row, 255)
        out[y, :len(row)] = row
    return out


def warp_points(warp: dict, xs, ys) -> tuple[np.ndarray, np.ndarray]:
    """拉正后的页坐标 (x, y)（左上原点，可为小数）→ 原图坐标；与 `free_rectify.warp_maps` 同一算式。"""
    X = np.atleast_1d(np.asarray(xs, np.float64))
    Y = np.atleast_1d(np.asarray(ys, np.float64))
    X0, Y0, X1, Y1 = warp["rect"]
    cv = warp["curves"]
    tl, tr, bl, br = warp["corners"]
    H = warp["size"][1]
    u = np.clip((X - X0) / (X1 - X0), 0, 1)
    hs = [(cv["top"], Y0, tl, tr)] + [(m["curve"], m["y"], *m["corners"]) for m in warp.get("mids", [])] \
        + [(cv["bottom"], Y1, bl, br)]
    Sx = np.zeros_like(X)
    Sy = np.zeros_like(Y)
    row = np.clip(np.floor(Y), 0, H - 1)      # warp_maps 按整行分片；小数 y 归它 floor 所在那行的片
    for i in range(len(hs) - 1):
        (ct, ya, a1, a2), (cb, yb, b1, b2) = hs[i], hs[i + 1]
        lo = 0 if i == 0 else int(np.ceil(ya))
        hi = H if i == len(hs) - 2 else int(np.ceil(yb))
        m = (row >= lo) & (row < hi)
        if hi <= lo or not m.any():
            continue
        v = np.clip((Y[m] - ya) / (yb - ya), 0, 1)
        Sx[m], Sy[m] = _coons(ct, cb, cv["left"], cv["right"], a1, a2, b1, b2, u[m], v)
    Sx = Sx + (X - (X0 + u * (X1 - X0)))
    Sy = Sy + (Y - np.clip(Y, Y0, Y1))
    return Sx, Sy


def rows_runs(L: np.ndarray) -> list[list[int]]:
    """逐行起点 → 游程 [[行, 值], …]（与 `cells.seam_runs` 同写法，落盘省地方）。"""
    runs = [[0, int(L[0])]] if len(L) else []
    for y in range(1, len(L)):
        if L[y] != L[y - 1]:
            runs.append([y, int(L[y])])
    return runs


def runs_rows(runs: list, n: int) -> np.ndarray:
    out = np.zeros(n, np.float64)
    for i, (y, v) in enumerate(runs):
        end = runs[i + 1][0] if i + 1 < len(runs) else n
        out[int(y):int(end)] = v
    return out
