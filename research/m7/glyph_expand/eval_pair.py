"""字形判法扩面（2026-10-22）：数据集人裁 + 字块图 → 整字 HOG／像素岭回归，按册留出评测。

用法：python eval_pair.py <dataset char-groups 根> 衛衞|刪删|扺抵 [--scan]
标签来自 `labels/unified.jsonl` 里 kind=shape、status=ok、form 属于该对的行；字块图用 `variant/*/crops/<id 的 : 换 _>.png`。
"""
from __future__ import annotations

import glob
import itertools
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from open_guji_cv.groups import ids_whole


def load(root: Path, chars: str):
    crops = {}
    for f in glob.glob(str(root / "variant" / "*" / "crops" / "*.png")) + glob.glob(str(root / "review" / "**" / "*.png"), recursive=True):
        crops.setdefault(Path(f).stem, f)
    cells = []
    for line in open(root / "labels" / "unified.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r["kind"] != "shape" or r["status"] != "ok" or r.get("form") not in set(chars):
            continue
        p = crops.get(r["id"].replace(":", "_"))
        if p is None:
            continue
        g = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        if g is not None:
            cells.append((r["form"], g, r["book"], r["id"]))
    return cells


def loo(cells, kind, region, lam, size):
    """按册留出：判某册的格时，模板库不含该册（每册只拟合一次）。"""
    from open_guji_cv.groups import ids_online as O
    d = ids_whole.build("x", cells, size)
    tpl = {k: [O._dec(s, size) for s in v] for k, v in d["templates"].items()}
    books, keys = d["source"]["books"], d["source"]["keys"]
    names = sorted(tpl)
    res = []   # (真字, 预测, margin, key)
    for bk in sorted({b for v in books.values() for b in v}):
        sub = {n: [t for j, t in enumerate(tpl[n]) if books[n][j] != bk] for n in names}
        for f in names:
            for i, x in enumerate(tpl[f]):
                if books[f][i] != bk:
                    continue
                ch, m, _ = ids_whole.score_norm(x, sub, kind, region, lam)
                res.append((f, ch, m, keys[f][i]))
    return res


def summarize(res):
    """0 错门槛与覆盖：每类的 对/错 数。"""
    wrongs = sorted((m for f, ch, m, _ in res if ch != f), reverse=True)
    thr = (wrongs[0] + 1e-6) if wrongs else 0.0
    ok = sum(1 for f, ch, m, _ in res if ch == f and m >= thr)
    per = {}
    for f, ch, m, _ in res:
        if ch == f and m >= thr:
            per[f] = per.get(f, 0) + 1
    return thr, ok, len(res), per, wrongs[:5]


if __name__ == "__main__":
    root, chars = Path(sys.argv[1]), sys.argv[2]
    cells = load(root, chars)
    from collections import Counter
    print("cells", Counter(c[0] for c in cells), Counter((c[0], c[2]) for c in cells))
    grid = itertools.product(("hog", "pix"), (32, 48), (0.3, 1.0, 3.0), ((0, 1, 0, 1),))
    out = []
    for kind, size, lam, region in grid:
        res = loo(cells, kind, region, lam, size)
        thr, ok, n, per, w = summarize(res)
        out.append((ok, kind, size, lam, thr, per, w))
        print(kind, size, lam, "0错门槛%.2f 覆盖 %d/%d" % (thr, ok, n), per, [round(x, 2) for x in w])
