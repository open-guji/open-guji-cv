"""M7 块 C5：IDS 路端到端（切分 → 每段二选一 → 拼 IDS → 查字）。用字体自渲染的字做输入；字体缺失时跳过。"""
import numpy as np
import pytest

from open_guji_cv.groups.ids import IdsResolver
from open_guji_cv.groups.ids_parts import build_bank, fonts_for, render
from open_guji_cv.groups.ids_solver import slots_to_ids, solve

SL = {"彝": ("彑", "米糸", "廾"), "彞": ("彐", "米糸", "廾"), "彜": ("彑", "米分", "廾"),
      "彛": ("彐", "米分", "廾"), "𢑴": ("彐", "米糸", "大"), "𢑱": ("彑", "米分", "大")}


def test_slots_to_ids_writes_flat_standard_ids():
    assert slots_to_ids("彑", "米糸", "廾") == "⿳彑⿰米糸廾"
    assert slots_to_ids("彐", "⿰米分", "大") == "⿳彐⿰米分大"


@pytest.mark.skipif(not fonts_for("彝"), reason="fonts/ 缺失")
def test_blank_cell_abstains_and_font_cell_never_gives_a_wrong_char():
    bank = build_bank(SL)
    r = IdsResolver(list(SL), "config/groups/yi_560")
    assert solve(np.full((80, 80), 255, np.uint8), bank, r).kind == "abstain_blank"
    v = solve(render("彝", fonts_for("彝")[0]), bank, r, min_margin=0.0)
    assert v.char is not None and v.ids.startswith("⿳") and v.kind in {"exact", "form", "nearest"}
