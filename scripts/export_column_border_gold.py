# -*- coding: utf-8 -*-
"""把「单列矫正·上下版框核校」的人裁结果并进 column-warp 金标。

    python scripts/export_column_border_gold.py read_back.html \\
        -o ../open-guji-dataset/char-segmentation/column-warp

**金标只记类别，不记坐标**（用户 2026-08-31 定：「如果确认了属于哪一类，基本
很好切分」）。所以每列的样本里加一个 `border_class` 字段：

```json
"border_class": {"top": "clean", "bottom": "none"}
```

  * `clean` 有版框残墨、跟首字之间有间隙（算法的 a 档=贴边、d 档=内缩，都算）
  * `glued` 有版框残墨、跟首字粘连，找不到间隙
  * `none`  这一端没有版框残墨
  * `idk`   拿不准（写进去，但评测时排除——它不是"两可"，是"没看清"）

只并**裁过**的那一端；没裁的键不写，评测脚本按"没有就跳过"处理。

**跑的顺序**：先 `export_column_warp_gold.py`（它会整份重写 metadata.json），
再跑这个（它只往里加字段）。反过来 border_class_distribution 会被冲掉。
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


def parse_page(html: str) -> tuple[list[dict], dict]:
    m = re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S)
    if not m:
        raise SystemExit("这份 HTML 里没有 #data——确认读回的是标注页本身")
    d = json.loads(m.group(1).replace("<\\/", "</"))
    return d["rows"], d.get("verdicts", {})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("html", help="从 Artifact 读回来的标注页 HTML")
    ap.add_argument("-o", "--out", required=True, help="column-warp 子集目录")
    args = ap.parse_args()

    rows, state = parse_page(Path(args.html).read_text(encoding="utf-8"))
    samples_dir = Path(args.out) / "samples"
    by_col: dict[str, dict[str, str]] = {}
    for r in rows:
        rec = state.get(r["id"])
        if not rec or not rec.get("v"):
            continue                      # 没裁 ≠ 默认通过，是还没看
        key = f"{r['book']}_{r['page']}_c{r['col']}"
        by_col.setdefault(key, {})["top" if r["end"] == "top" else "bottom"] = rec["v"]

    counts: Counter = Counter()
    touched = 0
    for key, cls in by_col.items():
        f = samples_dir / f"{key}.json"
        if not f.exists():
            raise SystemExit(f"{f} 不存在——先跑 export_column_warp_gold.py")
        s = json.loads(f.read_text(encoding="utf-8"))
        s["border_class"] = cls
        f.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
        touched += 1
        for end, v in cls.items():
            counts[(end, v)] += 1

    meta_path = Path(args.out) / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["border_class_distribution"] = {f"{e}:{v}": n for (e, v), n in sorted(counts.items())}
    note = (" 另有 border_class：矫正图上下两端各一条人裁的**类别**（clean 有残墨且跟"
            "首字有间隙 / glued 有残墨但粘连 / none 没残墨 / idk）——**只记类别不记"
            "坐标**，类别定了切在哪一行算法自己算得准。")
    if note not in meta["gold_definition"]:      # 重跑要幂等，别越追加越长
        meta["gold_definition"] += note
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")

    print(f"并入 {touched} 列的 border_class（共 {sum(counts.values())} 条端裁决）")
    for (end, v), n in sorted(counts.items()):
        print(f"  {end:>6} {v:<6} {n}")


if __name__ == "__main__":
    main()
