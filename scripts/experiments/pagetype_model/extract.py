# -*- coding: utf-8 -*-
"""抽 page-type 金标页的信号特征 → features_v1.csv（含现行规则判型）。

用法：python extract.py --ws <沙箱工作区> --out feats.csv   （只读沙箱 products/<book>/border_detect/ 里有的页）
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import pandas as pd

from open_guji_cv.clustering.page_type import classify_page_type
from open_guji_cv.pagetype_model import signals as S

ap = argparse.ArgumentParser()
ap.add_argument("--ws", required=True)
ap.add_argument("--dataset", default="/home/user/open-guji-dataset/page-type")
ap.add_argument("--out", required=True)
a = ap.parse_args()
ws = Path(a.ws)
gold = {}
for l in open(Path(a.dataset) / "items.jsonl", encoding="utf-8"):
    r = json.loads(l)
    if r.get("status") == "active":
        gold[(r["anchor"]["book"], r["anchor"]["page"])] = r["expected"]["page_type"]
rows = []
for (book, page), t in sorted(gold.items()):
    pj = ws / "products" / book / "border_detect" / f"p{page:04d}.json"
    if not pj.exists():
        continue
    borders = json.loads(pj.read_text(encoding="utf-8"))["borders"]
    img = cv2.imread(str(ws / "data_full" / "zongmu" / book / f"{page}.png"), cv2.IMREAD_GRAYSCALE)
    f = S.extract(img, borders)
    cp, pol = classify_page_type(img)
    rows.append({"book": book, "page": page, "gold": t, "rule_type": cp, "rule_policy": pol, **f})
pd.DataFrame(rows).to_csv(a.out, index=False)
print(len(rows), "pages ->", a.out)
