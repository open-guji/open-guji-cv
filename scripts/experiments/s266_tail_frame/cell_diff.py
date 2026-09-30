import json, sys
from pathlib import Path
import os
S = Path(os.environ.get("S266_DIR", "."))
TARGETS = set("11:1:21 17:1:21 17:3:21 17:7:21 18:4:21 18:7:21 25:1:21 25:2:21 25:4:21 28:1:20 28:1:21 42:4:21 43:3:21 43:4:20 43:4:21 43:7:20 43:7:21 47:1:21 48:6:21 64:7:21 70:6:20 72:2:21 80:5:21 88:2:21 89:8:21 104:8:21 110:1:21".split())
out = []
for f in sorted((S / "cs_new").glob("p*.json")):
    a = json.loads((S / "cs_base" / f.name).read_text()); b = json.loads(f.read_text())
    pg = b["page"]
    bc = {c["col"]: c for c in b["columns"]}
    for ca in a["columns"]:
        cb = bc.get(ca["col"])
        if not cb or not ca["ok"] or not cb["ok"]: continue
        ra = {(r["slot"], r["sub"]): r for r in ca["chars"]}; rb = {(r["slot"], r["sub"]): r for r in cb["chars"]}
        for k in sorted(set(ra) | set(rb), key=lambda k: (k[0], k[1] or "")):
            x, y = ra.get(k), rb.get(k)
            if x and y and x["cell_type"] == y["cell_type"] and x["patch_key"] and y["patch_key"] and \
                    max(abs(p - q) for p, q in zip(x["bbox_col"], y["bbox_col"])) <= 2:
                continue
            if x and y and not x["patch_key"] and not y["patch_key"]:
                continue
            cid = f"{pg}:{ca['col']}:{k[0]}{k[1] or ''}"
            out.append(dict(id=cid, target=cid in TARGETS,
                            base=None if not x else dict(type=x["cell_type"], bbox=[round(v) for v in x["bbox_col"]], patch=x["patch_key"], s3=x["step3_kind"]),
                            new=None if not y else dict(type=y["cell_type"], bbox=[round(v) for v in y["bbox_col"]], patch=y["patch_key"], s3=y["step3_kind"])))
json.dump(out, open(S / "cell_diff.json", "w"), ensure_ascii=False, indent=0)
print("changed cells", len(out), "targets among them", sum(o["target"] for o in out))
import collections
print(collections.Counter((o["base"] or {}).get("type", "-") + "→" + (o["new"] or {}).get("type", "-") + ("" if (o["base"] or {}).get("patch") else " (base无图)") + ("" if (o["new"] or {}).get("patch") else " (new无图)") for o in out))
