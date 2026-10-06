"""形近字组的上下文决策表（overview#428）。

在语料上数每个组内字的前后文共现，建「决策表」：键 = 前后文片段，值 = 组内各字计数。
判一格时按特异度从高到低查键，第一个满足 `n ≥ min_n` 的键：最高字占比 ≥ purity 就定字，否则弃权
（见过但不纯 → 不往更粗的键退，粗键只会更混）。特异度：(2,2) > (1,1) > (2,0) > (0,2) > (1,0) > (0,1)。

语料 = 域内（《總目》光盘版整理本，一行一列）＋ 外部通用（daizhige）。域内语料与被测刻本同书，
所以**分块留出**：行序切 K 块，一个格只用「不含它自己那一块」的计数（`Table.decide(..., excl=块号)`）；
块号由格的前后 3 字窗口在语料里查到。查不到（异文）→ excl=None，用全表并在报告里记数。
"""
from __future__ import annotations
from collections import defaultdict, Counter

GROUPS = {"jys": "己已巳", "ry": "日曰", "rr": "入人八"}
ORDER = [(2, 2), (1, 1), (2, 0), (0, 2), (1, 0), (0, 1)]
K = 10


class Table:
    def __init__(self, group, domain_paths, ext_paths=(), k=K):
        self.fam = set(GROUPS[group]); self.k = k
        self.ext = defaultdict(Counter)                       # 外部语料，不分块
        self.tot = defaultdict(Counter)                       # 域内总计
        self.blk = [defaultdict(Counter) for _ in range(k)]  # 域内分块
        self.win = defaultdict(set)                           # (l3, r3) → 块号集合
        for p in ext_paths:
            for line in open(p, encoding="utf-8"):
                self._scan(line.strip(), self.ext, None)
        lines = []
        for p in domain_paths:
            lines += [l.strip() for l in open(p, encoding="utf-8") if not l.startswith("#")]
        n = len(lines)
        for i, line in enumerate(lines):
            self._scan(line, self.tot, i * k // max(n, 1))

    def _scan(self, line, tab, blk):
        for i, ch in enumerate(line):
            if ch not in self.fam:
                continue
            for a, b in ORDER:
                if i - a < 0 or i + b >= len(line):
                    continue
                key = ((a, b), line[i - a:i], line[i + 1:i + 1 + b])
                tab[key][ch] += 1
                if blk is not None:
                    self.blk[blk][key][ch] += 1
            if blk is not None:
                l3, r3 = line[max(0, i - 3):i], line[i + 1:i + 4]
                for key in ((l3, r3), (l3, None), (None, r3)):
                    self.win[key].add(blk)

    def block_of(self, left, right):
        """格的前后 3 字窗口所在的块。两侧一起找不到（窗口跨列）就分别按左 3 字、右 3 字找。"""
        for key in ((left[-3:], right[:3]), (left[-3:], None), (None, right[:3])):
            bs = self.win.get(key)
            if bs:
                return min(bs)
        return None

    def counts(self, key, excl):
        c = Counter(self.ext.get(key, ()))
        c.update(self.tot.get(key, ()))
        if excl is not None:
            c.subtract(self.blk[excl].get(key, ()))
        return +c

    def decide(self, prev, nxt, purity=0.98, min_n=5, excl=None):
        P, N = prev or "", nxt or ""
        for a, b in ORDER:
            if len(P) < a or len(N) < b:
                continue
            l, r = (P[len(P) - a:] if a else ""), N[:b]
            c = self.counts(((a, b), l, r), excl)
            n = sum(c.values())
            if n >= min_n:
                ch, k = c.most_common(1)[0]
                if k / n >= purity:
                    return ch, f"ctx{a}{b}:{l}_{r} {k}/{n}"
                return None, f"mixed{a}{b}:{l}_{r} {dict(c)}"
        return None, "none"
