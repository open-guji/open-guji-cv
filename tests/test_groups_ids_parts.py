"""M7 块 C4：字体模板的每段二选一。依赖仓里 fonts/（自由字体）；字体文件缺失时跳过。"""
from pathlib import Path

import numpy as np
import pytest

from open_guji_cv.groups.ids_parts import build_bank, choose, font_parts, fonts_for, norm_part

SL = {"彝": ("彑", "米糸", "廾"), "彞": ("彐", "米糸", "廾"), "彜": ("彑", "米分", "廾"),
      "彛": ("彐", "米分", "廾"), "𢑴": ("彐", "米糸", "大"), "𢑱": ("彑", "米分", "大")}
pytestmark = pytest.mark.skipif(not fonts_for("彝"), reason="fonts/ 缺失")


def test_every_member_has_a_font_and_bank_has_both_options_per_slot():
    for ch in SL:
        assert fonts_for(ch), ch
    bank = build_bank(SL)
    assert set(bank[0]) == {"彑", "彐"} and set(bank[1]) == {"米糸", "米分"} and set(bank[2]) == {"廾", "大"}


def test_choose_picks_the_matching_template_for_a_known_font_part():
    bank = build_bank(SL)
    fp = fonts_for("彜")[0]
    for k, want in enumerate(SL["彜"]):
        part = font_parts("彜", fp)[k]
        best, margin, scores = choose(255 - (part * 255).astype(np.uint8), bank[k])   # 模板里含它自己 → 必中
        assert best == want and margin > 0, (k, scores)


def test_blank_part_abstains_and_min_margin_abstains():
    bank = build_bank(SL)
    assert choose(np.full((20, 20), 255, np.uint8), bank[0])[0] is None
    part = font_parts("彝", fonts_for("彝")[0])[0]
    best, margin, _ = choose(255 - (part * 255).astype(np.uint8), bank[0], min_margin=10.0)
    assert best is None and margin > 0


def test_norm_part_size():
    g = np.full((50, 30), 255, np.uint8); g[10:20, 5:25] = 0
    assert norm_part(g).shape == (32, 32)
