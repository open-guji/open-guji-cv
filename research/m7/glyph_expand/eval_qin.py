"""禽會俞命舍 一簇：一对多整字 HOG／像素岭回归，按册留出。标签＝产物 seed_admit 放行字（无疑问）＋禽的预填（待 sheldon 看图确认）。"""
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from open_guji_cv.groups import ids_online as O, ids_whole

OVERRIDE = {"vol09:265:6:12": "禽", "vol10:19:5:4": "俞"}   # 看图预填，sheldon 10-22 在确认页确认（dataset variant/glyph_expand_1022；54:8:4 他改成「其他」，不进库）
CAP = 60


def labels(pool, d):
    out = []
    rng = np.random.default_rng(0)
    for r in pool:
        if r["char"] == "含" and r["id"] not in OVERRIDE:
            continue   # 含 与 舍 在放行里混了，标签不可靠，不进库
        f = OVERRIDE.get(r["id"]) or (r["char"] if r["admit"] and (not r["doubts"] or r["char"] == "禽") else None)
        if f is None:
            continue
        g = cv2.imread(str(d / (r["id"].replace(":", "_") + ".png")), cv2.IMREAD_GRAYSCALE)
        if g is not None:
            out.append((f, g, r["book"], r["id"]))
    byf = {}
    for c in out:
        byf.setdefault(c[0], []).append(c)
    res = []
    for f, cs in byf.items():
        if len(cs) > CAP:
            idx = rng.choice(len(cs), CAP, replace=False)
            cs = [cs[i] for i in sorted(idx)]
        res += cs
    return res


def loo(cells, kind, region, lam, size):
    d = ids_whole.build("x", cells, size)
    tpl = {k: [O._dec(s, size) for s in v] for k, v in d["templates"].items()}
    books, keys = d["source"]["books"], d["source"]["keys"]
    names = sorted(tpl)
    res = []
    for bk in sorted({b for v in books.values() for b in v}):
        sub = {n: [t for j, t in enumerate(tpl[n]) if books[n][j] != bk] for n in names}
        for f in names:
            for i, x in enumerate(tpl[f]):
                if books[f][i] == bk:
                    ch, m, _ = ids_whole.score_norm(x, sub, kind, region, lam)
                    res.append((f, ch, m, keys[f][i]))
    return res


if __name__ == "__main__":
    pool = json.load(open(sys.argv[1]))
    d = Path(sys.argv[1]).with_suffix(".d")
    cells = labels(pool, d)
    print(Counter(c[0] for c in cells))
    for kind, size, lam in [(k, s, l) for k in ("hog",) for s in (48,) for l in (0.1, 0.3, 1.0)]:
        res = loo(cells, kind, (0, 1, 0, 1), lam, size)
        wr = sorted((m for f, ch, m, _ in res if ch != f and (f in "禽會俞命舍" or ch in "禽會俞命舍")), reverse=True)
        thr = wr[0] + 1e-6 if wr else 0
        ok = Counter(f for f, ch, m, _ in res if ch == f and m >= thr)
        tot = Counter(f for f, *_ in res)
        if (kind, size, lam) == ("hog", 48, 0.3):
            print(sorted([(round(m, 2), f, ch, k) for f, ch, m, k in res if ch != f], reverse=True)[:14])
        print(kind, size, lam, "thr %.2f" % thr, {f: f"{ok[f]}/{tot[f]}" for f in tot if f in "禽會俞命舍"}, "wrong>=0.5:", sum(1 for w in wr if w >= .5))

    # 取定参数后在多个门槛上数对／弃／错
    res = loo(cells, "hog", (0, 1, 0, 1), 0.3, 48)
    for thr in (0.3, 0.5, 0.7, 1.0):
        r = Counter(); 
        for f, ch, m, k in res:
            if f not in "禽會俞命舍":
                continue
            r["对" if ch == f and m >= thr else "弃" if m < thr or ch is None else "错"] += 1
        print(thr, dict(r))
