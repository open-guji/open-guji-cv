# -*- coding: utf-8 -*-
"""`label_page` 对 replace 段的采信闸。

闸的用意：replace 段的标签只靠位置站着，位置不可信就会漏进错标
（历史实例：卷→曰、己→已）。所以要求段长 ≤3 且左右被 equal 夹住。

2026-09-06 把「两侧都 ≥2」放宽成「一侧 ≥2、另一侧 ≥1」——原规则丢掉了
「连续单字 replace 被 1 字 equal 隔开、而整段外面锚得很牢」这一整类真实模式。
"""
from __future__ import annotations

from open_guji_cv.clustering.align_label import build_ngram_index, label_page


def _slots(text: str) -> list[tuple[int, int, str]]:
    """一列到底的字位表，(col, slot, char)。"""
    return [(1, i + 1, ch) for i, ch in enumerate(text)]


def _labeled(hyp: str, corpus: str) -> dict[int, tuple[str, str]]:
    """→ {slot: (整理本字, 转写字)}；只含通过采信闸的位。"""
    got, ok = label_page("1", _slots(hyp), "t", corpus, build_ngram_index(corpus))
    assert ok, "这些用例都该锚得上"
    return {int(x.instance_id.split(":")[3]): (x.char, x.hyp) for x in got}


# 尾部那段长 equal 是为了让 8-gram 锚定站得住（GRAM=8）
TAIL = "今詳考之實不盡然如乾彖引周氏說大象引宋衷說"


def test_single_equal_between_two_replaces_is_kept():
    """目→曰 | 口 | 誤→訣：中间只隔 1 个 equal，但后面锚得很牢，该收。

    实例 vol02:32:7:6。放宽前紧邻的 equal 只有「口」一字，整条被丢。
    """
    hyp = "便講習故目口誤" + TAIL
    ref = "便講習故曰口訣" + TAIL
    got = _labeled(hyp, ref)
    assert got.get(7) == ("訣", "誤"), f"誤→訣 该被收下，实得 {got.get(7)}"
    assert got.get(5) == ("曰", "目"), f"目→曰 该被收下，实得 {got.get(5)}"


def test_person_name_pattern_is_kept():
    """觀→覲 | 伏 | 雙→曼 | 容孔 | 頴→穎：人名「伏曼容」，实例 vol02:31:1:7。"""
    hyp = "佚其觀伏雙容孔頴" + TAIL
    ref = "佚其覲伏曼容孔穎" + TAIL
    got = _labeled(hyp, ref)
    assert got.get(5) == ("曼", "雙"), f"雙→曼 该被收下，实得 {got.get(5)}"


def test_replace_with_no_equal_on_one_side_is_dropped():
    """一侧完全没有 equal（段贴着页首）→ 位置不可信，仍然丢。"""
    hyp = "甲乙" + TAIL
    ref = "丙丁" + TAIL
    got = _labeled(hyp, ref)
    assert 1 not in got and 2 not in got, f"贴着页首的 replace 不该收，实得 {got}"


def test_long_replace_run_is_dropped():
    """段长 >3 → 丢（这条没动）。"""
    hyp = "一二甲乙丙丁戊三四" + TAIL
    ref = "一二庚辛壬癸己三四" + TAIL
    got = _labeled(hyp, ref)
    for slot in (3, 4, 5, 6, 7):
        assert slot not in got, f"5 字的 replace 段不该收，slot {slot} 却进来了"
