# -*- coding: utf-8 -*-
"""粘连格线：现役 Step3 切点 vs 人工理想切点（char-segmentation/touching-cuts）。

    python scripts/eval_touching_cuts.py [--book vol01] [--json out.json]

只算 verdict ∈ {moved, ok} 的条目；overlap 单独计数（切在哪都伤字，算法只能折中）；
idk（uncertain）不进指标。坐标系 = 现役 Step2 列图，col_h 对不上的条目报"漂移"并跳过。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from open_guji_cv.core.step import page_key  # noqa: E402
from open_guji_cv.eval.rulers import _col_profile  # noqa: E402
from open_guji_cv.eval.touching import polyline_to_seam, seam_deviation  # noqa: E402
from open_guji_cv.gold.store import GoldStore  # noqa: E402
from open_guji_cv.products import kinds as _k  # noqa: E402,F401
from open_guji_cv.products.store import ProductStore  # noqa: E402

SHARD = "char-segmentation/touching-cuts"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    gs, st = GoldStore(), ProductStore()
    items = [i for i in gs.list(SHARD) if i.status == "active"
             and (not a.book or i.anchor.book == a.book)]
    rows, overlap, drift, missing = [], 0, 0, 0
    tagged: dict[str, list] = {}
    poly_rows: list[dict] = []          # 折线金标 vs 现役缝
    for it in items:
        ex = it.expected
        v = ex.get("verdict")
        if ex.get("polyline") and len(ex["polyline"]) >= 2 and not ex.get("tags"):
            book, pg, col = it.anchor.book, it.anchor.page, it.anchor.col
            cells = st.read(book, "row_segment", page_key(pg), "cells")
            cc = next((c for c in (cells.columns if cells else []) if c.col == col and c.ok), None)
            if cc is not None:
                x0 = int(round(min(c.x0 for c in cc.cells))); x1 = int(round(max(c.x1 for c in cc.cells)))
                gold_seam = polyline_to_seam(ex["polyline"], x0, x1)
                # 现役缝：上格的 seam_bottom；没有就是直线（最近的格线）
                up = next((c for c in cc.cells if c.kind == "char" and c.slot == ex.get("slot_above")), None)
                if up is not None and getattr(up, "seam_bottom", None):
                    cur_seam = list(up.seam_bottom)
                else:
                    yy = float(min(cc.boundaries[1:-1], key=lambda b: abs(b - float(ex["y"]))))
                    cur_seam = [int(round(yy))] * len(gold_seam)
                mx, mean = seam_deviation(cur_seam, gold_seam)
                poly_rows.append(dict(id=it.id, max_dev=mx, mean_dev=mean, has_seam=up is not None and bool(getattr(up, "seam_bottom", None))))
        if ex.get("tags"):
            # 有干扰因素（污点 / 界行 / 邻字残墨）的条目单独一档：切点本身不是算法能决定的
            for t in ex["tags"]:
                tagged.setdefault(t, []).append(it.id)
            continue
        if v == "overlap":
            overlap += 1
            continue
        if v not in ("moved", "ok") or ex.get("y") is None:
            continue
        book, pg, col = it.anchor.book, it.anchor.page, it.anchor.col
        cells = st.read(book, "row_segment", page_key(pg), "cells")
        cc = next((c for c in (cells.columns if cells else []) if c.col == col and c.ok), None)
        if cc is None:
            missing += 1
            continue
        prof = _col_profile(st, book, pg, col)
        if prof is not None and ex.get("col_h") and abs(len(prof) - int(ex["col_h"])) > 2:
            drift += 1
            continue
        # 金标是一个物理位置（"该切在这两个字之间"），不是"第 bi 条格线"——切分把空白格
        # 放到别处后格线序号会整体错位（2026-09-05 实测按序号比会报出 115–132px 的假偏差）。
        # 口径：金标位置到最近一条内部格线的距离；bi 只作展示。
        bi = ex.get("bi")
        inner = cc.boundaries[1:-1]
        if not inner:
            missing += 1
            continue
        cur = float(min(inner, key=lambda b: abs(b - float(ex["y"]))))
        rows.append(dict(id=it.id, book=book, page=pg, col=col, bi=bi, gold_y=float(ex["y"]),
                         cur_y=cur, err=abs(cur - float(ex["y"])), verdict=v))
    if not rows:
        print(f"touching-cuts：没有可比条目（overlap {overlap}，干扰 {sum(len(v) for v in tagged.values())}，漂移 {drift}，缺产物 {missing}，金标 {len(items)}）")
        return 0
    e = np.array([r["err"] for r in rows])
    print(f"touching-cuts n={len(e)}（moved {sum(r['verdict']=='moved' for r in rows)} / ok {sum(r['verdict']=='ok' for r in rows)}；"
          f"overlap 另计 {overlap}，干扰另计 {sum(len(v) for v in tagged.values())}，漂移跳过 {drift}，缺产物 {missing}）")
    print(f"  像素误差 mean {e.mean():.1f}  median {np.median(e):.1f}  p90 {np.percentile(e, 90):.1f}  max {e.max():.0f}")
    print(f"  ≤3px {100*(e<=3).mean():.1f}%   ≤5px {100*(e<=5).mean():.1f}%   ≤10px {100*(e<=10).mean():.1f}%")
    worst = sorted(rows, key=lambda r: -r["err"])[:8]
    print("  最差:", [(r["id"], round(r["err"])) for r in worst])
    if tagged:
        print("  干扰另计:", {k: len(v) for k, v in tagged.items()}, {k: v[:5] for k, v in tagged.items()})
    if poly_rows:
        mx = np.array([r["max_dev"] for r in poly_rows]); mn = np.array([r["mean_dev"] for r in poly_rows])
        ns = sum(r["has_seam"] for r in poly_rows)
        print(f"  折线金标 n={len(poly_rows)}（现役有缝 {ns}）：最大偏差 mean {mx.mean():.1f} median {np.median(mx):.1f} p90 {np.percentile(mx, 90):.1f}；"
              f"平均偏差 median {np.median(mn):.1f}；最大偏差 ≤3px {100*(mx<=3).mean():.1f}%  ≤6px {100*(mx<=6).mean():.1f}%")
        worst = sorted(poly_rows, key=lambda r: -r["max_dev"])[:5]
        print("  折线最差:", [(r["id"], round(r["max_dev"])) for r in worst])
    if a.json:
        Path(a.json).write_text(json.dumps({"rows": rows, "overlap": overlap, "drift": drift,
                                            "missing": missing}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
