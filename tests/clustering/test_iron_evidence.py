# -*- coding: utf-8 -*-
"""铁证放行闸（clustering/iron_evidence.py）单测：D 道影子验收 2026-09-25~27
三轮实测踩出来的四条护栏，逐条钉回归用例，别再踩同一个坑。见模块头。"""

from __future__ import annotations

import random

import numpy as np

from open_guji_cv.clustering.iron_evidence import (
    extra_confusable_partners, form_inseparable, iron, iron_with_disc,
)
from open_guji_cv.clustering.synth import synthetic_glyph


def _gray(binary: np.ndarray, canvas: int = 80) -> np.ndarray:
    """二值字形放到大灰度画布（白底黑字），仿真实字块图。"""
    g = np.full((canvas, canvas), 230, dtype=np.uint8)
    h, w = binary.shape
    y0, x0 = (canvas - h) // 2, (canvas - w) // 2
    region = g[y0:y0 + h, x0:x0 + w]
    region[binary > 0] = 20
    return g


def _glyph(seed: int) -> np.ndarray:
    return _gray(synthetic_glyph(random.Random(seed)))


# ---------- iron()：四条护栏 ----------

def test_single_candidate_no_competitor_is_not_iron():
    """护栏 3：候选只有 1 个时不能放行——vol03:94:1:4 实测踩到的坑（库里「生」零
    人裁实例，唯一候选「注」cov 0.9576 单独蒙混过关）。"""
    ic, top, second, why = iron([("生", 0.9576)], {"生"}, {})
    assert ic is None
    assert why == "分数不够"


def test_two_candidates_low_tier_admitted():
    """同样 0.95~0.99 档，候选有 2 个且次优够低——应放行。"""
    ic, top, second, why = iron([("生", 0.96), ("注", 0.5)], {"生", "注"}, {})
    assert ic == "生"


def test_high_tier_single_candidate_still_admitted():
    """≥0.99 档不受候选数限制（护栏 3 只管低档）。"""
    ic, *_ = iron([("之", 0.995)], {"之"}, {})
    assert ic == "之"


def test_tied_high_confidence_rejected():
    """护栏 2：两个人裁字都 ≥0.99，互相打架，不算铁证。"""
    ic, top, second, why = iron([("早", 0.9961), ("皁", 0.9935)], {"早", "皁"}, {})
    assert ic is None
    assert why == "两个人裁字都像"


def test_same_char_runner_up_does_not_count_as_second():
    """次优是同一个字的另一刻例——不算竞争者。"""
    ic, top, second, why = iron(
        [("之", 0.995), ("之", 0.992), ("乏", 0.5)], {"之", "乏"}, {})
    assert ic == "之"
    assert second == 0.5


def test_missing_partner_in_human_library_rejected():
    """护栏 4：形近对家不在人裁库里，不算铁证——cov 对一点一横不敏感。"""
    partners = {"太": frozenset({"大"})}
    ic, top, second, why = iron([("太", 0.995)], {"太"}, partners)
    assert ic is None
    assert "大" in why


def test_admits_when_partner_present_in_library():
    partners = {"太": frozenset({"大"})}
    ic, *_ = iron([("太", 0.995)], {"太", "大"}, partners)
    assert ic == "太"


def test_no_candidates():
    ic, top, second, why = iron([], set(), {})
    assert ic is None
    assert why == "无候选"


# ---------- 配置表：config/iron_extra_confusable.json ----------

def test_config_partners_are_symmetric():
    partners = extra_confusable_partners()
    assert "皁" in partners["早"]
    assert "早" in partners["皁"]


def test_ru_ba_registered_in_both_tables():
    """入/八 曾经的坑：只登记在 form_inseparable，没登记进 extra_confusable_pairs，
    导致 _discriminate 里的 FORM_INSEPARABLE 检查从未触发。两张表都要有。"""
    partners = extra_confusable_partners()
    assert "八" in partners.get("入", frozenset())
    assert frozenset({"入", "八"}) in form_inseparable()


