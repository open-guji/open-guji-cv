"""选判法（离线工具，不进线上）：比两个字的模板笔名序列，建议用哪种笔画判据。

- 只差一笔、其余笔对得上 → 差一笔（verify），给出多出来那一笔在笔多的字模板里的下标；
- 笔名序列一样 → 量几何（geometry）；
- 别的（差两笔以上、部件不同）→ 不适用，交 IDS／HOG。
A24 拿建议去 groups/registry 注册、写死参数（注册表仍是单一真源）。
"""
from __future__ import annotations

from dataclasses import dataclass

from .template import StrokeTemplate


@dataclass(frozen=True)
class PairPlan:
    kind: str                   # "verify" | "geometry" | "none"
    more: str = ""              # verify：笔多的字
    less: str = ""
    stroke: int = -1            # verify：more 模板里多出来的那一笔
    tpl_char: str = ""          # geometry：用哪个字的模板贴
    why: str = ""


def _base(name: str) -> str:
    return name.rstrip("*")


def plan_pair(a: StrokeTemplate, b: StrokeTemplate) -> PairPlan:
    na, nb = [_base(n) for n in a.names], [_base(n) for n in b.names]
    if na == nb:
        return PairPlan("geometry", tpl_char=a.char, why="笔名序列相同")
    if abs(len(na) - len(nb)) == 1:
        more, less = (a, b) if len(na) > len(nb) else (b, a)
        nm, nl = [_base(n) for n in more.names], [_base(n) for n in less.names]
        hits = [k for k in range(len(nm)) if nm[:k] + nm[k + 1:] == nl]
        if hits:
            # 多处可删（如连续两横）时取最后一处：差异笔多在后写
            return PairPlan("verify", more=more.char, less=less.char, stroke=hits[-1],
                            why=f"{more.char} 比 {less.char} 多第 {hits[-1] + 1} 笔「{nm[hits[-1]]}」")
    return PairPlan("none", why=f"笔名序列差太多：{''.join(na)} / {''.join(nb)}")


__all__ = ["PairPlan", "plan_pair"]
