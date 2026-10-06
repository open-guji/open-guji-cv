import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import collections, common, rules
which = sys.argv[1:] or ["dev"]
items = common.strong(common.load_items())
sets = {"dev": common.DEV, "val": common.VAL, "vol05": common.POOL_GOLD}
for w in which:
    rows = [x for x in items if x["book"] in sets[w]]
    pred, why = {}, {}
    for x in rows:
        l, r = common.ctx(x)
        pred[x["id"]], why[x["id"]] = rules.classify(l, r)
    print(f"== {w}", common.fmt(common.metrics(rows, pred)))
    for b, m in common.by_book(rows, pred).items(): print("  ", b, common.fmt(m))
    c = collections.Counter((why[x["id"]], pred[x["id"]] == x["gold"]) for x in rows if pred[x["id"]])
    for k, v in sorted(c.items()): print("   ", k, v)
    if w == "dev":
        for x in rows:
            if pred[x["id"]] and pred[x["id"]] != x["gold"]:
                l, r = common.ctx(x, 6); print("   错", x["id"], x["gold"], "→", pred[x["id"]], why[x["id"]], l + "【?】" + r)
