# -*- coding: utf-8 -*-
"""按排除名单把已进库的坏图块撤库。

    PYTHONPATH=. python scripts/apply_crop_exclusions.py --dry-run
    PYTHONPATH=. python scripts/apply_crop_exclusions.py

撤库走 `clustering.audit.evict_instance`（删 admissions/exemplars/derived/
instances 四表行，并清掉因此变空的壳 glyph），与体检页「撤库重审」同一条路。

**撤库不等于删证据**：名单本身留在 `config/crop_exclusions.jsonl`，重扫之后
按名单逐条对新图复核、该回来的回来。本脚本另出一份撤库回执
（`--receipt`），记下每条撤的是哪个字、当初怎么进来的——`glyph.db` 是可重建
索引，回执才是这次动作的账。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from open_guji_cv.clustering.audit import evict_instance  # noqa: E402
from open_guji_cv.clustering.exclusions import load_exclusions  # noqa: E402
from open_guji_cv.clustering.glyph_db import GlyphDB  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="output/glyph.db")
    ap.add_argument("--list", default="config/crop_exclusions.jsonl")
    ap.add_argument("--receipt", default="output/crop_exclusion_receipt.jsonl")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    ex = load_exclusions(args.list)
    con = sqlite3.connect(args.db)
    rows = {r[0]: (r[1], r[2]) for r in con.execute(
        """SELECT i.instance_id, i.label, a.provenance FROM instances i
           LEFT JOIN admissions a USING(instance_id)""")}
    hit = [i for i in rows if i in ex]
    n_before = len(rows)
    n_glyph = con.execute("SELECT count(*) FROM glyphs").fetchone()[0]
    con.close()

    print(f"库内 {n_before} 条实例 / {n_glyph} 个字头；名单命中 {len(hit)} 条")
    print("  按名单来源:", dict(Counter(ex[i]["origin"] for i in hit)))
    print("  按进库通道:", dict(Counter(rows[i][1] or "?" for i in hit)))
    only = Counter()
    for i in hit:
        only[rows[i][0]] += 1
    single = [c for c, n in Counter(v[0] for v in rows.values()).items()
              if n == 1 and only.get(c)]
    print(f"  其中 {len(single)} 个字头在库里**只有这一个刻例**，撤掉字头就空了："
          f"{''.join(sorted(single))[:60]}")
    if args.dry_run:
        return

    db = GlyphDB(args.db)
    receipt = []
    for iid in hit:
        label, prov = rows[iid]
        ch = evict_instance(db, iid)
        receipt.append({"instance_id": iid, "char": ch or label,
                        "provenance": prov, "origin": ex[iid]["origin"],
                        "evidence": ex[iid]["evidence"], "round": ex[iid]["round"]})
    Path(args.receipt).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in receipt)
        + "\n", encoding="utf-8")
    con = sqlite3.connect(args.db)
    a = con.execute("SELECT count(*) FROM instances").fetchone()[0]
    g = con.execute("SELECT count(*) FROM glyphs").fetchone()[0]
    print(f"\n撤库 {len(receipt)} 条 → 实例 {n_before} → {a}，字头 {n_glyph} → {g}")
    print(f"回执 → {args.receipt}")


if __name__ == "__main__":
    main()
