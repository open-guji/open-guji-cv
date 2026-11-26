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
FRAME_KINDS = ("double", "single", "none")   # 内外双线／只有一条线／没有（装订侧）
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
    for side, f in (doc.get("frame") or {}).items():
        if side not in ("top", "bottom", "left", "right"):
            bad.append(f"frame 不认识的边 {side}")
            continue
        k = f.get("kind")
        if k not in FRAME_KINDS:
            bad.append(f"frame.{side}.kind 不认识：{k}")
        o = f.get("outer")
        if k == "double" and not (o and len(o.get("pts") or []) >= 2):
            bad.append(f"frame.{side} kind=double 但没有外框线")
        if k != "double" and o:
            bad.append(f"frame.{side} kind={k} 不该有外框线")
        for pt in (o or {}).get("pts") or []:
            if not (-0.5 <= pt[0] <= W + 0.5 and -0.5 <= pt[1] <= H + 0.5):
                bad.append(f"frame.{side} 外框线有点在图外")
                break
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
    raised = head_raise_spans(r)
    straight_top = top
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
    doc["frame"] = _frame_from_borders(b, straight_top, bottom, vl)   # 外框先按直线上框推
    if raised:                                        # 抬头列：上内框、上外框是阶梯折线
        doc["top"] = {"pts": top_polyline_pts(straight_top["pts"], raised, W, "inner")}
        _raise_outer_top(doc["frame"], r, raised, W)
    if gate:
        doc["page_type"] = gate.get("page_type")
        doc["policy"] = gate.get("page_type_policy")
        if gate.get("n_cols") is not None:
            doc["n_cols"] = gate["n_cols"]
        # 闸实际采用的期望列数（含册配置里按页覆盖的 expected_cols_pages，如殿本 vol01 p100 实有 10 列）
        doc["expected_cols"] = gate.get("expected_cols")
    return doc


def head_raise_spans(r) -> list[tuple[float, float, float, float]]:
    """抬头列 → [(x_右起, x_左起, inner_y, outer_y)]，x 从页面右缘起算（产物坐标）。
    同一列多级台阶取 inner_y 最小（最高的一级）；列的左右边取该列两条界行在抬头内框高度处的 x。"""
    best: dict[int, Any] = {}
    for h in r.head_raise or []:
        if h.col not in best or h.inner_y < best[h.col].inner_y:
            best[h.col] = h
    out = []
    nv = len(r.verticals)
    for col in sorted(best):
        if not (1 <= col < nv):
            continue
        h = best[col]
        a, b = r.verticals[col - 1].x_at(h.inner_y), r.verticals[col].x_at(h.inner_y)
        out.append((float(min(a, b)), float(max(a, b)), float(h.inner_y), float(h.outer_y)))
    return out


#: 外框台阶竖边往外让出「内外框间距 × 此值」。产物的 outer_y 是粗框条**外延**，金标标在框条中间，间距多出约半条框宽；
#: 殿本抬头页金标实测竖边外让 22–43 px（中位 30），产物间距 37–45 px。
OUTER_STEP_K = 0.8


def top_polyline_pts(base: list[list[float]], spans: list, W: int, which: str) -> list[list[float]]:
    """把直线上框 base（左上原点点列）改成阶梯折线：每段抬头在其左右边处各加两个同 x 的点（金标同一台阶用同 x 两点），
    中间取抬头框的 y（which=inner 取 inner_y，outer 取 outer_y）。相邻抬头列连成一段，台阶直接接、不回落到主框。
    外框（which=outer）的台阶竖边在内框竖边**外侧**，往外让出该列的内外框间距（inner_y − outer_y，乘 `OUTER_STEP_K`）：
    抬头框是一圈双线，竖边的外框跟上边的外框离内框一样远（vol04:6 实测 31 px，2026-11-25 用户复核）。"""
    ys = np.array([p[1] for p in base]); xs = np.array([p[0] for p in base])
    o = np.argsort(xs, kind="stable"); xs, ys = xs[o], ys[o]
    k = 2 if which == "inner" else 3
    segs = sorted(((W - 1) - sp[1], (W - 1) - sp[0], sp[k], abs(sp[2] - sp[3])) for sp in spans)
    groups: list[list[tuple]] = []
    for sg in segs:
        if groups and abs(sg[0] - groups[-1][-1][1]) < 2.0:
            groups[-1].append(sg)
        else:
            groups.append([sg])
    steps: list[tuple[float, float, list[list[float]]]] = []    # (x 起, x 止, 台阶点)
    for grp in groups:
        a, b = grp[0][0], grp[-1][1]
        if which != "inner":
            a, b = a - OUTER_STEP_K * grp[0][3], b + OUTER_STEP_K * grp[-1][3]
        joints = [(grp[n][1] + grp[n + 1][0]) / 2.0 for n in range(len(grp) - 1)]   # 相邻列共用一个 x，免得排序颠倒
        mid: list[list[float]] = []
        for n, (_, _, yy, _) in enumerate(grp):
            xa = a if n == 0 else joints[n - 1]
            xb = b if n == len(grp) - 1 else joints[n]
            mid += [[xa, yy], [xb, yy]]
        steps.append((a, b, [[a, float(np.interp(a, xs, ys))]] + mid + [[b, float(np.interp(b, xs, ys))]]))
    pts: list[list[float]] = [[float(x), float(y)] for x, y in zip(xs, ys)
                              if not any(a <= x <= b for a, b, _ in steps)]
    for _, _, sp in steps:
        pts += sp
    pts.sort(key=lambda p: p[0])          # 排序稳定：同 x 的点保持「主框→台阶→台阶→主框」的次序
    return pts


def _raise_outer_top(frame: dict, r, spans: list, W: int) -> None:
    f = frame.get("top") or {}
    if f.get("kind") == "double" and f.get("outer"):
        f["outer"] = {"pts": top_polyline_pts(f["outer"]["pts"], spans, W, "outer")}


def _shift(pts: list[list[float]], d: float, horiz: bool) -> list[list[float]]:
    return [[x, y + d] if horiz else [x + d, y] for x, y in pts]


def _frame_from_borders(b, top: dict, bottom: dict, vl: list[dict]) -> dict:
    """产物的框型字段 → `frame`。横边：`*_frame_kind`（缺→none）＋ `*_outer_offset`（上负下正，
    相对内框线）；竖边：外框只在纸边一侧（`v_outer_side`），偏移取 |v_outer_offset|，
    右侧外框在最右竖线右边，左侧在最左竖线左边；另一侧记 none。"""
    fr: dict[str, dict] = {}
    for side, ln in (("top", top), ("bottom", bottom)):
        kind = getattr(b, f"{side}_frame_kind", None) or "none"
        off = getattr(b, f"{side}_outer_offset", None)
        f = {"kind": kind, "outer": None, "inner_w": None, "outer_w": None}
        if kind == "double" and off is not None:
            f["outer"] = {"pts": _shift(ln["pts"], float(off), True)}
        elif kind == "double":
            f["kind"] = "none"                 # 双线但外框没量出位置：不冒充
        fr[side] = f
    side_out = getattr(b, "v_outer_side", None)
    off = getattr(b, "v_outer_offset", None)
    for side, idx, sgn in (("right", 0, 1.0), ("left", -1, -1.0)):
        f = {"kind": "none", "outer": None, "inner_w": None, "outer_w": None}
        if side_out == side and off is not None and vl:
            f["kind"] = "double"
            f["outer"] = {"pts": _shift(vl[idx]["pts"], sgn * abs(float(off)), False)}
        fr[side] = f
    return fr


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
