"""形近护栏的部首族（2026-10-24，A24「门族、辶族」）：库形在一族字里紧咬（間0.955 閩0.952 聞0.951…）、整理本字也在族里的格，
用整字 HOG 一对多判刻形，**与整理本同字才补放**（`FlowSpec.lift_ref_agree`）。

用法：python build_family.py <组 id> <原图根（<册>/<页>.png）> <产物根> [--write] [--size N] [--lam X] [--cap N]
产物根下是 `<册>/seed_admit/p*.json` 与 `<册>/cell_shrink/p*.json`（`guji products pack fetch` 的布局）。

标签：已放行格的放行字（人裁格与印章通道不收；放行时带疑问的不收），每册每字最多 `PER_VOL` 格、每字最多 `CAP` 格；
组外的常见陪衬字（`EXTRA_CLASSES`）也进库，判成它们＝弃权。先按册留出，与标签不一致的格逐格看图，
看图确认标签错或看不清的进 `DROP`，再评一遍，0 错门槛 ×1.1 进 `ids_online.SPECS`。
"""
from __future__ import annotations

import argparse
import glob
import json
import random
from collections import Counter
from pathlib import Path

import cv2

from open_guji_cv.core.anchor import crop_patch
from open_guji_cv.groups import ids_online as O, ids_whole
from open_guji_cv.groups.flow import is_provisional

PER_VOL = 4
CAP = 30
#: 组 → (进库的组员, 进库的组外陪衬字, 看图剔出的格)
PLAN = {
    "men": ("間聞問闡閱閣闢關閩閭開闌閔闇閑闕閨門閒閻閏閉", "刪删圖固同國岡剛圓冊因曲",
            set()),
    "chuo": ("通過遺適迥遇運道迫遁遣進違逋邁還遼逆遍逸遭連邇遠退逾選述近迎造遵遞追邊巡遷遜", "",
             set()),
    # 形近不同字对（2026-10-26，A24「组外异体对未定码位」）：整理本×库首位是一对形近不同字、刻形分得开的格。
    "xjz": ("冶治冐冑胄齊齋住往榮滎祇祗前翦揚楊水永孰熟窿隆嘗當勾句仝全章草壙曠卑埤可阿令冷偏徧釆采",
            "柱木未耒米朱洽蔣朝剌牘擴墳墉蹟廣編冒問目常官旬勻甸幻金有舍革尊揭場粲柴禄陸歴匪氷僅性仲周何卓阜肅亦書𤰞",
            # 已放行的 釆 全是 采 的刻形（殿本 采 上作 丿＋两点，同 釆），不进库：釆 只当入口
            {"vol03:18:1:3", "vol09:167:8:4", "vol89:150:5:17", "vol97:85:1:3"}),
}


def _page(imgs: Path, book: str, page: int, _c={}):
    k = (book, page)
    if k not in _c:
        _c.clear()
        _c[k] = cv2.imread(str(imgs / book / f"{page}.png"), cv2.IMREAD_GRAYSCALE)
    return _c[k]


def gather(prod: Path, imgs: Path, chars: str, drop: set, per_vol: int = PER_VOL, cap: int = CAP):
    random.seed(0)
    pool: dict = {}                                  # 字 → [(册, id)]
    for vd in sorted(glob.glob(str(prod / "vol*"))):
        book = Path(vd).name
        rs = []
        for f in sorted(glob.glob(f"{vd}/seed_admit/p*.json")):
            for col in json.load(open(f, encoding="utf-8"))["seed_admit"]["columns"]:
                rs += [r for r in col["chars"] if r.get("admit") and r.get("char") in set(chars) and not r.get("doubts")
                       and r.get("channel") not in ("human", "seal") and r["id"] not in drop and not is_provisional(r)]
        random.shuffle(rs)
        per: Counter = Counter()
        for r in rs:
            if per[r["char"]] < per_vol:
                per[r["char"]] += 1
                pool.setdefault(r["char"], []).append((book, r["id"]))
    want = {}
    for ch, ks in pool.items():
        random.shuffle(ks)
        for b, k in ks[:cap]:
            want[k] = ch
    cells = []
    by_page: dict = {}
    for k, f in want.items():
        b, p = k.split(":")[:2]
        by_page.setdefault((b, int(p)), []).append((k, f))
    for (b, p), ks in sorted(by_page.items()):
        sh = prod / b / "cell_shrink" / f"p{p:04d}.json"
        img = _page(imgs, b, p)
        if not sh.exists() or img is None:
            continue
        box = {c["id"]: c["bbox_page"] for col in json.load(open(sh, encoding="utf-8"))["char_index"]["columns"] for c in col["chars"]}
        for k, f in ks:
            g = crop_patch(img, tuple(box[k])) if box.get(k) else None
            if g is not None:
                cells.append((f, ids_whole.clean_patch(g), b, k))
    return cells


