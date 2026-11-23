"""版面金标（layout-gold）与预测的适配器（A21，2026-11-23）。

金标条目放在 open-guji-dataset 的 `layout/items.jsonl`，走统一信封（见 `gold/item.py`），
`expected` 就是 `eval/layout_metrics.py` 的 `LayoutDoc`（原图像素、左上原点、竖线右→左）。
本模块负责三件事：

1. `validate_doc`：金标文档格式体检（坐标越界、线乱序、断口区间不在线内……）。
2. 预测侧：`doc_from_borders` 把 `borders`（＋ gate 清单）产物转成 `LayoutDoc`。
   产物坐标是右上原点（x 向左），这里换成左上原点。
3. 旧金标侧：`docs_from_page_geometry`、`docs_from_page_type` 把 dataset 里已有的
   page-geometry（界行三高度 x）、page-type 条目转成 `LayoutDoc`，作为起点并入。

不 import 产物类型到模块顶层：评测纯函数要能在没装 pipeline 全套依赖的环境里跑。
"""
from __future__ import annotations

from typing import Any

import numpy as np

LayoutDoc = dict[str, Any]
STATES = ("intact", "faint", "broken", "inferred")
POLICIES = ("standard", "custom", "skip")
# 页型 → 网格策略（与 clustering/page_type.py 的口径一致：blank 并入 body）
TYPE_POLICY = {"body": "standard", "blank": "standard", "roster": "standard", "toc": "standard",
               "edict": "custom", "uncertain": "standard", "table": "skip",
               "cover": "skip", "label": "skip", "colophon": "skip"}


def validate_doc(doc: LayoutDoc) -> list[str]:
    """返回问题清单（空＝合格）。"""
    bad: list[str] = []
    W, H = doc.get("width"), doc.get("height")
    if not (isinstance(W, (int, float)) and isinstance(H, (int, float)) and W > 0 and H > 0):
        bad.append("缺 width/height")
        return bad
    xs_mid = []
    for i, v in enumerate(doc.get("vlines", [])):
        pts = np.asarray(v.get("pts") or [], dtype=float)
        if pts.ndim != 2 or pts.shape[0] < 2 or pts.shape[1] != 2:
            bad.append(f"vlines[{i}] 点列不合格")
            continue
        if (pts[:, 0] < -0.5).any() or (pts[:, 0] > W + 0.5).any() or \
           (pts[:, 1] < -0.5).any() or (pts[:, 1] > H + 0.5).any():
            bad.append(f"vlines[{i}] 有点在图外")
        if v.get("state", "intact") not in STATES:
            bad.append(f"vlines[{i}] state 不认识：{v.get('state')}")
        y0, y1 = pts[:, 1].min(), pts[:, 1].max()
        for g in v.get("gaps", []) or []:
            if not (g[0] <= g[1] and g[0] >= y0 - 0.5 and g[1] <= y1 + 0.5):
                bad.append(f"vlines[{i}] 断口区间 {g} 不在线的 y 范围内")
        if v.get("state") in ("broken", "inferred") and not v.get("gaps"):
            bad.append(f"vlines[{i}] state={v['state']} 但没写 gaps")
        xs_mid.append(float(np.interp((y0 + y1) / 2, pts[:, 1], pts[:, 0])))
    if any(a <= b for a, b in zip(xs_mid, xs_mid[1:])):
        bad.append("竖线没按从右到左排（或有重叠）")
    n = doc.get("n_cols")
    if n is not None and doc.get("vlines") and len(doc["vlines"]) not in (n + 1, n):
        bad.append(f"n_cols={n} 与竖线条数 {len(doc['vlines'])} 对不上（应为 n 或 n+1）")
    if doc.get("policy") is not None and doc["policy"] not in POLICIES:
        bad.append(f"policy 不认识：{doc['policy']}")
    return bad


# ───────────────── 预测侧：borders 产物 → LayoutDoc ─────────────────

