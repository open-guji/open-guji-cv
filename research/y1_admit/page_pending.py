# -*- coding: utf-8 -*-
"""四册待审集中页 + 页型（overview#493）。用法：python page_pending.py <导出 jsonl> [vol01 页型 items.jsonl]
输出：待审最集中的前 N 页（待审/全页/桶/列），及（vol01）按人工页型 toc/roster/edict/colophon/body 的待审数。
页型的人工标签只有 vol01、vol02（feedback/verdicts/page-type/items.jsonl）；其余册靠看图。"""
import json, sys, collections, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bucket_pending.py"), encoding="utf-8").read()
ns = {"re": re}
exec("import re\n" + src[src.index("norm = lambda"):src.index("T = {}")], ns)
bucket = ns["bucket"]
ex = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
pend = [d for d in ex if not d["admit"]]
tot = collections.Counter(int(d["id"].split(":")[1]) for d in ex)
pg = collections.defaultdict(list)
for d in pend:
    pg[int(d["id"].split(":")[1])].append(d)
for p, ds in sorted(pg.items(), key=lambda kv: -len(kv[1]))[:12]:
    print(f"p{p} 待审{len(ds)}/全页{tot[p]} 桶{dict(collections.Counter(bucket(d) for d in ds).most_common(3))} "
          f"列{dict(collections.Counter(int(d['id'].split(':')[2]) for d in ds).most_common(4))}")
if len(sys.argv) > 2:
    pt = {}
    for l in open(sys.argv[2], encoding="utf-8"):
        d = json.loads(l)
        if d["anchor"]["book"] == ex[0]["id"].split(":")[0]:
            pt[d["anchor"]["page"]] = d["expected"]["page_type"]
    c = collections.Counter()
    for d in pend:
        c[(pt.get(int(d["id"].split(":")[1]), "?"), "excluded" in d["doubts"])] += 1
    print("按页型（页型, 是否 excluded）待审：", sorted(c.items()))
