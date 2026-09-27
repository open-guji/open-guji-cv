# -*- coding: utf-8 -*-
"""双线版框：剥第二道 / 按 Step1 内框位置剥贴字的内框线（column_projection，2026-09-26）。"""
import numpy as np

from open_guji_cv.utils.column_projection import clean_column, column_border_trim


def _col(h=400, w=120):
    img = np.full((h, w), 255, np.uint8)
    img[:, 0:4] = 0                        # 左界行
    img[:, w - 4:] = 0                     # 右界行
    return img


def _char(img, y0, y1, x0=35, x1=85):
    img[y0:y1, x0:x0 + 8] = 0
    img[y0:y0 + 6, x0:x1] = 0
    img[y1 - 6:y1, x0:x1] = 0


def test_second_bottom_line_is_stripped_when_two_layers():
    img = _col()
    _char(img, 150, 300)
    img[340:346, 10:110] = 0               # 内框（离末字 40 行）
    img[375:390, 8:112] = 0                # 外框粗线（贴近底边）
    _, d1 = clean_column(img)
    _, d2 = clean_column(img, layers=(1, 2), layer_gap=(None, 30.0))
    h = img.shape[0]
    assert h - d1["bottom"]["px"] > 346     # 只剥一道：内框留在图里
    assert h - d2["bottom"]["px"] <= 340    # 两道：内框也剥了
    assert h - d2["bottom"]["px"] >= 300    # 末字不碰


def test_wide_char_stroke_is_not_taken_as_second_line():
    img = _col()
    img[362:367, 40:80] = 0                # 「一」：宽 40/112，够不上 0.85，也没边距证据
    img[380:392, 8:112] = 0
    _, d = clean_column(img, layers=(1, 2), layer_gap=(None, 30.0))
    assert img.shape[0] - d["bottom"]["px"] >= 367


def test_inner_line_touching_char_uses_step1_position():
    img = _col()
    _char(img, 200, 322)
    img[320:326, 8:112] = 0                # 内框线与末字底横粘连
    img[380:392, 8:112] = 0
    _, d = clean_column(img, layers=(1, 2), layer_gap=(None, 30.0), inner_bottom=323.0)
    cut = img.shape[0] - d["bottom"]["px"]
    assert 314 <= cut <= 320 and d["bottom"]["case"].endswith("i")


def test_inner_line_glued_to_char_by_faint_rows_is_stripped():
    # 内框与末字之间只隔几行淡墨（收笔、麻点），不归零——旧判据把字身连进来、厚过 30 行就不认了
    img = _col()
    _char(img, 200, 330)
    img[330:338, 60:64] = 0                # 末字收笔的一根细竖，把线和字连起来
    img[338:346, 10:110] = 0               # 内框
    img[372:388, 8:112] = 0                # 外框
    _, d = clean_column(img, layers=(1, 2), layer_gap=(None, 30.0))
    cut = img.shape[0] - d["bottom"]["px"]
    assert d["bottom"]["case"] == "d2"
    assert 330 <= cut <= 338               # 线剥了，字没碰


def test_char_bottom_ramp_is_not_taken_as_third_line():
    # 两道框都剥完之后，里面那段淡墨慢慢爬上来（字底）——不是线
    img = _col()
    img[250:330, 40:44] = 0                # 竖笔
    for i, y in enumerate(range(300, 326, 2)):   # 从淡到浓一行行爬上来
        img[y:y + 2, 40:44 + 4 * i] = 0
    img[326:332, 20:100] = 0               # 字底横
    img[336:344, 10:110] = 0               # 内框
    img[372:388, 8:112] = 0                # 外框
    _, d = clean_column(img, layers=(1, 2), layer_gap=(None, 30.0))
    assert img.shape[0] - d["bottom"]["px"] >= 332


def test_worn_inner_line_uses_step1_position_for_extent():
    # 磨得只剩四成宽的内框：落在 Step1 位置旁边才认；离得远（像末格里的「一」）不认
    img = _col()
    _char(img, 150, 280)
    img[338:344, 30:75] = 0                # 残内框，宽 45/112
    img[372:388, 8:112] = 0
    h = img.shape[0]
    _, near = clean_column(img, layers=(1, 2), layer_gap=(None, 30.0), inner_bottom=341.0)
    assert h - near["bottom"]["px"] <= 338
    _, far = clean_column(img, layers=(1, 2), layer_gap=(None, 30.0), inner_bottom=300.0)
    assert h - far["bottom"]["px"] >= 344


def test_inner_vertical_bar_next_to_edge_rule_is_outside_band():
    # 页边列：外框贴边、内框是离边十几像素的一条孤立竖线（vol02 p73c1）
    from open_guji_cv.utils.column_projection import column_text_band
    img = np.full((240, 200), 255, np.uint8)
    img[:, 196:200] = 0                    # 贴边的外框
    img[:, 180:186] = 0                    # 内框竖线，两侧白
    img[20:220, 60:140] = 0                # 字身
    lo, hi = column_text_band(img)
    assert hi <= 180
    img2 = img.copy(); img2[:, 180:186] = 255
    assert column_text_band(img2)[1] > 186  # 没有内框竖线时带宽照旧
