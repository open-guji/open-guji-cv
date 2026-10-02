"""日/曰 上下文次要判据：前一字（整理本 ref_char，同列上一格，跨列取上一列末格）的分布。
用法：GUJI_SNAP_ROOT=… python context.py samples.jsonl"""
import json, os, sys, collections
SNAP = os.environ["GUJI_SNAP_ROOT"]
R = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
R = [r for r in R if r["admit"] and r["tier"] in ("human", "tri", "dual")]
prev = {"日": collections.Counter(), "曰": collections.Counter()}
nxt = {"日": collections.Counter(), "曰": collections.Counter()}
cache = {}
for r in R:
    k = (r["vol"], r["page"])
    if k not in cache:
        a = json.load(open(f"{SNAP}/{r['vol']}/products/{r['vol']}/align_ref/p{r['page']:04d}.json"))["align_ref"]
        cache[k] = {(c["col"], c["slot"]): c["ref_char"] for c in a.get("coord", [])}
    m = cache[k]
    p, n = m.get((r["col"], r["slot"] - 1)), m.get((r["col"], r["slot"] + 1))
    prev[r["label"]][p or "∅"] += 1
    nxt[r["label"]][n or "∅"] += 1
for lab in "日曰":
    print(lab, "前一字 top12:", prev[lab].most_common(12), " 后一字 top8:", nxt[lab].most_common(8))
tot = {l: sum(prev[l].values()) for l in "日曰"}
for c in ["子", "云", "∅"]:
    print("前字", c, {l: f"{prev[l][c]}/{tot[l]}" for l in "日曰"})
