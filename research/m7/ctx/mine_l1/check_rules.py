import json, re, collections, sys
GROUPS = {"zy": "于千子干", "yz": "予子", "guan": "官宫宮", "hou": "侯候𠉀俟", "liang": "兩雨"}
FAMILY = {"宮": "宫", "𠉀": "候"}
rows = [json.loads(l) for l in open("cells.jsonl")]
mined = json.load(open("mined.json"))
def rx(f): return re.compile(re.escape(f).replace("◎", ""))
for g, rules in mined.items():
    mem = GROUPS[g]
    ev = []
    for r in rows:
        txt = r["left"] + "" + r["right"]
        if r["admit"] and r["char"] in mem: ev.append(("adm", FAMILY.get(r["char"], r["char"]), txt, r["id"]))
        if r["ref"] and r["ref"] in mem: ev.append(("ref", FAMILY.get(r["ref"], r["ref"]), txt, r["id"]))
    bad = collections.defaultdict(list)
    for ch, f, a, b in rules:
        p = rx(f)
        for src, lab, txt, cid in ev:
            if lab != ch and p.search(txt): bad[(ch, f)].append((src, lab, cid))
    print(g, "rules", len(rules), "conflicting", len(bad))
    for k, v in bad.items(): print("  ", k, v[:4])
