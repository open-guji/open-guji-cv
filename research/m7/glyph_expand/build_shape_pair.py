"""按刻形拆判的异体对（2026-10-24，sheldon「尙尚、盖蓋葢…按 IDS 拆判」）：产物里已放行格（放行字当标签）＋人裁 → 整字 HOG 模板库，按册留出评测。

用法：python build_shape_pair.py <组 id> <原图根（<册>/<页>.png）> <数据目录（含 output/glyph_store，取人裁）> <产物根…> [--write]
产物根下是 `<册>/seed_admit/p*.json` 与 `<册>/cell_shrink/p*.json`（`guji products pack fetch` 的布局）。

标签：已放行格的放行字（人裁格与印章通道不收），每册每字最多 `PER_VOL` 格；人裁刻形；`EXTRA` 是看图补的格（如送审格里的 盖）。
放行字是跟整理本或台账走的，混着码位错的格：先做一轮按册留出，与标签不一致的格逐格看过图（`DROP` 里的是看图确认标签错或看不清的），
不进模板，再按册留出评一遍，0 错门槛 ×1.1 进 `ids_online.SPECS`。
"""
from __future__ import annotations

import glob
import json
import random
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from open_guji_cv.core.anchor import crop_patch
from open_guji_cv.groups import freq, ids_online as O, ids_whole

PER_VOL = 12      # 每册每字最多收几格（模板库 <1MB）
#: 组 → (字, 看图补的格 {id: 字}, 看图剔出的格)
PLAN = {
    # 尙／尚：上部 小（左撇外撇）对 ⺌（两点内收）。首轮按册留出与放行字不一致的 12 格看图：10 格是放行字码位错（按刻形改标签不如直接剔），
    # vol08:67:9:3（顶上压黑框）、vol14:3:9:12（印章底纹）看不清。
    "shang": ("尙尚", {}, {"vol16:48:2:12", "vol16:28:7:9", "vol13:188:8:8", "vol04:98:5:6", "vol17:72:9:19", "vol10:114:7:11",
                          "vol10:104:6:9", "vol05:115:6:7b", "vol09:116:3:11", "vol08:67:1:1", "vol08:67:9:3", "vol14:3:9:12"}),
    # 盖／蓋／葢：盖 无草头；蓋 草头下 去皿；葢 草头下 大皿（殿本多作葢）。盖 放行只 5 格，补 vol16–20 送审里看图确认是 盖 的 6 格。
    "gai": ("蓋葢", {}, {"vol16:30:2:12", "vol05:181:1:6"}),
    # 䟦／跋：右边 叐（横下作又、无点）对 犮（撇上带点）。䟦 放行少（15），补 vol11–20 送审里看图确认整理本作 䟦、刻形是 䟦 的 31 格。
    "ba": ("䟦跋", dict.fromkeys([
        "vol12:25:2:12", "vol12:92:5:21", "vol12:94:3:20", "vol12:151:8:17", "vol13:149:5:7", "vol13:152:6:20", "vol13:169:8:18",
        "vol13:185:7:17", "vol13:198:9:13", "vol13:199:7:10", "vol13:199:8:20", "vol13:225:3:11", "vol14:49:4:13", "vol15:5:3:10",
        "vol15:94:1:20", "vol15:103:3:14", "vol15:123:6:6", "vol16:128:3:10", "vol16:145:3:8", "vol17:73:5:14", "vol17:83:8:11",
        "vol17:110:3:16", "vol17:110:7:4", "vol17:110:8:20", "vol18:66:1:5", "vol19:5:6:19", "vol19:5:8:9", "vol19:5:8:20",
        "vol19:162:8:14", "vol20:98:1:15", "vol20:120:1:6",
    ], "䟦"), {"vol06:106:1:17", "vol09:239:1:18", "vol10:65:4:4", "vol14:48:8:19"}),   # 放行成 跋、刻形是 叐（无点、下作又）
}


def _page(imgs: Path, book: str, page: int, _c={}):
    k = (book, page)
    if k not in _c:
        _c.clear()
        _c[k] = cv2.imread(str(imgs / book / f"{page}.png"), cv2.IMREAD_GRAYSCALE)
    return _c[k]


