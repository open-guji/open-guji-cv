"""卡片 id／格键 → (book, page, col, slot)。

原在 `harvest.py`；2026-10-20 挪到这里，因为 `events.EventTarget` 读回老事件时也要用它补空字段
（`harvest` 依赖 `events`，反过来就成了循环导入）。格键语法总表见 `doc/formats/人裁事件规范.md` §3。
"""
from __future__ import annotations

import re
from typing import Any

#: 册名。**不能写死成 `vol\d+|book\d+`**（2026-09-17 修）：那样只认四库那批册号，
#: 别的书一律匹配不上、`parse_card_id` 返回 `{}`，于是事件的 anchor（book/page/col/
#: slot）全空——**静默的**，事件照样落盘、接口照样 200。实测北行日錄刻本 `bxgb`
#: 的 822 条定字裁决 anchor 全是空的，金标/回流全靠 `key` 字符串硬扛。
#: 册名的实际形态是 `books/<id>.yaml` 的 id：字母数字加下划线短横，不含冒号。
_BOOK = r"[A-Za-z][A-Za-z0-9_-]*"

_ID_PATTERNS = [
    # colborder:vol01:47:2:top —— 边框类裁决，带列号 + 端点后缀（非数字，不进 slot）
    re.compile(rf"^(?P<prefix>[a-z_]+):(?P<book>{_BOOK}):(?P<page>\d+):(?P<col>\d+):[a-z]+$"),
    # outer:vol01:47:top —— 边框类裁决，带端点后缀（非数字，不进任何字段）
    re.compile(rf"^(?P<prefix>[a-z_]+):(?P<book>{_BOOK}):(?P<page>\d+):[a-z]+$"),
    # headcol:vol02:11:4 —— 列级裁决，末段是**列号**没有端点后缀（2026-09-12）。
    # 必须排在下面那条「prefix:book:page」之前：那条以 `$` 收尾匹配不到带列号的
    # id，于是会一路掉到最后返回 {}，金标 anchor 就只剩一个 key（book/page/col
    # 全空）。上面两条带后缀的更具体，先匹配，互不抢。
    re.compile(rf"^(?P<prefix>[a-z_]+):(?P<book>{_BOOK}):(?P<page>\d+):(?P<col>\d+)$"),
    re.compile(rf"^(?P<prefix>[a-z_]+):(?P<book>{_BOOK}):(?P<page>\d+)$"),          # cols:vol02:171
    re.compile(rf"^(?P<book>{_BOOK}):(?P<page>\d+):(?P<col>\d+):(?P<slot>-?\d+)(?P<sub>[ab])?$"),  # vol01:22:5:4
    re.compile(rf"^(?P<book>{_BOOK})/(?P<page>\d+):(?P<col>\d+):(?P<slot>-?\d+)$"),  # vol01/50:7:21
    # bxgb:3:1 —— **列级** id（书:页:列），Step2 列清理裁决用（2026-09-17）。
    # 排在「book:page」之前，否则那条匹配不到三段、一路掉到底返回 {}。
    re.compile(rf"^(?P<book>{_BOOK}):(?P<page>\d+):(?P<col>\d+)$"),
    re.compile(rf"^(?P<book>{_BOOK}):(?P<page>\d+)$"),
]


def parse_card_id(card_id: str) -> dict[str, Any]:
    for pat in _ID_PATTERNS:
        m = pat.match(card_id)
        if m:
            d = m.groupdict()
            out: dict[str, Any] = {"book": d.get("book")}
            for k in ("page", "col", "slot"):
                if d.get(k) is not None:
                    out[k] = int(d[k])
            return out
    return {}
