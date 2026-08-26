"""无偏 rand 抽样 + **现场提取**（不依赖 phase4 产物，免整册重建）。

为什么要现算：改一处切分逻辑就整册重建太贵，但产物里的图块是旧的，
拿旧图块判读量出来的正确率是**上一版代码**的。这里只对抽中的页现跑
extract_page，判读的就是当前代码的产出。

抽样设计（自加权两阶段，抑制「缺陷按页扎堆」带来的方差膨胀）：
  一阶段  正文页按字格数 PPS 抽 --pages 页（不放回近似）
  二阶段  每页均匀抽 --per-page 格
两阶段合起来每格入样概率近似相等，可直接读作全书字格正确率。

用法：PYTHONPATH=. python scripts/sample_live.py --pages 200 --per-page 2 \
        --tag r3 --out output/self_assess_r3
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

BOOKS = ("vol01", "vol02")


def body_pages(dataset: Path) -> set[tuple[str, str]]:
    gold = json.loads((dataset / "page-type" / "expected.json")
                      .read_text(encoding="utf-8"))
    rows = gold if isinstance(gold, list) else gold.get("pages", [])
    return {(e["book"], str(e["page"])) for e in rows
            if e.get("page_type") == "body"}


def page_sizes(body: set) -> dict:
    """每页字格数——只用来做 PPS 权重，用旧产物的计数够了。"""
    n = defaultdict(int)
    for book in BOOKS:
        p = Path("output") / book / "phase4_chars" / "index.jsonl"
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            k = (r["book"], r["page"])
            if k in body and r.get("cell_type") == "char":
                n[k] += 1
    return {k: v for k, v in n.items() if v > 0}


def main() -> None:
    import cv2
    from open_guji_cv.clustering.extractor import CharExtractor

    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="../open-guji-dataset")
    ap.add_argument("--pages", type=int, default=200)
    ap.add_argument("--per-page", type=int, default=2)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--tag", default="r3")
    ap.add_argument("--out", default="output/self_assess_r3")
    a = ap.parse_args()

    body = body_pages(Path(a.dataset))
    sizes = page_sizes(body)
    rng = random.Random(a.seed)

    # PPS 不放回：按 size 权重逐个抽，抽中即移出
    pool = list(sizes.items())
    picked = []
    for _ in range(min(a.pages, len(pool))):
        tot = sum(v for _, v in pool)
        x = rng.random() * tot
        acc = 0.0
        for i, (k, v) in enumerate(pool):
            acc += v
            if acc >= x:
                picked.append(k)
                pool.pop(i)
                break
    picked.sort()

    out = Path(a.out)
    (out / "patches").mkdir(parents=True, exist_ok=True)
    ex = CharExtractor()
    rows = []
    for book, page in picked:
        gp = Path("output") / book / "phase3_char_grid" / f"{page}_char_grid.json"
        img = cv2.imread(f"output/{book}/{page}.png")
        if img is None or not gp.exists():
            continue
        grid = json.loads(gp.read_text(encoding="utf-8"))
        got = [(i, p) for i, p in ex.extract_page(img, grid, book, page)
               if i.cell_type == "char"]
        if not got:
            continue
        for inst, patch in rng.sample(got, min(a.per_page, len(got))):
            cid = f"{book}:{page}:{inst.col}:{inst.idx}{inst.sub or ''}"
            rel = f"patches/{book}_{page}_{inst.col}_{inst.idx}{inst.sub or ''}.png"
            cv2.imwrite(str(out / rel), patch)
            rows.append({"book": book, "page": page, "col": inst.col,
                         "idx": inst.idx, "sub": inst.sub, "id": cid,
                         "stratum": "rand", "flags": sorted(inst.flags),
                         "bbox": [round(v, 1) for v in inst.bbox],
                         "patch_path": rel, "seed": f"self_assess_{a.tag}",
                         "n_page": sizes[(book, page)]})
    (out / "sample.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"抽中 {len(picked)} 页 / {len(rows)} 格 → {out}")


if __name__ == "__main__":
    main()
