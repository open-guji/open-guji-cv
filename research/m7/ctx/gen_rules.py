"""由 char-groups/<组>/context_stats.json 的 external（殆知阁，与《總目》无重叠）pure 键生成单侧 L1 规则草稿。
用法: python gen_rules.py <组> <n_min> <纯度> → 在 stdout 打 yaml 规则片段 + 审计表(stderr)。
筛选不看《總目》的标注：只看外部统计；再由 lab.py 在强真值/C 弱真值上验，有错的键回来人工审后手工剔除。"""
import json, sys, collections
from common import *
g, NMIN, PUR = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
d = json.load(open(CG / g / "context_stats.json"))["corpora"]["external"]["pure"]
by = collections.defaultdict(list)
for side in ("l1", "r1"):
    for key, ch, k, n in d[side]:
        if n >= NMIN and k / n >= PUR and len(key) == 1 and key != "□":
            by[(side, ch)].append((key, k, n))
for (side, ch), L in sorted(by.items()):
    keys = "".join(k for k, _, _ in sorted(L, key=lambda x: -x[2]))
    pat = f"[{keys}]◎" if side == "l1" else f"◎[{keys}]"
    print(f"  - {{id: {g}-ext-{side}-{ch}, char: {ch}, src: external-pure, re: '{pat}', note: 外部语料 {side}→{ch}；n≥{NMIN} 纯度≥{PUR}}}")