def loo(cells, size, lam, region=(0.0, 1.0, 0.0, 1.0), min_class=8):
    d = ids_whole.build("x", cells, size)
    tpl = {k: [O._dec(s, size) for s in v] for k, v in d["templates"].items()}
    books, keys = d["source"]["books"], d["source"]["keys"]
    res = []
    for bk in sorted({b for v in books.values() for b in v}):
        sub = {n: [t for j, t in enumerate(tpl[n]) if books[n][j] != bk] for n in tpl}
        for f in tpl:
            for i, x in enumerate(tpl[f]):
                if books[f][i] == bk:
                    ch, m, _ = ids_whole.score_norm(x, sub, "hog", region, lam)
                    ok = len(sub.get(ch, [])) >= min_class
                    res.append((f, ch if ok else None, m, keys[f][i]))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("group")
    ap.add_argument("imgs", type=Path)
    ap.add_argument("prod", type=Path)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--size", type=int, default=32)
    ap.add_argument("--lam", type=float, default=1.0)
    ap.add_argument("--cap", type=int, default=CAP)
    ap.add_argument("--per-vol", type=int, default=PER_VOL)
    ap.add_argument("--region", default="0,1,0,1", help="取框 x0,x1,y0,y1")
    ap.add_argument("--dump", type=Path, help="把错例写成 json（看图用）")
    a = ap.parse_args()
    mem, extra, drop = PLAN[a.group]
    cells = gather(a.prod, a.imgs, mem + extra, drop, a.per_vol, a.cap)
    print(a.group, "cells", len(cells), dict(Counter(c[0] for c in cells)), "册", len({c[2] for c in cells}))
    region = tuple(float(v) for v in a.region.split(","))
    res = loo(cells, a.size, a.lam, region)
    wrong = sorted(((m, f, ch, k) for f, ch, m, k in res if ch and ch != f), reverse=True)
    thr0 = wrong[0][0] if wrong else 0.0
    inmem = [r for r in res if r[0] in mem]
    for t in sorted({0.3, 0.5, 0.7, round(thr0 * 1.1, 2)}):
        give = [r for r in inmem if r[1] and r[2] >= t]
        print(f"  门槛 {t:.2f}: 组员格给字 {len(give)}/{len(inmem)}，错 {sum(1 for r in give if r[1] != r[0])}")
    print("  错例（不设门槛，前 30）", [(k, f, "→", ch, round(m, 2)) for m, f, ch, k in wrong[:30]])
    if a.dump:
        json.dump([dict(id=k, label=f, pick=ch, margin=m) for m, f, ch, k in wrong], open(a.dump, "w"), ensure_ascii=False)
    if a.write:
        d = ids_whole.build(a.group, cells, a.size, {"labels": f"殿本 vol04–20 已放行格（无疑问，每册每字 ≤{a.per_vol}、每字 ≤{a.cap}，放行字当标签，去掉看图确认标签错的格）；组外陪衬字也进库"})
        p = Path(__file__).resolve().parents[3] / "config" / "groups" / a.group / "ids_bank.json"
        O.write_bank(d, p)
        print("写", p, p.stat().st_size)
