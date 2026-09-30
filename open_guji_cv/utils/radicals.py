# -*- coding: utf-8 -*-
"""康熙部首／部首补充码位 → 正字（overview#247）。

网上抓来的整理本偶尔混进**部首码位**：看着是「己」，码位却是 U+2F30 ⼰（KANGXI RADICAL
SELF）。这种字在我们的管线里有两个后果：

1. `steps/align_ref._corpus_text` 只留 U+4E00–U+9FFF，部首码位整个被**删掉**——整理本少一个字，
   对位从那里起错开一格；
2. 卡片／上下文上显示的是 ⼰，人看着像「己」，事件里却可能被当成另一个码位写回去。

`fold_radicals` 只做 NFKC 能给出的那部分映射（U+2F00–U+2FD5 全部有兼容分解；U+2E80–U+2EFF
部首补充区只有 ⺟→母、⻳→龟 两个有），不碰任何别的字符——所以不会顺手把繁体、异体归并掉。

2026-09-28 实查（#247 交单写了数）：四庫 5 份整理本、北行日錄校對本、全唐文維基 16 份逐卷本、
仓内 `corpus/` 6 份，**康熙部首码位 0 个**；部首补充区只在戴震閣原始 jsonl 里有 8 个 ⺊（U+2E8A，
没有兼容分解、NFKC 也不动它，派生出的 `siku_daizhige.txt` 里已经没有）与全唐文 repairs/notes
表格里 12 个（注释文字，不进字流）。所以眼下这是**护栏**：进卡片与上下文的整理本字过一遍它。
"""
from __future__ import annotations

import unicodedata

_KANGXI = range(0x2F00, 0x2FE0)          # 康熙部首（含未分配尾巴，NFKC 对未分配码位原样返回）
_SUPPLEMENT = range(0x2E80, 0x2F00)      # CJK 部首补充


def is_radical(ch: str) -> bool:
    """单个字符是不是部首码位（康熙部首或部首补充）。"""
    return len(ch) == 1 and (ord(ch) in _KANGXI or ord(ch) in _SUPPLEMENT)


def fold_radicals(s: str | None) -> str | None:
    """把字符串里有 NFKC 兼容分解的部首码位换成正字；其余字符原样。None 原样返回。"""
    if not s:
        return s
    if not any(is_radical(c) for c in s):
        return s
    out = []
    for c in s:
        if is_radical(c):
            n = unicodedata.normalize("NFKC", c)
            out.append(n if len(n) == 1 and not is_radical(n) else c)
        else:
            out.append(c)
    return "".join(out)


def count_radicals(s: str) -> dict[str, int]:
    """文本里各部首码位出现次数（`{字: 次数}`），核查整理本用。"""
    out: dict[str, int] = {}
    for c in s:
        if is_radical(c):
            out[c] = out.get(c, 0) + 1
    return out
