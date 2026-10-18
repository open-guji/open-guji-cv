"""字组统一流程 group_flow 的 A/B 报告：组内格升降对错 ＋ 组外格必须逐格不变。

  python research/m7/flow/flow_report.py <实验目录> <工作区> [--book vol04] [--gold <dataset>/char-groups] [--out report.md]

真值：形近组（jys／ry／rr）用 dataset char-groups 强真值（A_human、B_vision，按文意）；其余用工作区人裁刻形
（`groups.freq.human_shapes`：字形库 human 标注＋confirm 事件）。没有真值的格只报数。
"""
import argparse
import collections
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from open_guji_cv.groups.freq import human_shapes  # noqa: E402
from open_guji_cv.groups.registry import GROUPS  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("exp"); ap.add_argument("workspace"); ap.add_argument("--book", default="vol04")
ap.add_argument("--gold", default="/home/user/open-guji/open-guji-dataset/char-groups"); ap.add_argument("--out", default="")
a = ap.parse_args()
NEAR = ("jys", "ry", "rr")


def load(arm):
    out = {}
    for f in glob.glob(str(Path(a.exp) / arm / a.book / "seed_admit" / "p*.json")):
        for col in json.load(open(f, encoding="utf-8"))["seed_admit"]["columns"]:
            for c in col["chars"] or []:
                out[c["id"]] = c
    return out


A, B = load("A"), load("B")
shape = human_shapes(Path(a.workspace))
gold = {}
for g in NEAR:
    p = Path(a.gold) / g / "items.jsonl"
    if p.exists():
        for line in p.open(encoding="utf-8"):
            r = json.loads(line)
            if r.get("gold_tier") in ("A_human", "B_vision"):
                gold[r["id"]] = r["gold"]


def truth(cid, g):
    if g in NEAR and cid in gold:
        return gold[cid]
    return shape.get(cid)


def key(c):
    return (bool(c.get("admit")), c.get("char") if c.get("admit") else None)


lines = []
P = lines.append
P(f"# group_flow A/B 报告（{a.book}）\n\n格数 A={len(A)} B={len(B)}；有真值的格：人裁刻形 {len(shape)}、形近组强真值 {len(gold)}\n")
outside, rows = [], collections.defaultdict(list)
entered = collections.Counter()
why = collections.defaultdict(collections.Counter)
for cid, b in B.items():
    ev = (b.get("evidence") or {}).get("group")
    x = A.get(cid)
    if x is None:
        outside.append((cid, "A 缺")); continue
    if ev:
        entered[ev["id"]] += 1
        why[ev["id"]][f"{ev['mode']}:{ev['decision']}"] += 1
    if key(x) == key(b):
        continue
    if not ev:
        outside.append((cid, key(x), key(b))); continue
    rows[ev["id"]].append((cid, x, b, ev))
P(f"## 一、组外格逐格不变\n\n变了的格里没进流程的：**{len(outside)}**" + ("（必须为 0）" if outside else "，通过") + "\n")
for o in outside[:30]:
    P(f"- {o}")
P("\n## 二、各组\n\n| 组 | 进流程 | 入口:结论 | 送审→放行 | 对/错/无真值 | 放行→送审 | 降对/降错/无真值 |\n|---|---|---|---|---|---|---|")
detail = []
for g in sorted(entered, key=lambda g: -entered[g]):
    up = [r for r in rows[g] if not r[1].get("admit") and r[2].get("admit")]
    dn = [r for r in rows[g] if r[1].get("admit") and not r[2].get("admit")]
    ok = bad = unk = 0
    for cid, x, b, ev in up:
        t = truth(cid, g)
        if t is None:
            unk += 1
        elif t == b["char"]:
            ok += 1
        else:
            bad += 1; detail.append(f"- 错放 {g} {cid}：放 {b['char']}，真值 {t}；{json.dumps(ev['solvers'], ensure_ascii=False)}")
    dok = dbad = dunk = 0
    for cid, x, b, ev in dn:
        t = truth(cid, g)
        if t is None:
            dunk += 1
        elif t != x["char"]:
            dok += 1
        else:
            dbad += 1; detail.append(f"- 错降 {g} {cid}：原放 {x['char']}（{x.get('channel')}），真值 {t}；pick {ev.get('pick')}")
    P(f"| {g} {GROUPS[g].name} | {entered[g]} | {dict(why[g])} | {len(up)} | {ok}/{bad}/{unk} | {len(dn)} | {dok}/{dbad}/{dunk} |")
na, nb = sum(1 for c in A.values() if c.get("admit")), sum(1 for c in B.values() if c.get("admit"))
P(f"\n放行格：A={na}，B={nb}（{nb - na:+d}）；待审：A={len(A) - na}，B={len(B) - nb}\n")
if detail:
    P("## 三、错例\n"); lines.extend(detail)
txt = "\n".join(lines) + "\n"
if a.out:
    Path(a.out).write_text(txt, encoding="utf-8")
print(txt)
