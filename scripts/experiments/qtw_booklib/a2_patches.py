"""a2：给导入的确认格渲染字块（顺带落进 $QTW_WS/cache，glyphdb_admit 进库时从缓存取）。

  GUJI_WORKSPACE=$QTW_WS python a2_patches.py <imp_dir>   → <imp_dir>/patches.pkl {key: 灰度图}
"""
from __future__ import annotations

import collections
import json
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from qb_common import cell_index, ctx_for  # noqa: E402


def main():
    d = Path(sys.argv[1])
    final = [json.loads(l) for l in open(d / "final.jsonl", encoding="utf-8")]
    want = collections.defaultdict(list)
    for r in final:
        if r["import"] and r["act"] == "confirm":
            want[r["key"].split(":")[0]].append(r["key"])
    out, miss = {}, []
    for b, keys in sorted(want.items()):
        ctx, cells = ctx_for(b), cell_index(b)
        for k in keys:
            try:
                out[k] = ctx.image("char_patch", cells[k]["patch_key"])
            except Exception as e:  # noqa: BLE001
                miss.append((k, repr(e)[:200]))
        print(b, len(keys), "miss", len(miss), flush=True)
    pickle.dump(out, open(d / "patches.pkl", "wb"))
    json.dump(miss, open(d / "patches_miss.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
