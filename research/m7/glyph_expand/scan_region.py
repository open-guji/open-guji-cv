"""字形判法扩面：对一对字扫整字／取框 HOG 的参数，按册留出，报「0 错覆盖」。

用法：python scan_region.py <dataset char-groups 根> 衛衞 [size,size…]
区域取 0.25 网格上宽高 ≥0.5 的子框；只看覆盖 ≥ 次形一半的组合时要留意：次形样本极少，覆盖几乎全是主形。
"""
import itertools
import sys
from pathlib import Path

from eval_pair import load, loo, summarize

if __name__ == "__main__":
    root, chars = Path(sys.argv[1]), sys.argv[2]
    sizes = [int(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else [48]
    cells = load(root, chars)
    g = (0.0, 0.25, 0.5)
    h = (0.5, 0.75, 1.0)
    regions = [(x0, x1, y0, y1) for x0, x1 in itertools.product(g, h) for y0, y1 in itertools.product(g, h)
               if x1 - x0 >= 0.5 and y1 - y0 >= 0.5]
    rows = []
    for size in sizes:
        for region in regions:
            for lam in (0.3, 1.0, 3.0):
                res = loo(cells, "hog", region, lam, size)
                thr, ok, n, per, w = summarize(res)
                rows.append((ok, per.get(chars[1], 0), size, region, lam, round(thr, 2), per))
    rows.sort(key=lambda r: (-r[0]))
    for r in rows[:12]:
        print(r)
