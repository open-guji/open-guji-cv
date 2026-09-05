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
    for it in items:
        ex = it.expected
        v = ex.get("verdict")
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
        bi = ex.get("bi")
        if bi is None or not (0 < bi < len(cc.boundaries) - 1):
            # 退路：按上格格位找那条格线
            idx = next((k for k, c in enumerate(cc.cells) if c.slot == it.anchor.slot), None)
            if idx is None:
                missing += 1
                continue
            bi = idx + 1
        cur = float(cc.boundaries[bi])
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
    if a.json:
        Path(a.json).write_text(json.dumps({"rows": rows, "overlap": overlap, "drift": drift,
                                            "missing": missing}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
