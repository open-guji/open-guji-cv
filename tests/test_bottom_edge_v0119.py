"""vol01–19 换新图：下版框贴图底不崩、下框贴搜索带边界时重找倾角（A22，2026-11-08）。"""
import numpy as np

from open_guji_cv.books.siku_zongmu.row_boundaries import trim_content_span
from open_guji_cv.seg import lines as L


def test_trim_content_span_x2_beyond_curve():
    curve = np.zeros(100)
    curve[30:60] = 5.0
    # 下框在列图底之外（新图版框贴图底，x2 比曲线长度还大），原先 IndexError
    assert trim_content_span(curve, 0, 130, 1.0) == (30, 59)


def _page_with_tilted_text_and_flat_bar(h=1000, w=600):
    m = np.zeros((h, w))
    # 正文：散的墨块（字），只到 y≈930
    rng = np.random.default_rng(0)
    for _ in range(4000):
        y, x = int(rng.integers(40, 925)), int(rng.integers(30, w - 40))
        m[y:y + 5, x:x + 4] = 1
    # 真下框：一条平的粗横线
    m[960:966, 10:w - 10] = 1
    return m


def test_lock_reslope_off_is_default():
    m = _page_with_tilted_text_and_flat_bar()
    a = L.find_horizontal_border(m, "bottom")
    b = L.find_horizontal_border(m, "bottom", lock_reslope=False)
    assert (a.position, a.slope) == (b.position, b.slope)


def test_lock_reslope_finds_flat_frame_when_locked(monkeypatch):
    m = _page_with_tilted_text_and_flat_bar()
    h = m.shape[0]
    lo = h - max(10, int(h * 0.15))
    # 模拟联合搜索锁在带边界、挑了个大斜角（vol12 p27 新图 0.047）
    monkeypatch.setattr(L, "joint_search_coarse_to_fine",
                        lambda *a, **k: L.LineMatch(position=float(lo), slope=0.047, score=96.8, width=6.0, proj=1.0))
    r = L.find_horizontal_border(m, "bottom", lock_reslope=True)
    assert 955 <= r.position <= 970 and abs(r.slope) < 0.01
