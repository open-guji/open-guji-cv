"""208is 抽样：切分坏 366 抽 60、非字 123 抽 50；种子 20261014；id 按 tsv 出现顺序读成列表后 random.Random(seed).sample。
用法：python3 208is抽样.py <overview 根> <输出目录>
"""
import random, sys
from pathlib import Path
root, out = Path(sys.argv[1]), Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
D = root / "项目进展/CV候选字挑选/计划"
def ids(p):
    r = []
    for l in open(p, encoding="utf-8"):
        l = l.strip()
        if l and not l.startswith("#") and l != "id":
            r.append(l.split("\t")[0])
    return r
for name, f, n in (("切分坏", "切分坏366格id-Enzo.tsv", 60), ("非字", "非字123格id-Enzo.tsv", 50)):
    L = ids(D / f)
    s = random.Random(20261014).sample(L, n)
    (out / f"抽样_{name}_{n}.txt").write_text("\n".join(s) + "\n", encoding="utf-8")
    print(name, len(L), "→", len(s))
