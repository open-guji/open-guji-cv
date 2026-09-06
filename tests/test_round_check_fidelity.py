# -*- coding: utf-8 -*-
"""判据 E（字形保真率）的判灯：错例是硬信号，下界是置信度信号。

2026-09-06 踩的坑：原先 `FIDELITY_GREEN=0.99` 与 `FIDELITY_MIN_AUDIT=50` 自相矛盾
——Wilson 下界在小样本上天然保守，50 条**全对**的下界也只有 0.9286，要 ≥0.99 得
全对 400 条。于是「攒够了 50 条、一条没错」却仍然亮红，判据把自己锁死了。
"""

from __future__ import annotations

import pytest

from open_guji_cv.eval import round_check as rc


def test_wilson_low_is_conservative_on_small_samples():
    """全对时下界随样本量爬升——这就是阈值必须照着定的那条曲线。"""
    assert rc._wilson_low(50, 50) == pytest.approx(0.9286, abs=1e-3)
    assert rc._wilson_low(150, 150) == pytest.approx(0.975, abs=1e-3)
    assert rc._wilson_low(400, 400) == pytest.approx(0.990, abs=1e-3)
    assert rc._wilson_low(0, 0) == 0.0


def test_yellow_threshold_is_below_full_marks_at_min_audit():
    """**门槛必须低于「达到最小样本量且全对」的下界**，否则判据自锁。

    这条断言就是那个坑的护栏：谁把 FIDELITY_YELLOW 调到 0.9286 以上，
    或把 MIN_AUDIT 调低而不同步降门槛，这里立刻失败。
    """
    low_at_min = rc._wilson_low(rc.FIDELITY_MIN_AUDIT, rc.FIDELITY_MIN_AUDIT)
    assert rc.FIDELITY_YELLOW < low_at_min, (
        f"攒够 {rc.FIDELITY_MIN_AUDIT} 条且全对时下界 {low_at_min:.4f}，"
        f"却低于黄灯线 {rc.FIDELITY_YELLOW} —— 判据自锁，人不知道还要做什么")
    assert rc.FIDELITY_GREEN > rc.FIDELITY_YELLOW


def _fid(hit, n, errors=()):
    """按 form_fidelity 的判灯逻辑算灯（不碰产物）。"""
    low = rc._wilson_low(hit, n)
    if errors:
        return rc.RED
    if n < rc.FIDELITY_MIN_AUDIT:
        return "none"
    return rc.GREEN if low >= rc.FIDELITY_GREEN else (
        rc.YELLOW if low >= rc.FIDELITY_YELLOW else rc.RED)


def test_one_error_is_red_regardless_of_sample_size():
    """放行档判错 = 往字形库塞错字形且会自我复制，一条都不能有。"""
    assert _fid(999, 1000, errors=[{"id": "x"}]) == rc.RED
    assert _fid(4, 5, errors=[{"id": "x"}]) == rc.RED


def test_below_min_audit_shows_no_light():
    assert _fid(20, 20) == "none"
    assert _fid(49, 49) == "none"


def test_full_marks_at_min_audit_is_yellow_not_red():
    """本次实测那一档：50/50 = 100%，下界 0.929 → 黄（够用，但样本还少）。"""
    assert _fid(50, 50) == rc.YELLOW


def test_enough_samples_all_correct_is_green():
    assert _fid(150, 150) == rc.GREEN
    assert _fid(400, 400) == rc.GREEN
