"""Step5-a 共识升档（2026-09-19）：unsure 档里 top 字 cov 够、比次优异字高够、且已有足够
人裁例时升成 same。标定与理由见 steps/glyph_match.py 模块头。"""

from __future__ import annotations

from open_guji_cv.steps.glyph_match import consensus_same

LIB = {"𠊓": 18, "宐": 7, "空": 1, "宣": 0}


def _n(ch):
    return LIB.get(ch, 0)


def test_upgrades_when_all_three_hold():
    # bxgb:34:3:19 实测：𠊓 0.9903 / 僃 0.9499 / 佛 0.9408，库里 𠊓 18 例——现役判 unsure
    cands = [("𠊓", 0.9903), ("僃", 0.9499), ("佛", 0.9408)]
    assert consensus_same(cands, _n, 0.99, 0.03, 3) == ("𠊓", 18)


def test_cov_below_threshold_stays_unsure():
    assert consensus_same([("𠊓", 0.985), ("僃", 0.90)], _n, 0.99, 0.03, 3) is None


def test_riding_between_two_chars_stays_unsure():
    """次优**异字**只差 0.01：骑在两字之间，不升。"""
    assert consensus_same([("𠊓", 0.995), ("僃", 0.986)], _n, 0.99, 0.03, 3) is None


def test_same_char_runner_up_does_not_count_as_margin():
    """次优是同一个字的另一刻例：不算竞争者，看再往下的异字。"""
    cands = [("𠊓", 0.995), ("𠊓", 0.994), ("僃", 0.95)]
    assert consensus_same(cands, _n, 0.99, 0.03, 3) == ("𠊓", 18)


def test_thin_library_stays_unsure():
    """库里只有一两例人裁：kNN 邻域太薄，不升。"""
    assert consensus_same([("空", 0.995), ("宣", 0.90)], _n, 0.99, 0.03, 3) is None


def test_no_rival_uses_unsure_floor_as_margin():
    assert consensus_same([("宐", 0.995)], _n, 0.99, 0.03, 3) == ("宐", 7)
    assert consensus_same([("宐", 0.87)], _n, 0.99, 0.03, 3) is None


def test_disabled_by_min_confirmed_zero():
    assert consensus_same([("𠊓", 0.999), ("僃", 0.5)], _n, 0.99, 0.03, 0) is None
