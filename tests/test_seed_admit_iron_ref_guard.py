"""铁证放行与整理本互证（2026-09-27 整理 Z7：vol03 铁证 11 格错 3，align_ref 都标 replace）。"""
from open_guji_cv.clustering.seeding import context_conflicts_ref
from open_guji_cv.steps.seed_admit import SeedAdmitParams


class _Ident:
    def semantic(self, c):
        return c


def test_guard_default_on():
    assert SeedAdmitParams().iron_ref_guard is True


def test_guard_blocks_vol03_cases():
    for iron, ref in [("曰", "白"), ("夬", "夫"), ("而", "面")]:
        assert context_conflicts_ref(iron, ref, _Ident())


def test_guard_passes_same_or_no_ref():
    assert not context_conflicts_ref("之", "之", _Ident())
    assert not context_conflicts_ref("之", None, _Ident())
