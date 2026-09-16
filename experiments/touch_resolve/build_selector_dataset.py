# -*- coding: utf-8 -*-
"""攒「切法选择器」的训练集：每个有人裁的切点 → 逐候选特征 + 人选了哪条。

    python experiments/touch_resolve/build_selector_dataset.py [--books vol01,vol02,vol03]

为什么要这个（10 卡第九节）：夜里试的三条自动化路子（一致率 margin / 识别置信否决 / 默认选 U-Net 缝）
全部证伪，说明**单个特征都不够**，要的是一个在多特征上训出来的选择器。现在 vol02 有 228 条人裁，
其中 147 条落在难例上且带 `cand`（人明确选了哪种切法）——先把特征抽出来存成表，样本够了直接训。

**产物已被人裁收敛**（池里只剩人选的那条），所以要**关掉 resolved_cuts 重算该列**拿原池，
与 `exp11_recog_veto.py` 同一套办法。

每条候选的特征（都能在生产里零成本拿到，不依赖金标）：
  几何：seam_ink（穿墨量）、dev_max（离直线最大偏移）、dev_mean、kind 独热
  裁判：agree（U-Net 置信加权一致率）、dis_unet（与归属图分歧最大块）、agree 在池内的排名与差距
  池级：n_cand、该切点上下两格的高度比、直线是否穿墨、切点墨量
标签：is_pick（人选了这条）。产出 out/selector_ds/<books>.jsonl（一行一个候选）+ 一份统计。
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
from common import INK_TH, OUT_ROOT  # noqa: E402
from open_guji_cv.core.book import load_book  # noqa: E402
from open_guji_cv.core.spec import column_key  # noqa: E402
from open_guji_cv.core.step import page_key  # noqa: E402
from open_guji_cv.eval.touching import SHARD  # noqa: E402
from open_guji_cv.feedback.consumers import verdict_store  # noqa: E402
from open_guji_cv.products import kinds as _k  # noqa: E402,F401
from open_guji_cv.products.cache import ImageCache  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402
from open_guji_cv.steps.row_segment import RowSegmentParams  # noqa: E402
from open_guji_cv.utils.cut_select import get_judge  # noqa: E402
from verify_prod_judge import run_column  # noqa: E402

KINDS = ("straight", "seam_narrow", "seam_wide", "unet_seam", "period_up", "period_dn")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--books", default="vol01,vol02,vol03")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    st, ic = ProductStore(), ImageCache()
    judge = get_judge()
    rp = RowSegmentParams()
    out_rows: list[dict] = []
    stat = Counter()
    for book in a.books.split(","):
        picks: dict[str, str] = {}
        for it in verdict_store().list(SHARD):
            if it.anchor.book != book or it.status != "active":
                continue
            ex = it.expected
            k = ex.get("cand") or ("straight" if ex.get("verdict") == "ok" else None)
            if k:
                picks[it.id] = k
        if not picks:
            continue
        try:
            bk = load_book(book)
        except Exception:
            continue
        stat[f"{book}_picks"] = len(picks)
        gate_cache: dict = {}
        col_cache: dict = {}
        cells_cache: dict = {}

        def repool(pg: int, col: int):
            key = (pg, col)
            if key in col_cache:
                return col_cache[key]
            if pg not in gate_cache:
                gate_cache[pg] = st.read(book, "column_gate", page_key(pg), "gate_manifest")
            gate = gate_cache[pg]
            res = (None, {})
            if gate is not None and gate.period is not None:
                gc = next((g for g in gate.columns if g.col == col), None)
                p_ = ic.get(book, "column_image", column_key(pg, col))
                img_ = cv2.imread(str(p_), cv2.IMREAD_GRAYSCALE) if p_ else None
                if gc is not None and img_ is not None:
                    r_ = run_column(bk, gate, gc, img_, rp, judge)
                    if r_ is not None:
                        res = (img_, {cp.slot_above: cp for cp in r_.cut_candidates})
            col_cache[key] = res
            return res

        for cid, pick in picks.items():
            try:
                _, pg, col, slot = cid.split(":")
                pg, col, slot = int(pg), int(col), int(slot)
            except ValueError:
                continue
            img, pool = repool(pg, col)
            cp = pool.get(slot)
            if cp is None or img is None:
                stat["no_pool"] += 1
                continue
            if pg not in cells_cache:
                cells_cache[pg] = st.read(book, "row_segment", page_key(pg), "cells")
            cells = cells_cache[pg]
            cc = next((c for c in (cells.columns if cells else []) if c.col == col and c.ok), None)
            if cc is None:
                continue
            cm = {c.slot: c for c in cc.cells if c.sub is None}
            up, dn = cm.get(cp.slot_above), cm.get(cp.slot_below)
            if up is None or dn is None:
                continue
            x_lo, x_hi = [int(round(v)) for v in cc.content_x]
            w = x_hi - x_lo
            y_line = int(round(cp.y))
            ink_col = img[:, x_lo:x_hi] < INK_TH
            straight_ink = int(ink_col[y_line].sum()) if 0 <= y_line < ink_col.shape[0] else 0
            hs = sorted(c.y1 - c.y0 for c in cc.cells if c.kind == "char" and c.sub is None)
            med = float(hs[len(hs) // 2]) if hs else 1.0
            agrees = [c.agree for c in cp.candidates if c.agree is not None]
            best_agree = max(agrees) if agrees else None
            kinds_here = [c.kind for c in cp.candidates]
            if pick not in kinds_here:
                stat["pick_not_in_pool"] += 1
                continue
            stat["cut_points"] += 1
            for c in cp.candidates:
                seam = np.full(w, y_line) if c.y is None else np.asarray(c.y, dtype=int)
                dev = np.abs(seam - y_line)
                row = {
                    "id": cid, "book": book, "kind": c.kind, "is_pick": int(c.kind == pick),
                    "n_cand": len(cp.candidates),
                    "seam_ink": int(c.seam_ink), "dev_max": int(c.dev_max), "dev_mean": round(float(dev.mean()), 2),
                    "agree": c.agree, "dis_unet": c.dis_unet,
                    "agree_gap_to_best": (round(best_agree - c.agree, 5) if (c.agree is not None and best_agree is not None) else None),
                    "agree_rank": (sorted(agrees, reverse=True).index(c.agree) if (c.agree is not None and agrees) else None),
                    "up_h_ratio": round((up.y1 - up.y0) / med, 3) if med else None,
                    "dn_h_ratio": round((dn.y1 - dn.y0) / med, 3) if med else None,
                    "straight_ink": straight_ink,
                    "origin": getattr(cp, "origin", "touching"),
                    "escalate": bool(cp.escalate),
                }
                for k in KINDS:
                    row[f"is_{k}"] = int(c.kind == k)
                out_rows.append(row)
    out = Path(a.out) if a.out else OUT_ROOT / "selector_ds" / f"{a.books.replace(',', '_')}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out_rows) + "\n", encoding="utf-8")
    n_pts = len({r["id"] for r in out_rows})
    print(f"切点 {n_pts}，候选行 {len(out_rows)}  → {out}")
    print("统计:", dict(stat))
    print("人选的 kind 分布:", Counter(r["kind"] for r in out_rows if r["is_pick"]))
    print("候选 kind 分布:", Counter(r["kind"] for r in out_rows))
    # 单特征基线（给将来的模型一个要打败的下限）
    import numpy as _np
    by_pt: dict = {}
    for r in out_rows:
        by_pt.setdefault(r["id"], []).append(r)
    for name, key, rev in (("agree 最高", "agree", True), ("dis_unet 最小", "dis_unet", False),
                           ("seam_ink 最小", "seam_ink", False), ("dev_max 最小", "dev_max", False)):
        hit = 0
        tot = 0
        for _id, cs in by_pt.items():
            v = [c for c in cs if c.get(key) is not None]
            if len(v) < 2:
                continue
            tot += 1
            best = (max if rev else min)(v, key=lambda c: c[key])
            hit += best["is_pick"]
        if tot:
            print(f"  单特征基线「{name}」: {hit}/{tot} = {hit / tot:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
