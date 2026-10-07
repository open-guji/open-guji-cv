# -*- coding: utf-8 -*-
"""#477 S 道：按快照 products 统计「劈格对」——相邻两格都偏矮、高度之和≈列中位格高。
用法：python split_pairs.py <products 根> <book>   （只读，不写任何产物）"""
import collections, glob, json, sys

root, book = sys.argv[1], sys.argv[2]
tot = collections.Counter()
for f in sorted(glob.glob(f"{root}/{book}/cell_shrink/p*.json")):
    for col in json.load(open(f, encoding="utf-8"))["char_index"]["columns"]:
        ch = [x for x in col["chars"] if x["cell_type"] == "char" and x["slot"] > 0
              and not set(x["flags"]) & {"tail_junk", "edge_blob"}]
        if len(ch) < 6:
            continue
        hs = sorted(x["height"] for x in ch)
        med = hs[len(hs) // 2]
        for i in range(len(ch) - 1):
            a, b = ch[i], ch[i + 1]
            if (b["slot"] - a["slot"] == 1 and 0.2 * med < a["height"] < 0.7 * med
                    and 0.2 * med < b["height"] < 0.9 * med
                    and 0.8 * med <= a["height"] + b["height"] <= 1.25 * med):
                tot["head" if a["slot"] <= 2 else "tail" if i >= len(ch) - 3 else "mid"] += 1
print(book, dict(tot))
