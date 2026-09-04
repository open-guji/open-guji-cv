"""IDS 护栏的回归 + **它为什么没有接进准入**的实测记录。

护栏本身是对的：麗/麓、玉/王、數/敷 这些手工表漏掉的对，它都能算出来。
但 2026-09-04 在 vol01 dev_set 上量过成本之后**没有接进 `seed_admit`**，
理由记在 `test_guard_would_cost_more_than_it_saves` 里——别看见「有这个模块
却没用上」就顺手接进去。
"""

from __future__ import annotations

import pytest

from open_guji_cv.clustering.ids_guard import (component_distance, components,
                                               ids_of, is_near_form,
                                               near_form_in, structure)


@pytest.mark.parametrize("a,b", [
    ("諭", "論"),   # ⿰言俞 / ⿰言侖 —— 手工表里有，实审出过错
    ("麗", "麓"),   # ⿱丽鹿 / ⿱林鹿 —— 手工表**没有**，三方一致漏放过
    ("玉", "王"),   # ⿱一圡 / ⿱一土 —— 库 cov 0.967 的真形近
    ("數", "敷"),   # ⿰婁攵 / ⿰旉攵 —— 库 top1/top2 只差 0.0017
])
def test_catches_one_component_pairs(a, b):
    assert is_near_form(a, b), f"{a}/{b} 该判形近：{ids_of(a)} vs {ids_of(b)}"


@pytest.mark.parametrize("a,b", [
    ("稍", "精"),   # ⿰禾肖 / ⿰米青 —— cov 0.958 是 HOG 饱和，不是结构像
    ("河", "同"),   # ⿰氵可 / ⿵冂𠮛 —— 结构都不同
    ("呂", "目"),   # ⿳口丿口 / ⿴囗二
])
def test_ignores_hog_saturation_pairs(a, b):
    assert not is_near_form(a, b), f"{a}/{b} 不该判形近：{ids_of(a)} vs {ids_of(b)}"


@pytest.mark.parametrize("a,b", [("人", "入"), ("已", "巳"), ("己", "已"), ("己", "巳")])
def test_stroke_described_pairs_have_no_opinion(a, b):
    """笔画描述的字对必须返回「没有意见」，不是「不像」。

    人 / 己 / 巳 在 lv1 里是 `#(-丿乀)` 这种**笔画组合**，没有部件可比；
    入 `⿹乀丿`、已 `⿹コ乚` 倒是有部件——但只要**一侧**不可比，整对就该
    返回 None。调用方要能分清「不像」和「这条判据管不了」：返回 0 会被
    当成「完全一样」，返回大数会被当成「差得远，可以放心采信」，两种都
    会让形近对偷偷溜过去。

    这几对归手工表 `NEVER_MATCH_FAMILIES` 管——护栏管不了，也不该假装能管。
    """
    assert component_distance(a, b) is None,         f"{a}/{b} 该是「没有意见」：{ids_of(a)!r} vs {ids_of(b)!r}"
    assert not is_near_form(a, b), "没有意见时不该判形近"


def test_parses_region_tags_and_alternates():
    """`⿰言俞(.,T,J,K,V,P)` 剥标记；`⿹コ乚(.);⿹コ𠃊(z)` 取第一个写法。"""
    assert ids_of("諭") == "⿰言俞"
    assert "(" not in ids_of("麗") and ";" not in ids_of("麗")
    assert components("諭") == ("言", "俞")
    assert structure("諭") == "⿰"


def test_near_form_in_scans_candidate_list():
    cands = [("麗", 0.94), ("麓", 0.938), ("鹿", 0.9)]
    assert near_form_in(cands) == ("麗", "麓")
    assert near_form_in([("書", 0.99), ("晝", 0.5)], top=1) is None


def test_guard_would_cost_more_than_it_saves():
    """**负结果记录**：护栏没有接进 `seed_admit`，因为在实测数据上净亏。

    2026-09-04 vol01 dev_set（A 刀之后，自动放行 1869 / 人审 64）实测：

    | 接法 | 命中 | 其中本来判对 | 拦下的真错 |
    |---|---|---|---|
    | 全通道 | 490 (26.2%) | **487** | 3 |
    | 只在纯形状通道 | 2 | 2（㫖 无金标，实为对）| 0 |
    | 只在三方一致（B 的新通道）| 2 | 2 | **0** |

    全通道接法的成本收益比是 487:3——因为 319 次命中落在 `dual` 上，而那条
    通道有 align × OCR 两路**零同源**证据。护栏防的是「形状判据自己认错」，
    对已经有文本证据的通道，它拦的全是好人。

    纯形状通道上倒是无害，但那里只有 8 条放行，护栏命中 2 条还都是对的
    （㫖/旨 是异体，刻本刻 㫖、整理本作 旨，属字形/文意分岔不是错）。

    **什么时候该重新考虑**：库长大、`match_solo` 放行量上来之后（现在只有
    8 条，样本太小），或者接了字体模板/部件模型这类**新的纯形状候选源**时
    ——那些源没有文本证据兜底，正是护栏的用武之地。
    """
    # 这条用例只保护「模块可用」这一点；上面的表是给人读的决策依据。
    assert is_near_form("麗", "麓")
    assert not is_near_form("稍", "精")
