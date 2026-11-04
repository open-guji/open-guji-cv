"""把 vol20–99 ★main 产物里字组相关的格摊成 cells.json：[{id,vol,admit,char,ref,op,channel,grp,dec,pick,doubts}]。
字组相关＝字或整理本字在 `groups` 登记的任一字组成员里。用法：python dump_cells.py <产物根> <输出.json> [volNN,…]"""
import glob, json, sys, os
from open_guji_cv.groups.registry import FLOW_GROUPS, GROUPS
root, out = sys.argv[1], sys.argv[2]
vols = sys.argv[3].split(",") if len(sys.argv) > 3 else sorted(os.path.basename(d) for d in glob.glob(f"{root}/vol*"))
mem = set()
for g in list(FLOW_GROUPS.values()):
    mem |= set(g.members)
res = []
for v in vols:
    al = {}
    for f in glob.glob(f"{root}/{v}/align_ref/p*.json"):
        for c in json.load(open(f))["align_ref"].get("chars", []):
            al[c["id"]] = c
    for f in sorted(glob.glob(f"{root}/{v}/seed_admit/p*.json")):
        d = json.load(open(f))["seed_admit"]
        for col in d["columns"]:
            for c in col["chars"]:
                a = al.get(c["id"], {}); ref = a.get("align_char")
                if (c.get("char") in mem) or (ref in mem):
                    g = (c.get("evidence") or {}).get("group") or {}
                    res.append({"id": c["id"], "vol": v, "admit": bool(c.get("admit")), "char": c.get("char"), "ref": ref,
                                "op": a.get("align_op"), "channel": c.get("channel"), "grp": g.get("id"), "dec": g.get("decision"),
                                "pick": g.get("pick"), "doubts": c.get("doubts")})
json.dump(res, open(out, "w"), ensure_ascii=False)
print(len(res))
