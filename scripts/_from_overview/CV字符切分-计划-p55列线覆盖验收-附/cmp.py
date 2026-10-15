import json,sys
S="/tmp/claude-0/sbx"
def load(root,b,p):
    d=json.load(open(f"{S}/{root}/{b}/cell_shrink/p{p:04d}.json"))["char_index"]
    g=json.load(open(f"{S}/{root}/{b}/column_gate/p{p:04d}.json"))["gate_manifest"]
    return d,g
for b,p in (("vol04",217),("vol04",80),("vol07",130),("vol07",128)):
    for tag,root in (("基线","products"),("n_cols=8","ov8")):
        d,g=load(root,b,p)
        print(b,p,tag,"列宽",[int(c["band_width"]) for c in g["columns"]],"flags",sum(1 for c in g["columns"] if any(f.startswith("column_narrow") for f in c["flags"]+c["reject"])),"被拒列",sum(1 for c in g["columns"] if not c["admitted"]))
        print("   每列(实例/char型/含夹注半格)",[(c["col"],len(c["chars"]),sum(1 for x in c["chars"] if x["cell_type"]=="char"),sum(1 for x in c["chars"] if x.get("sub"))) for c in d["columns"] if c.get("chars")],"总",sum(len(c.get("chars",[])) for c in d["columns"]))
