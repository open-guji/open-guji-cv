"""按刻形拆判的异体对（2026-10-24，sheldon「尙尚、盖蓋葢…按 IDS 拆判」）：产物里已放行格（放行字当标签）＋人裁 → 整字 HOG 模板库，按册留出评测。

用法：python build_shape_pair.py <组 id> <原图根（<册>/<页>.png）> <数据目录（含 output/glyph_store，取人裁）> <产物根…> [--write] [--char-patch]
      [--dataset=<dataset>/char-groups/variant --by=claude-<线程> --date=YYYY-MM-DD]（训练集落 dataset）
产物根下是 `<册>/seed_admit/p*.json` 与 `<册>/cell_shrink/p*.json`（`guji products pack fetch` 的布局）。

标签：已放行格的放行字（人裁格与印章通道不收），每册每字最多 `PER_VOL` 格；人裁刻形；`EXTRA` 是看图补的格（如送审格里的 盖）。
放行字是跟整理本或台账走的，混着码位错的格：先做一轮按册留出，与标签不一致的格逐格看过图（`DROP` 里的是看图确认标签错或看不清的），
不进模板，再按册留出评一遍，0 错门槛 ×1.1 进 `ids_online.SPECS`。
`--char-patch`：字块改用线上同款 char_patch（工作区 GUJI_WORKSPACE 要有该册产物与原图；kou 起用，早先的组是原图按框裁）。
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
#: 组 → 放行格每字总共最多收几格（人裁与看图补的格不限）：口框族 國圖固 放行格多、64×64 模板大，不封顶模板库 4MB
CAP = {"kou": 30}
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
    # 凖／準（长尾异体对，2026-10-24）：左旁 冫（点＋一长提斜穿）对 氵（三笔竖排）。放行成 準、刻形是 冫 的 2 格剔出（vol20:100:1:6 是送审格本身），
    # vol17:92:1:8 中间一笔看不清，剔出。
    "zhun": ("凖準", {}, {"vol05:177:6:17", "vol20:100:1:6", "vol17:92:1:8"}),
    # 宻／密：中部 㐅 交叉（无点）对 必（两侧带点）。放行成 密、刻形是 㐅 的 2 格（vol17:139:4:15、vol17:70:4:21）剔出，vol20:104:3:6 墨团看不清剔出。
    "mi": ("宻密", {}, {"vol17:139:4:15", "vol17:70:4:21", "vol20:104:3:6"}),
    # 口框族 國圖圍園固圓圜（形近不同义，框内部件不同）；圃 圈 囿 进库当陪衬。團 殿本没有放行格，不进库。
    # 首轮按册留出与标签不一致的格看图：vol12:41:9:14 放行 圃、刻形是 園（标签错）；vol19:65:2:12、vol13:223:6:21、vol11:86:2:21、
    # vol20:224:1:21 字块切坏（连进邻字或缺半边）。其余不一致的是真判错（圜↔園、圓↔圖），留着定门槛。
    "kou": ("國圖圍園固圓圜圃圈囿", {}, {"vol12:41:9:14", "vol19:65:2:12", "vol13:223:6:21", "vol11:86:2:21", "vol20:224:1:21"}),
    # 撰／𢰅（3–4 格异体对，2026-10-24）：撰 ⿰扌巽（巳巳 下 共：两短竖＋小八）对 𢰅 ⿰扌㢲（巳巳 下 丌，殿本刻作长撇长捺大开）。
    # 𢰅 放行 33 格（vol19–20 为主）。用首轮库把 vol04–20 全部 1,633 格 撰／𢰅 判一遍，放行成 撰、判成 𢰅 的格逐格看图：22 格刻形是 𢰅
    # （vol05 p128–150 一批「某某撰」、vol17:83:8:7、vol19:100:2:6、vol19:107:3:6，后者是按册留出唯一的错例），改标 𢰅 补进；
    # vol08:5:4:6 下部看不清，剔出；印章格、人裁格各 1 与 vol16:65:8:7（0.09）是 撰，不动。
    "zhuan": ("撰𢰅", dict.fromkeys([
        "vol05:128:2:7", "vol05:128:8:7", "vol05:130:4:6", "vol05:133:2:6", "vol05:134:1:7", "vol05:134:9:7", "vol05:135:6:7",
        "vol05:135:9:7", "vol05:136:6:7", "vol05:138:9:7", "vol05:139:5:7", "vol05:140:1:6", "vol05:141:1:7", "vol05:142:1:7",
        "vol05:143:1:7", "vol05:144:1:7", "vol05:144:8:7", "vol05:146:3:7", "vol05:150:1:7", "vol17:83:8:7", "vol19:100:2:6",
        "vol19:107:3:6",
    ], "𢰅"), {"vol08:5:4:6"}),
}


#: 剔出模板的格里看图有结论的（只进数据集当记录，不进模板）：组 → {格: (刻形, 说明)}
LOOKED = {
    "zhun": {"vol05:177:6:17": ("凖", "放行成 準，刻形左旁是 冫"), "vol20:100:1:6": ("凖", "放行成 準（文意通道），刻形左旁是 冫；整理本作 凖")},
    "mi": {"vol17:139:4:15": ("宻", "放行成 密，中部是 㐅 交叉、无点"), "vol17:70:4:21": ("宻", "放行成 密，中部是 㐅 交叉、无点"),
           "vol20:104:3:6": ("宻", "放行成 密，墨重，中部偏 㐅；不进模板")},
}


def export(g: str, cells, data: Path, out: Path, by: str, date: str):
    """训练集落 dataset `char-groups/variant/<组>/`：labels.jsonl（一格一行）、crops/（建库用的清洗后字块）、split.json（按册分折）。"""
    human = {k for k, f in freq.human_shapes(data).items() if f in PLAN[g][0]}
    d = out / g
    (d / "crops").mkdir(parents=True, exist_ok=True)
    rows, split = [], {}
    for f, gray, b, k in sorted(cells, key=lambda c: c[3]):
        cv2.imwrite(str(d / "crops" / (k.replace(":", "_") + ".png")), np.asarray(gray))
        src = "human" if k in human else ("look" if k in PLAN[g][1] else "admit")
        rows.append({"id": k, "form": f, "by": {"human": "sheldon", "look": by, "admit": "auto-admit"}[src], "date": date,
                     "src": {"human": "central:人裁刻形", "look": "看图补", "admit": "已放行格（放行字当标签）"}[src], "in_bank": True})
        split.setdefault(b, []).append(k)
    for k, (f, note) in sorted(LOOKED.get(g, {}).items()):
        rows.append({"id": k, "form": f, "by": by, "date": date, "src": "看图（剔出模板的格）", "note": note, "in_bank": False})
    with open(d / "labels.jsonl", "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    (d / "split.json").write_text(json.dumps({b: sorted(v) for b, v in sorted(split.items())}, ensure_ascii=False, indent=1) + "\n",
                                  encoding="utf-8")
    print("数据集", d, len(rows), "行")


def _page(imgs: Path, book: str, page: int, _c={}):
    k = (book, page)
    if k not in _c:
        _c.clear()
        _c[k] = cv2.imread(str(imgs / book / f"{page}.png"), cv2.IMREAD_GRAYSCALE)
    return _c[k]


def char_patch_fn():
    """线上同款字块（`ctx.image("char_patch")`，列图＋折线缝）：要工作区（GUJI_WORKSPACE）里有该册产物与原图。→ fn(册, 格 id)。"""
    from open_guji_cv import steps as _s  # noqa: F401
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.step import RunContext
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore
    cache, ctxs = ImageCache(), {}

    def fn(book: str, cid: str):
        _, p, c, s = cid.split(":")
        sub = s[-1] if s[-1] in "ab" else ""
        if book not in ctxs:
            ctxs[book] = RunContext(load_book(book), ProductStore(), cache, log=lambda _: None)
        try:
            return ctxs[book].image("char_patch", f"p{int(p):04d}c{int(c):02d}s{s.rstrip('ab')}{sub}")
        except Exception:   # noqa: BLE001 —— 再生不出的格不进库
            return None
    return fn


def gather(prods, imgs: Path, data: Path, chars: str, extra: dict, drop: set, group: str = "", patch_fn=None):
    """`patch_fn(册, 格 id)` 给了就用它取字块（线上同款 char_patch，见 `char_patch_fn`），否则按 cell_shrink 框从原图裁。"""
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
    cap = CAP.get(group)
    if cap:
        byc: dict = {}
        for k, (f, _) in sorted(want.items()):
            byc.setdefault(f, []).append(k)
        for f, ks in byc.items():
            if len(ks) > cap:
                for k in set(ks) - set(random.sample(ks, cap)):
                    del want[k]
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
            if k not in box:
                continue
            g = patch_fn(b, k) if patch_fn is not None else crop_patch(img, tuple(box[k]))
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
    prods = [a for a in sys.argv[4:] if not a.startswith("--")]
    chars, extra, drop = PLAN[g]
    sp = O.SPECS[g]
    cells = gather(prods, imgs, data, chars, extra, drop, g, char_patch_fn() if "--char-patch" in sys.argv else None)
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
    ds = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--dataset=")), None)
    if ds:                                            # --dataset=<dataset>/char-groups/variant --by=claude-<线程> --date=YYYY-MM-DD
        kv = dict(a[2:].split("=", 1) for a in sys.argv if a.startswith("--") and "=" in a)
        export(g, cells, data, Path(ds), kv.get("by", "claude"), kv.get("date", ""))
