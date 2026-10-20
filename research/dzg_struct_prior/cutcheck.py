"""格线穿字检查（不靠整理本）：两组 Step3 产物并排，数每列「横穿字的格线」，列出 B 比 A 多的列。

    python cutcheck.py <列图目录 cache/<册>/column_image> <A 的 row_segment 目录> <B 的 row_segment 目录> [--min-page 4]

判据同 `steps/row_segment._cut_rows`：字格与相邻格的分界线上下 ±2 行、列宽中间 80% 的墨占比都 ≥ 0.06 算一条。
单看绝对数噪声大（殿本 vol04 对照组就有 1,810 条：笔画粘连、字挨得紧），只看两组之差、差得多的列。

为什么要它：`structcmp.py` 只比格号集合，抬头字不在列图里、格网整体错一位时格号集合照样对得上（vol04 p84 c5），
看不出劈字；这个检查只看图，正好补上。
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

THR = 0.06


def cuts(img, col):
    h, w = img.shape
    ink = (img[:, int(w * 0.1):int(w * 0.9)] < 128).mean(axis=1)
    cs = sorted(col.get('cells') or [], key=lambda c: c['y0'])
    out = []
    for a, b in zip(cs, cs[1:]):
        if a['kind'] == 'blank' and b['kind'] == 'blank':
            continue
        if a.get('sub') and b.get('sub') and a['slot'] == b['slot']:
            continue
        y = int(round(b['y0']))
        if 2 <= y < h - 2 and ink[y - 2:y + 3].min() >= THR:
            out.append(y)
    return out


def main():
    imgdir, A, B = map(Path, sys.argv[1:4])
    minp = int(sys.argv[sys.argv.index('--min-page') + 1]) if '--min-page' in sys.argv else 1
    load = lambda d, p: {c['col']: c for c in json.load(open(d / f'p{p:04d}.json'))['cells']['columns']} \
        if (d / f'p{p:04d}.json').exists() else {}
    ta = tb = 0
    worse, better = [], 0
    for f in sorted(A.glob('p*.json')):
        p = int(f.stem[1:])
        if p < minp:
            continue
        ca, cb = load(A, p), load(B, p)
        for c in ca:
            im = cv2.imread(str(imgdir / f'p{p:04d}c{c:02d}.png'), cv2.IMREAD_GRAYSCALE)
            if im is None or c not in cb:
                continue
            na, nb = len(cuts(im, ca[c])), cuts(im, cb[c])
            ta += na
            tb += len(nb)
            if len(nb) > na:
                worse.append((p, c, na, len(nb), nb[:6]))
            elif len(nb) < na:
                better += 1
    print(f'穿字格线：A {ta}  B {tb}；B 多的列 {len(worse)}，B 少的列 {better}')
    for p, c, na, nb, ys in sorted(worse, key=lambda w: w[2] - w[3]):
        print(f'  p{p} c{c}  {na}→{nb}  y={ys}')


if __name__ == '__main__':
    main()
