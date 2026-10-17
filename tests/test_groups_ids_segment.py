"""M7 块 C3：折线掩码与评测。自造数据。"""
import numpy as np
import pytest

from open_guji_cv.groups.ids_segment import (
    ink_of, pixel_accuracy, polylines_to_mask, split_parts, straight_baseline,
)


def test_straight_polyline_gives_horizontal_bands():
    m = polylines_to_mask((100, 50), [[0, 0.3], [1, 0.3]], [[0, 0.7], [1, 0.7]])
    assert (m[:30] == 0).all() and (m[30:70] == 1).all() and (m[70:] == 2).all()


def test_slanted_polyline_follows_the_line():
    m = polylines_to_mask((100, 100), [[0, 0.2], [1, 0.6]], [[0, 0.8], [1, 0.9]])
    assert m[30, 5] == 1 and m[30, 95] == 0           # 左侧 y=0.2 之下已是中段；右侧 y=0.6 之上仍是上段
    assert (m[:, :] <= 2).all()


def test_polyline_with_kink_not_a_straight_line():
    # 折点：x=0.5 处上/中界下沉到 0.5；直线（y=0.3）会把中间这块上段残留判成中段
    m = polylines_to_mask((100, 100), [[0, 0.3], [0.5, 0.5], [1, 0.3]], [[0, 0.8], [1, 0.8]])
    assert m[40, 50] == 0 and m[40, 5] == 1 and m[40, 95] == 1


def test_lines_never_cross():
    m = polylines_to_mask((100, 40), [[0, 0.7], [1, 0.7]], [[0, 0.4], [1, 0.4]])   # 第二条在第一条上方
    assert not (m == 1).any() or (m == 1).sum() == 0       # 中段被压成空，不出现负宽度


def test_extends_to_edges_with_single_endpoint_values():
    m = polylines_to_mask((10, 10), [[0.4, 0.5], [0.6, 0.5]], [[0.4, 0.9], [0.6, 0.9]])
    assert (m[:5] == 0).all() and (m[5:9] == 1).all()


def test_baseline_finds_gaps_and_accuracy_on_ink_only():
    img = np.full((100, 40), 255, np.uint8)
    img[5:25] = 0; img[40:60] = 0; img[75:95] = 0       # 三段墨，之间是空行
    ink = ink_of(img)
    y1, y2 = straight_baseline(ink)
    assert 0.25 <= y1 <= 0.4 and 0.6 <= y2 <= 0.75
    gold = polylines_to_mask(img.shape, [[0, 0.32], [1, 0.32]], [[0, 0.68], [1, 0.68]])
    pred = polylines_to_mask(img.shape, [[0, y1], [1, y1]], [[0, y2], [1, y2]])
    assert pixel_accuracy(pred, gold, ink) == 1.0
    wrong = np.zeros_like(gold)
    assert pixel_accuracy(wrong, gold, ink) == pytest.approx((gold[ink] == 0).mean())


def test_split_parts_partition_the_ink():
    img = np.full((30, 10), 255, np.uint8); img[2:8] = 0; img[12:18] = 0; img[22:28] = 0
    mask = polylines_to_mask(img.shape, [[0, 0.33], [1, 0.33]], [[0, 0.66], [1, 0.66]])
    parts = split_parts(img, mask)
    assert sum(int((p < 128).sum()) for p in parts) == int((img < 128).sum())
    assert (parts[0] < 128).sum() == 60 and (parts[1] < 128).sum() == 60
