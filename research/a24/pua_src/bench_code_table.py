"""X01 benchmark：拿 replay_code_table.py 的输出（TSV）对金标 X01_gold.tsv，出指标（A24 2026-11-06）。
用法：python bench_code_table.py <replay.tsv> [--gold X01_gold.tsv]   退出码 1＝红线不过。
指标：
  错放    金标格回放后字≠金标字（族内字不算错）            红线 0
  漏改    金标格原放行字≠金标字、回放没改也没降审          红线 0
  误改    金标格原放行字＝金标字、回放却改了                红线 0
  仍不一致 全表放行字≠码表字的格（人裁与码表冲突，族内不算） 越小越好，要人来改
  同码异处理 同一个码的各格回放后字不全相同（族外）           红线 0
"""
import argparse, collections, csv, sys
FAM = {"F1001": set("乖垂埀"), "F1055": set("乖垂埀")}
ap = argparse.ArgumentParser(); ap.add_argument("replay"); ap.add_argument("--gold", default=__file__.rsplit("/", 1)[0] + "/X01_gold.tsv")
a = ap.parse_args()
R = {r["格号"]: r for r in csv.DictReader(open(a.replay, encoding="utf-8"), delimiter="\t")}
G = list(csv.DictReader(open(a.gold, encoding="utf-8"), delimiter="\t"))
ok = lambda code, ch, gold: ch == gold or ch in FAM.get(code, ())
bad, miss, over = [], [], []
for g in G:
    r = R.get(g["格号"])
    if r is None:
        miss.append((g["格号"], "回放里没有这格")); continue
    if not ok(g["码"], r["回放后字"], g["金标字"]): bad.append((g["格号"], r["回放后字"], g["金标字"]))
    if not ok(g["码"], r["原放行字"], g["金标字"]) and not r["动作"] and ok(g["码"], r["回放后字"], g["金标字"]) is False: miss.append((g["格号"], r["原放行字"]))
    if ok(g["码"], r["原放行字"], g["金标字"]) and r["动作"] == "改字": over.append(g["格号"])
rest = [r["格号"] for r in R.values() if r["原通道"] != "None" and r["码表字"] and not ok(r["码"], r["回放后字"], r["码表字"])]
by = collections.defaultdict(set)
for r in R.values():
    if r["回放后字"] and r["码"] not in FAM and r["原通道"] != "None" and r["原provenance"] != "human": by[r["码"]].add(r["回放后字"])
split = {c: s for c, s in by.items() if len(s) > 1}
print(f"金标 {len(G)} 格 | 错放 {len(bad)} {bad} | 漏改 {len(miss)} {miss} | 误改 {len(over)} {over}")
print(f"全表 {len(R)} 格有码 | 仍不一致 {len(rest)} 格 | 同码异处理 {len(split)} 码 {split}")
sys.exit(1 if bad or miss or over or split else 0)
