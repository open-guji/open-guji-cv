# -*- coding: utf-8 -*-
"""Step4（字框收缩）随机层裁决：给全线立尺子用的独立人工基准。

Step4 现在报 R4 = 0.51%（10/1953），但没有人工核校的独立基准说这个数对不对。
手上的金标都不能用来验收：`instances` 现有条目和 `recrop` 是定向富集的缺陷
四分类，读不出全书比例；`self_assess_r1~r4`（`../open-guji-dataset/
char-segmentation/instances/self_assess_r*.json`）虽然也叫 `stratum=rand`，
但 `label_origin` 全是 `model`——算法标自己，循环论证，不能当验收基准用。

这里出的候选是**等概率随机**抽的、给控制台 Step4 页面裁决用：

- 抽样框：已经跑过 cell_shrink 的书（现状 2026-09：vol01 206 页 / vol02 188 页；
  vol03 只有 40 页且没有 page-type 金标，先不进来；vol04~vol10 还没有产物）；
- 只要 page-type 金标判为 body 的页；
- 只要 `cell_type == "char"`；
- `random.Random(seed).sample()`，不看 flags、不挑可疑样本。

裁决走控制台既有的 `POST /api/events`（`kind=confirm, payload.v=seg_defect,
payload.quality=<clean|truncated|contaminated|not_text>, payload.stratum=
rand_human`），落 `gold_add` → `char-segmentation/instances`，与既有的
`self_assess` 系列和其余定向层分开，报数时不能合并算。
"""
from __future__ import annotations

import json
import random
from functools import lru_cache
from pathlib import Path

from ..products.store import ProductStore

DATASET = Path(__file__).resolve().parent.parent.parent.parent / "open-guji-dataset"
BOOKS = ("vol01", "vol02")   # 有 cell_shrink 产物 + page-type 金标的书
DEFAULT_SEED = 20260911


@lru_cache(maxsize=8)
def _body_pages(book: str) -> frozenset[int]:
    f = DATASET / "page-type" / "items.jsonl"
    if not f.exists():
        return frozenset()
    rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    return frozenset(int(r["anchor"]["page"]) for r in rows
                     if r["anchor"]["book"] == book
                     and (r.get("expected") or {}).get("page_type") == "body")


def _load_pool(store: ProductStore) -> list[dict]:
    out = []
    for book in BOOKS:
        body = _body_pages(book)
        for key in store.keys(book, "cell_shrink"):
            page = int(key[1:])
            if page not in body:
                continue
            d = store.read_raw(book, "cell_shrink", key)
            if d is None or "char_index" not in d:
                continue
            for col in d["char_index"]["columns"]:
                for ch in col["chars"]:
                    if ch.get("cell_type") != "char":
                        continue
                    out.append({
                        "id": ch["id"], "book": book, "page": page,
                        "col": col.get("col", col.get("col_idx")),
                        "patch_key": ch["patch_key"], "bbox_page": ch["bbox_page"],
                    })
    return out


def rand_sample(n: int = 400, seed: int = DEFAULT_SEED, tag: str = "r1",
                store: ProductStore | None = None) -> dict:
    """全书（现有产物范围内）正文页字格里等概率随机抽 n 条。

    `tag` 只用来给 `seed` 字段起名字（写进金标 `input`），换 tag 不改抽样结果
    ——真正决定抽样的是 `seed`（整数）。同一 `(seed, n)` 总是抽到同一批，
    重复调用/刷新页面不会换一批候选。
    """
    store = store or ProductStore()
    pool = _load_pool(store)
    rng = random.Random(seed)
    picked = list(pool)
    rng.shuffle(picked)
    picked = picked[:n]
    for r in picked:
        r["stratum"] = "rand_human"
        r["seed_tag"] = f"cell_shrink_rand_{tag}"
    # 顺序打乱且与选样种子无关：分层/分页挨着排会让人连续看到同一页的字，
    # 锚定后面的判断（同一页版式/墨色相近，容易顺着上一张的判断惯性点）。
    random.Random(seed + 1).shuffle(picked)
    return {"n_pool": len(pool), "n": len(picked), "seed": seed, "rows": picked}
