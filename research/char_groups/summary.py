"""字组测试集的格数与真值档统计（overview#437，G0）→ 打印 markdown，写 <dataset>/char-groups/metadata.json。
用法：python research/char_groups/summary.py <dataset>/char-groups
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import GROUPS, SPLIT  # noqa: E402

ROOT = sys.argv[1]
TIERS = ("A_human", "B_vision", "C_weak", None)


def main():
    meta = {"name": "char-groups", "version": "0.1.0", "schema_version": 1,
            "description": "字组测试集：形近/异体字按组拆开，每组单独积累数据（overview#437，G0，2026-10-06）。"
                           "先收三组形近字：己已巳(jys)、日曰(ry)、入人八(rr)。",
            "created": "2026-10-06", "status": "实集（全量格 + 分档真值；强真值偏难例）",
            "sample_unit": "字位×组（一格可同属多组）", "groups": {}}
    ids = set()
    for gk in GROUPS:
        rows = [json.loads(l) for l in open(f"{ROOT}/{gk}/items.jsonl", encoding="utf-8")]
        ids |= {r["id"] for r in rows}
        c = defaultdict(Counter)
        for r in rows:
            k = r["book"]
            c[k]["rows"] += 1
            c[k]["core" if r["core"] else "peripheral"] += 1
            if r["core"]:
                c[k][r["gold_tier"]] += 1
                c[k]["crop"] += r["crop"] is not None
                c[k]["conflict"] += r["gold_conflict"]
                if r["gold_tier"] in ("A_human", "B_vision") and r["gold"] in GROUPS[gk]["members"]:
                    c[k]["strong_in_group"] += 1
        print(f"\n### {gk}（{GROUPS[gk]['members']}）\n")
        print("| 册 | 划分 | core 格 | 人裁 A | 看图 B | 弱 C | 无真值 | 强真值且真值在组内 | 真值冲突 | 有字块图 | 外围格 |")
        print("|---|---|---|---|---|---|---|---|---|---|---|")
        tot = Counter()
        for bk in sorted(c):
            x = c[bk]
            tot.update(x)
            print(f"| {bk} | {SPLIT[bk]} | {x['core']} | {x['A_human']} | {x['B_vision']} | {x['C_weak']} | {x[None]} | "
                  f"{x['strong_in_group']} | {x['conflict']} | {x['crop']} | {x['peripheral']} |")
        print(f"| 合计 | | {tot['core']} | {tot['A_human']} | {tot['B_vision']} | {tot['C_weak']} | {tot[None]} | "
              f"{tot['strong_in_group']} | {tot['conflict']} | {tot['crop']} | {tot['peripheral']} |")
        meta["groups"][gk] = {"members": GROUPS[gk]["members"], "type": GROUPS[gk]["type"], "rows": tot["rows"],
                              "core": tot["core"], "peripheral": tot["peripheral"],
                              "gold_tier": {"A_human": tot["A_human"], "B_vision": tot["B_vision"],
                                            "C_weak": tot["C_weak"], "none": tot[None]},
                              "by_book": {bk: {k if k is not None else "none": v for k, v in x.items()}
                                          for bk, x in sorted(c.items())}}
    meta["total_rows"] = sum(g["rows"] for g in meta["groups"].values())
    meta["unique_cells"] = len(ids)
    meta["label_origin_values"] = ["human", "vision", "align"]
    meta["eval_command"] = ("cd open-guji-cv && python research/char_groups/baseline.py <dataset>/char-groups "
                            "（现行产物基线）；新方法照 README「评测口径」与 <组>/baseline.json 比")
    with open(f"{ROOT}/metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
