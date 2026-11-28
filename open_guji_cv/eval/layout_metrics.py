"""第 1 大步「版面」的评测指标：线、边框、列数／行数、页型（A21，2026-11-23）。

为什么新写
---------
版面（直线 → 边框 → 界行 → 页型 → 几行几列）以前没有统一的评测：
`eval/colgeom.py`、`rulers.py`、`scripts/eval_pagetype.py`、dataset 里各个「判对错」式分片，
各量各的，也没有一个量「线到底偏了多少像素」的指标。本模块只做**纯函数**
（numpy＋scipy，不碰产物、不碰工作区），金标和预测都先转成同一种「版面文档」再比。

版面文档（`LayoutDoc`，普通 dict，坐标一律是**原图像素、左上角原点**）
-------------------------------------------------------------------
```
{"width": W, "height": H,
 "vlines": [{"pts": [[x, y], ...],            # 折线点列，y 递增；至少 2 点
             "state": "intact|faint|broken|inferred",   # 仅金标有意义
             "gaps": [[y0, y1], ...]}, ...],  # 断裂（金标人补全）的 y 区间，可空
 "top": {"pts": [[x, y], ...]} | None,        # 上内版框、下内版框
 "bottom": {...} | None,
 "n_cols": int | None,                        # 正文列数（竖线数 - 1 的页别）
 "rows_per_col": [int, ...] | None,           # 每列字格数，右起；None=未标
 "page_type": str | None, "policy": "standard|custom|skip" | None,
 "tags": [str, ...],                          # 分层用：faint/broken/seal/wide/inverted/ink/bent…
 "frame": {"top"|"bottom"|"left"|"right":     # 框型（2026-11-23 起，可缺）
           {"kind": "double|single|none",     # 内外双线／只有一条（脈經上下）／没有（装订侧）
            "outer": {"pts": [...]} | None,   # kind=double 时的外框折线
            "inner_w": px|None, "outer_w": px|None}}}   # 线粗（像素）
```
`top`/`bottom` 是内框线（single 时就是那唯一一条）；左右内框线是 `vlines[-1]`（左）、`vlines[0]`（右）。
竖线按**从右到左**排。适配器在 `layout_gold.py`。

指标口径（和 doc 方案一致）
-------------------------
- 线匹配：沿金标线的 y 范围等距取点，算预测线在这些 y 处的 x 与金标 x 的差；
  匈牙利匹配（代价＝中位绝对偏差），匹配门限放宽到 `GATE_PITCH` 个列距，
  之后再按严格容差（0.02/0.05/0.1 个列距）算命中，所以「匹配到了但偏得多」会如实落在偏差里。
- 一条线「命中 τ」＝它的 p95 偏差 ≤ τ×列距（整条线贴住，不只中点贴住）。
- 列距＝金标相邻线在页面中高处的间距中位数，让不同书、不同分辨率可比；同时报像素。
- 破损线：金标 `state` 为 broken/faint 的线单独汇总；断裂区间内的偏差单独记（`err_gap`），
  实线区间记 `err_solid`——线「找到了」不等于「断口里补对了」。
- 页型：策略准确率＋**漏切率**（金标该切却判 skip）。漏切是不可接受的那一类，单独列。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

import numpy as np
from scipy.optimize import linear_sum_assignment

LayoutDoc = dict[str, Any]

GATE_PITCH = 0.5                       # 匹配放宽到半个列距，超出不配对
TOL_PITCH = (0.02, 0.05, 0.10)         # 严格容差（列距的倍数）
N_SAMPLES = 64                         # 每条线沿 y 的采样点数
BAD_STATES = ("broken", "faint")       # 破损线

SKIP_POLICY = "skip"


# ───────────────────────── 几何小工具 ─────────────────────────

def _pts(d: dict | None) -> np.ndarray | None:
    if not d or not d.get("pts"):
        return None
    a = np.asarray(d["pts"], dtype=float)
    if a.ndim != 2 or a.shape[0] < 2:
        return None
    return a


def _monotone(t: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """按画线次序把自变量 t 压成单调不减（整条反画的先倒过来），再插值。

    不能按 t 排序：抬头台阶是同 t 两点，人标时竖边常画得歪一点（如 [1209.5, 77.3] → [1204.5, 190.5]，
    t 往回走了 5 px），一排序台阶顶点就跟下一段错配，整段插成斜线（vol01:45 一页 p95 因此虚报 106 px）。
    取累计最大值等于把歪的竖边扶正，次序不变。"""
    if len(t) > 1 and t[-1] < t[0]:
        t, v = t[::-1], v[::-1]
    return np.maximum.accumulate(t), v


def x_at(pts: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """折线在各 y 处的 x（按画线次序，y 压成单调；范围外取端点值，端点以外不外推）。"""
    t, v = _monotone(pts[:, 1], pts[:, 0])
    return np.interp(ys, t, v)


def y_at(pts: np.ndarray, xs: np.ndarray) -> np.ndarray:
    """折线在各 x 处的 y（同 `x_at`，按画线次序，x 压成单调；阶梯折线的台阶不会被排序打乱）。"""
    t, v = _monotone(pts[:, 0], pts[:, 1])
    return np.interp(xs, t, v)


def _in_gaps(ys: np.ndarray, gaps: list[list[float]] | None) -> np.ndarray:
    m = np.zeros(ys.shape, dtype=bool)
    for g in gaps or []:
        m |= (ys >= g[0]) & (ys <= g[1])
    return m


def gold_pitch(gold: LayoutDoc) -> float | None:
    """金标相邻竖线在页面中高处的间距中位数（像素）。线少于 2 条返回 None。"""
    lines = [p for p in (_pts(v) for v in gold.get("vlines", [])) if p is not None]
    if len(lines) < 2:
        return None
    ys = np.array([np.median([p[:, 1].min() for p in lines]) / 2 +
                   np.median([p[:, 1].max() for p in lines]) / 2])
    xs = np.sort([float(x_at(p, ys)[0]) for p in lines])
    d = np.diff(xs)
    d = d[d > 1.0]
    return float(np.median(d)) if d.size else None


# ───────────────────────── 竖线（界行） ─────────────────────────

def _line_samples(g: np.ndarray) -> np.ndarray:
    return np.linspace(g[:, 1].min(), g[:, 1].max(), N_SAMPLES)


def match_vlines(gold: LayoutDoc, pred: LayoutDoc, pitch: float | None = None) -> dict:
    """金标竖线与预测竖线配对，逐线给偏差。

    返回 {"pitch", "pairs": [{gi, pi, med, p95, max, err_solid, err_gap, state}],
          "missed": [gi...], "extra": [pi...]}。偏差单位像素。
    """
    gl = gold.get("vlines", [])
    pl = pred.get("vlines", [])
    g_pts = [_pts(v) for v in gl]
    p_pts = [_pts(v) for v in pl]
    pitch = pitch or gold_pitch(gold)
    out = {"pitch": pitch, "pairs": [], "missed": [], "extra": []}
    gi_ok = [i for i, p in enumerate(g_pts) if p is not None]
    pi_ok = [i for i, p in enumerate(p_pts) if p is not None]
    if not gi_ok or not pi_ok or not pitch:
        out["missed"] = gi_ok
        out["extra"] = pi_ok
        return out
    cost = np.zeros((len(gi_ok), len(pi_ok)))
    errs: dict[tuple[int, int], np.ndarray] = {}
    for a, gi in enumerate(gi_ok):
        ys = _line_samples(g_pts[gi])
        gx = x_at(g_pts[gi], ys)
        for b, pi in enumerate(pi_ok):
            e = np.abs(x_at(p_pts[pi], ys) - gx)
            errs[(gi, pi)] = e
            cost[a, b] = float(np.median(e))
    # 超门限的配对给一个巨大代价：先保证配对数最多，再求总偏差最小；
    # 否则漏一条线会让整排线错位一格去凑数（总偏差反而更小）。
    ri, ci = linear_sum_assignment(np.where(cost > GATE_PITCH * pitch, 1e9, cost))
    matched_g, matched_p = set(), set()
    for a, b in zip(ri, ci):
        if cost[a, b] > GATE_PITCH * pitch:
            continue
        gi, pi = gi_ok[a], pi_ok[b]
        e = errs[(gi, pi)]
        ys = _line_samples(g_pts[gi])
        gm = _in_gaps(ys, gl[gi].get("gaps"))
        out["pairs"].append({
            "gi": gi, "pi": pi, "state": gl[gi].get("state", "intact"),
            "med": float(np.median(e)), "p95": float(np.percentile(e, 95)), "max": float(e.max()),
            "err_solid": e[~gm].tolist(), "err_gap": e[gm].tolist()})
        matched_g.add(gi)
        matched_p.add(pi)
    out["missed"] = [i for i in gi_ok if i not in matched_g]
    out["extra"] = [i for i in pi_ok if i not in matched_p]
    return out


def vline_counts(m: dict, gold: LayoutDoc) -> dict:
    """把 match_vlines 的结果折成可累加的计数（按严格容差算命中）。"""
    pitch = m["pitch"] or 0.0
    gl = gold.get("vlines", [])
    n_gold = len(m["pairs"]) + len(m["missed"])
    n_pred = len(m["pairs"]) + len(m["extra"])
    hit = {t: [p for p in m["pairs"] if pitch and p["p95"] <= t * pitch] for t in TOL_PITCH}
    bad_gold = [i for i, v in enumerate(gl) if v.get("state") in BAD_STATES]
    bad_pairs = [p for p in m["pairs"] if p["state"] in BAD_STATES]
    bad_missed = [i for i in m["missed"] if i in bad_gold]
    return {
        "n_gold": n_gold, "n_pred": n_pred, "n_matched": len(m["pairs"]),
        "hit": {str(t): len(v) for t, v in hit.items()},
        "n_bad_gold": len(bad_pairs) + len(bad_missed),
        "n_bad_matched": len(bad_pairs),
        "n_bad_hit": {str(t): sum(1 for p in bad_pairs if pitch and p["p95"] <= t * pitch)
                      for t in TOL_PITCH},
        "line_p95": [p["p95"] for p in m["pairs"]],
        "line_med": [p["med"] for p in m["pairs"]],
        "err_gap": [x for p in m["pairs"] for x in p["err_gap"]],
        "err_solid": [x for p in m["pairs"] for x in p["err_solid"]],
        "pitch": pitch,
    }


# ───────────────────────── 横线（版框） ─────────────────────────

def hline_error(gold_h: dict | None, pred_h: dict | None) -> dict | None:
    """上或下内版框：在金标的 x 范围内等距采样比 y。任一方缺失返回 None。"""
    g, p = _pts(gold_h), _pts(pred_h)
    if g is None or p is None:
        return None
    xs = np.linspace(g[:, 0].min(), g[:, 0].max(), N_SAMPLES)
    e = np.abs(y_at(p, xs) - y_at(g, xs))
    return {"med": float(np.median(e)), "p95": float(np.percentile(e, 95)), "max": float(e.max())}


FRAME_SIDES = ("top", "bottom", "left", "right")


def frame_errors(gold: LayoutDoc, pred: LayoutDoc) -> dict | None:
    """框型与外框位置。金标没写 `frame` 返回 None。
    kind：四边各比一次；两边都是 double 时再量外框线的位置偏差（沿金标外框线的范围采样；
    横边比 y、竖边比 x）。预测没写 frame 的边按 kind 缺失算错。"""
    gf = gold.get("frame")
    if not gf:
        return None
    pf = pred.get("frame") or {}
    out: dict[str, Any] = {}
    for s in FRAME_SIDES:
        g = gf.get(s)
        if not g:
            continue
        p = pf.get(s) or {}
        rec: dict[str, Any] = {"gold": g.get("kind"), "pred": p.get("kind"),
                               "ok": p.get("kind") == g.get("kind"), "outer": None}
        if g.get("kind") == "double" and p.get("kind") == "double":
            gp, pp = _pts(g.get("outer")), _pts(p.get("outer"))
            if gp is not None and pp is not None:
                if s in ("top", "bottom"):
                    xs = np.linspace(gp[:, 0].min(), gp[:, 0].max(), N_SAMPLES)
                    e = np.abs(y_at(pp, xs) - y_at(gp, xs))
                else:
                    ys = np.linspace(gp[:, 1].min(), gp[:, 1].max(), N_SAMPLES)
                    e = np.abs(x_at(pp, ys) - x_at(gp, ys))
                rec["outer"] = {"med": float(np.median(e)), "p95": float(np.percentile(e, 95))}
        out[s] = rec
    return out


# ───────────────────────── 单页 ─────────────────────────

def page_metrics(gold: LayoutDoc, pred: LayoutDoc) -> dict:
    """一页的全部指标（可累加的原始量，聚合见 `aggregate`）。"""
    m = match_vlines(gold, pred)
    rec: dict[str, Any] = {"vlines": vline_counts(m, gold) if gold.get("vlines") else None}
    rec["top"] = hline_error(gold.get("top"), pred.get("top"))
    rec["bottom"] = hline_error(gold.get("bottom"), pred.get("bottom"))
    gp = gold.get("n_cols")
    rec["n_cols"] = None if gp is None else {"gold": gp, "pred": pred.get("n_cols"),
                                              "ok": pred.get("n_cols") == gp}
    gr, pr = gold.get("rows_per_col"), pred.get("rows_per_col")
    if gr:
        k = min(len(gr), len(pr or []))
        rec["rows"] = {"n": len(gr), "ok": sum(1 for a, b in zip(gr, pr or []) if a == b),
                       "have_pred": k > 0}
    else:
        rec["rows"] = None
    gpol, ppol = gold.get("policy"), pred.get("policy")
    if gpol is not None:
        rec["policy"] = {"gold": gpol, "pred": ppol, "ok": gpol == ppol,
                         "wrong_skip": gpol != SKIP_POLICY and ppol == SKIP_POLICY,
                         "wrong_keep": gpol == SKIP_POLICY and ppol is not None and ppol != SKIP_POLICY,
                         "gold_type": gold.get("page_type"), "pred_type": pred.get("page_type")}
    else:
        rec["policy"] = None
    rec["frame"] = frame_errors(gold, pred)
    rec["tags"] = list(gold.get("tags", []))
    rec["book"] = gold.get("book")
    rec["stratum"] = gold.get("stratum")
    return rec


# ───────────────────────── 聚合 ─────────────────────────

def _pct(a: list[float], q: float) -> float | None:
    return float(np.percentile(a, q)) if a else None


def aggregate(pages: Iterable[dict], key: str | None = None) -> dict:
    """把 `page_metrics` 的结果汇成一张表。key：每页 rec 里取分层名的函数式字段名
    （缺省不分层）；传 `"tags"` 则一页可落入多层。返回 {层名: 汇总}。"""
    pages = list(pages)
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in pages:
        if key is None:
            groups["all"].append(r)
        else:
            v = r.get(key)
            for g in (v if isinstance(v, list) else [v]):
                groups[str(g)].append(r)
        if key is not None:
            groups.setdefault("all", []).append(r)
    return {g: _summarize(rs) for g, rs in sorted(groups.items())}


def _summarize(rs: list[dict]) -> dict:
    vs = [r["vlines"] for r in rs if r.get("vlines")]
    ng = sum(v["n_gold"] for v in vs)
    npred = sum(v["n_pred"] for v in vs)
    nm = sum(v["n_matched"] for v in vs)
    pitch = float(np.median([v["pitch"] for v in vs if v["pitch"]])) if vs else None
    p95 = [x for v in vs for x in v["line_p95"]]
    s: dict[str, Any] = {"pages": len(rs), "vline_pages": len(vs), "lines_gold": ng,
                         "lines_pred": npred, "lines_matched": nm, "pitch_px": pitch}
    for t in TOL_PITCH:
        hit = sum(v["hit"][str(t)] for v in vs)
        s[f"recall@{t}"] = hit / ng if ng else None
        s[f"precision@{t}"] = hit / npred if npred else None
    s["line_p95_px"] = {"median": _pct(p95, 50), "p90": _pct(p95, 90), "max": max(p95) if p95 else None}
    s["line_med_px"] = _pct([x for v in vs for x in v["line_med"]], 50)
    nb = sum(v["n_bad_gold"] for v in vs)
    s["broken"] = {"gold_lines": nb, "matched": sum(v["n_bad_matched"] for v in vs),
                   **{f"hit@{t}": sum(v["n_bad_hit"][str(t)] for v in vs) for t in TOL_PITCH}}
    eg = [x for v in vs for x in v["err_gap"]]
    s["gap_err_px"] = {"n": len(eg), "median": _pct(eg, 50), "p95": _pct(eg, 95)}
    for name in ("top", "bottom"):
        es = [r[name] for r in rs if r.get(name)]
        s[f"{name}_frame_px"] = ({"pages": len(es), "median": _pct([e["med"] for e in es], 50),
                                  "p95": _pct([e["p95"] for e in es], 50)} if es else None)
    fr = [r["frame"] for r in rs if r.get("frame")]
    if fr:
        allk = [x for f in fr for x in f.values()]
        outer = [x["outer"] for x in allk if x.get("outer")]
        s["frame"] = {
            "pages": len(fr),
            "kind_acc": sum(1 for x in allk if x["ok"]) / len(allk),
            "kind_acc_by_side": {side: (sum(1 for f in fr if side in f and f[side]["ok"])
                                        / max(1, sum(1 for f in fr if side in f)))
                                 for side in FRAME_SIDES},
            "outer_px": ({"n": len(outer), "median": _pct([o["med"] for o in outer], 50),
                          "p95": _pct([o["p95"] for o in outer], 50)} if outer else None)}
    nc = [r["n_cols"] for r in rs if r.get("n_cols")]
    s["n_cols_acc"] = (sum(1 for x in nc if x["ok"]) / len(nc)) if nc else None
    rows = [r["rows"] for r in rs if r.get("rows") and r["rows"]["have_pred"]]
    tot = sum(x["n"] for x in rows)
    s["rows_acc"] = (sum(x["ok"] for x in rows) / tot) if tot else None
    pol = [r["policy"] for r in rs if r.get("policy")]
    s["policy"] = ({"n": len(pol), "acc": sum(1 for x in pol if x["ok"]) / len(pol),
                    "wrong_skip": sum(1 for x in pol if x["wrong_skip"]),
                    "wrong_keep": sum(1 for x in pol if x["wrong_keep"])} if pol else None)
    return s


def worst_pages(per_page: list[tuple[str, dict]], n: int = 10) -> list[tuple[str, float]]:
    """按线 p95 最大值排序，给人看叠图用。per_page: [(页键, page_metrics 结果)]。"""
    rows = []
    for k, r in per_page:
        v = r.get("vlines")
        if not v:
            continue
        score = max(v["line_p95"] + [0.0])
        if v["n_gold"] > v["n_matched"]:
            score = float("inf")
        rows.append((k, score))
    rows.sort(key=lambda t: -t[1])
    return rows[:n]


# ───────────────────────── 无金标体检（第 0 层） ─────────────────────────

def health(pred: LayoutDoc, expected_cols: int | None = None) -> dict:
    """没有金标时的自洽性体检：只看预测本身像不像一页合格的版面。

    - n_cols_ok：竖线数是否 = expected_cols + 1（expected_cols 缺省取预测文档里闸采用的值，
      它含册配置的按页覆盖；要独立核就显式传，页上真实列数不同的页会被如实判错）；
    - pitch_cv：相邻竖线间距（页面中高处）的变异系数；列距应当近似均匀，
      CV 大多半是漏线、多线或跑飞（北行这类残破线的书看它最有用）；
    - pitch_dev_max：最偏的间距相对中位数的比；
    - inside：所有竖线、版框点都在图内；
    - frame_ok：上框在下框之上，且框高占页高 ≥ 40%。
    它不能证明线「对」，只能筛出一定不对的页；**不替代金标指标**。
    """
    W, H = pred.get("width") or 0, pred.get("height") or 0
    lines = [p for p in (_pts(v) for v in pred.get("vlines", [])) if p is not None]
    if expected_cols is None:
        expected_cols = pred.get("expected_cols")       # 缺省取闸当时用的期望（含按页覆盖）
    out: dict[str, Any] = {"n_lines": len(lines)}
    out["n_cols_ok"] = None if expected_cols is None else (len(lines) == expected_cols + 1)
    if len(lines) >= 3:
        ym = float(np.mean([(p[:, 1].min() + p[:, 1].max()) / 2 for p in lines]))
        xs = np.sort([float(x_at(p, np.array([ym]))[0]) for p in lines])
        d = np.diff(xs)
        med = float(np.median(d))
        out["pitch"] = med
        out["pitch_cv"] = float(np.std(d) / med) if med > 0 else None
        out["pitch_dev_max"] = float(np.max(np.abs(d - med)) / med) if med > 0 else None
    else:
        out["pitch"] = out["pitch_cv"] = out["pitch_dev_max"] = None
    inside = True
    if W and H:
        for p in lines + [q for q in (_pts(pred.get("top")), _pts(pred.get("bottom"))) if q is not None]:
            if (p[:, 0] < -1).any() or (p[:, 0] > W).any() or (p[:, 1] < -1).any() or (p[:, 1] > H).any():
                inside = False
    out["inside"] = inside
    t, b = _pts(pred.get("top")), _pts(pred.get("bottom"))
    if t is not None and b is not None and H:
        xm = float((t[:, 0].min() + t[:, 0].max()) / 2)
        yt, yb = float(y_at(t, np.array([xm]))[0]), float(y_at(b, np.array([xm]))[0])
        out["frame_ok"] = bool(yt < yb and (yb - yt) >= 0.4 * H)
    else:
        out["frame_ok"] = None
    return out


def summarize_health(recs: list[dict]) -> dict:
    """体检结果汇总：各项的页比例与间距变异分位。"""
    def rate(k):
        v = [r[k] for r in recs if r.get(k) is not None]
        return (sum(1 for x in v if x) / len(v)) if v else None
    cv = [r["pitch_cv"] for r in recs if r.get("pitch_cv") is not None]
    dev = [r["pitch_dev_max"] for r in recs if r.get("pitch_dev_max") is not None]
    return {"pages": len(recs), "n_cols_ok": rate("n_cols_ok"), "inside": rate("inside"),
            "frame_ok": rate("frame_ok"),
            "pitch_cv": {"median": _pct(cv, 50), "p95": _pct(cv, 95)},
            "pitch_dev_max": {"median": _pct(dev, 50), "p95": _pct(dev, 95)}}
