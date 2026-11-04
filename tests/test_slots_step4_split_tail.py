# -*- coding: utf-8 -*-
"""字位流 · Step3 记整格正文、Step4 自己拆成 a/b 的夹注段尾（overview#434）。

vol04 218:2：Step3 把 13、21 位记成一整格正文（`sub=None`），Step4 extractor 按旧判据拆成
13a/13b、21a/21b 两半。`_lookup_cell` 查不到 `(13,'a')`，此前按正文处理，9.1 写成
`<…上>下<…諸>傳`，与 char-cord 按格位后缀定左右的 `<…上下|…諸傳>` 不一致。
`sub` 已经给了左右，按 sub 记夹注。
"""

from __future__ import annotations

from open_guji_cv.products.kinds.recog import AdmitRec
from open_guji_cv.report.slots import _to_slot


def _rec(slot: int, sub: str | None, char: str) -> AdmitRec:
    return AdmitRec(id=f"vol04:218:2:{slot}{sub or ''}", slot=slot, sub=sub, admit=True, char=char,
                    reading=None, channel="match_ref", doubts=[], evidence={})


def test_missing_cell_with_sub_takes_jiazhu_kind():
    assert _to_slot("vol04", 218, 2, _rec(13, "a", "下"), None).kind == "jiazhu_a"
    assert _to_slot("vol04", 218, 2, _rec(13, "b", "傳"), None).kind == "jiazhu_b"


def test_missing_cell_without_sub_stays_main():
    assert _to_slot("vol04", 218, 2, _rec(14, None, "如"), None).kind == "char"


