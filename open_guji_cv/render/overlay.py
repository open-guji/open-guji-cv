# -*- coding: utf-8 -*-
"""五个 Step 的叠图画法。

从 `console/app.py` 搬来（控制台重构 C2）。**画法一行未改**——这一轮的验收是
「行为一模一样」，掺了画法改动就没法用 46 条快照来验（后端任务书 §五）。

搬迁时只动了三处，都不影响画出来的像素：

1. `_overlay` / `_draw_vline` 改成公开名 `overlay` / `draw_vline`；
2. `ProductStore()` 改成可注入参数（不传就现建一个，与原来一致）；
3. 三处 `HTTPException` 换成 `open_guji_cv.errors` 的领域异常——**本模块不 import
   fastapi**，这样 CLI 与云端道也能直接调（方案 §四·2）。HTTP 状态码的映射在
   `console/errors.py`，三条都仍然是 404。

## 谁在用

- 控制台 `GET /api/overlay/{book}/{step}/{page}.png`
- （C5 之后）`guji product overlay --out`
"""
from __future__ import annotations

import cv2
import numpy as np

from ..core.anchor import x_tr_to_tl
from ..core.book import load_book
from ..core.spec import page_key
from ..errors import ImageMissing, ProductMissing, Unsupported
from ..products.store import ProductStore


def draw_vline(img: np.ndarray, v: dict, W: int, H: int, color, thick: int = 3) -> None:
    pts = []
    for y in range(0, H, 16):
        if v.get("k2") is None or y <= v["y1"]:
            x = v["x_at_top"] + v["slope"] * y
        elif y <= v["y2"]:
            x = v["x_at_top"] + v["slope"] * v["y1"] + v["k2"] * (y - v["y1"])
        else:
            x = (v["x_at_top"] + v["slope"] * v["y1"] + v["k2"] * (v["y2"] - v["y1"])
                 + v["k3"] * (y - v["y2"]))
        pts.append((int(round(x_tr_to_tl(x, W))), y))
    cv2.polylines(img, [np.array(pts, dtype=np.int32)], False, color, thick)


def overlay(book: str, step: str, page: int,
            store: ProductStore | None = None) -> np.ndarray:
    """把某一步的产物画回原图。画法逐字照搬自 `console/app.py::_overlay`。"""
    b = load_book(book)
    st = store or ProductStore()
    img = cv2.imread(str(b.raw_path(page)))
    if img is None:
        raise ImageMissing("原图缺失")
    H, W = img.shape[:2]
    d = st.read_raw(book, step, page_key(page))
    if d is None:
        raise ProductMissing("没有这份产物")
    if step == "border_detect":
        bd = d["borders"]
        for v in bd["verticals"]:
            draw_vline(img, v, W, H, (0, 0, 255))
        for h in (bd["top"], bd["bottom"]):
            p0 = (W - 1, int(round(h["y_at_right"])))
            p1 = (0, int(round(h["y_at_right"] + h["slope"] * (W - 1))))
            cv2.line(img, p0, p1, (255, 0, 0), 3)
        for hr in bd.get("head_raise", []):
            cv2.putText(img, f"HR c{hr['col']}", (W // 2, int(hr["inner_y"])), cv2.FONT_HERSHEY_SIMPLEX,
                        1.2, (0, 140, 255), 3)
    elif step == "column_warp":
        for c in d["column_windows"]["columns"]:
            draw_vline(img, c["left_line"], W, H, (0, 0, 255), 2)
            draw_vline(img, c["right_line"], W, H, (0, 0, 255), 2)
            y0, y1 = int(c["top_y"]), int(c["bottom_y"])
            xr = int(round(x_tr_to_tl(c["right_line"]["x_at_top"], W)))
            cv2.putText(img, f"c{c['col']}", (xr - 60, max(30, y0 - 10)), cv2.FONT_HERSHEY_SIMPLEX,
                        1.0, (0, 140, 255), 2)
    elif step == "column_gate":
        gm = d["gate_manifest"]
        for c in gm["columns"]:
            color = (0, 160, 0) if c["admitted"] else (0, 0, 220)
            cv2.putText(img, f"c{c['col']} {'ok' if c['admitted'] else 'x'}", (40 + 250 * (c["col"] - 1), 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3)
        cv2.putText(img, f"period {gm['period']} ref_w {gm['ref_w']} {' | '.join(gm['reject'])}",
                    (40, H - 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 220), 2)
    elif step == "row_segment":
        for col in d["cells"]["columns"]:
            for c in col["cells"]:
                q = c.get("quad_page")
                if not q:
                    continue
                pts = np.array([(int(round(x_tr_to_tl(x, W))), int(round(y))) for x, y in q], dtype=np.int32)
                color = {"char": (0, 160, 0), "blank": (160, 160, 160)}.get(c["kind"], (200, 0, 200))
                cv2.polylines(img, [pts], True, color, 2)
    elif step == "cell_shrink":
        for col in d["char_index"]["columns"]:
            for c in col["chars"]:
                bb = c.get("bbox_page")
                if not bb:
                    continue
                x0, y0, x1, y1 = bb
                X0, X1 = int(round(x_tr_to_tl(x1, W))), int(round(x_tr_to_tl(x0, W)))
                color = (0, 0, 220) if c["flags"] else (0, 160, 0)
                cv2.rectangle(img, (X0, int(y0)), (X1, int(y1)), color, 2)
    else:
        raise Unsupported(f"{step} 还没有叠图画法")
    return img
