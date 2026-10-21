# -*- coding: utf-8 -*-
"""CJK 兼容汉字 → 统一汉字（2026-10-19，sheldon：福 U+FA1B 与 U+798F 字形相同，应出 U+798F）。

U+F900–FAFF、U+2F800–2FA1F 里的字符，Unicode 为它们定了**规范分解**（NFC 就会折）：
字形与目标统一汉字完全相同，只是为了与旧编码表（KS X 1001、CNS 等）往返才单独占了码位。
字体渲染它们与统一汉字**一模一样**，所以字形匹配分数并列，谁排前面全看遍历顺序——
殿本 vol01 p131 第 9 列的「福」就这么被人裁成了 U+FA1B（候选面板里它和 U+798F 并排出现）。

规矩：**入口**（候选字表、整理本用字、人裁事件、字形库标签）和**出口**（产物里的字）都过
`fold_compat`，这些码位不应在任何地方出现。折叠只走 Unicode 规范分解，不碰繁简、异体
（NFKC 会把全角、部首等也折掉，所以不用 NFKC；部首见 `utils/radicals.py`）。

不会被折的兼容区码位：U+FA0E/0F/11/13/14/1F/21/23/24/27/28/29 这 12 个其实是**真正的统一汉字**，
没有规范分解，NFC 原样返回，本模块也原样放过。

`KEEP` 是人定的「古籍里确有区别意义，不折」名单；现在是空的，要加由 sheldon 定。
"""
from __future__ import annotations

import re
import unicodedata

_RANGES = ((0xF900, 0xFAFF), (0x2F800, 0x2FA1F))
#: 同 `_RANGES`，给整串快速判断用（C 里扫，不逐字进 Python）。
_COMPAT_RE = re.compile("[\uF900-\uFAFF\U0002F800-\U0002FA1F]")

#: 人定不折的兼容码位（目前为空）。
KEEP: frozenset[str] = frozenset()


def in_compat_block(ch: str) -> bool:
    """单字符是否落在兼容汉字区段（不论有没有规范分解）。"""
    if len(ch) != 1:
        return False
    o = ord(ch)
    return any(lo <= o <= hi for lo, hi in _RANGES)


def is_compat(ch: str) -> bool:
    """单字符是不是**会被折掉**的兼容汉字（在区段内、有规范分解、不在 KEEP）。"""
    return (in_compat_block(ch) and ch not in KEEP
            and unicodedata.normalize("NFC", ch) != ch)


def fold_compat(s: str | None) -> str | None:
    """字符串里的兼容汉字换成统一汉字；其余字符（含 IDS、IVS 序列）原样。None 原样返回。"""
    if not s:
        return s
    # 绝大多数串一个兼容字都没有：正则在 C 里扫一遍就返回（2026-10-20，提速；原来逐字
    # `in_compat_block`，align_ref 起跑时折整部语料要 1 s，现在 16 ms，结果相同）
    if not _COMPAT_RE.search(s):
        return s
    # 只换正则扫出来的兼容区段字符，其余原样（2026-10-21，提速：整部语料里有一个兼容字就要逐字
    # 进 Python，align_ref 起跑折语料 12 s；改后同一份语料逐字相同）
    return _COMPAT_RE.sub(_fold_one, s)


def _fold_one(m: re.Match) -> str:
    c = m.group(0)
    return unicodedata.normalize("NFC", c) if is_compat(c) else c


def fold_unique(chars) -> list[str]:
    """字表折叠 + 去重，保持首次出现顺序。"""
    seen: set[str] = set()
    out: list[str] = []
    for c in chars:
        f = fold_compat(c)
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def count_compat(s: str) -> dict[str, int]:
    """文本里各兼容码位（会被折的）出现次数，普查用。"""
    out: dict[str, int] = {}
    for c in s:
        if is_compat(c):
            out[c] = out.get(c, 0) + 1
    return out
