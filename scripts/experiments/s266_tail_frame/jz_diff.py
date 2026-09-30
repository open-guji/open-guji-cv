import json, sys, hashlib
from pathlib import Path
S = Path(sys.argv[1]); A, B = S / "cs_j0", S / "cs_j1"
def h(tag, key):
    f = S / f"cache_{tag}" / "vol03" / "char_patch" / f"{key}.png"
    return hashlib.md5(f.read_bytes()).hexdigest() if f.exists() else None
changed_cells = {}; other = 0; n = 0
for f in sorted(A.glob("p*.json")):
    a = json.loads(f.read_text()); b = json.loads((B / f.name).read_text()); pg = a["page"]
    bc = {c["col"]: c for c in b["columns"]}
    for ca in a["columns"]:
        cb = bc[ca["col"]]
        ra = {(r["slot"], r["sub"]): r for r in ca.get("chars", [])}; rb = {(r["slot"], r["sub"]): r for r in cb.get("chars", [])}
        for k in set(ra) | set(rb):
            n += 1
            x, y = ra.get(k), rb.get(k)
            same = x and y and x["bbox_col"] == y["bbox_col"] and x["flags"] == y["flags"] and x["cell_type"] == y["cell_type"] \
                and (x["patch_key"] is None) == (y["patch_key"] is None) and (x["patch_key"] is None or h("j0", x["patch_key"]) == h("j1", y["patch_key"]))
            if not same:
                changed_cells.setdefault(f"{pg}:{ca['col']}:{k[0]}", []).append((k[1], x and x["flags"], y and y["flags"]))
print("records", n, "changed slots", len(changed_cells))
for k, v in sorted(changed_cells.items(), key=lambda kv: tuple(map(int, kv[0].split(":")))): print(k, v)
json.dump(sorted(changed_cells), open(S / "jz_changed.json", "w"))
