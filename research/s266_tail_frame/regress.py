import json, glob, re, collections, numpy as np
from pathlib import Path
import os
S = Path(os.environ.get("S266_DIR", "."))
A, B = S / "run_base", S / "run_new"
M = {'char': 'C', 'blank': '.', 'jiazhu_a': 'a', 'jiazhu_b': 'b', 'jiazhu_solo': 's'}
def col(t, pg, c):
    d = json.load(open(S / t / f"p{pg:04d}.json")); return d, next(x for x in d["columns"] if x["col"] == c)
tot = {"base": collections.Counter(), "new": collections.Counter()}
kind_changes = []; moved_nontail = []; ncols = 0; nchg = 0
for f in sorted(A.glob("p*.json")):
    a = json.loads(f.read_text()); b = json.loads((B / f.name).read_text())
    bc = {c["col"]: c for c in b["columns"]}
    for ca in a["columns"]:
        cb = bc[ca["col"]]; ncols += 1
        for x in ca["cells"]: tot["base"][x["kind"]] += 1
        for x in cb["cells"]: tot["new"][x["kind"]] += 1
        if not (ca["ok"] and cb["ok"]): continue
        ba, bn = ca["boundaries"], cb["boundaries"]
        mv = [i for i, (x, y) in enumerate(zip(ba, bn)) if abs(x - y) > 2]
        ka = "".join(M[x["kind"]] for x in ca["cells"]); kb = "".join(M[x["kind"]] for x in cb["cells"])
        if mv or ka != kb: nchg += 1
        # 非列尾：末 3 条格线以外有移动
        if any(i < len(ba) - 3 for i in mv): moved_nontail.append((a["page"], ca["col"], min(mv), ka, kb))
        if ka != kb: kind_changes.append((a["page"], ca["col"], ka, kb))
print(f"列 {ncols}，变化列 {nchg}")
print("格类型计数 base", dict(tot["base"])); print("格类型计数 new ", dict(tot["new"]))
print(f"格类型有变的列 {len(kind_changes)}"); [print("  ", *k) for k in kind_changes]
print(f"非列尾格线有移动的列 {len(moved_nontail)}"); [print("  ", *k) for k in moved_nontail]
# 夹注金标
keys = {}
for fn in glob.glob(os.environ['GUJI_WORKSPACE'] + '/feedback/events/vol03-*.jsonl'):
    for l in open(fn):
        e = json.loads(l); k = (e.get('target') or {}).get('key') or ''
        m = re.fullmatch(r'vol03:(\d+):(\d+):(-?\d+)([ab])', k)
        if m: keys[k] = (int(m[1]), int(m[2]), int(m[3]), m[4])
hit = {"run_base": 0, "run_new": 0}
for k, (pg, c, slot, sub) in keys.items():
    for t in hit:
        _, cc = col(t, pg, c)
        hit[t] += any(x["slot"] == slot and x["kind"] == "jiazhu_" + sub for x in cc["cells"])
print(f"夹注金标（人裁 a/b 半格）{len(keys)} 条：base 命中 {hit['run_base']}，new 命中 {hit['run_new']}")
# 切线金标
fn = glob.glob(os.environ['GUJI_WORKSPACE'] + '/feedback/verdicts/char-segmentation/touching-cuts/items.jsonl')[0]
items = [json.loads(l) for l in open(fn)]
items = [i for i in items if i['anchor'].get('book') == 'vol03' and i.get('status', 'active') == 'active' and 'y' in i['expected']]
E = {"run_base": [], "run_new": []}; Tl = {"run_base": [], "run_new": []}; ch = []
for it in items:
    g = float(it['expected']['y']); pg, c = it['anchor']['page'], it['anchor']['col']; e2 = {}
    for t in E:
        _, cc = col(t, pg, c)
        e = min(abs(x - g) for x in cc['boundaries'][1:]) if cc['ok'] else 999
        E[t].append(e); e2[t] = e
        if it['anchor'].get('slot', 0) >= 18: Tl[t].append(e)
    if abs(e2['run_base'] - e2['run_new']) > 0.5:
        ch.append((f"{pg}:{c}:{it['anchor'].get('slot')}", it['expected'].get('verdict'), round(e2['run_base'], 1), round(e2['run_new'], 1)))
for t in E:
    e = np.array(E[t]); te = np.array(Tl[t]); nt = np.array([x for x, it in zip(E[t], items) if it['anchor'].get('slot', 0) < 18])
    print(f"切线金标 {t}: n={len(e)} 均值 {e.mean():.2f} ≤10px {(e<=10).mean()*100:.1f}% | 列尾(slot≥18) n={len(te)} 均值 {te.mean():.2f} ≤10px {(te<=10).mean()*100:.1f}% | 非列尾 n={len(nt)} 均值 {nt.mean():.2f}")
print("切线金标有变化的条目", ch)
