"""M7 A/B 报告：组内格的升降对错 + 组外格必须逐格不变。
  python m7_report.py <A seed_admit 目录> <B seed_admit 目录> <align_ref 目录> [--gold <char-groups>] [--out report.md]
金标：char-groups/<组>/items.jsonl（id、gold、gold_tier）；只用强真值（A_human、B_vision）判对错，其余只报数。
"""
import argparse, collections, glob, json
from pathlib import Path

ap = argparse.ArgumentParser(); ap.add_argument("A"); ap.add_argument("B"); ap.add_argument("align")
ap.add_argument("--gold", default="/home/user/open-guji/open-guji-dataset/char-groups"); ap.add_argument("--out", default="")
a = ap.parse_args()
FAM = {"jys": "己已巳", "ry": "日曰", "rr": "人入八"}
STRONG = ("A_human", "B_vision")
gold = {}
for g in FAM:
    p = Path(a.gold) / g / "items.jsonl"
    if p.exists():
        for l in p.open(encoding="utf-8"):
            r = json.loads(l)
            if r.get("gold_tier") in STRONG:
                gold[r["id"]] = r["gold"]

def load(d):
    out = {}
    for f in glob.glob(str(Path(d) / "*.json")):
        x = json.load(open(f, encoding="utf-8"))["seed_admit"]
        for col in x["columns"]:
            for c in col["chars"]:
                out[c["id"]] = c
    return out
A, B = load(a.A), load(a.B)
ref = {}
for f in glob.glob(str(Path(a.align) / "*.json")):
    for c in json.load(open(f, encoding="utf-8"))["align_ref"]["chars"]:
        ref[c["id"]] = c["align_char"]
allfam = "".join(FAM.values())
def grp(cid):
    gs = []
    for g, m in FAM.items():
        if any(x and x in m for x in (ref.get(cid), A[cid].get("char"), B[cid].get("char"))):
            gs.append(g)
    return gs
key = lambda c: (bool(c.get("admit")), c.get("char") if c.get("admit") else None, c.get("channel") if c.get("admit") else None)
lines = []; P = lines.append
P(f"# M7 A/B 报告\n\n格数 A={len(A)} B={len(B)}，强真值 {len(gold)} 格（char-groups，A_human＋B_vision）\n")
# 组外
out_diff = []
for cid in A:
    if cid not in B:
        out_diff.append((cid, "B 缺")); continue
    if grp(cid):
        continue
    if key(A[cid]) != key(B[cid]):
        out_diff.append((cid, key(A[cid]), key(B[cid])))
n_out = sum(1 for cid in A if not grp(cid))
P(f"## 一、组外格逐格不变\n\n组外 {n_out} 格，**有差异 {len(out_diff)} 格**" + ("（必须为 0）" if out_diff else "，通过 ✔") + "\n")
for x in out_diff[:30]:
    P(f"- {x}")
# 组内
P("\n## 二、组内格（按组；一个字可属多组时各算）\n")
for g, m in FAM.items():
    cells = [cid for cid in A if g in grp(cid)]
    trans = collections.Counter(); rows = collections.defaultdict(list)
    for cid in cells:
        ka, kb = key(A[cid]), key(B[cid])
        if ka == kb:
            t = "不变"
        elif not ka[0] and kb[0]:
            t = "送审→放行"
        elif ka[0] and not kb[0]:
            t = "放行→送审"
        else:
            t = "放行字或通道变"
        trans[t] += 1; rows[t].append(cid)
    P(f"### {g} {m}：{len(cells)} 格\n\n| 变化 | 格数 |\n|---|---|")
    for t in ("不变", "送审→放行", "放行→送审", "放行字或通道变"):
        P(f"| {t} | {trans[t]} |")
    def judged(ids, side):
        ok = bad = unk = 0
        for cid in ids:
            c = (A if side == "A" else B)[cid]
            gg = gold.get(cid)
            if gg is None:
                unk += 1
            elif c.get("char") == gg:
                ok += 1
            else:
                bad += 1
        return ok, bad, unk
    for t, side in (("送审→放行", "B"), ("放行→送审", "A"), ("放行字或通道变", "B")):
        ids = rows[t]
        if ids:
            ok, bad, unk = judged(ids, side)
            what = {"送审→放行": "B 放行字", "放行→送审": "A 原放行字（降掉的）", "放行字或通道变": "B 放行字"}[t]
            P(f"\n- **{t}**（{what} 对金标）：对 {ok}，错 {bad}，无强真值 {unk}")
            for cid in ids[:6]:
                P(f"  - {cid}  A={key(A[cid])}  B={key(B[cid])}  整理本={ref.get(cid)}  金标={gold.get(cid)}  m7={ (B[cid].get('evidence') or {}).get('m7_group')}")
    # 有金标的放行错
    for side, D in (("A", A), ("B", B)):
        adm = [c for c in cells if D[c].get("admit") and c in gold]
        err = [c for c in adm if D[c].get("char") != gold[c]]
        P(f"\n- {side} 臂：有强真值的已放行格 {len(adm)}，放行错 {len(err)}")
    P("")
txt = "\n".join(lines)
if a.out:
    Path(a.out).write_text(txt, encoding="utf-8")
print(txt)