def doc_from_borders(borders: dict | Any, gate: dict | None = None, n_y: int = 24,
                     n_x: int = 24) -> LayoutDoc:
    """borders 产物（dict 或 Borders 模型）→ LayoutDoc。

    竖线沿内版框的上下两条边之间取 n_y 个点（含折线折点处的弯），上下版框沿 x 取 n_x 个点。
    gate：`border_detect_gate_manifest` 的 dict，给页型和策略；缺省不填页型。
    """
    from ..products.kinds.borders import Borders   # 延迟导入，见模块头

    b = borders if isinstance(borders, Borders) else Borders.model_validate(borders)
    r = b.to_result()
    W, H = int(b.width), int(b.height)
    xs_new = np.linspace(0, W - 1, n_x)               # 新坐标：x 向左递增
    top_y = np.array([r.top.y_at(x) for x in xs_new])
    bot_y = np.array([r.bottom.y_at(x) for x in xs_new])
    xtl = (W - 1) - xs_new                            # 换成左上原点
    top = {"pts": [[float(x), float(y)] for x, y in zip(xtl, top_y)]}
    bottom = {"pts": [[float(x), float(y)] for x, y in zip(xtl, bot_y)]}
    ym = (float(np.mean(top_y)), float(np.mean(bot_y)))
    ys = np.linspace(ym[0], ym[1], n_y)
    filled = list(b.vline_filled or [])
    vl = []
    for i, v in enumerate(r.verticals):
        xs = np.array([v.x_at(y) for y in ys])
        vl.append({"pts": [[float((W - 1) - x), float(y)] for x, y in zip(xs, ys)],
                   "state": "inferred" if (i < len(filled) and filled[i]) else "intact",
                   "gaps": []})
    doc: LayoutDoc = {"width": W, "height": H, "vlines": vl, "top": top, "bottom": bottom,
                      "n_cols": max(len(vl) - 1, 0), "rows_per_col": None,
                      "page_type": None, "policy": None, "tags": []}
    if gate:
        doc["page_type"] = gate.get("page_type")
        doc["policy"] = gate.get("page_type_policy")
        if gate.get("n_cols") is not None:
            doc["n_cols"] = gate["n_cols"]
    return doc


# ───────────────── 旧金标 → LayoutDoc ─────────────────

def _dedupe(lines: list[list[float]], tol: float = 5.0) -> list[list[float]]:
    """page-geometry 偶有同一条线记两次（各高度 x 都差不到 tol）。"""
    out: list[list[float]] = []
    for ln in lines:
        if out and all(abs(a - b) <= tol for a, b in zip(ln, out[-1])):
            continue
        out.append(ln)
    return out


def docs_from_page_geometry(items: list[dict]) -> list[tuple[str, LayoutDoc]]:
    """page-geometry 的 active 条目 → [(页键 "册/页", 文档)]。界行三高度 x 成 3 点折线。
    没有版框坐标（只有一个 frame_y），top/bottom 留空，不进版框指标。"""
    out = []
    for it in items:
        if it.get("status") != "active":
            continue
        e = it["expected"]
        ys = e["band_ys"]
        lines = [[r["x_top"], r["x_mid"], r["x_bot"]] for r in e["rules"] if r.get("kind") == "rule"]
        lines = _dedupe(sorted(lines, key=lambda t: -t[1]))
        vl = [{"pts": [[x, y] for x, y in zip(ln, ys)], "state": "intact", "gaps": []} for ln in lines]
        a = it.get("anchor", {})
        doc: LayoutDoc = {"width": e["image_size"]["width"], "height": e["image_size"]["height"],
                          "vlines": vl, "top": None, "bottom": None,
                          "n_cols": e.get("n_cols"), "rows_per_col": None,
                          "page_type": None, "policy": None, "tags": [], "book": a.get("book"),
                          "stratum": "page-geometry"}
        out.append((f"{a.get('book')}/{a.get('page')}", doc))
    return out


def docs_from_page_type(items: list[dict]) -> dict[str, LayoutDoc]:
    """page-type 的 active 条目 → {页键: 只含页型信息的文档}（宽高未知，填 0，
    只用于页型指标，不进 `validate_doc`）。"""
    out = {}
    for it in items:
        if it.get("status") != "active":
            continue
        a = it["anchor"]
        t = it["expected"]["page_type"]
        out[f"{a['book']}/{a['page']}"] = {
            "width": 0, "height": 0, "vlines": [], "top": None, "bottom": None, "n_cols": None,
            "rows_per_col": None, "page_type": t, "policy": TYPE_POLICY.get(t), "tags": [],
            "book": a["book"], "stratum": "page-type",
            "last_text_col": it["expected"].get("last_text_col"),
            "text_col_count": it["expected"].get("text_col_count")}
    return out
