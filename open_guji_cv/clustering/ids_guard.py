# -*- coding: utf-8 -*-
"""IDS（表意文字描述序列）护栏：差一个部件的字对，别让形状判据自己下断言。

## 为什么要它

`NEVER_MATCH_FAMILIES` 是**手工枚举**的 21 对，每对都有实审案底。可它天生
补不全：麗/麓 不在表里，于是「三方一致」通道把 麓 当 麗 放了过去（A 刀回放
实测）。稍/精 0.958、救/枚 0.956、玉/王 0.967 这些也一样——`cov` 是个标量，
对「差一个部件」的字对和「根本不像但 HOG 巧合」的字对**给的分是一个量级**。

IDS 把这件事从「记住哪些字像」变成「算出哪些字只差一个部件」：

| 字对 | IDS | 差异 |
|---|---|---|
| 諭 / 論 | ⿰言俞 / ⿰言侖 | 一个部件 |
| 麗 / 麓 | ⿱丽鹿 / ⿱林鹿 | 一个部件 |
| 稍 / 精 | ⿰禾肖 / ⿰米青 | 两个部件（形近但结构差得远）|
| 玉 / 王 | ⿱一圡 / ⿱一土 | 一个部件 |

**像素域里被摊薄的差别，在结构域里是离散的**——这正是
`glyph_match_research.md` §④ 写下却一直没做的那条便宜路：
「只用 IDS 当护栏，不用它当匹配器」。从图块里抽部件是难题，但**比较两个
候选字的 IDS** 不用碰图像，零训练、零推理成本。

## 数据

`config/ids/ids_lv1.txt`，来自 [yi-bai/ids](https://github.com/yi-bai/ids)（MIT），
zi.tools 同款拆字表，102,031 字。取 lv1 档：笔形差异（丶/乀）已合并，但部件
差异保留——正是护栏要的粒度。

格式有三种要处理：

- `諭\t⿰言俞(.,T,J,K,V,P)` —— 括号里是地区码表标记，剥掉；
- `已\t⿹コ乚(.);⿹コ𠃊(z)` —— 分号分隔的多个写法，取第一个（`.` 档）；
- `人\t#(-丿乀)(.)` —— `#(...)` 是**笔画组合**而非部件组合，这类字
  （人/入/己/巳 这些独体字）本来就没有部件可比，直接标记为「不可比」。

## 纪律：护栏只降档，不改判

命中只把 `same` 降成 `unsure`，交给上下文/人。**错拦的代价是「少一次自动
采信」，错放的代价是「一个字被判死」**——两者不对称，所以护栏宁可多拦。
这也是 confusable.py 里 FONT_TABLE 与 NEVER_MATCH_FAMILIES 门槛不同的同一条理由。

`confusable-context` 154 题实测过：形近位上字形层 top-1 只有 64.3%，**低于
多数类基线 76.0%**。所以「降档」不是损失，是把题交给更会做的那一方。
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_CFG = Path(__file__).resolve().parents[2] / "config"
IDS_TABLE = _CFG / "ids" / "ids_lv1.txt"

# 表意文字描述字符（IDC）：⿰⿱⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻ 及扩展
IDC = set("⿰⿱⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻⿼⿽⿾⿿㇯")
_REGION = re.compile(r"\([^)]*\)")


def _clean(seq: str) -> str:
    """剥掉地区码标记、只取第一个写法。返回 "" 表示不可比。"""
    seq = seq.split(";")[0]
    seq = _REGION.sub("", seq).strip()
    # `#(...)` 是笔画组合，不是部件组合——独体字没部件可比
    if not seq or seq.startswith("#"):
        return ""
    return seq


@lru_cache(maxsize=1)
def _table(path: str | None = None) -> dict[str, str]:
    p = Path(path) if path else IDS_TABLE
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split("\t")
        if len(parts) < 2:
            continue
        seq = _clean(parts[1])
        if seq:
            out[parts[0]] = seq
    return out


def ids_of(ch: str, path: str | None = None) -> str:
    """单字的 IDS；表里没有或不可比（独体字）返回 ""。"""
    return _table(path).get(ch, "")


def components(ch: str, path: str | None = None) -> tuple[str, ...]:
    """IDS 里的**部件**（去掉 IDC 结构符）。不可比时返回空元组。"""
    seq = ids_of(ch, path)
    return tuple(c for c in seq if c not in IDC) if seq else ()


def structure(ch: str, path: str | None = None) -> str:
    """结构符序列，如 ⿰ / ⿱ / ⿰⿱。用来判「结构都不同」。"""
    seq = ids_of(ch, path)
    return "".join(c for c in seq if c in IDC) if seq else ""


def component_distance(a: str, b: str, path: str | None = None) -> int | None:
    """两个字的部件差异数；任一不可比时返回 None（**不是 0，也不是无穷**）。

    None 的意思是「这条判据对这一对没有意见」，调用方该退回其他证据，
    而不是当成「不像」或「很像」。人/入、己/巳 这类独体字全落在这里
    ——它们本来就该由手工表 NEVER_MATCH_FAMILIES 管。
    """
    ca, cb = components(a, path), components(b, path)
    if not ca or not cb:
        return None
    if structure(a, path) != structure(b, path):
        # 结构不同：部件再像也不是「差一个部件」那种危险的像
        return max(len(ca), len(cb))
    sa, sb = list(ca), list(cb)
    if len(sa) != len(sb):
        return abs(len(sa) - len(sb)) + sum(1 for x, y in zip(sa, sb) if x != y)
    return sum(1 for x, y in zip(sa, sb) if x != y)


def is_near_form(a: str, b: str, max_diff: int = 1,
                 path: str | None = None) -> bool:
    """同结构且部件差异 ≤ max_diff → 形近，形状判据不该自己下断言。

    默认 1：差一个部件。諭/論、麗/麓、玉/王 都命中；稍/精（⿰禾肖 vs ⿰米青，
    差两个部件）不命中——它俩的 0.958 是 HOG 饱和，不是结构相似。
    """
    if a == b:
        return False
    d = component_distance(a, b, path)
    return d is not None and d <= max_diff


def near_form_in(cands: list, max_diff: int = 1, top: int = 3,
                 path: str | None = None) -> tuple[str, str] | None:
    """候选前 top 名里第一对形近字；没有返回 None。

    `cands` 是 `[(char, score), ...]` 或 `[char, ...]`。
    """
    chars = [c[0] if isinstance(c, (tuple, list)) else c for c in cands[:top]]
    for i, a in enumerate(chars):
        for b in chars[i + 1:]:
            if is_near_form(a, b, max_diff, path):
                return (a, b)
    return None
