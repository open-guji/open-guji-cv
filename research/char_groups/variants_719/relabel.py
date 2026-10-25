"""把看图确认过的库标更正写成中心库 glyph_audit relabel 事件（同 A23 批 H-A23-719-variants-1024 的格式）。

用法：python relabel.py <已核清单 tsv> <批名> <输出 jsonl> [--ts=2026-10-25T00:00:00Z]
清单列：instance_id 库标 来路 组 判 margin 依据 [采纳] [说明]；「采纳」列为空或 yes 的行才写。只生成文件；
导入中心库要 sheldon 在线程里说「推」。
"""
from __future__ import annotations

import csv
import json
import sys


def events(rows, batch: str, ts: str):
    for seq, r in enumerate(rows, 1):
        iid = r["instance_id"]
        key = iid.split(":", 1)[1] if iid.startswith(("v1:", "v2:")) else iid
        book, page, col, slot = key.split(":")
        why = r.get("说明") or ("殿本只一种刻法，码位跟刻形走" if r["组"] == "one_form" else f"{r['组']} 判法 margin {r['margin']}，看图确认")
        yield {"actor": "user", "batch": batch, "id": f"evt_{batch}_{seq:06d}", "kind": "glyph_audit",
               "payload": {"char": r["判"], "char_self": r["库标"], "instance_id": iid, "key": f"claude:{iid}",
                           "note": f"GUJI-719 异体组重判：库标 {r['库标']}（原 {r['来路']}）→ {r['判']}；{why}",
                           "source": "A24 异体组纳入形近比对（research/char_groups/variants_719），看图确认", "v": "relabel"},
               "reviewer": "claude-A24", "seq": seq, "source_format": None,
               "target": {"anchor": None, "book": book, "col": int(col), "key": iid, "page": int(page),
                          "slot": int(slot.rstrip("ab")), "step": "glyph_audit", "unit": "cell"},
               "ts": ts}


if __name__ == "__main__":
    src, batch, out = sys.argv[1:4]
    ts = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--ts=")), "2026-10-25T00:00:00Z")
    rows = [r for r in csv.DictReader(open(src, encoding="utf-8"), delimiter="\t") if (r.get("采纳") or "yes") == "yes"]
    with open(out, "w", encoding="utf-8") as fh:
        for e in events(rows, batch, ts):
            fh.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")
    print(out, len(rows))
