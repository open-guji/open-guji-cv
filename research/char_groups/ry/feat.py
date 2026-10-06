"""日曰 字形特征：从 char-groups/ry/crops 灰度图抽墨迹外框宽高比等，缓存到 ry/features.json。
只读测试集，不碰管线。用法: python feat.py <dataset>/char-groups"""
import json, sys, cv2, numpy as np
from pathlib import Path

def feats(path):
    im = cv2.imread(str(path), 0)
    if im is None: return None
    h, w = im.shape
    _, b = cv2.threshold(im, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
    if n < 2: return None
    # 取面积≥最大分量 10% 的分量并集，去掉邻字残笔小碎片
    big = max(st[1:, 4]); keep = [i for i in range(1, n) if st[i, 4] >= 0.1 * big]
    x0 = min(st[i, 0] for i in keep); y0 = min(st[i, 1] for i in keep)
    x1 = max(st[i, 0] + st[i, 2] for i in keep); y1 = max(st[i, 1] + st[i, 3] for i in keep)
    m = np.isin(lab, keep)[y0:y1, x0:x1]
    iw, ih = x1 - x0, y1 - y0
    # 行/列投影：内部横笔数与墨密度
    rows = m.sum(1) / max(iw, 1)
    return dict(cw=w, ch=h, iw=int(iw), ih=int(ih), ar=iw / ih, wc=iw / w, hc=ih / h,
                dens=float(m.mean()), ncomp=len(keep), x0=x0 / w, x1=x1 / w, y0=y0 / h, y1=y1 / h,
                r_top=float(rows[:max(1, ih // 4)].mean()), r_bot=float(rows[-max(1, ih // 4):].mean()))

if __name__ == '__main__':
    root = Path(sys.argv[1]) / 'ry'
    out = {}
    for l in open(root / 'items.jsonl'):
        r = json.loads(l)
        if r['crop']:
            f = feats(root / r['crop'])
            if f: out[r['id']] = f
    json.dump(out, open(root / 'features.json', 'w'), ensure_ascii=False)
    print(len(out))
