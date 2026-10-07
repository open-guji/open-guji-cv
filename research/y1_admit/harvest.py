# -*- coding: utf-8 -*-
"""回收待标审查页的裁决 → 看图结论.jsonl 同格式（可直接当 `guji exp` 的 `source: vision` 标签）。
用法：先 Artifact action:"read" 把页读到本地，再  python harvest.py page.html out.jsonl
对→v=ok；错→v=wrong（char=用户填的正字）；拿不准→v=unsure。judge=user，口径 A（按刻形，不并通行字）。"""
import json, re, sys, time
html = open(sys.argv[1], encoding="utf-8").read()
d = json.loads(re.search(r'<script[^>]*id="data"[^>]*>(.*?)</script>', html, re.S).group(1).replace("<\\/", "</"))
rows = {r["id"]: r for r in d["rows"]}
n = {"ok": 0, "wrong": 0, "unsure": 0, "wrong_no_char": 0}
with open(sys.argv[2], "w", encoding="utf-8") as f:
    for k, s in (d.get("verdicts") or {}).items():
        v = {"ok": "ok", "wrong": "wrong", "idk": "unsure"}.get(s.get("v"))
        if not v or k not in rows:
            continue
        rec = {"cell": k, "v": v, "shown": rows[k]["sug"], "judge": "user",
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(s.get("t", 0) / 1000)),
               "note": "[Y1 待标页] 用户裁决"}
        if v == "wrong":
            if s.get("c"):
                rec["char"] = s["c"]
            else:
                n["wrong_no_char"] += 1
        n[v] += 1
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
print(n)
