"""徵徴 挡门两分类（2026-10-26，A24「压低徵徴送审」）：库常把 微 排进 徵徴 的分差内，格进不了组。
组里放宽入口（`FlowSpec.ref_top_enter`：库首位与整理本都是 徵／徴），但 微 是真竞争者，先用下半框 HOG 判「微／组」两类，判成组才往下判 徵／徴。

用法：GUJI_WORKSPACE=<工作区> python build_guard.py <产物根> [--size 48] [--write]
- 微：产物里 seed_admit 已放行、无疑问、通道 match_ref 的 微（每册至多 3 格）；
- 组：`config/groups/zheng/ids_bank.json` 的人裁模板（75）＋ 产物里组流程 keep、整字判别值 ≥0.7 的已放行 徵徴（每册至多 3 格）。
- 字块：线上同款 char_patch（`RunContext.image`，工作区要有该册 books/*.yaml 与原图）。
- 评测：按册留出（判某册时模板不含该册），两向错例的最大判别值；门槛取它的 1.3 倍以上。
"""
import argparse, collections, json, random, re, sys, glob
from pathlib import Path
import numpy as np
from open_guji_cv.groups import ids_online as O, ids_whole as W

ap = argparse.ArgumentParser()
ap.add_argument("root"); ap.add_argument("--size", type=int, default=48); ap.add_argument("--lam", type=float, default=3.0)
ap.add_argument("--region", default="0.25,0.75,0.3,1.0"); ap.add_argument("--per-vol", type=int, default=3)
ap.add_argument("--write", action="store_true")
a = ap.parse_args()
REG = tuple(float(x) for x in a.region.split(","))
root = Path(a.root)
ROOT = Path(__file__).resolve().parents[3]

wei, grp = collections.defaultdict(list), collections.defaultdict(list)
for f in sorted(glob.glob(str(root / "vol*/seed_admit/p*.json"))):
    for col in json.load(open(f, encoding="utf-8"))["seed_admit"]["columns"]:
        for r in col["chars"]:
            if not r.get("admit") or r.get("doubts"):
                continue
            g = (r.get("evidence") or {}).get("group") or {}
            if r.get("char") == "微" and r.get("channel") == "match_ref":
                wei[r["id"].split(":")[0]].append(r["id"])
            elif r.get("char") in ("徵", "徴") and g.get("id") == "zheng" and g.get("decision") == "keep":
                ids = [t for t in g.get("solvers") or [] if t.get("solver") == "ids"]
                if ids and (ids[0].get("margin") or 0) >= 0.7:
                    grp[r["id"].split(":")[0]].append(r["id"])
random.seed(1026)
pick = lambda d: [i for v in sorted(d) for i in random.sample(d[v], min(a.per_vol, len(d[v])))]
wei_ids, grp_ids = pick(wei), pick(grp)

from open_guji_cv.core.book import load_book
from open_guji_cv.core.spec import cell_key
from open_guji_cv.core.step import RunContext
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
st, cache, ctxs = ProductStore(root), ImageCache(), {}


def patch(cid):
    v, p, c, s = cid.split(":")
    if v not in ctxs:
        ctxs[v] = RunContext(load_book(v), st, cache, log=lambda s: None)
    m = re.match(r"(-?\d+)([ab]?)", s)
    try:
        return ctxs[v].image("char_patch", cell_key(int(p), int(c), int(m.group(1))) + m.group(2))
    except Exception:          # noqa: BLE001
        return None


cells = []   # (类, 归一图, 册, 格)
for cls, ids in (("微", wei_ids), (O.GUARD_GROUP, grp_ids)):
    for i in ids:
        g = patch(i)
        x = W.norm(np.asarray(g), a.size) if g is not None else None
        if x is not None:
            cells.append((cls, x, i.split(":")[0], i))
hb = json.load(open(ROOT / "config/groups/zheng/ids_bank.json", encoding="utf-8"))
hbank = O.load_bank(ROOT / "config/groups/zheng/ids_bank.json")
for n, ts in hbank.items():
    for j, t in enumerate(ts):
        x = W.norm((255 * (1 - t)).astype(np.uint8) if t.mean() < 0.5 else (255 * t).astype(np.uint8), a.size)
        if x is not None:
            cells.append((O.GUARD_GROUP, x, hb["source"]["books"][n][j], hb["source"]["keys"][n][j]))
print({k: sum(c[0] == k for c in cells) for k in ("微", O.GUARD_GROUP)})

wrong = []
res = collections.Counter()
for v in sorted({c[2] for c in cells}):
    b = {"微": [c[1] for c in cells if c[0] == "微" and c[2] != v], O.GUARD_GROUP: [c[1] for c in cells if c[0] != "微" and c[2] != v]}
    for cls, x, vv, i in cells:
        if vv == v:
            best, m, _ = W.score_norm(x, b, "hog", REG, a.lam)
            res[(cls, best)] += 1
            if best != cls:
                wrong.append((round(m, 3), cls, best, i))
print("按册留出", dict(res))
print("错例（判别值降序）", sorted(wrong, reverse=True)[:8])
for t in (0.3, 0.4, 0.5):
    print(t, "组判对过门槛", sum(1 for cls, x, vv, i in cells if cls != "微") - sum(1 for w in wrong if w[1] != "微"),
          "错过门槛", sum(1 for w in wrong if w[0] >= t))
if a.write:
    tpl = {"微": [c[1] for c in cells if c[0] == "微"], O.GUARD_GROUP: [c[1] for c in cells if c[0] != "微"]}
    src = {"pool": "微＝产物 match_ref 已放行；组＝人裁模板＋组流程 keep 判别值≥0.7 的已放行 徵徴（线上同款 char_patch）",
           "books": {k: [c[2] for c in cells if (c[0] == "微") == (k == "微")] for k in tpl},
           "keys": {k: [c[3] for c in cells if (c[0] == "微") == (k == "微")] for k in tpl}, "cells": len(cells)}
    O.write_bank(O.dump_bank("zheng", tpl, src, size=a.size), ROOT / "config/groups/zheng/guard_bank.json")
    print("写", ROOT / "config/groups/zheng/guard_bank.json")
