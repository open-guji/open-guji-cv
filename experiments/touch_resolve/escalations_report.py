# -*- coding: utf-8 -*-
"""L2′ 升级切点盘点：从 Step3 产物里数「escalate=True」的切点，对金标核账，并出对照图。

    python experiments/touch_resolve/escalations_report.py --book vol02 [--pages all] [--sheet]

报：全书粘连切点数 / 多候选数 / 升级数（含单候选升级数）、按 chosen_by 分布、升级理由分布；
金标核账（workspace 裁决表里坐标系一致的 touching-cuts）：升级的里真大块错几条（召回）、
未升级却大块错几条（漏网）；`--sheet` 出升级切点的对照图：绿=现役所选，蓝=金标（有则画），红/蓝底色=U-Net 归属。
产出 out/escalations/<book>/summary.json、sheet.png、list.txt（id 一行一个，可直接喂控制台 list: 清单）。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import INK_TH, OUT_ROOT, jdump  # noqa: E402
from exp3_partition_eval import err_stats  # noqa: E402
from open_guji_cv.core.spec import column_key  # noqa: E402
from open_guji_cv.core.step import page_key  # noqa: E402
from open_guji_cv.core.workspace import feedback_root  # noqa: E402
from open_guji_cv.eval.touching import SHARD, polyline_to_seam  # noqa: E402
from open_guji_cv.feedback.consumers import verdict_store  # noqa: E402
from open_guji_cv.products import kinds as _k  # noqa: E402,F401
from open_guji_cv.products.cache import ImageCache  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402
from open_guji_cv.utils.cut_select import get_judge, owner_from_seam  # noqa: E402


def gold_seam(ex: dict, x_lo: int, x_hi: int):
    if ex.get("polyline") and len(ex["polyline"]) >= 2:
        return np.asarray(polyline_to_seam(ex["polyline"], x_lo, x_hi), dtype=int)
    if ex.get("y") is not None:
        return np.full(x_hi - x_lo, int(round(ex["y"])))
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="vol02")
    ap.add_argument("--pages", default="all")
    ap.add_argument("--sheet", action="store_true")
    a = ap.parse_args()
    st, ic = ProductStore(), ImageCache()
    out = OUT_ROOT / "escalations" / a.book
    out.mkdir(parents=True, exist_ok=True)
    pages = sorted(int(p.stem[1:]) for p in (st.root / a.book / "row_segment").glob("p*.json")) if a.pages == "all" \
        else [int(x) for x in a.pages.split(",")]
    gold = {}
    for it in verdict_store().list(SHARD):
        if it.anchor.book == a.book and it.status == "active" and not it.expected.get("tags"):
            gold[(int(it.anchor.page), int(it.anchor.col), it.expected.get("slot_above"))] = it
    cnt = Counter()
    esc = []
    by_col_h: dict = {}
    for pg in pages:
        cells = st.read(a.book, "row_segment", page_key(pg), "cells")
        if cells is None:
            continue
        for cc in cells.columns:
            if not cc.ok:
                continue
            for cp in cc.cut_candidates or []:
                cnt["cut_points"] += 1
                n = len(cp.candidates)
                cnt["multi" if n >= 2 else "single"] += 1
                cnt[f"by_{cp.chosen_by}"] += 1
                if cp.escalate:
                    cnt["escalated"] += 1
                    cnt["escalated_single" if n == 1 else "escalated_multi"] += 1
                    esc.append((pg, cc, cp))
    print(f"{a.book} {len(pages)} 页：粘连切点 {cnt['cut_points']}，多候选 {cnt['multi']}，单候选 {cnt['single']}；"
          f"chosen_by rule {cnt['by_rule']} / unet {cnt['by_unet']} / human {cnt['by_human']}")
    print(f"升级 {cnt['escalated']}（{cnt['escalated'] / max(1, cnt['cut_points']):.1%}；≈{cnt['escalated'] / max(1, len(pages)):.2f} 条/页）："
          f"单候选 {cnt['escalated_single']}，多候选 {cnt['escalated_multi']}")

    # ── 金标核账 ──
    judge = get_judge()
    rows = []
    for pg in pages:
        cells = st.read(a.book, "row_segment", page_key(pg), "cells")
        if cells is None:
            continue
        for cc in cells.columns:
            if not cc.ok:
                continue
            path = None
            img = None
            for cp in cc.cut_candidates or []:
                g = gold.get((pg, cc.col, cp.slot_above))
                if g is None:
                    continue
                ex = g.expected
                if img is None:
                    path = ic.get(a.book, "column_image", column_key(pg, cc.col))
                    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) if path else None
                if img is None or ex.get("col_h") is None or abs(int(ex["col_h"]) - img.shape[0]) > 2:
                    continue
                cellmap = {c.slot: c for c in cc.cells if c.sub is None}
                up, dn = cellmap.get(cp.slot_above), cellmap.get(cp.slot_below)
                if up is None or dn is None:
                    continue
                x_lo, x_hi = [int(round(v)) for v in cc.content_x]
                y0, y1 = int(round(up.y0)), int(round(dn.y1))
                win = img[y0:y1, x_lo:x_hi]
                W = (win < INK_TH).astype(np.uint8)
                gs = gold_seam(ex, x_lo, x_hi)
                if gs is None or len(gs) != win.shape[1]:
                    continue
                og = owner_from_seam(W, gs - y0)
                cand = cp.candidates[cp.chosen]
                cs = np.full(x_hi - x_lo, int(round(cp.y))) if cand.y is None else np.asarray(cand.y, dtype=int)
                px, blob = err_stats(owner_from_seam(W, cs - y0), og)
                rows.append({"id": g.id, "page": pg, "col": cc.col, "slot": cp.slot_above, "verdict": ex.get("verdict"),
                             "escalate": bool(cp.escalate), "chosen_by": cp.chosen_by, "n_cand": len(cp.candidates),
                             "dis_unet": cand.dis_unet, "px": px, "blob": blob})
    if rows:
        big = [r for r in rows if r["blob"] >= 150]
        esc_rows = [r for r in rows if r["escalate"]]
        print(f"金标核账（坐标系一致 {len(rows)} 条）：大块错 {len(big)}，其中已升级 {sum(1 for r in big if r['escalate'])}，"
              f"漏网 {sum(1 for r in big if not r['escalate'])}；升级的 {len(esc_rows)} 条里真大块错 {sum(1 for r in esc_rows if r['blob'] >= 150)}、"
              f"一笔错(60..150) {sum(1 for r in esc_rows if 60 <= r['blob'] < 150)}、其实对的(<60) {sum(1 for r in esc_rows if r['blob'] < 60)}")
        for r in big:
            print("   大块错:", r["id"], r["verdict"], "escalate" if r["escalate"] else "漏网", f"dis_unet={r['dis_unet']} blob={r['blob']} by={r['chosen_by']} n={r['n_cand']}")
    ids = [f"{a.book}:{pg}:{cc.col}:{cp.slot_above}" for pg, cc, cp in esc]
    (out / "list.txt").write_text("# L2′ 升级切点（所选切法与 U-Net 分歧块 ≥100px），控制台页码框填 list:<名字> 出卡\n" + "\n".join(ids) + "\n", encoding="utf-8")
    jdump({"counts": dict(cnt), "gold_rows": rows, "escalated_ids": ids}, out / "summary.json")
    print("→", out / "list.txt", f"（{len(ids)} 条）")

    if a.sheet and esc:
        tiles = []
        for pg, cc, cp in esc[:48]:
            path = ic.get(a.book, "column_image", column_key(pg, cc.col))
            img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) if path else None
            if img is None:
                continue
            cellmap = {c.slot: c for c in cc.cells if c.sub is None}
            up, dn = cellmap.get(cp.slot_above), cellmap.get(cp.slot_below)
            if up is None or dn is None:
                continue
            x_lo, x_hi = [int(round(v)) for v in cc.content_x]
            y0, y1 = int(round(up.y0)), int(round(dn.y1))
            win = img[y0:y1, x_lo:x_hi]
            vis = cv2.cvtColor(win, cv2.COLOR_GRAY2BGR)
            if judge is not None:
                W, ou, _ = judge.owner(win)
                ov = vis.copy(); ov[ou == 1] = (60, 60, 230); ov[ou == 2] = (230, 120, 40)
                vis = cv2.addWeighted(vis, 0.45, ov, 0.55, 0)
            cand = cp.candidates[cp.chosen]
            cs = np.full(x_hi - x_lo, int(round(cp.y))) if cand.y is None else np.asarray(cand.y, dtype=int)
            layers = [(cs, (0, 200, 0), 2)]
            g = gold.get((pg, cc.col, cp.slot_above))
            if g is not None and abs(int(g.expected.get("col_h") or 0) - img.shape[0]) <= 2:
                gs = gold_seam(g.expected, x_lo, x_hi)
                if gs is not None and len(gs) == win.shape[1]:
                    layers.append((gs, (255, 0, 0), 2))
            for seam, colr, th in layers:
                pts = [(k, int(round(v - y0))) for k, v in enumerate(seam)]
                for p1, p2 in zip(pts, pts[1:]):
                    cv2.line(vis, p1, p2, colr, th)
            H = 230; s = H / vis.shape[0]; vis = cv2.resize(vis, (max(1, int(vis.shape[1] * s)), H))
            canvas = np.full((H + 16, max(vis.shape[1], 210), 3), 255, np.uint8); canvas[:H, :vis.shape[1]] = vis
            cv2.putText(canvas, f"p{pg} c{cc.col} s{cp.slot_above} {cand.kind[:6]} n={len(cp.candidates)} dis={cand.dis_unet}",
                        (2, H + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (0, 0, 0), 1)
            tiles.append(canvas)
        if tiles:
            Wm = max(t.shape[1] for t in tiles); rowsimg = []
            for i in range(0, len(tiles), 6):
                row = [np.pad(t, ((0, 0), (0, Wm - t.shape[1]), (0, 0)), constant_values=255) for t in tiles[i:i + 6]]
                while len(row) < 6:
                    row.append(np.full_like(row[0], 255))
                rowsimg.append(np.hstack(row))
            cv2.imwrite(str(out / "sheet.png"), np.vstack(rowsimg))
            print("→", out / "sheet.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
