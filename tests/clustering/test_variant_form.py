"""「义定形未定」的三档判定：纯函数，用假账本，不碰图与模型。"""

from __future__ import annotations

import pytest

from open_guji_cv.clustering import variant_form as vf
from open_guji_cv.variant_ledger import BookLedger


def _ledger(human_hair: int = 3) -> BookLedger:
    return BookLedger({
        "meta": {"edition": "t"},
        "groups": {
            "髮": {"canonical": "髮", "members": ["髪", "髮"],
                   "forms": {"髪": {"book": {"products": 14, "db": 17, "human": human_hair, "align": 0},
                                   "ref": 0, "tier": "T1", "sources": ["twedu"]},
                             "髮": {"book": {"products": 0, "db": 0, "human": 0, "align": 0},
                                   "ref": 41, "tier": None, "sources": []}},
                   "pairs": {}, "ref_policy": "single", "ref_minor": [], "preferred": "髪"},
            "即": {"canonical": "即", "members": ["即", "卽", "皍"],
                   "forms": {"即": {"book": {"products": 30, "db": 25, "human": 2, "align": 10},
                                   "ref": 563, "tier": None, "sources": []},
                             "卽": {"book": {"products": 19, "db": 33, "human": 5, "align": 0},
                                   "ref": 0, "tier": "T1", "sources": ["twedu"]},
                             "皍": {"book": {"products": 0, "db": 0, "human": 0, "align": 0},
                                   "ref": 1, "tier": "T1", "sources": ["twedu"]}},
                   "pairs": {}, "ref_policy": "single", "ref_minor": ["皍"], "preferred": "卽"},
        },
    })


def test_group_forms_orders_by_book_preference():
    led = _ledger()
    assert vf.group_forms(led, "髮") == ["髪", "髮"]        # preferred 在前，整理本形也在
    assert vf.group_forms(led, "即") == ["卽", "即", "皍"]   # 皍 只在整理本出现过 1 次，仍列
    assert vf.group_forms(led, "廳") == ["廳"]              # 账本里没有 → 只有自己


def test_single_form_short_circuits():
    d = vf.decide_form("廳", ["廳"], [("廳", 0.99)], _ledger())
    assert d.state == "single" and d.char == "廳"


def test_fixed_by_library_when_confirmed_and_clear():
    d = vf.decide_form("髮", ["髪", "髮"], [("髪", 0.973), ("數", 0.91)], _ledger())
    assert d.state == "fixed_lib" and d.char == "髪"
    assert d.evidence["lib"] == [("髪", 0.973)]


def test_library_needs_human_confirmation_first():
    # 首例：本书还没人确认过 髪，库再像也不能自动定——落组视图一次
    d = vf.decide_form("髮", ["髪", "髮"], [("髪", 0.99)], _ledger(human_hair=0))
    assert d.state == "open" and d.char is None


def test_library_rival_within_margin_stays_open():
    d = vf.decide_form("即", ["卽", "即", "皍"], [("卽", 0.972), ("即", 0.966)], _ledger())
    assert d.state == "open"


# ── 完美匹配档（2026-09-05 标定）────────────────────────────
# 卽/即 在库里差 0.0006，永远过不了 FORM_LIB_MARGIN=0.01；但 cov 1.0000 + 人裁 21 次
# 已经足够。见 variant_form 里那张标定表。

def test_exact_match_admits_despite_tiny_margin():
    d = vf.decide_form("即", ["卽", "即", "皍"], [("卽", 1.0), ("即", 0.9994)], _ledger())
    assert d.state == "fixed_lib" and d.char == "卽"
    assert d.evidence["exact"] is True


def test_exact_match_needs_two_human_confirmations():
    """人裁 1 次不算（𢑴 那条：组内五形彼此极像，一次误裁会自我复制）。"""
    led = _ledger()
    led.groups["即"]["forms"]["卽"]["book"]["human"] = 1
    assert vf.decide_form("即", ["卽", "即"], [("卽", 1.0), ("即", 0.9994)], led).state == "open"


def test_exact_match_still_requires_the_top_to_be_confirmed_form():
    """cov 完美但 top1 是没人确认过的形 → 不放行（即 在账本里 human=2，卽 才是本书惯用）。"""
    led = _ledger()
    led.groups["即"]["forms"]["皍"]["book"]["human"] = 0
    d = vf.decide_form("即", ["卽", "即", "皍"], [("皍", 1.0), ("卽", 0.9994)], led)
    assert d.state == "open"


def test_just_below_exact_falls_back_to_margin_rule():
    # 0.9998 不到完美档，又拉不开 0.01 → 仍然人审
    assert vf.decide_form("即", ["卽", "即"], [("卽", 0.9998), ("即", 0.9994)], _ledger()).state == "open"


def test_library_below_cov_stays_open_without_image():
    d = vf.decide_form("髮", ["髪", "髮"], [("髪", 0.93)], _ledger())
    assert d.state == "open"
    assert d.forms == ["髪", "髮"]


def test_fixed_by_image_when_three_sources_agree():
    ranks = {"hog": [("髪", 0.81), ("髮", 0.78)],
             "cls": [("髪", 0.7), ("髮", 0.3)],
             "emb": [("髪", 0.91), ("髮", 0.84)]}
    d = vf.decide_form("髮", ["髪", "髮"], [], _ledger(), ranks)
    assert d.state == "fixed_form" and d.char == "髪"
    assert d.evidence["agree"] is True and d.evidence["emb_gap"] == pytest.approx(0.07)


def test_image_disagreement_or_small_gap_stays_open():
    ranks = {"hog": [("髮", 0.81), ("髪", 0.80)],
             "cls": [("髪", 0.6), ("髮", 0.4)],
             "emb": [("髪", 0.91), ("髮", 0.84)]}
    assert vf.decide_form("髮", ["髪", "髮"], [], _ledger(), ranks).state == "open"
    ranks2 = {"hog": [("髪", 0.81), ("髮", 0.80)],
              "cls": [("髪", 0.6), ("髮", 0.4)],
              "emb": [("髪", 0.86), ("髮", 0.85)]}       # 差 0.01 < FORM_EMB_GAP
    assert vf.decide_form("髮", ["髪", "髮"], [], _ledger(), ranks2).state == "open"


def test_evidence_is_serializable_and_names_the_semantic():
    d = vf.decide_form("髮", ["髪", "髮"], [("髪", 0.93)], _ledger())
    ev = d.to_evidence()
    assert ev["state"] == "open" and ev["semantic"] == "髮" and ev["human"] == {"髪": 3, "髮": 0}
    import json
    json.dumps(ev, ensure_ascii=False)
