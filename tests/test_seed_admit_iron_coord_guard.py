# -*- coding: utf-8 -*-
"""铁证与坐标对位字互证（`iron_coord_guard`，A31 vol07:30:4:8 水→木）。

现役对位字被库分歧过滤掉时，坐标对位字是唯一的整理本证人；殿本 17 册 main 包里铁证与它语义不同的
（宫/官、子/予、人/代、木/本、木/水）看图都是错放。整理本的异体写法（會/㑹）有直接异体边，不拦。"""
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _iron_coord_dissent


class _Ident:
    def semantic(self, c):
        return c


class _Merge:
    def __init__(self, a, b):
        self._m = {b: a}

    def semantic(self, c):
        return self._m.get(c, c)


def test_default_on():
    assert SeedAdmitParams().iron_coord_guard is True


def test_blocks_real_cases():
    for iron, ref in [("木", "水"), ("宫", "官"), ("子", "予"), ("人", "代"), ("木", "本")]:
        assert _iron_coord_dissent(iron, ref, _Ident()), (iron, ref)


def test_passes_no_witness():
    for ref in (None, "", "〓"):
        assert not _iron_coord_dissent("木", ref, _Ident())


def test_passes_same_or_variant():
    assert not _iron_coord_dissent("木", "木", _Ident())
    assert not _iron_coord_dissent("出", "岀", _Merge("出", "岀"))   # 书级码位归一
    assert not _iron_coord_dissent("會", "㑹", _Ident())             # 直接异体边
