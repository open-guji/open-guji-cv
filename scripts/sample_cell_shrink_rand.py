# -*- coding: utf-8 -*-
"""Step4（字框收缩）随机层抽样：给全线立尺子用的独立人工基准。

Step4 现在报 R4 = 0.51%（10/1953），但没有人工核校的独立基准说这个数对不对。
`self_assess_r1~r4`（`../open-guji-dataset/char-segmentation/instances/self_assess_r*.json`）
虽然也叫 `stratum=rand`，但 `label_origin` 全是 `model`——是算法自己标自己，
循环论证，不能当验收基准用。这份脚本出的是**要给真人看**的候选，`label_origin`
留给标注环节写 `human`。

抽样框（哪些字块算「全书」）：
- 只用已经跑过 cell_shrink 的书（现状 2026-09：vol01 206 页 / vol02 188 页；
  vol03 只有 40 页且没有 page-type 金标，先不进来——见任务书讨论，
  vol04~vol10 还没有 cell_shrink 产物）；
- 只要 page-type 金标判为 body 的页（目录/花名册/职名页各有各的版式，
  混进来会稀释「正文字框收缩准不准」这个问题）；
- 只要 `cell_type == "char"`（跳过行首标记等非字格）。

等概率抽样：`random.Random(seed).sample(pool, n)`，不看 flags、不挑可疑样本
——挑出来的样本没法读作全书缺陷率（教训见 column-warp 随机层 n=40 的做法）。

用法：
    PYTHONPATH=. python scripts/sample_cell_shrink_rand.py --n 400 --tag r1 \
        --out output/cell_shrink_rand_r1.json
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from open_guji_cv.products.store import ProductStore  # noqa: E402

DATASET = REPO.parent / "open-guji-dataset"
BOOKS = ("vol01", "vol02")  # 有 cell_shrink 产物 + page-type 金标的书


def body_pages(book: str) -> set[int]:
    f = DATASET / "page-type" / "items.jsonl"
    rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    return {int(r["anchor"]["page"]) for r in rows
            if r["anchor"]["book"] == book
            and (r.get("expected") or {}).get("page_type") == "body"}


def load_pool(st: ProductStore) -> list[dict]:
    """全书（现有产物范围内）正文页的字格实例，逐字一条。"""
    out = []
    for book in BOOKS:
        body = body_pages(book)
        for key in st.keys(book, "cell_shrink"):
            page = int(key[1:])
            if page not in body:
                continue
            d = st.read_raw(book, "cell_shrink", key)
            if d is None or "char_index" not in d:
                continue
            for col in d["char_index"]["columns"]:
                for ch in col["chars"]:
                    if ch.get("cell_type") != "char":
                        continue
                    out.append({
                        "book": book, "page": page, "col": col.get("col_idx", col.get("idx")),
                        "id": ch["id"], "patch_key": ch["patch_key"],
                        "bbox_page": ch["bbox_page"], "flags": ch.get("flags") or [],
                    })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--seed", type=int, default=20260911)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--exclude", nargs="*", default=[],
                     help="要排除的既往抽样文件（避免重复消耗同一批字，如已有的模型自评样本）")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    st = ProductStore()
    pool = load_pool(st)
    print(f"抽样框：{len(pool)} 字格（{Counter(r['book'] for r in pool)}）")

    exclude_ids: set[str] = set()
    for path in a.exclude:
        rows = json.loads(Path(path).read_text(encoding="utf-8"))
        exclude_ids.update(r["id"] for r in rows if "id" in r)
    if exclude_ids:
        before = len(pool)
        pool = [r for r in pool if r["id"] not in exclude_ids]
        print(f"排除已抽过 {before - len(pool)} 条 → 剩 {len(pool)}")

    rng = random.Random(a.seed)
    picked = list(pool)
    rng.shuffle(picked)
    picked = picked[:a.n]
    for r in picked:
        r["stratum"] = "rand_human"
        r["seed"] = f"cell_shrink_rand_{a.tag}"
        r["label_origin"] = None  # 待标注环节人裁后填 "human"
        r["schema_version"] = 1

    outp = Path(a.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(picked, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"抽出 {len(picked)} 格 → {outp}")


if __name__ == "__main__":
    main()
