# -*- coding: utf-8 -*-
"""收回 jys2 放行复核页的裁决：并入 jys/items.jsonl 的真值（A 档，src user_review_jys2，排最前、后到覆盖），
再按分层算放行错率（Wilson 95%）。不碰快照；用法：merge_jys2.py（读 dataset char-groups/review/jys2_*）。"""
import json, math, sys, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common

R = common.DATASET / "char-groups" / "review"
ver = {json.loads(l)["id"]: json.loads(l)["verdict"] for l in open(R / "jys2_verdicts.jsonl", encoding="utf-8")}
cards = {json.loads(l)["id"]: json.loads(l) for l in open(R / "jys2_cards.jsonl", encoding="utf-8")}
preds = {json.loads(l)["id"]: json.loads(l) for l in open(common.JYS_DIR / "classifier_preds.jsonl", encoding="utf-8")}

# 1 并入 items.jsonl
p = common.JYS_DIR / "items.jsonl"
rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
for r in rows:
    v = ver.get(r["id"])
    if v is None or not r["core"]:
        continue
    if v in common.FAM:
        old = r["gold"] if r["gold_tier"] in common.STRONG else None
        r["golds"] = [{"char": v, "tier": "A_human", "src": "user_review_jys2",
                       "note": "放行复核页（Z-jys，overview#443）" + (f"；覆盖旧真值 {old}" if old and old != v else "")}] + r["golds"]
        r["gold"], r["gold_tier"], r["label_origin"], r["gold_src"] = v, "A_human", "human", "user_review_jys2"
        r["gold_conflict"] = len({g["char"] for g in r["golds"] if g["tier"] in common.STRONG}) > 1
    else:
        r["golds"] = [{"char": None, "tier": "X_unclear", "src": "user_review_jys2", "note": v}] + r["golds"]
p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def wilson(k, n, z=1.96):
    if n == 0: return (0, 1)
    ph = k / n; d = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / d; h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / d
    return max(0, c - h), min(1, c + h)


# 2 放行错率：只数分层抽样的 30 格（不含 recheck），按层，权重 = 框内格数/抽中格数
S = collections.defaultdict(lambda: [0, 0, 0])   # 层 → [裁出可用, 错, 看不清]
W = {}
out = {"strata": {}, "recheck": {}}
for i, c in cards.items():
    if c["stratum"] == "recheck":
        out["recheck"] = {"id": i, "旧真值": "己", "新人裁": ver[i], "分类器": preds[i]["final"]}
        continue
    v = ver[i]; W[c["stratum"]] = (c["frame_n"], c["picked"])
    if v not in common.FAM:
        S[c["stratum"]][2] += 1; continue
    S[c["stratum"]][0] += 1
    S[c["stratum"]][1] += v != preds[i]["final"]
tot_n = tot_k = 0; est = 0.0; var = 0.0
for s, (n, k, u) in sorted(S.items()):
    N, m = W[s]; lo, hi = wilson(k, n)
    out["strata"][s] = {"框内格数": N, "抽中": m, "可用": n, "错": k, "看不清": u, "错率": round(k / n, 3) if n else None,
                        "wilson95": [round(lo, 3), round(hi, 3)]}
    tot_n += n; tot_k += k
    if n:
        est += N * k / n; var += N * N * (k / n) * (1 - k / n) / n
frame = sum(W[s][0] for s in W)
out["total"] = {"抽样可用": tot_n, "错": tot_k, "框内格数": frame, "估计错格数": round(est, 1),
                "估计错率": round(est / frame, 4), "1.96se": round(1.96 * math.sqrt(var) / frame, 4)}
# 无错层的 Wilson 上界
(R / "jys2_analysis.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=1))
for i, v in ver.items():
    if i in preds and preds[i]["final"] != v and cards[i]["stratum"] != "recheck": print("错", i, "给", preds[i]["final"], "人裁", v, preds[i]["by"])
