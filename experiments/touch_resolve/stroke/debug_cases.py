# -*- coding: utf-8 -*-
"""对指定金标 id 跑一遍笔画级归属，出六联调试图（原图 | U-Net raw | U-Net 多数票 | 笔画级 | 金标 | 决策单元）。

    .venv/Scripts/python experiments/touch_resolve/stroke/debug_cases.py vol01:6:2:13 vol01:8:9:11 ...
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_stroke import (STROKE_OUT, UNetV2, cc_vote, err_stats, owner_from_seam,  # noqa: E402
                           raw_owner_from_pred, sheet)
from stroke_partition import draw_units, stroke_partition  # noqa: E402
from common import INK_TH, Loader, seam_chosen, seam_gold, window  # noqa: E402


def main() -> int:
    ids = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = STROKE_OUT / "debug"; out.mkdir(parents=True, exist_ok=True)
    L = Loader(); net = UNetV2()
    want = set(ids)
    items = [it for it in L.gold_items() if it.id in want]
    print(f"找到 {len(items)}/{len(ids)} 条")
    for it in items:
        case, why = L.resolve(it)
        if case is None:
            print(it.id, "resolve 失败:", why); continue
        img = L.image_of(case)
        win, y0, _ = window(case, img)
        W = (win < INK_TH).astype(np.uint8)
        pred = net.predict(win)
        raw = raw_owner_from_pred(pred, W)
        voted = cc_vote(raw, W)
        votes = (pred * W).astype(np.uint8)
        t0 = time.time(); res = stroke_partition(win, votes); dt = time.time() - t0
        og = owner_from_seam(W, seam_gold(case) - y0); oc = owner_from_seam(W, seam_chosen(case) - y0)
        e = {k: err_stats(o, og) for k, o in (("raw", raw), ("voted", voted), ("stroke", res.owner), ("chosen", oc))}
        title = (f"{case.id} {case.char_above}/{case.char_below} {case.verdict}  err px(blob): raw {e['raw'][0]}({e['raw'][1]}) "
                 f"voted {e['voted'][0]}({e['voted'][1]}) stroke {e['stroke'][0]}({e['stroke'][1]}) chosen {e['chosen'][0]}({e['chosen'][1]})"
                 f"  seg {len(res.segments)} pairs {res.n_pairs} chains {res.n_chains} splits {res.n_splits} {dt*1000:.0f}ms")
        print(title)
        sh = sheet(win, [("U-Net raw", raw), ("U-Net 多数票", voted), ("笔画级", res.owner), ("金标", og)], title,
                   extra=[draw_units(win, res, 2)])
        cv2.imwrite(str(out / (case.id.replace(":", "_") + ".png")), sh)
        big = np.concatenate([cv2.resize(cv2.cvtColor(win, cv2.COLOR_GRAY2BGR), None, fx=5, fy=5, interpolation=cv2.INTER_NEAREST),
                              draw_units(win, res, 5)], axis=1)
        cv2.imwrite(str(out / (case.id.replace(":", "_") + "_units.png")), big)
        # 最大错块周围 10× 放大：笔画级 owner（错处描白边） | 金标 | 决策单元+延伸种子
        m = (og > 0) & (res.owner > 0) & (res.owner != og)
        if m.any():
            k, lab, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
            j = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
            x, y, bw, bh = st[j, cv2.CC_STAT_LEFT], st[j, cv2.CC_STAT_TOP], st[j, cv2.CC_STAT_WIDTH], st[j, cv2.CC_STAT_HEIGHT]
            y0c, y1c = max(0, y - 14), min(win.shape[0], y + bh + 14); x0c, x1c = max(0, x - 14), min(win.shape[1], x + bw + 14)
            S = 10
            from common_stroke import tint
            a = tint(win[y0c:y1c, x0c:x1c], res.owner[y0c:y1c, x0c:x1c]); a[(lab == j)[y0c:y1c, x0c:x1c]] = (255, 255, 255)
            b = tint(win[y0c:y1c, x0c:x1c], og[y0c:y1c, x0c:x1c])
            c = tint(win[y0c:y1c, x0c:x1c], votes[y0c:y1c, x0c:x1c])
            a, b, c = [cv2.resize(t, None, fx=S, fy=S, interpolation=cv2.INTER_NEAREST) for t in (a, b, c)]
            u = draw_units(win[y0c:y1c, x0c:x1c], type(res)(res.owner, res.skeleton[y0c:y1c, x0c:x1c], res.zone[y0c:y1c, x0c:x1c],
                                                          res.seed_label[y0c:y1c, x0c:x1c], res.unit_label, res.segments), S)
            gap = np.full((a.shape[0], 8, 3), 255, np.uint8)
            cv2.imwrite(str(out / (case.id.replace(":", "_") + "_zoom.png")), np.concatenate([a, gap, b, gap, c, gap, u], axis=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
