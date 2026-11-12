"""原语 seg.rules：剥长直线（界行、版框横线）。"""
import cv2
import numpy as np

from open_guji_cv.seg.rules import long_rule_mask, strip_long_rules


def _img():
    ink = np.zeros((600, 120), np.uint8)
    ink[:, 5] = 1                       # 贯穿整列的界行
    ink[10, :] = 1                      # 版框横线
    ink[100:150, 40:80] = 1             # 一个「字」
    ink[300:320, 50:52] = 1             # 短竖笔（不该剥）
    return ink


def test_strips_rules_keeps_chars():
    out = strip_long_rules(_img())
    assert out[:, 5].sum() == 0 and out[10, 6:].sum() == 0
    assert out[100:150, 40:80].all() and out[300:320, 50:52].all()
    m = long_rule_mask(_img())
    assert m[:, 5].all() and m[100:150, 40:80].sum() == 0


def test_same_as_old_inline_copy():
    """与史記快筛／seg_screen 原先抄的那份逐像素同。"""
    rng = np.random.default_rng(0)
    ink = (rng.random((500, 90)) < 0.3).astype(np.uint8)
    ink[:, 20] = 1
    ink[250, :] = 1
    w = ink.shape[1]
    vl = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((200, 1), np.uint8))
    hl = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, max(40, int(0.85 * w))), np.uint8))
    old = ((ink > 0) & ~((vl | hl) > 0)).astype(np.uint8)
    assert np.array_equal(strip_long_rules(ink), old)


def test_params_on_signature():
    ink = np.zeros((300, 60), np.uint8)
    ink[75:225, 30] = 1                 # 150px 竖线（不贴图边）：缺省 200 不剥，vline=100 剥
    assert strip_long_rules(ink)[:, 30].sum() == 150
    assert strip_long_rules(ink, vline=101)[:, 30].sum() == 0     # 奇数核，锚点居中
