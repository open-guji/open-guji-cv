"""对比两套产物（原图 vs 抹斑点反事实）：Step1 线、Step3 边界、Step4 框。
用法: python compare.py <prodsA> <prodsB> <book> <page>"""
import json, sys
import numpy as np
A, B, book, page = sys.argv[1:5]
ld = lambda R, s: json.load(open(f"{R}/{book}/{s}/p{int(page):04d}.json"))
a, b = ld(A, "border_detect")["borders"], ld(B, "border_detect")["borders"]
print("Step1 竖线 x_at_top 差(px):", [round(x["x_at_top"] - y["x_at_top"], 1) for x, y in zip(a["verticals"], b["verticals"])])
print("Step1 top/bottom y_at_right 差:", round(a["top"]["y_at_right"] - b["top"]["y_at_right"], 1), round(a["bottom"]["y_at_right"] - b["bottom"]["y_at_right"], 1))
print("bend_w80_max", a["bend_w80_max"], b["bend_w80_max"], "med", a["bend_w80_med"], b["bend_w80_med"])
ca, cb = ld(A, "row_segment")["cells"]["columns"], ld(B, "row_segment")["cells"]["columns"]
tot = moved = 0; devs = []
for x, y in zip(ca, cb):
    ba, bb = x["boundaries"], y["boundaries"]
    same = len(ba) == len(bb)
    d = np.abs(np.array(ba) - np.array(bb)).max() if same else None
    kinds_a = [c["kind"] for c in x["cells"]]; kinds_b = [c["kind"] for c in y["cells"]]
    print(f"col{x['col']}: n_bound {len(ba)}/{len(bb)}", "maxΔ" if same else "", None if d is None else round(float(d), 1), "kinds differ" if kinds_a != kinds_b else "")
    if same:
        dd = np.abs(np.array(ba) - np.array(bb)); devs += list(dd); moved += int((dd > 5).sum()); tot += len(dd)
print(f"边界总 {tot}  偏差>5px {moved}  中位Δ {np.median(devs):.1f}  max {max(devs):.1f}")
sa, sb = ld(A, "cell_shrink")["char_index"]["columns"], ld(B, "cell_shrink")["char_index"]["columns"]
ds = []
for x, y in zip(sa, sb):
    mb = {c["id"]: c for c in y["chars"]}
    for c in x["chars"]:
        o = mb.get(c["id"])
        if o: ds.append(max(abs(p - q) for p, q in zip(c["bbox_page"], o["bbox_page"])))
ds = np.array(ds); print(f"Step4 框: 配对 {len(ds)} 框，最大边偏差 >5px {(ds>5).sum()}、>15px {(ds>15).sum()}、中位 {np.median(ds):.1f}")
