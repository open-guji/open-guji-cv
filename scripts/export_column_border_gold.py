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

顺带存 `end_fingerprint`：人当时看的那两张端裁剪图的 32×24 缩略。上游再改
列图时 `scripts/migrate_column_warp_gold.py` 拿它判断"还是不是同一张图"，
是就留用、不是才回去重看——这样上游小改动不必全量重标。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from migrate_column_warp_gold import (  # noqa: E402
    current_column, end_crops, fingerprint,
)


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
    orphan: list[str] = []
    for key, cls in sorted(by_col.items()):
        f = samples_dir / f"{key}.json"
        if not f.exists():
            # 这一列的**文字带**标注被上游几何改动作废了，但 border_class 是
            # 独立的一条人裁，没道理跟着丢——建一份只有 border_class 的样本，
            # text_band 标成 pending，等重标完再补进去。
            book, page, col = key.rsplit("_c", 1)[0].split("_", 1) + [int(key.rsplit("_c", 1)[1])]
            f.write_text(json.dumps({
                "book": book, "page": page, "col": col,
                "text_band": None, "pending_text_band": True,
                "label_origin": "human",
            }, ensure_ascii=False, indent=1), encoding="utf-8")
            orphan.append(key)
        s = json.loads(f.read_text(encoding="utf-8"))
        s["border_class"] = cls
        # 存一份人当时看的那两张端裁剪图的指纹。上游再改列图时，
        # migrate_column_warp_gold.py 靠它判断"人看的还是不是同一张图"——
        # 是就留用裁决，不是才回去重看。**不拿算法的一致性当留用判据**，
        # 那会让金标永远测不出算法错（循环论证）。
        warped = current_column(s)
        if warped is not None:
            crops = end_crops(warped)
            s["end_fingerprint"] = {e: fingerprint(crops[e]) for e in ("top", "bottom")}
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
    if orphan:
        print(f"  其中 {len(orphan)} 列只有 border_class、文字带待重标：{', '.join(orphan)}")
    for (end, v), n in sorted(counts.items()):
        print(f"  {end:>6} {v:<6} {n}")


if __name__ == "__main__":
    main()
