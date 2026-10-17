"""M7 块 A：已有标注总表。读 dataset `char-groups`（jys/ry/rr）+ 分支里的 `variant/yi_560/user_parts_labels.jsonl`，
写 `<out>/gold_all.jsonl`（每行一格：group,id,gold,tier,src,left,right）并打印 markdown 计数表。
用法：python research/m7/gold_inventory.py <char-groups> <yi_560_parts_labels.jsonl> <out_dir>
"""
import collections, json, sys
from pathlib import Path

cg, yi, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
rows, cnt = [], collections.defaultdict(collections.Counter)
for g in ("jys", "ry", "rr"):
    for line in (cg / g / "items.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        if r.get("gold_tier") not in ("A_human", "B_vision", "C_weak"):
            continue
        rows.append({"group": g, "id": r["id"], "gold": r["gold"], "tier": r["gold_tier"], "src": r.get("gold_src"),
                     "split": r.get("split"), "left": r.get("left"), "right": r.get("right")})
        cnt[g][r["gold_tier"]] += 1
for line in yi.open(encoding="utf-8"):
    r = json.loads(line)
    rows.append({"group": "yi_560", "id": r["id"], "gold": r["target"], "tier": "A_human", "src": "user_parts_labels",
                 "parts": [r["top"], r["mid"], r["bot"]]})
    cnt["yi_560"]["A_human"] += 1
with (out / "gold_all.jsonl").open("w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("| 组 | A_human | B_vision | C_weak |\n|---|---|---|---|")
for g, c in cnt.items():
    print(f"| {g} | {c['A_human']} | {c['B_vision']} | {c['C_weak']} |")
