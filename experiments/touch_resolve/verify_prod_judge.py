# -*- coding: utf-8 -*-
"""落地核对：生产 `segment_column(cut_judge=...)` 在金标列上，新旧两版切法的像素归属误差 + 改动清单 + 改选门槛 δ 扫描。

    python experiments/touch_resolve/verify_prod_judge.py [--books vol01,vol02,vol03] [--sheet]

与 `scripts/seg_harness.py` 同一套入参（gate / windows / column_image → segment_column），
对 frame_ok 金标涉及的每一列各跑两次：cut_judge=None（旧规则）与 get_judge()（U-Net 裁判），**不传裁决表**
（要看裁判自己的本事；生产里人裁回流在裁判之后、优先级更高，这里另按 workspace 裁决表标出哪些切点已有人裁，
「生产视角」= 已裁的按人、其余按裁判）。按 (slot_above, slot_below) 对到金标切点，对池里**每条候选**都算
与金标缝的错归属墨像素（尺子同实验三：err_px / blob≥60 / blob≥150），存 per_case，供离线扫改选门槛 δ：
只有最优候选的一致率比现役选中高出 ≥ δ 才改选（δ=0 即纯 argmax）。
`--sheet` 出前 24 条改选的对照图（红=旧 绿=新 蓝=金标）到 out/verify_prod_judge/。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import INK_TH, Loader, OUT_ROOT, jdump, seam_gold, window  # noqa: E402
from exp3_partition_eval import err_stats  # noqa: E402
from open_guji_cv.core.book import load_book  # noqa: E402
from open_guji_cv.core.spec import column_key  # noqa: E402
from open_guji_cv.core.step import page_key  # noqa: E402
from open_guji_cv.products.cache import ImageCache  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402
from open_guji_cv.steps.row_segment import RowSegmentParams  # noqa: E402
from open_guji_cv.utils import row_boundaries as RB  # noqa: E402
from open_guji_cv.utils.cut_select import get_judge, owner_from_seam  # noqa: E402


def run_column(bk, gate, gc, img, p: RowSegmentParams, judge):
    n_body = p.n_body_slots or bk.chars_per_line
    n_raised_col = max(p.n_raised, getattr(gc, "n_raised_hint", 0) or 0)
    n_body_col = RB.effective_body_slots(n_body, gc.border_top, gc.border_bottom, gate.period)
    return RB.segment_column(
        img, period=gate.period, n_body_slots=n_body_col, n_raised=n_raised_col,
        border_top=gc.border_top, border_bottom=gc.border_bottom, ref_w=gate.ref_w,
        top_slack=gc.top_slack, content_x=gc.content_x,
        ink_threshold=p.ink_threshold, min_ink_ratio=p.min_ink_ratio,
        raise_tol=p.raise_tol, detect_jiazhu=p.detect_jiazhu, seam_band=p.seam_band,
        resolved_cuts=None, cut_judge=judge)


def cut_point(r, slot_above: int, slot_below: int):
    for cp in r.cut_candidates:
        if cp.slot_above == slot_above and cp.slot_below == slot_below:
            return cp
    return None


def seam_of(r, cp, cand):
    x_lo, x_hi = r.content_x
    n = int(x_hi - x_lo)
    if cand.y is None:
        return np.full(n, int(round(cp.y)))
    return np.asarray(cand.y, dtype=int)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--books", default="vol01,vol02,vol03")
    ap.add_argument("--sheet", action="store_true")
    a = ap.parse_args()
    from open_guji_cv.feedback.lookup import resolved_cuts as _resolved
    L = Loader()
    frame_ok = set(json.loads((OUT_ROOT / "frame_ok.json").read_text(encoding="utf-8")))
    exp1 = {r["id"]: r for r in json.loads((OUT_ROOT / "exp1" / "per_case.json").read_text(encoding="utf-8"))}
    st, ic = ProductStore(), ImageCache()
    p = RowSegmentParams()
    judge = get_judge()
    assert judge is not None, "裁判不可用（torch / 权重）"
    out = OUT_ROOT / "verify_prod_judge"
    (out / "sheet").mkdir(parents=True, exist_ok=True)
    per, changed = [], []
    t_rule = t_judge = 0.0
    cache: dict = {}
    for book in a.books.split(","):
        bk = load_book(book)
        resolved = _resolved(book)          # {(page, col, slot_above): kind|ResolvedCut}
        items = [it for it in L.gold_items(books=[book]) if it.id in frame_ok]
        for it in items:
            c, _ = L.resolve(it)
            if c is None:
                continue
            key = (book, c.page, c.col)
            if key not in cache:
                gate = st.read(book, "column_gate", page_key(c.page), "gate_manifest")
                gc = next((g for g in gate.columns if g.col == c.col), None) if gate is not None else None
                path = ic.get(book, "column_image", column_key(c.page, c.col))
                img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) if path else None
                if gate is None or gc is None or img is None or gate.period is None:
                    cache[key] = None
                else:
                    t0 = time.time(); r0 = run_column(bk, gate, gc, img, p, None); t1 = time.time()
                    r1 = run_column(bk, gate, gc, img, p, judge); t2 = time.time()
                    t_rule += t1 - t0; t_judge += t2 - t1
                    cache[key] = (img, r0, r1)
            if cache[key] is None or cache[key][1] is None or cache[key][2] is None:
                continue
            img, r0, r1 = cache[key]
            sa, sb = it.expected.get("slot_above"), it.expected.get("slot_below")
            cp0, cp1 = cut_point(r0, sa, sb), cut_point(r1, sa, sb)
            win, y0, _ = window(c, img)
            W = (win < INK_TH).astype(np.uint8)
            og = owner_from_seam(W, seam_gold(c) - y0)
            rk = (exp1.get(c.id) or {}).get("rank", {}).get("gold", {})
            label_ok = bool(rk.get("fused_above") and rk["fused_above"] <= 5 and rk.get("fused_below") and rk["fused_below"] <= 5)
            rec = {"id": c.id, "verdict": c.verdict, "label_ok": label_ok,
                   "resolved": (c.page, c.col, sa) in resolved, "cands": [], "rule_idx": None, "judge_idx": None}
            if cp1 is None:                      # 干净格线：没有候选，直线即现役
                cells = {x.slot: x for x in r1.cells if x.sub is None}
                up = cells.get(sa)
                if up is None:
                    continue
                s_ = np.full(win.shape[1], int(round(up.y1)))
                e = err_stats(owner_from_seam(W, s_ - y0), og)
                rec["cands"] = [{"kind": "straight", "agree": None, "px": e[0], "blob": e[1]}]
                rec["rule_idx"] = rec["judge_idx"] = 0
                rec["by"] = None
            else:
                for cand in cp1.candidates:
                    s_ = seam_of(r1, cp1, cand)
                    if len(s_) != win.shape[1]:
                        break
                    e = err_stats(owner_from_seam(W, s_ - y0), og)
                    rec["cands"].append({"kind": cand.kind, "agree": cand.agree, "px": e[0], "blob": e[1]})
                if len(rec["cands"]) != len(cp1.candidates):
                    continue
                rule_kind = cp0.candidates[cp0.chosen].kind if cp0 is not None else "straight"
                rec["rule_idx"] = next((i for i, x in enumerate(rec["cands"]) if x["kind"] == rule_kind), 0)
                rec["judge_idx"] = cp1.chosen
                rec["by"] = cp1.chosen_by
                if cp0 is not None and cp1.chosen != rec["rule_idx"]:
                    changed.append((rec, win, y0, seam_of(r0, cp0, cp0.candidates[cp0.chosen]),
                                    seam_of(r1, cp1, cp1.candidates[cp1.chosen]), seam_gold(c)))
            per.append(rec)
    jdump(per, out / "per_case.json")

    def pick_delta(r, delta):
        cs = r["cands"]
        ri = r["rule_idx"]
        if len(cs) < 2 or any(x["agree"] is None for x in cs):
            return ri
        best = max(range(len(cs)), key=lambda i: (cs[i]["agree"], i == ri))
        return best if cs[best]["agree"] - cs[ri]["agree"] >= delta else ri

    def agg(errs):
        px = np.array([e["px"] for e in errs]); bl = np.array([e["blob"] for e in errs])
        return f"px {px.mean():5.1f} 中位 {np.median(px):3.0f} | ≤20px {np.mean(px <= 20):5.1%} | blob≥60 {np.mean(bl >= 60):5.1%} | ≥150 {np.mean(bl >= 150):5.1%}"

    rows = [r for r in per if r["label_ok"]]
    ncol = sum(1 for v in cache.values() if v)
    print(f"金标用例 {len(per)}（label_ok {len(rows)}；其中已有人裁 {sum(1 for r in rows if r['resolved'])}）；列数 {ncol}；"
          f"耗时 旧规则 {t_rule:.1f}s / 裁判 {t_judge:.1f}s（每列 +{(t_judge - t_rule) / max(1, ncol) * 1000:.0f} ms，设备 {judge.device}）")
    print("label_ok  旧规则           :", agg([r["cands"][r["rule_idx"]] for r in rows]))
    print("label_ok  裁判(生产,δ=0)   :", agg([r["cands"][r["judge_idx"]] for r in rows]))
    for d in (0.002, 0.003, 0.005, 0.008, 0.01):
        print(f"label_ok  裁判 δ={d:<6}     :", agg([r["cands"][pick_delta(r, d)] for r in rows]))
    print("label_ok  候选池上限       :", agg([min(r["cands"], key=lambda x: (x["blob"], x["px"])) for r in rows]))
    nr = [r for r in rows if not r["resolved"]]
    print(f"-- 未有人裁的 {len(nr)} 条（裁判真正起作用的范围）")
    print("   旧规则        :", agg([r["cands"][r["rule_idx"]] for r in nr]))
    for d in (0.0, 0.003, 0.005):
        print(f"   裁判 δ={d:<5}   :", agg([r["cands"][pick_delta(r, d)] for r in nr]))
    for v in ("seam_ok", "ok", "moved", "overlap"):
        rr = [r for r in rows if r["verdict"] == v]
        if rr:
            b0 = np.mean([r["cands"][r["rule_idx"]]["blob"] >= 150 for r in rr])
            b1 = np.mean([r["cands"][r["judge_idx"]]["blob"] >= 150 for r in rr])
            b2 = np.mean([r["cands"][pick_delta(r, 0.005)]["blob"] >= 150 for r in rr])
            print(f"  {v:8s} n={len(rr):3d} 大块错 旧 {b0:5.1%} → δ=0 {b1:5.1%} → δ=0.005 {b2:5.1%}")
    for d in (0.0, 0.003, 0.005):
        ch = [r for r in rows if pick_delta(r, d) != r["rule_idx"]]
        better = sum(1 for r in ch if (r["cands"][pick_delta(r, d)]["blob"], r["cands"][pick_delta(r, d)]["px"]) < (r["cands"][r["rule_idx"]]["blob"], r["cands"][r["rule_idx"]]["px"]))
        worse = len(ch) - better - sum(1 for r in ch if r["cands"][pick_delta(r, d)] == r["cands"][r["rule_idx"]])
        print(f"δ={d}: 改选 {len(ch)} 条，变好 {better}，变差 {worse}")
    print("chosen_by 分布:", Counter(r.get("by") for r in per))
    if a.sheet and changed:
        tiles = []
        for rec, win, y0, s0, s1, sg in changed[:24]:
            vis = cv2.cvtColor(win, cv2.COLOR_GRAY2BGR)
            for seam, col in ((s0, (0, 0, 255)), (s1, (0, 180, 0)), (sg, (255, 0, 0))):
                pts = [(k, int(round(v - y0))) for k, v in enumerate(seam)]
                for a_, b_ in zip(pts, pts[1:]):
                    cv2.line(vis, a_, b_, col, 1)
            H = 240; s = H / vis.shape[0]; vis = cv2.resize(vis, (int(vis.shape[1] * s), H))
            canvas = np.full((H + 16, max(vis.shape[1], 220), 3), 255, np.uint8); canvas[:H, :vis.shape[1]] = vis
            e0, e1 = rec["cands"][rec["rule_idx"]], rec["cands"][rec["judge_idx"]]
            cv2.putText(canvas, f"{rec['id']} {rec['verdict']} rule {e0['px']} -> judge {e1['px']}",
                        (2, H + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1)
            tiles.append(canvas)
        Wm = max(t.shape[1] for t in tiles); rowsimg = []
        for i in range(0, len(tiles), 4):
            row = [np.pad(t, ((0, 0), (0, Wm - t.shape[1]), (0, 0)), constant_values=255) for t in tiles[i:i + 4]]
            while len(row) < 4:
                row.append(np.full_like(row[0], 255))
            rowsimg.append(np.hstack(row))
        cv2.imwrite(str(out / "sheet" / "changed.png"), np.vstack(rowsimg))
        print("→", out / "sheet" / "changed.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
