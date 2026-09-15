# -*- coding: utf-8 -*-
"""实验十（L3 预研）：对「升级」的切点扩大候选池，看正确缝能不能进池、一致率能不能选中它。

    python experiments/touch_resolve/exp10_expand_pool.py --book vol02 [--ids-file <list.txt>] [--sheet]

只对 L2′/L0′ 升级的切点干活（10 卡：测下一层只测会传到这一层的样本）。对每个升级切点：
  现有池：产物里的候选（直线 / 窄 / 宽）；
  新候选：
    U   U-Net 归属导出的缝（归属图上「上/下」交界，按列取最靠近直线的换手行，再平滑）；
    P+  以「上格顶 + 中位格高」为中心、±20 走廊搜的最小墨缝；
    P−  以「下格底 − 中位格高」为中心搜的缝；
    V   以直线切点 ±45 内行投影局部最低点为中心搜的缝（最多 3 个）；
  对每条候选算：seam_ink、与 U-Net 归属的一致率 agree_w、分歧最大块 dis_unet。
报：
  - 有金标的升级切点：现有池最优 vs 扩池最优（err_px / blob），「正确缝进池率」（blob<60 的候选是否存在）；
  - 全部升级切点：扩池后一致率最高候选的 dis_unet 分布（≥100 的比例 = 扩池后仍拿不准、要传 L4/人的比例）；
  - `--sheet`：前 36 条对照图（现有所选=绿，扩池后一致率最高=品红，金标=蓝，U-Net 归属底色）。
产出 out/exp10/<book>/per_case.json、summary.json、sheet.png。
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
from open_guji_cv.eval.touching import SHARD, polyline_to_seam  # noqa: E402
from open_guji_cv.feedback.consumers import verdict_store  # noqa: E402
from open_guji_cv.products import kinds as _k  # noqa: E402,F401
from open_guji_cv.products.cache import ImageCache  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402
from open_guji_cv.utils.cut_select import ESCALATE_BLOB, get_judge, owner_from_seam  # noqa: E402
from open_guji_cv.utils.seam import SEAM_BAND, find_seam, seam_ink  # noqa: E402


def unet_seam(owner: np.ndarray, y_line_local: int, band: int = 45, step: int = 2, turn: float = 0.02) -> np.ndarray | None:
    """U-Net **引导**的缝：在直线 ±band 走廊里走一条 step≤2/列 的路径，代价 = 这一列切在 y 时归属错的墨像素数
    （U-Net 说是下字却在缝上方的 + 说是上字却在缝下方的）+ turn×纵向移动。第一版按列取「换手行」会画出字的轮廓
    （归属交错 / 整字翻边时不是一条切线），改成有约束的 seam DP 后得到的才是**可用的切线**。"""
    h, w = owner.shape
    up = (owner == 1).astype(np.int32)
    dn = (owner == 2).astype(np.int32)
    # mis[y, x] = 缝在 (x, y) 时该列错归属像素数：y 以上的下字像素 + y 及以下的上字像素
    cum_dn = np.cumsum(dn, axis=0)                   # 含当前行
    cum_up = np.cumsum(up, axis=0)
    tot_up = cum_up[-1]
    ys = np.arange(h)[:, None]
    above_dn = np.where(ys > 0, np.take_along_axis(cum_dn, np.clip(ys - 1, 0, h - 1), axis=0), 0)
    below_up = tot_up[None, :] - np.where(ys > 0, np.take_along_axis(cum_up, np.clip(ys - 1, 0, h - 1), axis=0), 0)
    mis = (above_dn + below_up).astype(np.float64)
    lo, hi = max(0, y_line_local - band), min(h - 1, y_line_local + band)
    n = hi - lo + 1
    rows = np.arange(lo, hi + 1)
    tie = 1e-4 * np.abs(rows - y_line_local)
    cost = mis[lo:hi + 1, 0] + tie
    back = np.zeros((w, n), dtype=np.int16)
    offsets = np.arange(-step, step + 1)
    for x in range(1, w):
        cand = np.full((len(offsets), n), np.inf)
        for i, d in enumerate(offsets):
            if d >= 0:
                cand[i, d:] = cost[:n - d] + turn * d
            else:
                cand[i, :n + d] = cost[-d:] + turn * (-d)
        best_i = np.argmin(cand, axis=0)
        cost = cand[best_i, np.arange(n)] + mis[lo:hi + 1, x] + tie
        back[x] = offsets[best_i]
    j = int(np.argmin(cost))
    out = np.empty(w, dtype=int)
    for x in range(w - 1, -1, -1):
        out[x] = lo + j
        j -= int(back[x, j]) if x > 0 else 0
        j = int(np.clip(j, 0, n - 1))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="vol02")
    ap.add_argument("--ids-file", default=None, help="升级切点清单；缺省读 out/escalations/<book>/list.txt")
    ap.add_argument("--sheet", action="store_true")
    a = ap.parse_args()
    st, ic = ProductStore(), ImageCache()
    judge = get_judge()
    assert judge is not None
    out = OUT_ROOT / "exp10" / a.book
    out.mkdir(parents=True, exist_ok=True)
    ids_path = Path(a.ids_file) if a.ids_file else OUT_ROOT / "escalations" / a.book / "list.txt"
    ids = [l.strip() for l in ids_path.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    gold = {}
    for it in verdict_store().list(SHARD):
        if it.anchor.book == a.book and it.status == "active" and not it.expected.get("tags"):
            gold[(int(it.anchor.page), int(it.anchor.col), it.expected.get("slot_above"))] = it.expected
    per = []
    tiles = []
    for cid in ids:
        _, pg, col, slot = cid.split(":")
        pg, col, slot = int(pg), int(col), int(slot)
        cells = st.read(a.book, "row_segment", page_key(pg), "cells")
        if cells is None:
            continue
        cc = next((c for c in cells.columns if c.col == col and c.ok), None)
        if cc is None:
            continue
        cp = next((cp for cp in cc.cut_candidates if cp.slot_above == slot), None)
        if cp is None:
            continue
        path = ic.get(a.book, "column_image", column_key(pg, col))
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
        ink_full = img[:, x_lo:x_hi] < INK_TH
        W, ou, conf = judge.owner(win)
        ink = W > 0
        cw = conf[ink]
        denom = float(cw.sum()) or 1e-6
        hs = sorted(c.y1 - c.y0 for c in cc.cells if c.kind == "char" and c.sub is None)
        med = float(hs[len(hs) // 2]) if hs else float(cells.period or 100)
        y_line = int(round(cp.y))
        w = x_hi - x_lo

        def eval_seam(seam_abs: np.ndarray):
            o = owner_from_seam(W, seam_abs - y0)
            eq = (o[ink] == ou[ink])
            agree = float((cw * eq).sum() / denom)
            m = ink & (o != ou)
            dis = 0
            if m.any():
                _, _, s_, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
                dis = int(s_[1:, cv2.CC_STAT_AREA].max())
            return round(agree, 4), dis

        cands = []
        for c in cp.candidates:
            seam_abs = np.full(w, y_line) if c.y is None else np.asarray(c.y, dtype=int)
            cands.append(("old:" + c.kind, seam_abs))
        # U：U-Net 导出缝
        us = unet_seam(ou, y_line - y0)
        if us is not None:
            cands.append(("U", us + y0))
        # P±：按中位格高推的中心
        for name, center in (("P+", int(round(up.y0 + med))), ("P-", int(round(dn.y1 - med)))):
            if 0 < center < img.shape[0]:
                sm = find_seam(ink_full, center, band=SEAM_BAND)
                cands.append((name, sm))
        # V：直线 ±45 内行投影的局部最低点
        prof = ink_full.sum(axis=1).astype(float)
        lo, hi = max(1, y_line - 45), min(len(prof) - 1, y_line + 45)
        vals = [(prof[y], y) for y in range(lo, hi) if prof[y] <= prof[y - 1] and prof[y] <= prof[y + 1]]
        vals.sort()
        seen_v = set()
        for v, yv in vals:
            if any(abs(yv - s) < 8 for s in seen_v):
                continue
            seen_v.add(yv)
            cands.append((f"V{yv - y_line:+d}", find_seam(ink_full, yv, band=SEAM_BAND)))
            if len(seen_v) >= 3:
                break
        # 去重
        uniq = []
        for name, sm in cands:
            if sm is None or len(sm) != w:
                continue
            key = tuple(int(v) for v in sm)
            if any(key == tuple(int(v) for v in s2) for _, s2 in uniq):
                continue
            uniq.append((name, np.asarray(sm, dtype=int)))
        g = gold.get((pg, col, slot))
        gs = None
        if g and g.get("col_h") is not None and abs(int(g["col_h"]) - img.shape[0]) <= 2:
            gs = (np.asarray(polyline_to_seam(g["polyline"], x_lo, x_hi), dtype=int) if g.get("polyline") and len(g["polyline"]) >= 2
                  else (np.full(w, int(round(g["y"]))) if g.get("y") is not None else None))
            if gs is not None and len(gs) != w:
                gs = None
        og = owner_from_seam(W, gs - y0) if gs is not None else None
        rows = []
        for name, sm in uniq:
            agree, dis = eval_seam(sm)
            rec = {"name": name, "agree": agree, "dis_unet": dis, "seam_ink": int(seam_ink(ink_full, sm)),
                   "dev": int(np.abs(sm - y_line).max())}
            if og is not None:
                px, blob = err_stats(owner_from_seam(W, sm - y0), og)
                rec["err"] = {"px": px, "blob": blob}
            rows.append(rec)
        old_rows = [r for r in rows if r["name"].startswith("old:")]
        best_old = max(old_rows, key=lambda r: r["agree"]) if old_rows else None
        best_all = max(rows, key=lambda r: r["agree"])
        per.append({"id": cid, "origin": getattr(cp, "origin", "touching"), "chosen": cp.candidates[cp.chosen].kind,
                    "has_gold": og is not None, "cands": rows,
                    "best_old": best_old["name"] if best_old else None, "best_all": best_all["name"],
                    "best_all_dis": best_all["dis_unet"]})
        if a.sheet and len(tiles) < 36:
            vis = cv2.cvtColor(win, cv2.COLOR_GRAY2BGR)
            ov = vis.copy(); ov[ou == 1] = (60, 60, 230); ov[ou == 2] = (230, 120, 40)
            vis = cv2.addWeighted(vis, 0.5, ov, 0.5, 0)
            chosen_seam = next(sm for name, sm in uniq if name == "old:" + cp.candidates[cp.chosen].kind)
            best_seam = next(sm for name, sm in uniq if name == best_all["name"])
            layers = [(chosen_seam, (0, 200, 0), 2), (best_seam, (255, 0, 255), 1)]
            if gs is not None:
                layers.append((gs, (255, 0, 0), 2))
            for seam, colr, th in layers:
                pts = [(k, int(round(v - y0))) for k, v in enumerate(seam)]
                for p1, p2 in zip(pts, pts[1:]):
                    cv2.line(vis, p1, p2, colr, th)
            H = 230; s = H / vis.shape[0]; vis = cv2.resize(vis, (max(1, int(vis.shape[1] * s)), H))
            canvas = np.full((H + 16, max(vis.shape[1], 230), 3), 255, np.uint8); canvas[:H, :vis.shape[1]] = vis
            cv2.putText(canvas, f"{cid[6:]} {cp.candidates[cp.chosen].kind[:5]}->{best_all['name']} dis {best_all['dis_unet']}",
                        (2, H + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (0, 0, 0), 1)
            tiles.append(canvas)
    jdump(per, out / "per_case.json")
    n = len(per)
    withg = [r for r in per if r["has_gold"]]
    print(f"升级切点 {n}（有金标 {len(withg)}）")
    if withg:
        def best_err(r, prefix=None):
            rs = [c for c in r["cands"] if "err" in c and (prefix is None or c["name"].startswith(prefix))]
            return min((c["err"] for c in rs), key=lambda e: (e["blob"], e["px"])) if rs else None
        in_old = sum(1 for r in withg if (best_err(r, "old:") or {"blob": 999})["blob"] < 60)
        in_all = sum(1 for r in withg if (best_err(r) or {"blob": 999})["blob"] < 60)
        pick = []
        for r in withg:
            c = next(c for c in r["cands"] if c["name"] == r["best_all"])
            pick.append(c["err"]["blob"] < 60)
        print(f"  正确缝（blob<60）在现有池里的 {in_old}/{len(withg)}；扩池后 {in_all}/{len(withg)}；扩池后取一致率最高者选对 {sum(pick)}/{len(withg)}")
        for r in withg:
            print("   ", r["id"], r["chosen"], "→", r["best_all"], "err", next(c["err"] for c in r["cands"] if c["name"] == r["best_all"]),
                  "| 池内最优", best_err(r, "old:"), "扩池最优", best_err(r))
    still = sum(1 for r in per if r["best_all_dis"] >= ESCALATE_BLOB)
    print(f"  扩池后一致率最高候选仍与 U-Net 分歧 ≥{ESCALATE_BLOB}px 的 {still}/{n}（= 扩池后仍拿不准）；"
          f"新候选被选中的分布 {Counter(r['best_all'].split(':')[0] if r['best_all'].startswith('old') else r['best_all'][:2] for r in per)}")
    jdump({"n": n, "with_gold": len(withg), "still_unsure": still}, out / "summary.json")
    if a.sheet and tiles:
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
