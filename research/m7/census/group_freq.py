"""字组频率统计：整理本里各字组成员的出现次数与占比；异体组另列人裁刻形数。输出 markdown 表。
用法：python research/m7/census/group_freq.py <整理本 txt> [字频表 freq.json]
整理本＝中心库 siku-zongmu 的 corpus/zongmu_wuyingdian_reference.txt（`WorkerSource.fetch_blobs(ext="txt")` 取）；
freq.json＝中心库 config/groups/freq.json（人裁刻形数，异体组用）。
⚠ 整理本已把异体规范成通行字，异体次形在整理本里常为 0，真实刻形占比要看人裁数（偏向被人看过的格）。
"""
import collections, json, sys
from open_guji_cv.groups.registry import GROUPS

ref = open(sys.argv[1], encoding="utf-8").read()
cnt = collections.Counter(c for c in ref if not c.isspace())
fg = json.load(open(sys.argv[2], encoding="utf-8")).get("groups", {}) if len(sys.argv) > 2 else {}
print(f"整理本 {sum(cnt.values())} 字\n")
for kind, title in (("near_form", "形近不同义组（按整理本合计降序）"), ("variant", "异体组")):
    rows = []
    for gid, g in GROUPS.items():
        if g.kind != kind:
            continue
        mem = sorted(g.members, key=lambda c: -cnt[c])
        tot = sum(cnt[c] for c in mem)
        share = " ".join(f"{c}{cnt[c]}({cnt[c] / tot:.0%})" for c in mem) if tot else "—"
        hum = " ".join(f"{c}{n}" for c, n in fg.get(gid, {}).items()) or "—"
        rows.append((tot, gid, g.name, share, hum, "+".join(g.flow.solvers) if g.flow else "—"))
    print(f"### {title}\n\n| 组 | id | 整理本合计 | 各形（占比） | 人裁刻形 | 判法 |\n|---|---|---|---|---|---|")
    for tot, gid, name, share, hum, fl in sorted(rows, reverse=True):
        print(f"| {name} | {gid} | {tot} | {share} | {hum} | {fl} |")
    print()
