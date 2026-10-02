import json, glob, collections
import os
E = os.environ["GUJI_WORKSPACE"] + "/feedback/events/*.jsonl"
def human_cells():
    """{cell_id: set(信号)}；信号 = quality:truncated / quality:contaminated / not_a_char / defect:truncated"""
    out = collections.defaultdict(set)
    for f in glob.glob(E):
        for l in open(f):
            try: d = json.loads(l)
            except Exception: continue
            t = d.get("target", {}); pl = d.get("payload", {})
            if t.get("step") not in ("seed_admit", "step8_collate") or not isinstance(pl, dict): continue
            k = t.get("key") or ""
            if not k.startswith(("vol02:", "vol03:")): continue
            if pl.get("quality") in ("truncated", "contaminated"): out[k].add("quality:" + pl["quality"])
            if pl.get("defect") == "truncated": out[k].add("defect:truncated")
            if pl.get("v") == "not_a_char": out[k].add("not_a_char")
    return out
if __name__ == "__main__":
    h = human_cells()
    print(len(h), collections.Counter(s for v in h.values() for s in v))
    print(collections.Counter(k.split(":")[0] for k in h))
