"""a8：并排审查页的数据——两书同字的原字块 / 归一 64² 图 / 四庫库归一图，外加失败例与仿真例。
输出 JSON（图全是 base64 PNG），供 review_page.html 内嵌。
  python a8_review_data.py <qtw_human.pkl> <vol03.pkl> <rm_qtw_human.jsonl> <out.json>
"""
from __future__ import annotations

import base64
import collections
import json
import os
import pickle
import random
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from a4_rematch import _sim, _thicken, _med  # noqa: E402

CHARS = ["之", "以", "於", "爲", "王", "其", "而", "人", "有", "天", "無", "心", "神", "三", "大", "令"]


def b64(img: np.ndarray, size: int = 88) -> str:
    h, w = img.shape
    f = size / max(h, w)
    im = cv2.resize(img, (max(1, round(w * f)), max(1, round(h * f))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", im)
    return base64.b64encode(buf.tobytes()).decode()


def norm_vis(n: np.ndarray) -> np.ndarray:
    return cv2.resize(((1 - (n > 0)) * 255).astype(np.uint8), (88, 88), interpolation=cv2.INTER_NEAREST)


def main():
    from open_guji_cv.clustering.normalize import normalize_patch as N
    from open_guji_cv.clustering.seeding import _unpng
    hp, vp, rmp, out = sys.argv[1:5]
    H = pickle.load(open(hp, "rb")); Vv = pickle.load(open(vp, "rb"))
    rm = {json.loads(l)["id"]: json.loads(l) for l in open(rmp, encoding="utf-8")}
    rnd = random.Random(0)
    c = sqlite3.connect(os.environ["GUJI_GLYPH_DB"])
    lib = collections.defaultdict(list)
    for ch, d in c.execute("""SELECT g.char, d.data FROM exemplars e JOIN glyphs g ON g.glyph_id=e.glyph_id
                              JOIN derived d ON d.instance_id=e.instance_id AND d.kind='norm'"""):
        lib[ch].append(d)

    def libn(ch, k=2):
        xs = lib.get(ch, [])[:]
        rnd.shuffle(xs)
        return [b64(norm_vis(_unpng(d))) for d in xs[:k]]

    def cell(r, extra=None):
        n = N(r["img"])
        d = {"id": r["id"], "raw": b64(r["img"]), "norm": b64(norm_vis(n)), "ink": round(float(n.mean()), 3)}
        x = rm.get(r["id"])
        if x:
            d["top"] = x["base"]["top"]; d["cov"] = x["base"]["cov"]; d["rank"] = x["base"]["rank"]
        if extra:
            d.update(extra)
        return d

    byq = collections.defaultdict(list); byv = collections.defaultdict(list)
    for r in H:
        byq[r["truth"]].append(r)
    for r in Vv:
        byv[r["truth"]].append(r)
    pairs = []
    for ch in CHARS:
        q = byq.get(ch, [])[:]; v = byv.get(ch, [])[:]
        if not q or not v:
            continue
        rnd.shuffle(q); rnd.shuffle(v)
        pairs.append({"char": ch, "n_qtw": len(byq[ch]), "n_vol03": len(byv[ch]),
                      "qtw": [cell(r) for r in q[:4]], "vol03": [cell(r) for r in v[:4]], "lib": libn(ch, 3)})
    # 失败例：人裁字 ≠ 四庫库首选，按 (真值, 库首选) 对取最常见的 12 对
    cnt = collections.Counter()
    ex = {}
    for r in H:
        x = rm.get(r["id"])
        if not x or x["base"]["rank"] == 1 or not x["base"]["top"]:
            continue
        k = (r["truth"], x["base"]["top"]); cnt[k] += 1; ex.setdefault(k, r)
    fails = []
    for (t, top), n in cnt.most_common(12):
        r = ex[(t, top)]
        fails.append({"truth": t, "top": top, "n": n, "cell": cell(r), "lib_truth": libn(t, 1), "lib_top": libn(top, 1)})
    # 仿真：vol03 同一字块 base / 削细 / 全套
    sims = []
    for r in rnd.sample(Vv, 6):
        sims.append({"char": r["truth"], "raw": b64(r["img"]), "base": b64(norm_vis(N(r["img"]))),
                     "thin": b64(norm_vis(N(_sim(r["img"], 3, 0.0)))), "all": b64(norm_vis(N(_sim(r["img"], 3, 0.25))))})
    # 全唐文加粗：同一字块 base / 加粗 2px
    thick = []
    for r in rnd.sample(H, 6):
        thick.append({"char": r["truth"], "raw": b64(r["img"]), "base": b64(norm_vis(N(r["img"]))),
                      "thick": b64(norm_vis(N(_thicken(_med(r["img"]), 2)))), "lib": (libn(r["truth"], 1) or [None])[0]})
    json.dump({"pairs": pairs, "fails": fails, "sims": sims, "thick": thick}, open(out, "w"), ensure_ascii=False)
    print(len(pairs), len(fails), os.path.getsize(out))


if __name__ == "__main__":
    main()
