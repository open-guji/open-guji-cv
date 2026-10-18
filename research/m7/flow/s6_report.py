"""S6 A/B 报告（doc/exp/group_flow-S6-vol04-报告.md）：A＝旧开关（rc/v0.3.3 5297b85），B＝旧开关删除＋group_flow 全组。
  python research/m7/flow/s6_report.py <实验目录> <B 臂名> [--book vol04] [--ws <工作区>] [--snap <快照 products 根>] [--detail N]
组相关格：A 字、B 字、整理本字、真值、库 top1 任一落在某个声明了 flow 的组里，或 B 写了 evidence.group。
其余＝组外格，必须逐格不变。
真值：jys/ry/rr 用 dataset char-groups 强真值（A_human/B_vision，按文意）；ry/rr 无强真值时及其余各组用工作区人裁刻形。
"""
import argparse, collections, glob, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from open_guji_cv.groups.freq import human_shapes  # noqa: E402
from open_guji_cv.groups.registry import GROUPS  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("exp"); ap.add_argument("arm"); ap.add_argument("--book", default="vol04")
ap.add_argument("--ws", default="/home/user/guji-workspace/96mid1ogzk-欽定四庫全書總目武英殿刻本")
ap.add_argument("--gold", default="/home/user/open-guji/open-guji-dataset/char-groups")
ap.add_argument("--snap", default="/home/user/snap/products")
ap.add_argument("--detail", type=int, default=40)
a = ap.parse_args()
FG = [g for g, s in GROUPS.items() if s.flow]
MEM = {ch: g for g in FG for ch in GROUPS[g].members}


def load(arm):
    out = {}
    for f in glob.glob(str(Path(a.exp) / arm / a.book / "seed_admit" / "p*.json")):
        for col in json.load(open(f, encoding="utf-8"))["seed_admit"]["columns"]:
            for c in col["chars"] or []:
                out[c["id"]] = c
    return out


A, B = load("A"), load(a.arm)
ref = {}
for f in glob.glob(f"{a.snap}/{a.book}/align_ref/p*.json"):
    for c in json.load(open(f, encoding="utf-8"))["align_ref"]["chars"]:
        ref[c["id"]] = c.get("align_char")
top1 = {}
for f in glob.glob(f"{a.snap}/{a.book}/glyph_match/p*.json"):
    d = json.load(open(f, encoding="utf-8"))
    for col in d["glyph_match"]["columns"]:
        for c in col.get("chars") or []:
            if c.get("candidates"):
                top1[c["id"]] = c["candidates"][0][0]
shape = human_shapes(Path(a.ws))
gold = {}
for g in ("jys", "ry", "rr"):
    p = Path(a.gold) / g / "items.jsonl"
    for line in p.open(encoding="utf-8"):
        r = json.loads(line)
        if r.get("gold_tier") in ("A_human", "B_vision") and r["id"].startswith(a.book + ":"):
            gold[r["id"]] = r["gold"]


def truth(cid, g):
    if cid in gold:
        return gold[cid]
    if g == "jys":
        return None          # 己已巳刻形不分，人裁刻形不当读法真值
    return shape.get(cid)


def grp(cid, x, b):
    ev = (b.get("evidence") or {}).get("group")
    if ev:
        return ev["id"]
    for ch in (x.get("char"), b.get("char"), ref.get(cid), gold.get(cid), top1.get(cid)):
        if ch in MEM:
            return MEM[ch]
    return None


def adm(c):
    return c.get("char") if c.get("admit") else None


outside = []
stat = collections.defaultdict(collections.Counter)
det = collections.defaultdict(list)
for cid, b in B.items():
    x = A.get(cid)
    if x is None:
        outside.append((cid, "A 缺")); continue
    g = grp(cid, x, b)
    ka, kb = adm(x), adm(b)
    if g is None:
        if ka != kb:
            outside.append((cid, ka, kb, x.get("channel"), b.get("channel")))
        continue
    t = truth(cid, g)
    s = stat[g]
    s["cells"] += 1
    for arm, k in (("A", ka), ("B", kb)):
        if k is not None:
            s[f"{arm}放"] += 1
            s[f"{arm}放" + ("?" if t is None else ("对" if t == k else "错"))] += 1
    if ka == kb:
        continue
    ev = (b.get("evidence") or {}).get("group") or {}
    tag = None
    if ka is None:
        tag = "审→放" + ("?" if t is None else ("对" if t == kb else "错"))
    elif kb is None:
        tag = "放→审" + ("?" if t is None else ("降对" if t != ka else "降错"))
    else:
        tag = "改字" + ("?" if t is None else ("对" if t == kb else "错"))
    s[tag] += 1
    det[g].append(f"{tag} {cid}：A {ka}（{x.get('channel')}）→ B {kb}（{b.get('channel')}）ref={ref.get(cid)} 真值={t} "
                  f"B证据={ev.get('mode')}/{ev.get('decision')} pick={ev.get('pick')} "
                  + " ".join(f"{s_['solver']}:{s_['char']}" for s_ in ev.get("solvers") or []))
print(f"# S6 A/B（{a.book}，A vs {a.arm}）\n\n格数 A={len(A)} B={len(B)}；强真值 {len(gold)}、人裁刻形 {len(shape)}\n")
print(f"组外格变了的：**{len(outside)}**")
for o in outside[:20]:
    print("-", o)
cols = ["cells", "A放", "A放对", "A放错", "A放?", "B放", "B放对", "B放错", "B放?",
        "审→放对", "审→放错", "审→放?", "放→审降对", "放→审降错", "放→审?", "改字对", "改字错", "改字?"]
print("\n| 组 | " + " | ".join(cols) + " |\n|" + "---|" * (len(cols) + 1))
tot = collections.Counter()
for g in sorted(stat, key=lambda g: -stat[g]["cells"]):
    tot.update(stat[g])
    print(f"| {g} {GROUPS[g].name} | " + " | ".join(str(stat[g][c]) for c in cols) + " |")
print("| 合计 | " + " | ".join(str(tot[c]) for c in cols) + " |")
na, nb = sum(1 for c in A.values() if c.get("admit")), sum(1 for c in B.values() if c.get("admit"))
print(f"\n放行格：A={na}，B={nb}（{nb - na:+d}）\n")
for g in det:
    print(f"\n### {g} {GROUPS[g].name}")
    for l in sorted(det[g], key=lambda l: (("错" not in l.split()[0]), l))[:a.detail]:
        print("-", l)
