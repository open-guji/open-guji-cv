"""普查：行网格是否跑出页面（跑出去的格必然装不下字，还会挤歪真字）。

刚性梳子按书级格高排，页面短一点点、或本页字距比书距小一点点，末格就
整个吊在图外——实测 vol02/129 越界 63px，末字「畜」被格线拦腰切开。
这是能全书普查的**结构性**错误：格在图外，一个像素都没有。

用法：PYTHONPATH=. python scripts/check_grid_offpage.py <数据集目录>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", nargs="?", default="../open-guji-dataset")
    ap.add_argument("--out", default="output")
    ap.add_argument("--tol", type=float, default=0.15,
                    help="越界超过此比例 × 格高才报")
    a = ap.parse_args()

    gold = json.loads((Path(a.dataset) / "page-type" / "expected.json")
                      .read_text(encoding="utf-8"))
    rows = gold if isinstance(gold, list) else gold.get("pages", [])
    body = {(e["book"], str(e["page"])) for e in rows
            if e.get("page_type") == "body"}

    bad = []
    for book in ("vol01", "vol02"):
        d = Path(a.out) / book / "phase3_char_grid"
        for gp in sorted(d.glob("*_char_grid.json")):
            page = gp.name.split("_")[0]
            if (book, page) not in body:
                continue
            g = json.loads(gp.read_text(encoding="utf-8"))
            img = cv2.imread(f"{a.out}/{book}/{page}.png", cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            H = img.shape[0]
            ch = float((g.get("grid") or {}).get("cell_h") or 115)
            over = 0.0
            for c in g.get("columns", []):
                cs = [k for k in c.get("cells", []) if k.get("type") == "char"]
                if cs:
                    over = max(over,
                               max(float(k["y_bottom"]) for k in cs) - H)
            if over > a.tol * ch:
                bad.append((book, page, round(over)))
    print(f"正文页 {len(body)}；**字格**越出页底的 {len(bad)} 页")
    for b, p, o in bad:
        print(f"  {b}/{p} 越界 {o}px")
    raise SystemExit(0 if not bad else 1)


if __name__ == "__main__":
    main()
