# -*- coding: utf-8 -*-
"""IDS 反查：给一个结构描述，Unicode 里有没有这个字。

## 为什么要它（字形库 04 的补件，2026-09-25）

人把刻例标成「最近似码位 / 无码」时要写下它的实际结构（IDS）。很多「Unicode 里
没有」的字其实在扩展 B–I 区有编码，只是常用字体里不显示、人想不起来。所以标之前
先拿这条 IDS 反查一遍 `config/ids/ids_lv1.txt`（yi-bai/ids，10.2 万字）：

- `exact`：表里某字的某种拆法与输入**逐字相同**；
- `expanded`：两边把部件**逐层展开到底**后相同（`⿰言俞` 与 `⿰言⿱亼⿰月巜` 这类
  拆到不同深度的写法）；
- `near`：按写出来的样子（不展开）逐 token 比，编辑距离 ≤2——换了一个部件、或
  结构符不同（供人挑）。不在展开到笔画的层面比：那一层 `⿰木⿱亠口` 会与
  笔画凑巧相同的 𡘗 判成零差，结构信息全丢。

前两档命中 = 「这个结构已经有码位」，应当改字而不是标「最近似」。
Unicode 标准本身不给逐字 IDS（Unihan 没有这一栏），社区表是唯一全量来源。
"""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache

from .ids_struct import load_table, tokenize

#: 表意文字描述符（含 Unicode 15.1 新增的 ⿼⿽⿾⿿ 与 ㇯）
IDC = set("⿰⿱⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻⿼⿽⿾⿿㇯")
_MAX_DEPTH = 8


def _is_decomposable(seq: str, ch: str) -> bool:
    return bool(seq) and not seq.startswith("#") and seq != ch and seq[0] in IDC


@lru_cache(maxsize=None)
def _expand_char(ch: str, depth: int = 0) -> tuple[str, ...]:
    """一个部件字 → 展开到底的 token 序列（取主拆法）。展不开就是它自己。"""
    e = load_table().get(ch)
    if e is None or depth >= _MAX_DEPTH or not _is_decomposable(e.primary, ch):
        return (ch,)
    return _expand_tokens(tuple(tokenize(e.primary)), depth + 1)


def _expand_tokens(toks: tuple[str, ...], depth: int = 0) -> tuple[str, ...]:
    out: list[str] = []
    for t in toks:
        if t in IDC or len(t) != 1:
            out.append(t)
        else:
            out.extend(_expand_char(t, depth))
    return tuple(out)


def expand(seq: str) -> tuple[str, ...]:
    return _expand_tokens(tuple(tokenize(seq.replace(" ", ""))))


@lru_cache(maxsize=1)
def _index():
    """(原样拆法 → 字集, 展开后 → 字集, 部件 → 字集, 字 → 各拆法 token)。首次约数秒。"""
    raw: dict[str, set[str]] = defaultdict(set)
    full: dict[tuple, set[str]] = defaultdict(set)
    by_comp: dict[str, set[str]] = defaultdict(set)
    toks_of: dict[str, list[tuple[str, ...]]] = {}
    for ch, e in load_table().items():
        ts = []
        for alt in e.alts:
            if not _is_decomposable(alt, ch):
                continue
            raw[alt].add(ch)
            full[expand(alt)].add(ch)
            t = tuple(tokenize(alt))
            ts.append(t)
            for c in t:
                if c not in IDC:
                    by_comp[c].add(ch)
        if ts:
            toks_of[ch] = ts
    return raw, full, by_comp, toks_of


def _edit(a: tuple[str, ...], b: tuple[str, ...], cap: int) -> int:
    """token 序列编辑距离，超过 cap 提前返回 cap+1。"""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, y in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def _block(ch: str) -> str:
    o = ord(ch[0])
    for lo, hi, name in ((0x4E00, 0x9FFF, "基本区"), (0x3400, 0x4DBF, "扩A"),
                         (0x20000, 0x2A6DF, "扩B"), (0x2A700, 0x2B73F, "扩C"),
                         (0x2B740, 0x2B81F, "扩D"), (0x2B820, 0x2CEAF, "扩E"),
                         (0x2CEB0, 0x2EBEF, "扩F"), (0x2EBF0, 0x2EE5F, "扩I"),
                         (0x30000, 0x3134F, "扩G"), (0x31350, 0x323AF, "扩H"),
                         (0xF900, 0xFAFF, "兼容区"), (0x2F800, 0x2FA1F, "兼容补充")):
        if lo <= o <= hi:
            return name
    return "其他"


def lookup(query: str, near: int = 12, max_diff: int = 2) -> dict:
    """反查一条 IDS。返回 {query, expanded, hits:[{char, cp, block, ids, match, diff}]}。"""
    q = query.strip().replace(" ", "")
    if not q or q[0] not in IDC:
        return {"query": q, "expanded": "", "hits": [],
                "error": "IDS 要以结构符（⿰⿱…）开头"}
    raw, full, by_comp, toks_of = _index()
    table = load_table()
    qx = expand(q)
    qt = tuple(tokenize(q))
    hits: list[dict] = []
    seen: set[str] = set()

    def add(ch: str, match: str, diff: int = 0):
        if ch in seen:
            return
        seen.add(ch)
        hits.append({"char": ch, "cp": ord(ch[0]), "block": _block(ch),
                     "ids": table[ch].primary if ch in table else "",
                     "match": match, "diff": diff})

    for ch in sorted(raw.get(q, ()), key=lambda c: ord(c[0])):
        add(ch, "exact")
    for ch in sorted(full.get(qx, ()), key=lambda c: ord(c[0])):
        add(ch, "expanded")

    comps = [c for c in qt if c not in IDC]
    if near and comps:
        cand: set[str] = set()
        for c in comps:
            cand |= by_comp.get(c, set())
        scored = []
        for ch in cand:
            if ch in seen:
                continue
            d = min(_edit(qt, t, max_diff) for t in toks_of.get(ch, [()]))
            if d <= max_diff:
                # 同差数里常用区在前：人要挑的多半是基本区/扩A 的字
                rank = {"基本区": 0, "扩A": 1}.get(_block(ch), 2)
                scored.append((d, rank, ord(ch[0]), ch))
        for d, _r, _o, ch in sorted(scored)[:near]:
            add(ch, "near", d)
    return {"query": q, "expanded": "".join(qx), "hits": hits}


def encoded_match(query: str) -> list[str]:
    """这条 IDS 在 Unicode 里已有同结构的字吗（exact / expanded 两档）。"""
    r = lookup(query, near=0)
    return [h["char"] for h in r["hits"] if h["match"] in ("exact", "expanded")]


def warm() -> None:
    """控制台启动时后台预热索引。"""
    try:
        _index()
    except Exception:            # noqa: BLE001 —— 预热失败不该拖垮控制台，首查时再报
        pass
