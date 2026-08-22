"""生成版面几何数据集（page-geometry）。

金标 = 界行竖线在**三个高度**上的 x，逐页人工目视确认。

候选由「这条横带里有没有一根够长的黑竖线」这个弱判据自动给出——它**不是**
被测对象（被测的是错切估计、周期/相位拟合、将来的射影矫正），所以不构成
循环论证。人工只需在渲染图上核对「标出来的线是不是界行、有没有漏」。

金标为什么不会过期：界行位置是**图像自身**的性质，算法怎么改它都在原地。
对照 char-segmentation/instances 的 page:col:idx——那个一重跑就漂。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from open_guji_cv.clustering.page_geometry import (BAND_FRACS, PageGeometry,
                                                   RuleLine)

BAND_HALF = 0.11          # 每条采样带的半高（占页高）
COV_T = 0.45              # 带内竖直长线覆盖率阈值
MERGE = 8                 # x 相距不超过此的高覆盖列并成同一条线
MIN_WIDTH = 2             # 太细的忽略（噪声）

# 人工核对结果：{page: {"drop": [x_mid 附近要删的], "class": 页型}}
# 只记**修正**，没记的表示候选全对。改标注只改这里。
REVIEW: dict[str, dict] = {}


def band_rules(gray: np.ndarray, yc: int, half: int) -> list[tuple[float, int]]:
    y0, y1 = max(0, yc - half), min(gray.shape[0], yc + half)
    b = (gray[y0:y1] < 128).astype(np.uint8)
    h = b.shape[0]
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(3, int(h * 0.75))))
    cov = cv2.dilate(cv2.erode(b, k), k).sum(axis=0) / h
    xs = np.where(cov > COV_T)[0]
    if len(xs) == 0:
        return []
    out, s, prev = [], xs[0], xs[0]
    for x in xs[1:]:
        if x - prev > MERGE:
            out.append(((s + prev) / 2, prev - s + 1))
            s = x
        prev = x
    out.append(((s + prev) / 2, prev - s + 1))
    return [(x, w) for x, w in out if w >= MIN_WIDTH]


def build_page(gray: np.ndarray, book: str, page: str,
               page_class: str | None, n_cols: int | None) -> PageGeometry:
    h = gray.shape[0]
    half = int(h * BAND_HALF)
    ys = [int(h * f) for f in BAND_FRACS]
    bands = [band_rules(gray, y, half) for y in ys]
    # 以中带为锚，上下带各取最近的一条；配不上的丢弃（宁缺勿错）
    tol = h * 0.02
    rules: list[RuleLine] = []
    for x_mid, _ in bands[1]:
        picked = []
        for b in (bands[0], bands[2]):
            if not b:
                picked = []
                break
            j = min(range(len(b)), key=lambda j: abs(b[j][0] - x_mid))
            if abs(b[j][0] - x_mid) > tol:
                picked = []
                break
            picked.append(b[j][0])
        if len(picked) == 2:
            rules.append(RuleLine(x_top=float(picked[0]), x_mid=float(x_mid),
                                  x_bot=float(picked[1])))
    drop = set(REVIEW.get(f"{book}/{page}", {}).get("drop", []))
    rules = [r for r in rules
             if not any(abs(r.x_mid - d) < 12 for d in drop)]
    return PageGeometry(
        book=book, page=page,
        image_size={"width": int(gray.shape[1]), "height": int(h)},
        band_ys=[float(y) for y in ys], rules=rules,
        n_cols=n_cols,
        page_class=REVIEW.get(f"{book}/{page}", {}).get("class", page_class))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--pages", required=True,
                    help="JSON: [{book,page,page_class,n_cols}]")
    args = ap.parse_args()
    spec = json.loads(Path(args.pages).read_text(encoding="utf-8"))
    out = Path(args.out)
    (out / "samples").mkdir(parents=True, exist_ok=True)
    n = 0
    kinds: dict[str, int] = {}
    for s in spec:
        img = cv2.imread(f"output/{s['book']}/{s['page']}.png",
                         cv2.IMREAD_GRAYSCALE)
        if img is None:
            print(f"  跳过 {s['book']}/{s['page']}: 读不到图")
            continue
        g = build_page(img, s["book"], s["page"],
                       s.get("page_class"), s.get("n_cols"))
        if len(g.rules) < 3:
            print(f"  跳过 {s['book']}/{s['page']}: 只认出 {len(g.rules)} 条界行")
            continue
        g.save(out / "samples" / f"{s['book']}_{s['page']}.json")
        kinds[g.page_class or "unknown"] = kinds.get(g.page_class or "unknown", 0) + 1
        n += 1
    print(f"写出 {n} 页 → {out}")
    print(f" 页型: {kinds}")


if __name__ == "__main__":
    main()
