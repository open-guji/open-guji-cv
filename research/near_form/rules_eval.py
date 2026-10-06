"""放行规则前后对比（overview#428）。用法：python rules_eval.py items.jsonl
A. 己已巳：现行 resolve 的分路精度；叠加上下文决策表后能多定多少格（S10 人审量）。
B. 形近冲突闸：已放行（非人裁）的字与整理本字/坐标证人字是同组不同字 → 不放行（送审）。
"""
import json, sys
from collections import Counter, defaultdict
sys.path.insert(0, "research/near_form")
from ctx_table import build, decide, GROUPS
from open_guji_cv.utils.ji_yi_si import resolve
rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
paths = ["corpus/external/daizhige_ru_yi.txt", "corpus/external/daizhige_zhaoling.txt"]
strong = lambda r: r["gold"] and r["gold_src"] not in (None, "witness_agree") and r["gold"] in GROUPS[r["group"]]
PUR, MN = 0.98, 5

print("## A 己已巳 现行 resolve 分路（强真值，use_ref=all）")
tab = build(paths, "jys")
jys = [r for r in rows if r["group"] == "jys"]
by = defaultdict(lambda: [0, 0])
for r in jys:
    if not strong(r): continue
    ch, why = resolve(r["left"][-1:] or None, r["right"][:1] or None, r["ref"] or r["coord_ref"], "all", r["right"][1:2] or None)
    k = why.split(":")[0]
    by[(r["book"], k)][1] += 1; by[(r["book"], k)][0] += ch != r["gold"]
for k in sorted(by): print(" ", *k, f"错{by[k][0]}/{by[k][1]}")

print("## A' 全册己已巳格：自动可定（干支/时辰）与上下文表可再定")
for bk in ("vol02", "vol03", "vol04"):
    U = [r for r in jys if r["book"] == bk and ((r["char"] or "") in "己已巳" and r["char"] or r["gold"] in ("己", "已", "巳"))]
    sure = ctx = ctx_dis = tot = 0
    for r in U:
        tot += 1
        ch, why = resolve(r["left"][-1:] or None, r["right"][:1] or None, r["ref"] or r["coord_ref"], "all", r["right"][1:2] or None)
        if why.startswith("干支") or why == "时辰": sure += 1; continue
        c2, w2 = decide(tab, "jys", r["left"][-2:], r["right"][:2], PUR, MN)
        if c2:
            ctx += 1
            cur = r["gold"] if strong(r) else r["char"]
            ctx_dis += (cur is not None and c2 != cur)
    print(f"  {bk}: 己已巳格 {tot}；干支/时辰可定 {sure}；其余里上下文表可定 {ctx}（与现字/真值不同 {ctx_dis}）；仍需人审 {tot-sure-ctx}")

print("## B 形近冲突闸（已放行、非人裁；放行字与整理本/证人字同组不同字）")
cnt = defaultdict(lambda: [0, 0, 0])   # 拦下数, 其中有真值数, 其中放行字错数
adm = Counter()
for r in rows:
    if not (r["admit"] and r["channel"] not in (None, "human") and r["char"] in GROUPS[r["group"]]): continue
    adm[(r["book"], r["group"])] += 1
    for w in (r["ref"], r["coord_ref"]):
        if w and w != r["char"] and w in GROUPS[r["group"]]:
            k = (r["book"], r["group"], r["channel"])
            cnt[k][0] += 1
            if r["gold"] and r["gold_src"] != "witness_agree":
                cnt[k][1] += 1; cnt[k][2] += r["char"] != r["gold"]
            break
for k in sorted(cnt): print(" ", *k, f"拦{cnt[k][0]} 有真值{cnt[k][1]} 其中放行字错{cnt[k][2]}")
print("  已放行非人裁格数", dict(adm))
