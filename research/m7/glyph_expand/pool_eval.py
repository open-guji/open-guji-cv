"""用全部人裁训一个库，在产物池上看：现放行字对不对（对人裁）、新方法会给什么、会补放几格。"""
import json
import sys
from collections import Counter
from pathlib import Path

import cv2

from eval_pair import load
from open_guji_cv.groups import ids_online as O, ids_whole

CONF = {"衛衞": ("hog", 48, (0.25, 0.75, 0.5, 1.0), 1.0, 0.7), "刪删": ("hog", 48, (0.0, 0.5, 0.5, 1.0), 1.0, 0.85),
        "扺抵": ("hog", 64, (0.0, 0.75, 0.5, 1.0), 3.0, 0.55)}
root, chars, pooldir = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
kind, size, region, lam, thr = CONF[chars]
cells = load(root, chars)
d = ids_whole.build("x", cells, size)
bank = {k: [O._dec(s, size) for s in v] for k, v in d["templates"].items()}
lab = {c[3]: c[0] for c in cells}
pool = json.load(open(pooldir / f"{chars}.json"))
cnt = Counter(); show = []
for r in pool:
    g = cv2.imread(str(pooldir / f"{chars}.d" / (r["id"].replace(":", "_") + ".png")), cv2.IMREAD_GRAYSCALE)
    ch, m, _ = ids_whole.score(g, bank, kind, region, lam, size)
    out = ch if (ch and m >= thr) else None
    t = lab.get(r["id"])
    cnt[("labeled" if t else "unlabeled", "现放行" if r["admit"] else "现送审", "现字对" if t == r["char"] else ("现字错" if t else "-"),
         "新给" + ("对" if out == t else "错") if out and t else ("新给" if out else "新弃权"))] += 1
    if out and out != r["char"]:
        show.append((r["id"], r["char"], r["admit"], t, out, round(m, 2)))
for k, v in sorted(cnt.items()): print(k, v)
print("新给字≠现字:"); [print(" ", s) for s in show]
