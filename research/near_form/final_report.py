"""N1 最终对照表（overview#428）。用法：python final_report.py items.jsonl
己已巳：现行（全部放行）vs 规则 ctx_rule（干支/时辰 + 上下文表放行，其余送审）vs 现有 ji_yi_si_review 三方一致闸。
日曰/入人八：上下文表只当否决（放行字与表高把握字不同 → 送审）的代价与收益。
"""
import json, sys
from collections import defaultdict
sys.path.insert(0, "research/near_form")
from ctx_table import Table, GROUPS
from open_guji_cv.utils.ji_yi_si import resolve
rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
EXT = ["corpus/external/daizhige_ru_yi.txt", "corpus/external/daizhige_zhaoling.txt"]
PUR, MN = 0.98, 5
strongr = lambda r: r["gold"] and r["gold_src"] not in (None, "witness_agree") and r["gold"] in GROUPS[r["group"]]
t = Table("jys", [], EXT)

def new_char(r):
    """规则判：→ (字|None, 路)。None = 送审。"""
    ch, why = resolve(r["left"][-1:] or None, r["right"][:1] or None, r["ref"] or r["coord_ref"], "all", r["right"][1:2] or None)
    if why.startswith("干支") or why == "时辰":
        return ch, "干支/时辰"
    c2, _ = t.decide(r["left"][-2:], r["right"][:2], PUR, MN)
    return (c2, "上下文表") if c2 else (None, "送审")

print("### 己已巳（样本=强真值格；全册格数=快照里本族全部格）")
print("| 册 | 全册本族格 | 强真值格 | 现行 放行/错 | 规则 放行/错 | 其中 干支时辰 | 其中 上下文表 | 送审(强真值) | 送审(全册) | 人审率 前→后 |")
print("|---|---|---|---|---|---|---|---|---|---|")
for bk in ("vol02", "vol03", "vol04"):
    J = [r for r in rows if r["group"] == "jys" and r["book"] == bk]
    U = [r for r in J if (r["char"] or "") in "己已巳" and r["char"] or r["gold"] in ("己", "已", "巳")]
    G = [r for r in U if strongr(r)]
    cur_err = sum(1 for r in G if resolve(r["left"][-1:] or None, r["right"][:1] or None, r["ref"] or r["coord_ref"], "all", r["right"][1:2] or None)[0] != r["gold"])
    n = defaultdict(int); err = 0
    for r in G:
        c, k = new_char(r); n[k] += 1
        err += (c is not None and c != r["gold"])
    nall = defaultdict(int)
    for r in U: nall[new_char(r)[1]] += 1
    auto_g = n["干支/时辰"] + n["上下文表"]
    print(f"| {bk} | {len(U)} | {len(G)} | {len(G)}/{cur_err} | {auto_g}/{err} | {n['干支/时辰']} | {n['上下文表']} | {n['送审']} | {nall['送审']} | 0% → {100*nall['送审']/len(U):.0f}% |")

print("\n### 现有闸 ji_yi_si_review（上下文判定＝整理本字＝库首位 三方一致才放行）在强真值格上")
for bk in ("vol02", "vol03", "vol04"):
    G = [r for r in rows if r["group"] == "jys" and r["book"] == bk and strongr(r)]
    ok = [r for r in G if (r["ref"] or r["coord_ref"]) and r["ctx"] == (r["ref"] or r["coord_ref"]) and (r["lib"][0][0] if r["lib"] else None) == r["ctx"]]
    print(f"  {bk}: 强真值 {len(G)}，三方一致放行 {len(ok)}，其中错 {sum(r['ctx'] != r['gold'] for r in ok)}")