def gather(prods, imgs: Path, data: Path, chars: str, extra: dict, drop: set):
    random.seed(0)
    want: dict = {}                                   # id → (字, 来源)
    per: Counter = Counter()
    for root in prods:
        for vd in sorted(glob.glob(str(Path(root) / "vol*"))):
            book = Path(vd).name
            rs = []
            for f in sorted(glob.glob(f"{vd}/seed_admit/p*.json")):
                for col in json.load(open(f, encoding="utf-8"))["seed_admit"]["columns"]:
                    rs += [r for r in col["chars"] if r.get("admit") and r.get("char") in set(chars)
                           and r.get("channel") not in ("human", "seal")]
            random.shuffle(rs)
            for r in rs:
                if per[(book, r["char"])] < PER_VOL and r["id"] not in drop:
                    per[(book, r["char"])] += 1
                    want[r["id"]] = (r["char"], r["channel"])
    for k, f in freq.human_shapes(data).items():
        if f in chars and k not in drop:
            want[k] = (f, "human")
    for k, f in extra.items():
        want[k] = (f, "look")
    cells = []
    by_page: dict = {}
    for k, v in want.items():
        b, p = k.split(":")[:2]
        by_page.setdefault((b, int(p)), []).append((k, v))
    for (b, p), ks in sorted(by_page.items()):
        sh = next((Path(r) / b / "cell_shrink" / f"p{p:04d}.json" for r in prods if (Path(r) / b / "cell_shrink" / f"p{p:04d}.json").exists()), None)
        img = _page(imgs, b, p)
        if sh is None or img is None:
            continue
        box = {c["id"]: c["bbox_page"] for col in json.load(open(sh, encoding="utf-8"))["char_index"]["columns"] for c in col["chars"]}
        for k, (f, src) in ks:
            g = crop_patch(img, tuple(box[k])) if k in box else None
            if g is not None:
                cells.append((f, ids_whole.clean_patch(g), b, k))
    return cells


def loo(cells, sp):
    d = ids_whole.build("x", cells, sp.size)
    tpl = {k: [O._dec(s, sp.size) for s in v] for k, v in d["templates"].items()}
    books, keys = d["source"]["books"], d["source"]["keys"]
    res = []
    for bk in sorted({b for v in books.values() for b in v}):
        sub = {n: [t for j, t in enumerate(tpl[n]) if books[n][j] != bk] for n in tpl}
        for f in tpl:
            for i, x in enumerate(tpl[f]):
                if books[f][i] == bk:
                    ch, m, _ = ids_whole.score_norm(x, sub, sp.whole, tuple(sp.region), sp.lam)
                    ok = len(sub.get(ch, [])) >= sp.min_class
                    res.append((f, ch if ok else None, m, keys[f][i]))
    return res


if __name__ == "__main__":
    g, imgs, data = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    prods = [a for a in sys.argv[4:] if a != "--write"]
    chars, extra, drop = PLAN[g]
    sp = O.SPECS[g]
    cells = gather(prods, imgs, data, chars, extra, drop)
    print(g, "cells", Counter(c[0] for c in cells), "册", len({c[2] for c in cells}))
    res = loo(cells, sp)
    wrong = sorted(((m, f, ch, k) for f, ch, m, k in res if ch and ch != f), reverse=True)
    thr0 = wrong[0][0] if wrong else 0.0
    for t in sorted({0.3, 0.5, sp.min_margin, round(thr0 * 1.1, 2)}):
        give = [r for r in res if r[1] and r[2] >= t]
        print(f"  门槛 {t:.2f}: 给字 {len(give)}/{len(res)}，错 {sum(1 for r in give if r[1] != r[0])}",
              dict(Counter(r[0] for r in give if r[1] == r[0])))
    print("  错例（不设门槛）", [(k, f, "→", ch, round(m, 2)) for m, f, ch, k in wrong[:10]])
    if "--write" in sys.argv:
        d = ids_whole.build(g, cells, sp.size, {"labels": f"殿本已放行格（每册每字 ≤{PER_VOL}，放行字当标签，去掉看图确认码位错的格）＋人裁刻形＋看图补的格"})
        p = Path(__file__).resolve().parents[3] / "config" / "groups" / g / "ids_bank.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        O.write_bank(d, p)
        print("写", p, p.stat().st_size)
