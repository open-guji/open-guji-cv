# -*- coding: utf-8 -*-
"""IDS 的最小解析：拆写法、取叶子部件。不建树——树和「差一槽」的判法在 `clustering.ids_struct`，
那边是 L2，本包在 L0，不能反过来 import，所以这里只留部件索引要的那一点。

认得字统网／yi-bai 那套扩展语法：`#(…)` 笔画描述、`{…}` 形体标注、`[…]` 括注、`.` `^` `$` 等标记一律跳过。
"""
from __future__ import annotations

import unicodedata

IDC = frozenset(chr(c) for c in range(0x2FF0, 0x3000)) | {"\u31EF"}
_MARKS = frozenset(".^$?*〾↔↷⊖⑴⑵⑶⑷⑸⑹⑺⑻⑼⑽")


def split_alternatives(raw: str) -> list[tuple[str, set[str]]]:
    """`⿰言俞(.,T,J);⿰言兪(K)` → [(写法, {地区…}), …]。口径同 `ids_struct._split_alternatives`：
    只把**末尾**一组全 ASCII 的括号当地区码，`#(H)(.)` 里的 `(H)` 属于写法本身。"""
    out = []
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue
        regions: set[str] = set()
        if part.endswith(")") and "(" in part:
            i = part.rindex("(")
            body = part[i + 1:-1]
            if body and all(ch.isascii() or ch == "." for ch in body):
                regions = {r.strip() for r in body.split(",") if r.strip()}
                part = part[:i]
        out.append((part, regions))
    return out


def _is_part(c: str) -> bool:
    """能当部件的单个码位：汉字、部首、CJK 笔画、私用区外的其他字母类符号。"""
    if c in IDC or c in _MARKS or c.isspace() or c.isascii():
        return False
    cat = unicodedata.category(c)
    return cat.startswith("L") or cat in ("So", "Nl", "No")


def leaves(seq: str) -> list[str]:
    """写法里的叶子部件（保序去重）。跳过 `#(…)`、`{…}`、`[…]` 与各种标记。"""
    out: list[str] = []
    i = 0
    n = len(seq)
    while i < n:
        c = seq[i]
        if c == "#" and i + 1 < n and seq[i + 1] == "(":
            j = seq.find(")", i)
            i = n if j < 0 else j + 1
            continue
        if c in "{[":
            j = seq.find("}" if c == "{" else "]", i)
            i = n if j < 0 else j + 1
            continue
        if c == "(":
            j = seq.find(")", i)
            i = n if j < 0 else j + 1
            continue
        if _is_part(c) and c not in out:
            out.append(c)
        i += 1
    return out
