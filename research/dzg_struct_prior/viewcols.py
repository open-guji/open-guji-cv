"""把若干列的「基线 / 约束后」Step4 字框并排画出来，人眼核对。

用法：python viewcols.py <wsBase> <wsNew> <out.png> vol:page:col [vol:page:col ...]
每列三幅：列图 + 基线字框（红）| 列图 + 约束后字框（绿）。字框用 cell_shrink 的 bbox_col。
"""
import json, sys
from pathlib import Path
import cv2
import numpy as np

base, new, out = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
specs = sys.argv[4:]
tiles = []
H = 1400


def boxes(ws, vol, page, col):
    f = ws / 'products' / vol / 'cell_shrink' / f'p{page:04d}.json'
    d = json.loads(f.read_text())['char_index']
    for c in d['columns']:
        if c['col'] == col:
            return [(r['bbox_col'], r.get('slot'), r.get('sub')) for r in c['chars'] if r['cell_type'] == 'char']
    return []


for sp in specs:
    vol, page, col = sp.split(':'); page, col = int(page), int(col)
    img = cv2.imread(str(base / 'cache' / vol / 'column_image' / f'p{page:04d}c{col:02d}.png'), 0)
    if img is None:
        continue
    pair = []
    for ws, colr in ((base, (0, 0, 255)), (new, (0, 160, 0))):
        im = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        for (x0, y0, x1, y1), slot, sub in boxes(ws, vol, page, col):
            cv2.rectangle(im, (int(x0), int(y0)), (int(x1), int(y1)), colr, 3)
            cv2.putText(im, f'{slot}{sub or ""}', (2, int(y0) + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, colr, 2)
        pair.append(im)
    t = np.hstack([pair[0], np.full((img.shape[0], 8, 3), 255, np.uint8), pair[1]])
    s = H / t.shape[0]
    t = cv2.resize(t, (int(t.shape[1] * s), H))
    cv2.putText(t, sp, (4, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 0), 2)
    tiles.append(t)
    tiles.append(np.full((H, 16, 3), 255, np.uint8))
cv2.imwrite(out, np.hstack(tiles))
print(out)
