"""列图坐标 ↔ 页面坐标：让切线金标不再随 Step2 几何漂移（2026-09-25）。

## 为什么要有

切线金标（`char-segmentation/touching-cuts`）的 `y` / `polyline` 存在**列图坐标**里，而列图是
Step2 按两条边线做的射影矫正（三段折线页每带一个矩阵）。任何边线几何的变化都会让同一行号
指到另一处——**列高却可以一点不变**。评测与控制台 drift 档只比 `col_h`，于是漂了也照算：

vol02 09-25 实测：≤10px 以外的 20 条里，p119c8「學」、p119c5「吉」、p45c5「非」、p110c7「言」
等金标落在字身上、现役切在字缝里，`col_h` 与当前列图**逐像素相等**。评测报「切分退步」，
实际是金标坐标对不上。事后无法补救：当时的列窗几何没留档。

## 现在怎么记

写入切线裁决时（控制台 `/api/events`、`remap_cutline_gold.py`）一并记：

- `geom_sig`：该列列窗几何（两条边线 + 上下界 + 页宽）的签名；
- `page_x` / `page_y`：切线（列中线那一点）的**页面坐标**；
- `page_polyline`：折线逐点的页面坐标。

矫正矩阵的源四边形顶/底边都是水平的，页面上的横线在列图里仍是横线，所以一条切线的行号
与 x 无关，列中线一点就能代表（与 `remap_cutline_gold.py` 同一推理）。

评测按 `gold_rows_now` 取当前坐标：有页面坐标 → 用当前几何换算（永不漂移）；只有签名 →
签名不同就判漂移；都没有（2026-09-25 之前的老条目）→ 退回 `col_h` 口径，并单独计数。
"""
from __future__ import annotations

import hashlib
import json

import numpy as np

GEOM_KEYS = ("left_line", "right_line", "top_y", "bottom_y")
STAMP_KEYS = ("geom_sig", "page_x", "page_y", "page_polyline")


def _round(v):
    if isinstance(v, float):
        return round(v, 3)
    if isinstance(v, dict):
        return {k: _round(x) for k, x in sorted(v.items())}
    if isinstance(v, (list, tuple)):
        return [_round(x) for x in v]
    return v


def geom_sig(rec: dict, page_w: int | None) -> str:
    """一列列窗几何的签名。`rec` 是 `column_windows` 里该列的 dict（JSON 形态）。"""
    payload = {k: _round(rec.get(k)) for k in GEOM_KEYS}
    payload["page_w"] = page_w
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]


class ColumnGeom:
    """一列的射影几何：分带矩阵 + 行号偏移（原在 scripts/remap_cutline_gold.py）。"""

    def __init__(self, rec: dict, page_w: int):
        from ..products.kinds.borders import VLineRec
        from ..utils.column_projection import _strip_bounds, column_warp_matrix
        self.sig = geom_sig(rec, page_w)
        self.left = VLineRec(**rec["left_line"]).to_vline()
        self.right = VLineRec(**rec["right_line"]).to_vline()
        self.top, self.bottom = float(rec["top_y"]), float(rec["bottom_y"])
        poly = self.left.segments == 3 or self.right.segments == 3
        self.strips = (_strip_bounds(self.left, self.right, self.top, self.bottom) if poly
                       else [(self.top, self.bottom)])
        mats = [column_warp_matrix(page_w, self.left, self.right, a, b) for a, b in self.strips]
        self.out_w = max(m[1] for m in mats)
        self.mats = [column_warp_matrix(page_w, self.left, self.right, a, b, out_w=self.out_w)
                     for a, b in self.strips]
        self.offs = [0]
        for m in self.mats:
            self.offs.append(self.offs[-1] + m[2])
        self.height = self.offs[-1]
        self.invs = [np.linalg.inv(m[0]) for m in self.mats]

    def row_to_page(self, r: float, u: float | None = None) -> tuple[float, float]:
        u = self.out_w / 2.0 if u is None else u
        i = max(0, min(len(self.strips) - 1,
                       next((k for k in range(len(self.strips)) if r < self.offs[k + 1]),
                            len(self.strips) - 1)))
        p = self.invs[i] @ np.array([u, r - self.offs[i], 1.0])
        return float(p[0] / p[2]), float(p[1] / p[2])

    def page_to_row(self, x: float, y: float) -> tuple[float, float]:
        """→ (列图行号, 列图 x)。"""
        i = max(0, min(len(self.strips) - 1,
                       next((k for k, (a, b) in enumerate(self.strips) if y < b),
                            len(self.strips) - 1)))
        p = self.mats[i][0] @ np.array([x, y, 1.0])
        return float(p[1] / p[2]) + self.offs[i], float(p[0] / p[2])


def current_geom(store, book: str, page: int, col: int) -> ColumnGeom | None:
    """当前 `column_windows` 产物里这一列的几何；取不到返回 None（不抛）。"""
    try:
        from ..core.spec import page_key
        pw = store.read(book, "column_warp", page_key(int(page)), "column_windows")
        rec = pw.column(int(col)) if pw is not None else None
        if rec is None:
            return None
        return ColumnGeom(rec.model_dump(mode="json"), int(pw.page_size[0]))
    except Exception:                                    # noqa: BLE001
        return None


def stamp(ex: dict, geom: ColumnGeom | None) -> dict:
    """由列图坐标的 `y` / `polyline` 算出 `STAMP_KEYS` 那几个键（不改 `ex`）。"""
    if geom is None:
        return {}
    out: dict = {"geom_sig": geom.sig}
    if ex.get("y") is not None:
        x, y = geom.row_to_page(float(ex["y"]))
        out["page_x"], out["page_y"] = round(x, 2), round(y, 2)
    if ex.get("polyline"):
        out["page_polyline"] = [[round(v, 2) for v in geom.row_to_page(float(py), float(px))]
                                for px, py in ex["polyline"]]
    return out


def gold_rows_now(ex: dict, geom: ColumnGeom | None) -> tuple[str, float | None, list | None]:
    """金标在**当前**列图里的 (口径, y, polyline)。

    口径：`page`（按页面坐标换算，可信）/ `sig_ok`（签名一致，原坐标可用）/
    `drift`（签名不一致又没有页面坐标，不可用）/ `legacy`（老条目，什么都没记，只能信原坐标）。
    """
    y, pl = ex.get("y"), ex.get("polyline")
    if geom is not None and ex.get("page_y") is not None:
        y_now = geom.page_to_row(float(ex["page_x"]), float(ex["page_y"]))[0]
        pl_now = pl
        if ex.get("page_polyline"):
            pl_now = []
            for x, yy in ex["page_polyline"]:
                r, u = geom.page_to_row(float(x), float(yy))
                pl_now.append([u, r])
        return "page", y_now, pl_now
    if ex.get("geom_sig"):
        if geom is not None and ex["geom_sig"] == geom.sig:
            return "sig_ok", y, pl
        return "drift", None, None
    return "legacy", y, pl