# ---------- iron_with_disc()：判别器触发场景 ----------

def test_form_inseparable_abstains_even_with_clear_images():
    """入/八 判别器也分不开，直接弃权——不管图像本身像不像。"""
    raw = _glyph(1)
    exemplars = {"入": [_glyph(1), _glyph(1)], "八": [_glyph(99), _glyph(99)]}

    def ex_raws(ch):
        return exemplars.get(ch, [])

    winner, *_rest, tag, dist = iron_with_disc(
        [("入", 0.996), ("八", 0.991)], {"入", "八"}, {}, raw, ex_raws, scale=1.0)
    assert winner is None
    assert tag == "形不可分"


def test_tied_candidates_discriminator_picks_closer_one():
    """护栏 2 命中（两个人裁字都 ≥0.99），非形近表登记对——用判别器成对判别。"""
    raw = _glyph(7)
    exemplars = {"甲": [_glyph(7), _glyph(7)], "乙": [_glyph(123), _glyph(123)]}

    def ex_raws(ch):
        return exemplars.get(ch, [])

    winner, *_rest, tag, dist = iron_with_disc(
        [("甲", 0.995), ("乙", 0.993)], {"甲", "乙"}, {}, raw, ex_raws, scale=1.0)
    assert winner == "甲"
    assert tag == "铁证(判别器)"


def test_tied_candidates_abstain_when_too_few_instances():
    """判别器查不了（实例不够）就弃权，不回退成铁证。"""
    raw = _glyph(7)
    exemplars = {"甲": [_glyph(7)], "乙": [_glyph(123), _glyph(123)]}

    def ex_raws(ch):
        return exemplars.get(ch, [])

    winner, *_rest, tag, dist = iron_with_disc(
        [("甲", 0.995), ("乙", 0.993)], {"甲", "乙"}, {}, raw, ex_raws, scale=1.0)
    assert winner is None
    assert "实例不足" in tag


def test_confirm_recheck_bypasses_top_k():
    """铁证已给出结论（早），字在追加形近表里有登记对手（皁）——不管候选列表里有没有
    皁，直接对它的库实例复核一次。2026-09-27 实测：要求对手先出现在 top-k 里会漏判
    （早/皁、上/土 都因此漏过），改成绕过候选列表直查。"""
    raw = _glyph(3)
    # 皁 不在候选列表里，只在人裁库（ex_raws）里有实例，跟 raw 明显不像。
    exemplars = {"早": [_glyph(3), _glyph(3)], "皁": [_glyph(200), _glyph(200)]}

    def ex_raws(ch):
        return exemplars.get(ch, [])

    winner, top, second, tag, dist = iron_with_disc(
        [("早", 0.995)], {"早", "皁"}, extra_confusable_partners(), raw, ex_raws, scale=1.0)
    # 复核确认原铁证结论——皁 的实例跟 raw 更不像。
    assert tag == "铁证(判别器复核)"
    assert winner == "早"


def test_confirm_recheck_abstains_when_partner_instances_insufficient():
    """复核查不了（对手实例不够）——弃权，不是照旧放行成原铁证结论。"""
    raw = _glyph(3)
    exemplars = {"早": [_glyph(3), _glyph(3)], "皁": [_glyph(3)]}

    def ex_raws(ch):
        return exemplars.get(ch, [])

    winner, top, second, tag, dist = iron_with_disc(
        [("早", 0.995)], {"早", "皁"}, extra_confusable_partners(), raw, ex_raws, scale=1.0)
    assert winner is None
    assert "复核" in tag


def test_plain_iron_result_untouched_when_no_registered_partner():
    """字不在追加形近表里——铁证结论直接采信，不触发判别器。"""
    raw = _glyph(5)

    def ex_raws(ch):
        return []

    winner, top, second, tag, dist = iron_with_disc(
        [("之", 0.995)], {"之"}, {}, raw, ex_raws, scale=1.0)
    assert winner == "之"
    assert tag == "铁证"
    assert dist is None
