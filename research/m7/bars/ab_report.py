"""量横 A/B 报告：对比 A、B 两臂 seed_admit 逐格结果。
用法：python research/m7/bars/ab_report.py <实验根>/m7_bars-vol04 [强真值 json（id→字，可多个）]
报告：组内（ts、wm 成员字）送审→放行、放行→送审、改字各多少；有强真值的格放对放错；**组外格必须逐格不变**。
"""
import glob, json, sys
from pathlib import Path

root = Path(sys.argv[1])
strong = {}
for f in sys.argv[2:]:
    strong.update({k: v for k, v in json.load(open(f)).items() if len(v) == 1})
MEM = set("土士未末")


def load(arm):
    out = {}
    for f in sorted(glob.glob(str(root / arm / "*" / "seed_admit" / "p*.json"))):
        j = json.load(open(f))["seed_admit"]
        for c in j["columns"]:
            for r in c["chars"]:
                out[r["id"]] = (r.get("char"), bool(r.get("admit")), r.get("channel"), r)
    return out


A, B = load("A"), load("B")
print(f"格数 A={len(A)} B={len(B)}")
outside = [i for i in A if i in B and A[i][:3] != B[i][:3] and not ({A[i][0], B[i][0]} & MEM)]
print("组外格差异（须为 0）：", len(outside))
lift, demote, rechar, same = [], [], [], 0
for i in A:
    if i not in B or A[i][:3] == B[i][:3]:
        continue
    (ca, aa, _, _), (cb, ab, _, rb) = A[i], B[i]
    if not aa and ab: lift.append(i)
    elif aa and not ab: demote.append(i)
    else: rechar.append(i)
print(f"组内：送审→放行 {len(lift)}，放行→送审 {len(demote)}，放行字改变 {len(rechar)}")
for name, ids in (("送审→放行", lift), ("放行→送审", demote), ("改字", rechar)):
    ok = bad = 0
    for i in ids:
        if i in strong:
            if B[i][0] == strong[i]: ok += 1
            else: bad += 1
    print(f"  {name}：有强真值 {ok + bad} 格，B 对 {ok} 错 {bad}")
conf = [i for i in B if ((B[i][3].get("evidence") or {}).get("m7_group") or {}).get("ts", {}).get("why") == "bars_conflict"
        or ((B[i][3].get("evidence") or {}).get("m7_group") or {}).get("wm", {}).get("why") == "bars_conflict"]
print("量横与文意不一致（bars_conflict）格数：", len(conf))
json.dump({"lift": lift, "demote": demote, "rechar": rechar, "conflict": conf, "outside": outside},
          open(root / "ab_ids.json", "w"), ensure_ascii=False)
