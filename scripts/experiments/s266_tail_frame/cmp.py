import json, sys, glob, collections
from pathlib import Path
A, B = Path(sys.argv[1]), Path(sys.argv[2])
chg = []; kinds = collections.Counter(); moved_nontail = 0; slotmoves = collections.Counter()
for f in sorted(A.glob("p*.json")):
    a = json.loads(f.read_text()); b = json.loads((B / f.name).read_text())
    pg = a["page"]
    bc = {c["col"]: c for c in b["columns"]}
    for ca in a["columns"]:
        cb = bc[ca["col"]]
        if ca["ok"] != cb["ok"]:
            chg.append((pg, ca["col"], "ok", ca["ok"], cb["ok"])); continue
        if not ca["ok"]: continue
        ba, bb = ca["boundaries"], cb["boundaries"]
        ka = [(c["slot"], c["kind"]) for c in ca["cells"]]; kb = [(c["slot"], c["kind"]) for c in cb["cells"]]
        d = [round(y - x) for x, y in zip(ba, bb)]
        if any(abs(x) > 2 for x in d) or ka != kb:
            moved = [i for i, x in enumerate(d) if abs(x) > 2]
            for i in moved: slotmoves[i] += 1
            chg.append((pg, ca["col"], "moved", moved, d[-4:], ka != kb, cb.get("flags")))
print("changed cols", len(chg))
print("boundary index moved counts", sorted(slotmoves.items()))
for c in chg: print(*c)
