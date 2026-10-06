# -*- coding: utf-8 -*-
"""overview#433（R2）：replay.py 的放行清单 × 人裁事件（feedback/events 里 actor=user 的末次裁决）→ 误放。

用法：`python research/review_lanes/vs_human.py <lanes.json> <工作区>/feedback/events <book>`
人裁字与放行字逐字相同记「对」，语义同字面不同记「异体」，其余记「错」；判非字 vs 放字、放非字 vs 人给字都记「错」。"""
import collections, glob, json, sys
from open_guji_cv.clustering.variants import VariantMap

lanes, ev_dir, book = sys.argv[1], sys.argv[2], sys.argv[3]
vm = VariantMap.load(None)
last = {}
for f in glob.glob(f"{ev_dir}/*.jsonl"):
    for line in open(f, encoding="utf-8"):
        try:
            e = json.loads(line)
        except Exception:
            continue
        key = ((e.get("target") or {}).get("key") or "")
        if not key.startswith(book + ":") or e.get("actor") != "user":
            continue
        pl = e.get("payload") or {}
        v = pl.get("v") or e.get("kind")
        if v == "confirm":
            ans = pl.get("shape") or pl.get("reading")
        elif v in ("not_a_char",):
            ans = "<非字>"
        else:
            continue
        if ans and (key not in last or e.get("ts", "") >= last[key][0]):
            last[key] = (e.get("ts", ""), ans)
R = json.load(open(lanes, encoding="utf-8"))
tab = collections.Counter(); bad = []
for x in R:
    if x["lane"].startswith("skip"):
        continue
    got = x["char"] or "<非字>"
    h = last.get(x["id"])
    if not h:
        tab[(x["lane"], "无人裁")] += 1
        continue
    ans = h[1]
    k = "对" if ans == got else ("异体" if "<" not in ans + got and vm.semantic(ans) == vm.semantic(got) else "错")
    tab[(x["lane"], k)] += 1
    if k != "对":
        bad.append((x["lane"], k, x["id"], got, ans))
for ln in sorted({k[0] for k in tab}):
    row = {k[1]: v for k, v in tab.items() if k[0] == ln}
    n = row.get("对", 0) + row.get("异体", 0) + row.get("错", 0)
    print(f"{ln:16s} 放行 {n + row.get('无人裁', 0)}，有人裁 {n}：{row}  错率 {row.get('错', 0) / max(1, n):.1%}")
for b in sorted(bad):
    print("  ", *b)
