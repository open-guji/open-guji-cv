"""铁证首选与证人是已知形近对时不放行（overview#426：vol04 铁证 20 格错 3，曰/日×2、人/八）。"""
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _iron_confusable_witness


class _Ident:
    def semantic(self, c):
        return c


class _Merge:
    """把一对字当同义（异体/码位）的语义表。"""
    def __init__(self, a, b):
        self._m = {b: a}

    def semantic(self, c):
        return self._m.get(c, c)


def test_guard_default_on():
    assert SeedAdmitParams().iron_confusable_guard is True


def test_blocks_vol04_cases_via_coord_witness():
    # 三格现役对位字都缺（None），证人只在坐标对位里
    for iron, ref in [("曰", "日"), ("曰", "日"), ("人", "八")]:
        assert _iron_confusable_witness(iron, (None, ref), _Ident()) == ref


def test_blocks_via_legacy_witness_and_extra_table():
    assert _iron_confusable_witness("王", ("玉", None), _Ident()) == "玉"     # 铁证补充表
    assert _iron_confusable_witness("未", ("末", "末"), _Ident()) == "末"     # 手工表


def test_passes_same_char_or_no_witness():
    assert _iron_confusable_witness("曰", ("曰", "曰"), _Ident()) is None
    assert _iron_confusable_witness("曰", (None, None), _Ident()) is None
    assert _iron_confusable_witness("曰", (None, ""), _Ident()) is None
    assert _iron_confusable_witness("確", (None, "〓"), _Ident()) is None


def test_passes_non_confusable_difference():
    # 证人不同但不在形近表里：不归这道闸管（iron_ref_guard 的事）
    assert _iron_confusable_witness("之", ("乎", None), _Ident()) is None


def test_passes_semantic_same_pair():
    # 形近表里有、但语义表认同字（异体/码位）——不拦
    assert _iron_confusable_witness("強", (None, "强"), _Merge("強", "强")) is None
