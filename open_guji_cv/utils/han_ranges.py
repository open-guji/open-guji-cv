# -*- coding: utf-8 -*-
"""对位字流认哪些码位是「一个汉字」：一处定义，align_ref／坐标对位／金标清洗共用。

2026-11-06（A23 诊断、A24 改）：`align_ref._corpus_text` 原先只留 U+4E00–9FFF，整理本里的扩展区字
（㣲 𮅕 䀠 䧟 𢰅……殿本语料约 1.26 万个）整个被删掉，整理本少一个字，difflib 在那里得到 delete 或字数不等的
replace，整段丢弃；殿本 Z01 394 格现役对位缺位里 109 格因此而起（ai-team
`domain/CV/质检/待审原因深挖/Z01-对位缺位诊断.md`）。现在收：

- 扩展 A（3400–4DBF）、基本区（4E00–9FFF）、兼容区（F900–FAFF，语料侧先 `fold_compat` 折过，留着无害）；
- 扩展 B 到 J（20000–3347F，含兼容补充 2F800–2FA1F；Ext J 口径同 cv#1135 `_ruling_han`）。

不收：私用区、〓、□、部首码位、标点。改这里会让所有书的 align_ref 判过期，要随一轮全套重跑。
"""
from __future__ import annotations

import re

#: 正则字符类的内容（不带方括号），给 `[...]`／`[^...]` 拼用。
HAN_CLASS = "㐀-䶿一-鿿豈-﫿\U00020000-\U0003347f"

HAN_RE = re.compile(f"[{HAN_CLASS}]")
NON_HAN_RE = re.compile(f"[^{HAN_CLASS}]")


def is_han_cp(cp: int) -> bool:
    return (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF
            or 0xF900 <= cp <= 0xFAFF or 0x20000 <= cp <= 0x3347F)
