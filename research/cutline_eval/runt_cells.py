"""矮格预警(评测外挂,不进 row_segment/triage):字格(kind=char)高 < RATIO×period,flags 为空,且非 raised/sub。
只读产物 `row_segment/p*.json`,不重算。用法: python3 -I runt_cells.py <row_segment 目录> [<目录> ...] [--ratio 0.6]"""
import sys, json, glob, os
ratio = 0.6
args = [a for a in sys.argv[1:] if not a.startswith("--")]
if "--ratio" in sys.argv: ratio = float(sys.argv[sys.argv.index("--ratio") + 1]); args = [a for a in args if a != str(ratio)]
for d in args:
    n = 0; hits = []; pages = 0
    for f in sorted(glob.glob(os.path.join(d, "p*.json"))):
        try: cs = json.load(open(f))["cells"]
        except Exception: continue
        pages += 1; per = cs.get("period") or 113; pg = int(os.path.basename(f)[1:-5])
        for c in cs["columns"]:
            for cell in c["cells"]:
                if cell["kind"] != "char": continue
                n += 1; h = cell["y1"] - cell["y0"]
                if h < ratio * per and not cell["flags"] and not cell.get("raised") and not cell.get("sub"):
                    hits.append((pg, c["col"], cell["slot"], round(h), round(per), round(h / per, 2), "tail(末格)" if cell["slot"] == c.get("n_body_slots") else ""))
    print(f"{d.split('products/')[-1]}: {pages} 页,{n} 个字格,矮格(<{ratio}×period,无 flag,非 raised/sub){len(hits)} 个({len(hits)/max(1,n):.3%})")
    for h in hits: print("  页%d 列%d slot%d 高%dpx period%d 比%.2f %s" % h)
