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
from ..errors import EncodeFailed, ImageMissing, NotFound, ProductMissing, Unsupported
from ..gates.query import GATE_TIER_COLOR, gate_column_tier
from ..products.store import ProductStore
from ..utils.preclean import band_boundary, band_ink_ratio, precleaned_path


def encode_png(img: np.ndarray, scale: float | None = None) -> bytes:
    """缩放并编成 PNG 字节。控制台的 `_png` 与 `guji product raw|overlay|patch`
    共用这一份——「同参同输出」是 C5 的验收判据，两边各写一遍就没法保证。"""
    if scale and scale != 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise EncodeFailed("编码失败")
    return buf.tobytes()


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
        wins = st.read_raw(book, "column_warp", page_key(page))
        win_by_col = {c["col"]: c for c in wins["column_windows"]["columns"]} if wins else {}
        for c in gm["columns"]:
            tier = gate_column_tier(c["reject"])
            color = GATE_TIER_COLOR[tier]
            win = win_by_col.get(c["col"])
            if win is not None:
                draw_vline(img, win["left_line"], W, H, color, 2)
                draw_vline(img, win["right_line"], W, H, color, 2)
                xr = int(round(x_tr_to_tl(win["right_line"]["x_at_top"], W)))
                y0 = int(win["top_y"])
                label = f"c{c['col']} {tier}" if tier != "ok" else f"c{c['col']} ok"
                cv2.putText(img, label, (xr - 70, max(30, y0 - 10)), cv2.FONT_HERSHEY_SIMPLEX,
                            1.0, color, 2)
            else:
                cv2.putText(img, f"c{c['col']} {tier}", (40 + 250 * (c["col"] - 1), 60),
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


def preclean_overlay(book: str, page: int) -> np.ndarray:
    """Step0 预清理专用叠图：不是"看修复完的图"，而是"看当初判定的这条反色带在哪"。

    走 `book.preclean` 里登记的规则现算边界，不经 ProductStore——preclean 不是
    `core/step.py` 注册的 Step，没有数值产物可读（见 utils/preclean.py 模块说明）。
    原图右上角原点与其它叠图一致，这里用 `x_tr_to_tl` 转成 cv2 的左上角原点画。
    """
    b = load_book(book)
    rules = (b.preclean or {}).get(page)
    if not rules:
        raise NotFound(f"{book} p{page} 没有登记 preclean 规则")
    img = cv2.imread(str(b.raw_path(page)))
    if img is None:
        raise ImageMissing("原图缺失")
    gray = cv2.imread(str(b.raw_path(page)), cv2.IMREAD_GRAYSCALE)
    H, W = gray.shape[:2]
    for r in rules:
        if r.get("kind", "inverted_band") != "inverted_band":
            continue
        y_lo, y_hi, y_probe = r["y_lo"], r["y_hi"], r["y_probe"]
        xs, top, bot = band_boundary(
            gray, y_lo=y_lo, y_hi=y_hi, y_probe=y_probe,
            ink_threshold=r.get("ink_threshold", 128),
            ctx=r.get("ctx", 170), smooth=r.get("smooth", 31))
        for x0, x1 in r["segments"]:
            seg = (xs >= x0) & (xs <= x1)
            if not seg.any():
                continue
            top_pts = np.array([(int(round(x_tr_to_tl(x, W))), int(y))
                                for x, y in zip(xs[seg], top[seg])], dtype=np.int32)
            bot_pts = np.array([(int(round(x_tr_to_tl(x, W))), int(y))
                                for x, y in zip(xs[seg], bot[seg])], dtype=np.int32)
            cv2.polylines(img, [top_pts], False, (0, 0, 255), 3)
            cv2.polylines(img, [bot_pts], False, (255, 0, 0), 3)
            xr = int(round(x_tr_to_tl(int(x1), W)))
            xl = int(round(x_tr_to_tl(int(x0), W)))
            cv2.line(img, (xl, y_probe), (xr, y_probe), (0, 200, 200), 1)
    return img


def preclean_report(book: str, page: int) -> dict:
    """Step0 预清理数值报告：每条规则修复前后的带内墨占比，与出闸阈值放在一起，
    不用再去读 JSON 猜。数值来自现算（与 `utils.preclean.apply_preclean` 同一套
    计算，但不改盘、不落产物），带 `precleaned_exists` 说明产物是否已生成。
    """
    from ..utils.preclean import (BODY_INK_GATE, BODY_INK_MEDIAN, BODY_INK_P95,
                                  band_mask)

    b = load_book(book)
    rules = (b.preclean or {}).get(page)
    if not rules:
        raise NotFound(f"{book} p{page} 没有登记 preclean 规则")
    gray = cv2.imread(str(b.raw_path(page)), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise ImageMissing("原图缺失")

    reports = []
    out = gray
    for r in rules:
        kind = r.get("kind", "inverted_band")
        if kind != "inverted_band":
            reports.append({"kind": kind})
            continue
        th = r.get("ink_threshold", 128)
        mask = band_mask(out, segments=r["segments"], y_lo=r["y_lo"], y_hi=r["y_hi"],
                         y_probe=r["y_probe"], ink_threshold=th,
                         ctx=r.get("ctx", 170), smooth=r.get("smooth", 31))
        before = band_ink_ratio(out, mask, th)
        fixed = out.copy()
        fixed[mask] = 255 - out[mask]
        after = band_ink_ratio(fixed, mask, th)
        out = fixed
        reports.append({
            "kind": kind, "segments": r["segments"],
            "y_lo": r["y_lo"], "y_hi": r["y_hi"], "y_probe": r["y_probe"],
            "ink_before": round(before, 4), "ink_after": round(after, 4),
            "gate": BODY_INK_GATE, "body_median": BODY_INK_MEDIAN, "body_p95": BODY_INK_P95,
            "passed": after <= BODY_INK_GATE,
        })
    return {"page": page, "rules": reports,
            "precleaned_exists": precleaned_path(book, page).exists()}
