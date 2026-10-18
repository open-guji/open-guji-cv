"""IDS 两段版（`groups/ids_two`）：自己造图，不依赖真书数据。"""
import numpy as np

from open_guji_cv.groups import ids_two as T
from open_guji_cv.groups.ids import IdsResolver


def _glyph(bottom: str) -> np.ndarray:
    """上半一块实心（厽 的替身）；下半：`bar` 三条横（彡 的替身）或 `col` 一根竖（小 的替身）。"""
    g = np.full((100, 100), 255, np.uint8)
    g[8:36, 25:75] = 0
    if bottom == "bar":
        for y in (56, 70, 84):
            g[y:y + 6, 25:75] = 0
    else:
        g[52:92, 45:55] = 0
    return g


def test_slot_names_and_resolver():
    r = IdsResolver(list("參㕘"), "config/groups/can")
    assert (T.slot_name(r, "參"), T.slot_name(r, "㕘")) == ("彡", "小")
    assert r.resolve("⿱厽彡").char == "參" and r.resolve("⿱厽小").char == "㕘"
    s = IdsResolver(list("慎愼"), "config/groups/shen")
    assert s.resolve("⿰忄真").char == "慎" and s.resolve("⿰忄眞").char == "愼"


def test_auto_cut_lands_between_parts_and_mask_splits():
    g = _glyph("bar")
    pl = T.auto_cut(g, "h", 0.5)
    ys = [p[1] for p in pl]
    assert 0.36 <= min(ys) and max(ys) <= 0.56
    m = T.cut_mask(g.shape, pl, "h")
    assert m[:30].sum() == 0 and m[-10:].all()


def test_vertical_cut_mask():
    g = np.full((100, 100), 255, np.uint8)
    g[:, 10:30] = 0; g[:, 50:90] = 0
    pl = T.auto_cut(g, "v", 0.4)
    m = T.cut_mask(g.shape, pl, "v")
    assert m[:, :30].sum() == 0 and m[:, 50:].all()


def test_solve_two_picks_by_template_and_abstains_on_tie():
    r = IdsResolver(list("參㕘"), "config/groups/can")
    pl = [[0, 0.45], [1, 0.45]]
    bank: dict = {}
    for _ in range(2):
        T.add_real(bank, _glyph("bar"), "彡", pl, "h")
        T.add_real(bank, _glyph("col"), "小", pl, "h")
    v = T.solve_two(_glyph("bar"), bank, r, "⿱厽{}", "h", 0.45, polyline=pl, min_margin=0.02)
    assert v.char == "參" and v.kind == "exact"
    v = T.solve_two(_glyph("col"), bank, r, "⿱厽{}", "h", 0.45, polyline=pl, min_margin=0.02)
    assert v.char == "㕘"
    v = T.solve_two(_glyph("bar"), bank, r, "⿱厽{}", "h", 0.45, polyline=pl, min_margin=0.99)
    assert v.char is None and v.kind == "abstain_slot"
    blank = np.full((100, 100), 255, np.uint8)
    assert T.solve_two(blank, bank, r, "⿱厽{}", "h", 0.45).kind == "abstain_blank"
