# -*- coding: utf-8 -*-
"""`_same_char` 按**来源数**判异体，不只看 tier（2026-09-22）。

用户在 bxgb 对勘报告里逐条指出四组误判，查下来是两个独立的 bug：

- **T1 只要一个弱来源就成立**：`twedu`（教育部異體字字典）在硬来源里，
  单凭它一条就判 T1。`auto.tsv` 的 9,031 条 graph 派生里有 1,125 条（12.5%）
  唯一来源是 twedu，抽样即见 `㐌→色`、`㐪→亥` 这类根本不是异体的对。
- **T2 的账本闸被自己的派生物架空**：T2 没过账本时原先不 return，径直落到
  `VariantMap` 兜底，而 `variants.auto.tsv` 正是从同一张关系图派生的。

两个 bug 的后果一样：对勘报告把**识别错**记进「异体·成果」档，说它没问题。
判据有 bug 时，按判据分出来的「成果」也不可信。

来源数为什么比账本可靠：账本只记这本书实际用过的转换，新书几乎是空的。
实测 `auto.tsv` 判 T2 的 20 条——多来源（≥3）15 条全是真异体，
单源 twedu 的 3 条（卞/其、皍/即、轄/輨）全是错的。
"""
from __future__ import annotations

import pytest

from open_guji_cv.eval.round_check import _same_char

#: 用户 2026-09-22 在 bxgb 报告里逐条指出的四组，后一个字是对的。
USER_REPORTED = [("治", "冶", False), ("瘗", "瘞", True),
                 ("劫", "刼", True), ("輨", "轄", False)]


@pytest.mark.parametrize("a,b,same", USER_REPORTED)
def test_user_reported_pairs(a, b, same):
    assert _same_char(a, b) is same, f"{a}/{b}"


@pytest.mark.parametrize("a,b", [("卽", "即"), ("厯", "歷"), ("㓂", "寇"),
                                 ("啟", "啓"), ("叅", "參"), ("効", "效")])
def test_real_variants_still_pass(a, b):
    """公认异体不能被误伤——只认账本会把这些全判成不同字（新书账本是空的）。"""
    assert _same_char(a, b) is True, f"{a}/{b} 被误伤"


@pytest.mark.parametrize("a,b", [("卞", "其"), ("皍", "即"),
                                 ("大", "太"), ("人", "入")])
def test_distinct_chars_stay_distinct(a, b):
    assert _same_char(a, b) is False, f"{a}/{b} 不该算同字"


def test_symmetric():
    """a/b 与 b/a 必须同判——`_edge_sources` 两个方向都要查。"""
    for a, b, _ in USER_REPORTED:
        assert _same_char(a, b) == _same_char(b, a), f"{a}/{b} 不对称"


def test_empty_and_none_are_not_same():
    for a, b in ((None, "甲"), ("甲", None), ("", "甲"), (None, None)):
        assert _same_char(a, b) is False
