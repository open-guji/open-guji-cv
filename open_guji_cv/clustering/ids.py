"""全局字符实例 ID：{book}:{page}:{col}:{idx}

- page 是页面文件 stem（拆分半页后如 "1_right"），不允许包含 ":"
- col  是 Phase 2 列编号（从右到左，1 起）
- idx  是 Phase 3 cell 的 index（char 与 empty 共享的编号序列）

(page, col, idx) 的排序即阅读顺序：col 升序 = 从右到左，idx 升序 = 从上到下。
"""

from __future__ import annotations

import re
from typing import NamedTuple

_SEP = ":"


class CharId(NamedTuple):
    book: str
    page: str
    col: int
    idx: int

    def __str__(self) -> str:
        return make_id(self.book, self.page, self.col, self.idx)


def make_id(book: str, page: str, col: int, idx: int) -> str:
    for part in (book, page):
        if _SEP in part:
            raise ValueError(f"ID 组成部分不允许包含 '{_SEP}': {part!r}")
    return f"{book}{_SEP}{page}{_SEP}{col}{_SEP}{idx}"


def parse_id(s: str) -> CharId:
    parts = s.split(_SEP)
    if len(parts) != 4:
        raise ValueError(f"非法字符实例 ID: {s!r}")
    book, page, col, idx = parts
    return CharId(book, page, int(col), int(idx))


_NUM_RE = re.compile(r"\d+")


def _page_sort_key(page: str) -> tuple:
    """页面 stem 排序：优先按其中最后一个数字，再按字面。

    "2" < "10"；"1_right" < "1_left"（同页时保持字面序——右半页文件名
    由 s5_split 产出为 _right/_left，字面序恰好 right < left 不成立，
    因此对 _left/_right 后缀做显式排序：right(阅读在前) < left）。
    """
    nums = _NUM_RE.findall(page)
    num = int(nums[-1]) if nums else -1
    # 筒子页阅读顺序：右半页在前
    if page.endswith("_right"):
        side = 0
    elif page.endswith("_left"):
        side = 1
    else:
        side = 0
    return (num, side, page)


def reading_order_key(cid: CharId) -> tuple:
    """阅读顺序排序键：页 → 列（从右到左=编号升序）→ 列内从上到下。"""
    return (_page_sort_key(cid.page), cid.col, cid.idx)
