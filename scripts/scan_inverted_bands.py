"""扫一册书，找可能的反色带（Step0 预清理的候选页）。

**这是辅助工具，不是自动化**：它给候选，人工看图确认，再把位置写进
`open_guji_cv/books/<book>.yaml` 的 `preclean:` 段。位置是参数，不猜。

判据
----
竖排页里列与列之间有贯通的空白窄条（栏线之间的纸）。正常页这些列几乎全白；
反色带经过时它们成段变黑。

坑：不能用「整页墨占比低」来找纸列 —— 被带穿过的列正因为带而变黑，会被排除掉
（循环论证，实测就是这么漏掉 p151 的）。改成先按行墨量挑出**干净行**
（多数行都是干净的），只在干净行上判定哪些列是纸列。

误报：职名页/目录页整列重复同一个字（vol01 p113 的「翰」、p117 的「編」）
会让纸列判定失真。所以默认只报**正文区**（y 在 --body 范围内）的命中，
上下版框那一带的命中一律忽略。

用法
----
    python scripts/scan_inverted_bands.py data_full/zongmu/vol02
    python scripts/scan_inverted_bands.py data_full/zongmu/vol01 --all
"""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image


def find_bands(path, min_rows=8, frac=0.20, min_paper=40, ink=128):
    g = np.array(Image.open(path).convert("L"))
    b = g < ink
    h, w = b.shape

    rowink = b.mean(axis=1)
    clean = rowink < np.median(rowink) * 1.5
    if clean.sum() < h * 0.3:
        return []
    paper = b[clean].mean(axis=0) < 0.02
    if paper.sum() < min_paper:
        return []

    rows = b[:, paper].mean(axis=1)
    hot = np.flatnonzero(rows > frac)
    if len(hot) < min_rows:
        return []
    brk = np.flatnonzero(np.diff(hot) > 8)
    segs = [s for s in np.split(hot, brk + 1) if len(s) >= min_rows]
    return [(int(s[0]), int(s[-1]), round(float(rows[s].mean()), 3)) for s in segs]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", help="原图目录，如 data_full/zongmu/vol02")
    ap.add_argument("--body", default="450,2600",
                    help="正文区 y 范围；这之外的命中当作上下版框忽略")
    ap.add_argument("--all", action="store_true", help="连版框区的命中一起报")
    args = ap.parse_args()

    lo, hi = (int(v) for v in args.body.split(","))
    pages = sorted(Path(args.dir).glob("*.png"), key=lambda p: int(p.stem))
    n = 0
    for p in pages:
        segs = find_bands(str(p))
        if not args.all:
            segs = [s for s in segs if lo < s[0] < hi]
        if segs:
            n += 1
            print(f"p{int(p.stem):<4} " +
                  "  ".join(f"y{a}-{b}(墨{f})" for a, b, f in segs))
    print(f"\n{len(pages)} 页里 {n} 页有候选"
          f"{'' if args.all else '（已滤掉版框区；--all 可全看）'}")
    print("下一步：人工看图确认，再把位置写进 books/<book>.yaml 的 preclean 段")


if __name__ == "__main__":
    main()
