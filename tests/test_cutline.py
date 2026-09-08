"""拖切线（cutline）事件 → touching-cuts 金标 的链路回归。

2026-09-05：粘连格线（R2s）的理想切点金标。事件 kind=cutline，路由到
char-segmentation/touching-cuts；expected 只留切点相关字段。
"""

from __future__ import annotations

from open_guji_cv.eval.touching import pick_cases
from open_guji_cv.feedback.consumers import _expected_of
from open_guji_cv.feedback.events import EventTarget, make_event
from open_guji_cv.feedback.routes import RouteTable


def _evt(payload: dict):
    return make_event("vol01-cutline", 1, "cutline",
                      EventTarget(step="row_segment", unit="boundary", key="vol01:44:2:17",
                                  book="vol01", page=44, col=2, slot=17),
                      payload)


def test_cutline_routes_to_touching_cuts():
    e = _evt({"y": 1980, "y_old": 1986, "verdict": "moved"})
    dests = RouteTable.load().destinations(e)
    assert any(d.consumer == "gold_add" and d.shard == "char-segmentation/touching-cuts" for d in dests), dests


def test_cutline_expected_keeps_only_cut_fields():
    e = _evt({"y": 1980, "y_old": 1986, "verdict": "moved", "bi": 17, "slot_above": 17, "slot_below": 18,
              "col_h": 2449, "char_above": "官", "char_below": "道", "client_ts": 1, "dwell_ms": 900})
    ex = _expected_of(e)
    assert ex["y"] == 1980 and ex["y_old"] == 1986 and ex["verdict"] == "moved"
    assert ex["slot_above"] == 17 and ex["slot_below"] == 18 and ex["col_h"] == 2449
    assert "client_ts" not in ex and "dwell_ms" not in ex


def test_pick_cases_spreads_over_pages_and_is_deterministic():
    cases = [dict(id=f"vol01:{p}:1:{s}", page=p) for p in (44, 71, 72) for s in range(1, 41)]
    cases += [dict(id=f"vol01:15:1:{s}", page=15) for s in range(1, 3)]
    a = pick_cases(cases, 30)
    b = pick_cases(cases, 30)
    assert [c["id"] for c in a] == [c["id"] for c in b]
    by_page = {}
    for c in a:
        by_page[c["page"]] = by_page.get(c["page"], 0) + 1
    # 轮转：只有 2 条的页全进；三个大页各拿到接近 1/3，而不是一页包场
    assert by_page[15] == 2
    assert all(8 <= by_page[p] <= 10 for p in (44, 71, 72)), by_page


def test_cutline_with_border_tag_also_feeds_side_rule():
    """标了「界行/版框」的切线事件要同时反馈上游：side-rule 正样本（用户 2026-09-05）。"""
    e = _evt({"y": 1980, "y_old": 1980, "verdict": "ok", "tags": ["border"]})
    dests = RouteTable.load().destinations(e)
    shards = {d.shard for d in dests if d.consumer == "gold_add"}
    assert "char-segmentation/touching-cuts" in shards and "char-segmentation/side-rule" in shards, shards
    plain = _evt({"y": 1980, "y_old": 1980, "verdict": "ok"})
    assert "char-segmentation/side-rule" not in {d.shard for d in RouteTable.load().destinations(plain)}


def test_cutline_expected_keeps_polyline():
    e = _evt({"y": 1980, "y_old": 1986, "verdict": "moved", "polyline": [[20, 1975], [90, 1990], [170, 1978]]})
    ex = _expected_of(e)
    assert ex["polyline"] == [[20, 1975], [90, 1990], [170, 1978]] and ex["y"] == 1980


def test_polyline_to_seam_interpolates_and_extends_ends():
    from open_guji_cv.eval.touching import polyline_to_seam, seam_deviation
    seam = polyline_to_seam([[10, 100], [20, 110], [30, 100]], x0=5, x1=36)
    assert len(seam) == 31
    assert seam[0] == 100 and seam[-1] == 100          # 两端水平延伸
    assert seam[20 - 5] == 110                          # 顶点 x=20
    assert seam[15 - 5] == 105                          # x=15：10→20 的中点线性插值
    mx, mean = seam_deviation(seam, [100] * 31)
    assert mx == 10 and 0 < mean < 10


def test_seam_ok_verdict_keeps_polyline_and_routes_like_cutline():
    e = _evt({"y": 1980, "y_old": 1986, "verdict": "seam_ok", "polyline": [[20, 1975], [26, 1979]]})
    ex = _expected_of(e)
    assert ex["verdict"] == "seam_ok" and ex["polyline"] == [[20, 1975], [26, 1979]]
    assert "char-segmentation/touching-cuts" in {d.shard for d in RouteTable.load().destinations(e)}


# ── 2026-09-08：「切进字里」候选的绝对墨量判据（47 条人裁金标标定）──
def test_split_char_ink_mass_separates_flat_chars_from_split_halves():
    """矮格里装的是扁字（一/二）还是被劈的半个字——只有绝对墨量分得开。

    金标实测：格高比例两组几乎完全重合（moved 0.70~0.79 / ok 0.66~0.80），
    而绝对墨量（墨像素 ÷ 中位格高×格宽）ok 0.034~0.066、moved 0.105~0.195。
    """
    import numpy as np

    from open_guji_cv.eval.touching import _cell_ink_mass

    class _Cell:
        def __init__(self, y0, y1, x0, x1):
            self.y0, self.y1, self.x0, self.x1 = y0, y1, x0, x1

    class _Cache:
        def __init__(self, img): self.img = img
        def get(self, *a, **k): return self.img

    med, w = 115.0, 150
    # 扁字「一」：矮格 85px，墨只有中间一条横（约 12px 高、满宽）
    flat = np.full((300, w), 255, np.uint8)
    flat[40:52, 20:130] = 0
    # 被劈的半个字：同样 85px 的格，墨铺满大半格
    half = np.full((300, w), 255, np.uint8)
    half[8:80, 20:130] = 0
    import cv2, tempfile, os
    out = []
    for img in (flat, half):
        fd, path = tempfile.mkstemp(suffix='.png'); os.close(fd)
        cv2.imwrite(path, img)
        import open_guji_cv.products.cache as _c
        orig = _c.ImageCache
        _c.ImageCache = lambda: _Cache(path)
        try:
            out.append(_cell_ink_mass(None, 'vol01', 1, 1, _Cell(0, 85, 10, 140), med))
        finally:
            _c.ImageCache = orig
            os.unlink(path)
    flat_mass, half_mass = out
    assert flat_mass < 0.100, f"扁字墨量 {flat_mass:.3f} 不该超阈值"
    assert half_mass >= 0.100, f"半个字墨量 {half_mass:.3f} 该超阈值"
