# -*- coding: utf-8 -*-
"""从字形库建「拆字识别」基准集：seen / unseen 两档，附 IDS。

## 为什么要单独建

用户 2026-09-05：「目前我们整个字形库都是你的测试和训练集，你可以反复验证算法
准确率。我希望你通过识别字符的结构、部件、笔画，再准确的找到对应字符。」

字形库 15,482 个有标签实例、1,958 字种。按每字样本数天然分两档：

- **seen**（≥5 样本，658 字种 / 13,206 实例）：按实例 80/20 切 train/test，
  量「见过这个字的其他刻例，能不能认出新刻例」——这是普通分类；
- **unseen**（≤2 样本，1,022 字种 / 1,327 实例）：**全部当 test**，模型/模板
  永远见不到这些字的任何刻例——这才是「拆字识别」要解决的零样本问题，也是
  生僻字的真实处境（换一本书，所有字一开始都是 unseen）。

unseen 里 1,020 字可拆 IDS，其中 **413 字（40%）的部件全部在 seen 字里出现过**
——这 413 字是部件法理论上够得着的上限；剩下 60% 含 seen 里没见过的部件，
只能靠字体渲染补。

## 输出

    cache/glyph_bench/png/<instance_id>.png      图块（从 instances.patch_png 解出）
    cache/glyph_bench/items.jsonl                {id, char, split, provenance, ids, structure, w, h}

split ∈ {seen_train, seen_test, unseen}。切分用固定种子，可复现。
"""
from __future__ import annotations

import json
import random
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

OUT = Path("cache/glyph_bench")
SEEN_MIN = 5
UNSEEN_MAX = 2
SEED = 20260905


def main() -> int:
    from open_guji_cv.clustering.ids_guard import ids_of, structure

    db = sqlite3.connect("output/glyph.db")
    rows = db.execute(
        "select i.instance_id, i.label, i.patch_png, i.width, i.height, a.provenance "
        "from instances i join admissions a on a.instance_id=i.instance_id "
        "where i.label is not null and i.label!='' and i.patch_png is not null").fetchall()
    by_char: dict[str, list] = defaultdict(list)
    for r in rows:
        by_char[r[1]].append(r)
    rng = random.Random(SEED)
    (OUT / "png").mkdir(parents=True, exist_ok=True)
    items = []
    split_n: Counter = Counter()
    for ch, lst in by_char.items():
        n = len(lst)
        if n >= SEEN_MIN:
            lst = sorted(lst, key=lambda r: r[0])
            rng.shuffle(lst)
            k = max(1, int(round(n * 0.2)))
            splits = ["seen_test"] * k + ["seen_train"] * (n - k)
        elif n <= UNSEEN_MAX:
            splits = ["unseen"] * n
        else:
            splits = ["mid"] * n          # 3~4 样本：两头都不算，留作将来
        for r, sp in zip(lst, splits):
            iid, label, png, w, h, prov = r
            p = OUT / "png" / (iid.replace(":", "_") + ".png")
            if not p.exists():
                p.write_bytes(png)
            items.append({"id": iid, "char": label, "split": sp, "provenance": prov,
                          "ids": ids_of(label), "structure": structure(label),
                          "w": w, "h": h, "png": str(p)})
            split_n[sp] += 1
    with open(OUT / "items.jsonl", "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(f"写出 {len(items)} 条 → {OUT}")
    print("split:", dict(split_n))
    print("字种: seen", len([c for c, l in by_char.items() if len(l) >= SEEN_MIN]),
          " unseen", len([c for c, l in by_char.items() if len(l) <= UNSEEN_MAX]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
