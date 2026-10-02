"""Y1：标定阈值 X —— 每册命中率、新增待审、人裁线索召回。python y1_analyze.py <结果目录> [MAXSEAL]"""
import json, sys, os, collections
sys.path.insert(0, os.path.dirname(__file__))
from y1_human import human_cells
S = sys.argv[1]            # 放 d_<book>.jsonl（y1_calibrate 输出）的目录
PRODS = os.environ["GUJI_PRODUCTS_DIR"]
H = human_cells()
data = {}
for b in ("vol03", "vol02"):
    f = f"{S}/d_{b}.jsonl"
    if not os.path.exists(f): continue
    for l in open(f):
        d = json.loads(l)
        if b == "vol03" and 105 <= d["page"] <= 108: continue
        if os.path.exists(f"{S}/seal_{b}.json"):   # 旧结果没记印章格数时用单独量的
            d["seal"] = json.load(open(f"{S}/seal_{b}.json")).get(str(d["page"])) or 0
        data[(b, d["page"])] = d
def admit_map(b, pg):
    try: d = json.load(open(f"{PRODS}/{b}/seed_admit/p{pg:04d}.json"))["seed_admit"]
    except Exception: return {}
    return {c["id"]: c for col in d["columns"] if col.get("ok", True) for c in col.get("chars", [])}
AM = {k: admit_map(*k) for k in data}
MAXSEAL = int(sys.argv[2]) if len(sys.argv) > 2 else 2   # 页内 seal_region 格数 > 这个 = 印章页弃权
THR = [0.03, 0.04, 0.05, 0.06, 0.08, 0.1, 0.15]
for b in ("vol03", "vol02"):
    pages = [k for k in data if k[0] == b]
    if not pages: continue
    print(f"== {b}：{len(pages)} 页")
    ab = [k for k in pages if data[k]["seal"] > MAXSEAL]   # seal = page_occluded 命中格数
    print(f"   印章页弃权(seal>{MAXSEAL}): {len(ab)} 页 {sorted(k[1] for k in ab)[:12]}")
    rows = [dict(r, b=b, seal=data[k]["seal"]) for k in pages if k not in ab for r in data[k]["rows"]]
    nm = [r for r in rows if r["ratio"] is not None]
    adm = lambda r: AM[(b, r["page"])].get(r["id"], {}).get("admit")
    print(f"   格 {len(rows)}，YOLO 配上 {len(nm)}（弃权 {len(rows)-len(nm)}）；其中原本自动放行 {sum(1 for r in nm if adm(r))}")
    hum = {k: v for k, v in H.items() if k.startswith(b + ":") and (b, int(k.split(":")[1])) in data and (b, int(k.split(":")[1])) not in ab}
    hid = {r["id"]: r for r in rows}
    hum_in = {k: v for k, v in hum.items() if k in hid}
    print(f"   人裁线索格（truncated/contaminated/not_a_char）落在已量页的: {len(hum_in)}，其中 YOLO 配上 {sum(1 for k in hum_in if hid[k]['ratio'] is not None)}")
    print("   X     命中格  占配上%  其中原本自动放行(=新增待审)  每页新增待审  人裁线索命中  命中里有人裁线索")
    e = collections.Counter(r.get("edge", "?") for r in nm if r["ratio"] > 0.15)
    e0 = collections.Counter(r.get("edge", "?") for r in nm if (r.get("ratio0") or 0) > 0.15)
    print(f"   X=0.15 命中的位置分布：跳版框侧 {dict(e)}；不跳版框侧 {dict(e0)}")
    for t in THR:
        fl = [r for r in nm if r["ratio"] > t]
        newrev = [r for r in fl if adm(r)]
        rec = sum(1 for k in hum_in if hid[k]["ratio"] is not None and hid[k]["ratio"] > t)
        prec = sum(1 for r in fl if r["id"] in H)
        print(f"   {t:<5} {len(fl):5d}  {100*len(fl)/max(1,len(nm)):5.2f}%   {len(newrev):5d}                    {len(newrev)/len(pages):5.2f}        {rec}/{len(hum_in)}        {prec}/{len(fl)}")
