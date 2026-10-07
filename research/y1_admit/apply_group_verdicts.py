"""把字组裁决应用到金标：整理看图对「刻形＝系统码位」组判成 wrong（图是正字）的格，口径 A 下系统码位才对 → 记 ok（v_raw 留原值）。
用法：python apply_group_verdicts.py <gold_in.jsonl> <gold_out.jsonl>"""
import json, sys
FAITHFUL = {"𫎇": "𫎇蒙䝉", "㸃": "㸃點", "㕘": "㕘參", "䜟": "䜟讖識", "𨽾": "𨽾隸", "慎": "慎愼", "㫖": "㫖旨"}
n = 0
out = []
for l in open(sys.argv[1], encoding="utf-8"):
    d = json.loads(l)
    g = FAITHFUL.get(d.get("shown"))
    if g and d["v"] == "wrong" and d.get("src") != "用户" and d.get("char") in g and d["char"] != d["shown"]:
        d["v_raw"], d["v"] = d.get("v_raw", "wrong"), "ok"
        d["note"] = (d.get("note") or "") + " [字组裁决：刻形＝系统码位，记对]"
        n += 1
    out.append(d)
open(sys.argv[2], "w", encoding="utf-8").write("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in out))
print(n, "格改记 ok")
