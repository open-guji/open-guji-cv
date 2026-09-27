# -*- coding: utf-8 -*-
"""字形库 × 工作区记录 对账：库里的刻例，与这一格现在的裁决、排除名单、管线决定、字块图是否还对得上。

    GUJI_WORKSPACE=<书目录> PYTHONPATH=. python scripts/glyph_crosscheck.py <out.jsonl> [--drift]

**2026-09-26 起改薄**：核心口径挪进了 `clustering/glyph_ledger.py::crosscheck()`——
`guji check ledger <book>` 是常规命令的入口，这个脚本留作兼容外壳（历史命令行不变）。
详见该函数的文档字符串；这里只剩参数解析与落盘。

v1 来源（四庫 vol01 旧管线，idx 从 0）默认按 slot = idx+1 猜现在的格（`v1_guess=true`，只作参考）；
给了 `--v1-map <glyph_v1_map.py 输出>` 就改用按形状确认过的现格。
只报不改；每条带足证据，改库走控制台字形库页或 glyph_audit 事件。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from open_guji_cv.clustering.glyph_ledger import crosscheck  # noqa: E402
from open_guji_cv.core.workspace import glyph_db_path  # noqa: E402


def main() -> int:
    out_path = Path(sys.argv[1])
    drift = "--drift" in sys.argv
    v1_map: dict[str, str] = {}
    if "--v1-map" in sys.argv:
        for ln in open(sys.argv[sys.argv.index("--v1-map") + 1], encoding="utf-8"):
            d = json.loads(ln)
            if d["status"] in ("exact", "match") and d["cell"]:
                v1_map[d["v1"]] = d["cell"]

    res = crosscheck(glyph_db_path(), drift=drift, v1_map=v1_map)
    with open(out_path, "w", encoding="utf-8") as f:
        for x in res["findings"]:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    if drift:
        print("drift: 缓存里没有字块的", res["drift_missing"])
    print(res["n_lib"], "刻例；", Counter(res["counts"]),
          Counter((x["check"], x["why"].split(":")[0]) for x in res["findings"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
