"""广宀族 廣實賔賓宸（2026-10-24，A24「强化广宀族形近判别」）：整字 HOG 一对多模板库，按册留出评测。

送审的 17 格（vol13、vol19）几乎全是「蕤賔」的 賔：字形库里没有 賔，库把它排成 實、廣、墳、須。
只许给 賔／賓（`IdsSpec.give`）——實、廣 库本来就认得，留出里判 實／廣 的错放（竇→實、寳→實、贋→廣）在 0.56 以上才清干净，不值得；
賔／賓 两形刻法分得开（宀下 丏 ／ 少），是同一字的两形，按刻形各给各的码位。

用法：python build_guang.py <原图根（<册>/<页>.png）> <数据目录（含人裁，如 ~/.guji-data/main/siku-zongmu）> <产物根…> [--write]
产物根下是 `<册>/seed_admit/p*.json` 与 `<册>/cell_shrink/p*.json`（`guji products pack fetch` 的布局）。

模板（按 `build_shape_pair.gather` 取：已放行格的放行字当标签＋人裁刻形＋看图补的格）：
- 成员 廣實賔賓宸，陪衬 `NEG`（库里常排在成员旁边的字，各自一类），每册每字至多 `PER_VOL` 格；賔／賓 全收；
- 「〇」其他池：`POOL` 里的字每册至多 `PER_POOL` 格合成一类，判成它＝弃权（开集：没见过的字别被硬判成 賔／賓）；
- `LOOK`：vol13、vol19 送审格看图补标（刻形清楚的 賔 15 格、賓 1 格）；`DROP`：看图刻形存疑或字块残缺的格。
模板库须 <1MB（size 32）。
"""
from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

import build_shape_pair as B
from open_guji_cv.groups import ids_online as O

G = "guang"
MEMBERS = "廣實賔賓宸"
GIVE = "賔賓"
NEG = "寶寳寅賞墳須煩裒盧資質贋寫竇賁責貴"
POOL = "痕黃度貫賢贊買簣虞竄廢庚庋慶康嚴廬價辰牘燬頁鹿富員屬庫篇增續竊寘賨賸擯"
PER_VOL, PER_POOL = 3, 3
LOOK = {**dict.fromkeys(("vol13:58:3:9 vol19:82:8:8 vol19:83:5:6 vol19:83:7:10 vol19:84:7:5 vol19:85:7:18 vol19:95:1:21 "
                         "vol19:96:7:13 vol19:110:2:15 vol19:115:9:19 vol19:120:9:15 vol19:121:3:10 vol19:121:4:17 "
                         "vol19:121:6:4 vol19:122:1:12").split(), "賔"),
        "vol19:37:3:4": "賓"}
# 放行成 賔 但刻形像 賓 或看不清（5 格）；寶 字块下半裁掉（vol20:185:2:3）；送审格里字块残缺或连进邻字（2 格）。
# vol19:84:7:5 刻 賔、产物里被文意通道放成 廣（错放），LOOK 按刻形标 賔。
DROP = {"vol17:6:2:16", "vol14:43:6:4", "vol05:103:2:15", "vol16:131:2:6", "vol16:131:2:9", "vol20:185:2:3",
        "vol19:143:9:7", "vol19:96:7:15"}


def cells_of(prods, imgs: Path, data: Path):
    a = B.gather(prods, imgs, data, MEMBERS + NEG, LOOK, DROP)
    keep, B.PER_VOL = B.PER_VOL, PER_POOL
    try:
        b = B.gather(prods, imgs, Path("/nonexistent"), POOL, {}, DROP)
    finally:
        B.PER_VOL = keep
    random.seed(0)
    per: Counter = Counter()
    out = []
    for f, g, book, k in a + [("〇", *x[1:]) for x in b]:
        if f in GIVE or k in LOOK:
            out.append((f, g, book, k))
        elif per[(book, f)] < (PER_POOL if f == "〇" else PER_VOL):
            per[(book, f)] += 1
            out.append((f, g, book, k))
    return out


if __name__ == "__main__":
    imgs, data = Path(sys.argv[1]), Path(sys.argv[2])
    prods = [a for a in sys.argv[3:] if a != "--write"]
    sp = O.SPECS[G]
    cells = cells_of(prods, imgs, data)
    print(G, "cells", len(cells), Counter(c[0] for c in cells), "册", len({c[2] for c in cells}))
    res = B.loo(cells, sp)
    wrong = sorted(((m, f, ch, k) for f, ch, m, k in res if ch and ch in GIVE and ch != f), reverse=True)
    for t in sorted({0.2, 0.3, 0.4, 0.5, sp.min_margin}):
        give = [r for r in res if r[1] and r[1] in GIVE and r[2] >= t]
        print(f"  门槛 {t:.2f}: 给字 {len(give)}，错 {sum(1 for r in give if r[1] != r[0])}",
              dict(Counter(r[0] for r in give if r[1] == r[0])), "／", dict(Counter(r[0] for r in res if r[0] in GIVE)))
    print("  给 賔／賓 的错例（不设门槛）", [(k, f, "→", ch, round(m, 3)) for m, f, ch, k in wrong[:10]])
    if "--write" in sys.argv:
        d = B.ids_whole.build(G, cells, sp.size, {
            "labels": f"殿本已放行格（成员与陪衬每册每字 ≤{PER_VOL}，賔賓 全收，放行字当标签，去掉看图存疑的格）＋人裁刻形"
                      f"＋送审格看图补标 {len(LOOK)}＋「〇」其他池（每册每字 ≤{PER_POOL}）"})
        p = Path(__file__).resolve().parents[3] / "config" / "groups" / G / "ids_bank.json"
        O.write_bank(d, p)
        print("写", p, p.stat().st_size)
