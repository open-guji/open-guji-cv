"""字形判法扩面：数据集人裁（`labels/unified.jsonl` 的 shape 行）＋字块图（`variant/*/crops`）→ `config/groups/<组>/ids_bank.json`。

用法：python build_bank.py <dataset char-groups 根> <组 id> [仓根]
参数（size/区域/λ）在 `PLAN` 里，与 `ids_online.SPECS` 一致；评测是按册留出（`eval_pair.loo`）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from eval_pair import load, loo, summarize  # noqa: E402

from open_guji_cv.groups import ids_online as O, ids_whole  # noqa: E402

#: 组 → (字, size)
PLAN = {"lih": ("厯歴", 48), "weiw": ("衛衞", 48), "shan": ("刪删", 48), "di": ("扺抵", 64)}

if __name__ == "__main__":
    root, g = Path(sys.argv[1]), sys.argv[2]
    repo = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(__file__).resolve().parents[3]
    chars, size = PLAN[g]
    sp = O.SPECS[g]
    cells = load(root, chars)
    d = ids_whole.build(g, cells, size, {"labels": "dataset char-groups labels/unified.jsonl（kind=shape、status=ok，sheldon 人裁刻形）"})
    O.write_bank(d, repo / "config" / "groups" / g / "ids_bank.json")
    res = loo(cells, sp.whole, tuple(sp.region), sp.lam, size)
    right = sum(1 for f, ch, m, _ in res if ch == f and m >= sp.min_margin)
    wrong = [(f, k, ch, round(m, 2)) for f, ch, m, k in res if ch != f and m >= sp.min_margin]
    print(g, "cells", d["source"]["cells"], "按册留出 门槛", sp.min_margin, "对", right, "弃", len(res) - right - len(wrong), "错", wrong)
    print("0错门槛", summarize(res)[0])
