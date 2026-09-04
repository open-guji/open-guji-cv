"""A 刀（整理本通道接进 v2）的回归。

这一刀踩了**两个不报错的坑**，两个都只表现为「数字变难看」，不会抛异常：

1. `label_page(book="")` → 键长 `":24:1:2"`，与产物的 `"vol01:24:1:2"` 对不上，
   **查表全 miss，整理本通道一条都不触发**。症状是「改完没效果」。
2. `dual` 档（align × OCR 一致）`admission_decision` 返回 `(True, None)`——
   **没有通道名**。按 `channel in (白名单)` 取字会漏掉它，char 掉进「库 top1」
   兜底：判决对、存进去的字却是第三方的。实测一次判错 9 条金标
   （vol01:42:3:20 align/OCR 都读「敷」，库 top1「數」0.957 vs 0.955）。

所以这里的用例专盯这两处，外加「己已巳永远人审」这条用户定的规则。
"""

from __future__ import annotations

import pytest

from open_guji_cv.clustering.seeding import admission_decision
from open_guji_cv.clustering.variants import VariantMap


@pytest.fixture(scope="module")
def vmap():
    return VariantMap.load()


def test_dual_channel_has_no_name(vmap):
    """`dual` 档返回 (True, None)——下游按通道名取字时必须把 None 算进去。

    这条用例存在的意义就是把「None 也是一条通道」钉死：谁把它当成
    「没放行」或漏出白名单，就会重演那 9 条错标。
    """
    ok, channel = admission_decision(
        ocr={"char": "敷", "prob": 0.91}, align_char="敷", ref_char=None,
        doubts=[], vmap=vmap, match_char=None,
        match_candidates=[("數", 0.957), ("敷", 0.955)],
        match_guard=None, match_wmax=17.1)
    assert ok is True
    assert channel is None, "dual 档不该有通道名——改了它就要同步改 seed_admit 取字"


def test_dual_unsure_does_not_take_db_guess_as_shape(vmap):
    """库 unsure 时，字形不能取库 top1——那会往字形库塞错例。

    库 top1「數」0.957 只比「敷」0.955 高 0.002（HOG 饱和区的无意义差距），
    而 align × OCR 两路零同源证据都指向「敷」，且「敷」根本不在库候选里。
    unsure 的字面意思就是「库不知道这是什么」，此时它没资格定字形。
    """
    from open_guji_cv.steps.seed_admit import _pick_char

    ok, channel = admission_decision(
        ocr={"char": "敷", "prob": 0.91}, align_char="敷", ref_char=None,
        doubts=[], vmap=vmap, match_char=None,
        match_candidates=[("數", 0.957), ("敷", 0.955)],
        match_guard=None, match_wmax=17.1)
    char, reading = _pick_char(ok=ok, channel=channel, align_char="敷",
                               match_char=None, verdict="unsure",
                               candidates=[("數", 0.957), ("敷", 0.955)])
    assert char == "敷", f"库 unsure 却拿它的猜测当字形：{char}"
    assert reading is None, "字形与文意相同时不该记转换"


def test_variant_keeps_carved_shape_and_records_reading():
    """库判 same 的异体位：字形照录刻本的形，整理本字只进 reading。

    刻本刻「㫖」而整理本作「旨」——字形库存前者，文本录入用后者。
    用整理本改 char 会污染字形库（charset_and_lm.md §四）。
    """
    from open_guji_cv.steps.seed_admit import _pick_char
    char, reading = _pick_char(ok=True, channel="match_replace", align_char="旨",
                               match_char="㫖", verdict="same",
                               candidates=[("㫖", 0.99)])
    assert char == "㫖", "字形被整理本覆盖了"
    assert reading == "旨", "没记下字形→文意的转换"


def test_match_solo_still_uses_db_top1():
    """没有整理本时仍取库 top1——别把上面两条修过头。"""
    from open_guji_cv.steps.seed_admit import _pick_char
    char, reading = _pick_char(ok=True, channel="match_solo", align_char=None,
                               match_char=None, verdict="unsure",
                               candidates=[("書", 0.995)])
    assert char == "書"
    assert reading is None


def test_align_label_ids_need_real_book_name():
    """`label_page` 的 id 是 `book:page:col:idx`——book 传空就全 miss。"""
    from open_guji_cv.clustering.align_label import build_ngram_index, label_page

    corpus = "臣等謹按四庫全書總目提要卷首上諭恭錄" * 20
    idx = build_ngram_index(corpus)
    slots = [(1, i + 1, ch) for i, ch in enumerate("臣等謹按四庫全書總目提要")]
    labs, ok = label_page("24", slots, "vol01", corpus, idx)
    assert ok and labs
    assert labs[0].instance_id.startswith("vol01:24:"), labs[0].instance_id
    labs2, ok2 = label_page("24", slots, "", corpus, idx)
    assert ok2 and labs2
    assert labs2[0].instance_id.startswith(":24:"), "空 book 的失败形态变了"


@pytest.mark.parametrize("ch", ["己", "已", "巳"])
def test_split_chars_never_auto_admitted(ch, vmap):
    """己/已/巳 永远人审（用户 2026-09-04 定）。

    这三个字的字形与文意会分岔，字形层护栏拦不住 align × 库 这种跨源一致，
    所以要在准入侧兜一道。
    """
    from open_guji_cv.steps.seed_admit import SeedAdmitParams
    p = SeedAdmitParams()
    assert ch in set(p.always_review)
