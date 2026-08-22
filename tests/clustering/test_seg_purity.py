"""格内净化：列级连通体归属的关键行为 + benchmark 打分。

用例都围绕同一个两难：**既要抹掉混进来的界行/邻字残余，又不能削掉
「高/卞/示」这类顶部与主体不连通的部件**。
"""

import numpy as np
import pytest

from open_guji_cv.clustering.extractor import (CharExtractor, _assign_column,
                                               _split_touching, clean_patch)
from open_guji_cv.clustering import seg_eval


CELL_H = 100.0
COL_W = 90.0


def _strip(n_cells: int = 3) -> tuple[np.ndarray, list]:
    h = int(n_cells * CELL_H)
    strip = np.full((h, int(COL_W)), 240, np.uint8)
    cells = [(i, i * CELL_H, (i + 1) * CELL_H) for i in range(n_cells)]
    return strip, cells


def _blob(strip, y0, y1, x0, x1, v=20):
    strip[int(y0):int(y1), int(x0):int(x1)] = v


def test_detached_top_stays_with_its_own_cell():
    """「高」式顶点：与主体隔 12px 不连通，仍须归本格。"""
    strip, cells = _strip()
    _blob(strip, 108, 120, 35, 55)      # 顶点（在第 1 格内，主体上方 12px）
    _blob(strip, 132, 190, 15, 75)      # 主体
    _blob(strip, 20, 90, 15, 75)        # 上一格的字
    _, owner = _assign_column(strip, cells, CELL_H, COL_W)
    assert owner[112, 45] == 2, "顶点被判给了上一格"
    assert owner[160, 45] == 2


def test_neighbor_residue_goes_to_its_own_cell():
    """邻字下探到本格的残余：主体在隔壁，须判给隔壁。"""
    strip, cells = _strip()
    _blob(strip, 20, 112, 15, 75)       # 上一格的字，尾巴越线 12px
    _blob(strip, 130, 190, 15, 75)      # 本格的字
    _, owner = _assign_column(strip, cells, CELL_H, COL_W)
    assert owner[108, 45] == 1, "邻字残余被判给了本格"
    assert owner[160, 45] == 2


def test_gap_is_not_the_criterion():
    """同样 12px 的间隙，一个要留一个要去——间隙本身不能当判据。"""
    keep, cells = _strip()
    _blob(keep, 108, 120, 35, 55)
    _blob(keep, 132, 190, 15, 75)
    drop, _ = _strip()
    _blob(drop, 20, 112, 15, 75)
    _blob(drop, 130, 190, 15, 75)
    _, o1 = _assign_column(keep, cells, CELL_H, COL_W)
    _, o2 = _assign_column(drop, cells, CELL_H, COL_W)
    assert o1[112, 45] == 2 and o2[108, 45] == 1


def test_rule_line_discarded():
    """贯穿整条列的界行竖线不归任何格。"""
    strip, cells = _strip()
    strip[:, 2:6] = 20                  # 左界行
    _blob(strip, 120, 190, 20, 70)
    _, owner = _assign_column(strip, cells, CELL_H, COL_W)
    assert owner[150, 3] == 0
    assert owner[150, 45] == 2


def test_wide_horizontal_stroke_survives():
    """「守」的宀、「書」的顶横能占满列宽——不得当版框横线抹掉。

    回归：曾按「整行满墨」剔除，把「守」削成「寸」、「范」削成「氾」。
    """
    strip, cells = _strip()
    _blob(strip, 110, 122, 4, int(COL_W) - 4)   # 满宽顶横
    _blob(strip, 130, 190, 20, 70)
    _, owner = _assign_column(strip, cells, CELL_H, COL_W)
    assert owner[115, 45] == 2


def test_split_touching_cuts_at_the_stem():
    """上一字竖尾粘住下一字顶横：在格线附近的细杆处切开。"""
    strip, cells = _strip()
    _blob(strip, 15, 95, 15, 75)        # 上一字主体
    _blob(strip, 95, 112, 40, 50)       # 细竖尾，跨过格线
    _blob(strip, 110, 126, 10, 80)      # 下一字顶横（与竖尾相连）
    _blob(strip, 135, 195, 15, 75)      # 下一字主体
    _, owner = _assign_column(strip, cells, CELL_H, COL_W)
    assert owner[115, 45] == 2, "被粘住的顶横整块判给了上一格"
    assert owner[50, 45] == 1


def test_split_keeps_upper_char_whole():
    """细杆若在字内（艹 与 早 之间），不得下刀。

    回归：只按「离格线最近的细行」切，把「草」的艹切给了上一格。
    """
    strip, cells = _strip()
    binary = np.zeros((int(3 * CELL_H), int(COL_W)), np.uint8)
    binary[10:60, 15:75] = 1            # 上一格的字（与艹粘住）
    binary[60:95, 42:48] = 1            # 粘连的细杆
    binary[95:107, 10:80] = 1           # 艹（刚过格线）
    binary[107:118, 42:48] = 1          # 艹与早之间的细颈
    binary[118:195, 15:75] = 1          # 早
    out = _split_touching(binary, cells, CELL_H, COL_W)
    assert out[112, 45] == 1, "在字内部下了刀"


def test_clean_patch_whitens_only_foreign_ink():
    strip, cells = _strip()
    _blob(strip, 20, 112, 15, 75)
    _blob(strip, 130, 190, 15, 75)
    _, owner = _assign_column(strip, cells, CELL_H, COL_W)
    patch = clean_patch(strip, owner, 1, 100, 200)
    assert patch[8, 45] == 255          # 邻字残余抹白
    assert patch[60, 45] < 128          # 本字保留


def test_extractor_strategy_switch():
    from tests.clustering.test_extractor import _make_page_and_grid
    page, grid = _make_page_and_grid()
    a = CharExtractor(strategy="padding_box").extract_page(page, grid, "b", "1")
    b = CharExtractor(strategy="component_owner").extract_page(page, grid, "b", "1")
    assert len(a) == len(b) == 6
    with pytest.raises(ValueError):
        CharExtractor(strategy="nope")


def test_seg_eval_scores_and_ranks(tmp_path):
    """benchmark 打分自洽：完美预测得满分，全空得零召回。"""
    gold = np.zeros((10, 10), bool); gold[2:6, 2:6] = True
    perfect = seg_eval.score_cell(gold.copy(), gold, 0)
    assert perfect.keep_recall == 1.0 and perfect.drop_precision == 1.0
    empty = seg_eval.score_cell(np.zeros_like(gold), gold, 0)
    assert empty.keep_recall == 0.0
    agg = seg_eval.aggregate([perfect, empty])
    assert agg["n"] == 2 and agg["intact_rate"] == 0.5


def test_all_strategies_registered():
    assert set(seg_eval.STRATEGIES) >= {"padding_box", "gap_threshold",
                                        "component_owner"}


# ── boundary_ink：切分缺陷自检 ────────────────────────────

def _patch(ink_rows, H=100, W=60):
    import numpy as np
    g = np.full((H, W), 255, np.uint8)
    for a, b in ink_rows:
        g[a:b, 15:45] = 0
    return g


def test_boundary_ink_zero_when_char_sits_inside_cell():
    from open_guji_cv.clustering.extractor import _boundary_ink_frac
    assert _boundary_ink_frac(_patch([(30, 70)])) == 0.0


def test_boundary_ink_immune_to_extra_whitespace():
    """多裁空白不得判失败——这正是「只看墨不看框」的要求。"""
    from open_guji_cv.clustering.extractor import _boundary_ink_frac
    tight = _patch([(30, 70)], H=100)
    padded = _patch([(60, 100)], H=160)      # 同样的字，上下多留 60px 空白
    assert _boundary_ink_frac(tight) == 0.0
    assert _boundary_ink_frac(padded) == 0.0


def test_boundary_ink_fires_on_neighbor_residue():
    from open_guji_cv.clustering.extractor import (BOUNDARY_INK_T,
                                                   _boundary_ink_frac)
    # 本字居中 + 顶部一条邻字残余
    assert _boundary_ink_frac(_patch([(0, 6), (30, 70)])) > BOUNDARY_INK_T


def test_boundary_ink_fires_on_truncated_char():
    from open_guji_cv.clustering.extractor import (BOUNDARY_INK_T,
                                                   _boundary_ink_frac)
    # 字被切在下边界上
    assert _boundary_ink_frac(_patch([(60, 100)])) > BOUNDARY_INK_T


def test_boundary_ink_empty_patch_is_zero():
    import numpy as np
    from open_guji_cv.clustering.extractor import _boundary_ink_frac
    assert _boundary_ink_frac(np.full((50, 40), 255, np.uint8)) == 0.0


def test_extract_page_emits_boundary_ink_flag():
    import numpy as np
    from open_guji_cv.clustering.extractor import CharExtractor
    # 一列两格，第 2 格的字紧贴格顶（模拟上邻字残余/截断）
    page = np.full((300, 120), 235, np.uint8)
    page[20:80, 30:90] = 25          # 第 1 格：居中
    page[100:112, 30:90] = 25        # 第 2 格：紧贴顶部
    page[150:190, 30:90] = 25
    grid = {"columns": [{"index": 1, "left_x": 20.0, "right_x": 100.0,
                         "cells": [
                             {"type": "char", "index": 0, "y_top": 10.0,
                              "y_bottom": 100.0},
                             {"type": "char", "index": 1, "y_top": 100.0,
                              "y_bottom": 200.0}]}]}
    res = CharExtractor().extract_page(page, grid, "b", "1")
    flags = {i.idx: i.flags for i, _ in res}
    assert "boundary_ink" in flags.get(1, []), flags


# ── 分层缺陷自检：确定层按成因分开标 ──────────────────────

def _blank(H=100, W=60):
    import numpy as np
    return np.full((H, W), 255, np.uint8)


def test_rule_bar_fires_on_interior_vertical_line():
    """混入的界行竖线**不一定贴边**——实测 x/W 从 0.08 到 0.96 都有。"""
    from open_guji_cv.clustering.extractor import _defect_flags
    g = _blank()
    g[30:70, 25:45] = 0          # 字身
    g[0:100, 8:12] = 0           # 满高细竖线，位于图块内部 x/W≈0.13
    assert "rule_bar" in _defect_flags(g)


def test_rule_bar_ignores_thick_stroke_attached_to_char():
    """满高的竖笔只要连在字身上就不是界行——竖线的特征是「独立」。"""
    from open_guji_cv.clustering.extractor import _defect_flags
    g = _blank()
    g[0:100, 28:32] = 0          # 满高竖笔
    g[45:55, 20:40] = 0          # 与之相连的横笔 → 同一个连通体
    assert "rule_bar" not in _defect_flags(g)


def test_edge_blob_fires_only_when_component_wholly_in_band():
    """「整体落在边缘带内」才算邻字残余；顶天立地的高字不该被冤枉。"""
    from open_guji_cv.clustering.extractor import _defect_flags
    residue = _blank()
    residue[30:70, 20:40] = 0
    residue[0:8, 15:45] = 0      # 独立的一小条，整体在上边缘带内
    assert "edge_blob" in _defect_flags(residue)

    tall = _blank()
    tall[2:98, 20:40] = 0        # 一个顶天立地的高字，墨确实进了边缘带
    assert "edge_blob" not in _defect_flags(tall)


def test_frame_bars_needs_two_bars_so_yi_stays_clean():
    """单条满宽扁横条是「一」字本身；版框总是成对出现。"""
    from open_guji_cv.clustering.extractor import _defect_flags
    yi = _blank()
    yi[48:56, 2:58] = 0
    assert "frame_bars" not in _defect_flags(yi)

    frame = _blank()
    frame[20:28, 0:60] = 0
    frame[70:78, 0:60] = 0
    assert "frame_bars" in _defect_flags(frame)


def test_wide_gap_flags_cross_column_patch():
    from open_guji_cv.clustering.extractor import _defect_flags
    g = _blank(W=120)
    g[30:70, 5:35] = 0           # 左列的墨
    g[30:70, 85:115] = 0         # 右列的墨，中间空一大截
    assert "wide_gap" in _defect_flags(g)


def test_defect_flags_clean_char_has_none():
    from open_guji_cv.clustering.extractor import _defect_flags
    g = _blank()
    g[30:70, 20:40] = 0
    assert _defect_flags(g) == []


def test_defect_flags_immune_to_extra_whitespace():
    """多裁空白仍然不得判失败——分层之后这条性质必须保持。"""
    from open_guji_cv.clustering.extractor import _defect_flags
    tight = _blank(H=100)
    tight[30:70, 20:40] = 0
    padded = _blank(H=200)
    padded[80:120, 20:40] = 0    # 同一个字，上下各多留 50px
    assert _defect_flags(tight) == []
    assert _defect_flags(padded) == []


def test_defect_flags_empty_patch_is_quiet():
    from open_guji_cv.clustering.extractor import _defect_flags
    assert _defect_flags(_blank()) == []


def test_run_book_clears_stale_patches(tmp_path):
    """重跑必须清掉上一次的残留图块。

    否则旧图块仍躺在磁盘上、却不在新 index.jsonl 里，按 page:col:idx
    对标的人工标签会对上**过期图块**——实测一次重跑留下 2456 个孤儿，
    直接测出了自相矛盾的报告。
    """
    import json
    import numpy as np
    import cv2
    from open_guji_cv.clustering.extractor import CharExtractor

    book = tmp_path / "vol"
    (book / "phase3_char_grid").mkdir(parents=True)
    (book / "s3_crop").mkdir(parents=True)
    page = np.full((300, 120), 235, np.uint8)
    page[20:80, 30:90] = 25
    cv2.imwrite(str(book / "s3_crop" / "1.png"), page)
    (book / "phase3_char_grid" / "1_char_grid.json").write_text(json.dumps(
        {"columns": [{"index": 1, "left_x": 20.0, "right_x": 100.0,
                      "cells": [{"type": "char", "index": 0,
                                 "y_top": 10.0, "y_bottom": 100.0}]}]}),
        encoding="utf-8")

    stale = book / "phase4_chars" / "patches" / "1"
    stale.mkdir(parents=True)
    (stale / "1_99.png").write_bytes(b"stale")     # 上一次切分留下的孤儿

    CharExtractor().run_book(book, source_dir=book / "s3_crop")

    live = {json.loads(l)["patch_path"] for l in
            (book / "phase4_chars" / "index.jsonl").read_text(
                encoding="utf-8").splitlines()}
    on_disk = {f"patches/1/{p.name}" for p in stale.glob("*.png")}
    assert on_disk == live, f"磁盘上有 index 之外的图块: {on_disk - live}"


# ── 版框横线 vs「一」字：形状分不清，只能到页级取证 ────────

def _page_with_bar(cross: bool, W=400, H=300, x0=150, x1=250, y=140):
    """造一页：列框 [x0,x1] 里有一条满宽扁横条。
    cross=True 时横条横穿整版（版框横线），False 时只在列内（「一」字）。
    """
    import numpy as np
    page = np.full((H, W), 255, np.uint8)
    a, b = (0, W) if cross else (x0 + 4, x1 - 4)
    page[y:y + 10, a:b] = 0
    return page


def test_bar_crossing_the_column_is_a_frame_line():
    from open_guji_cv.clustering.extractor import _bar_crosses_column
    page = _page_with_bar(cross=True)
    patch = page[100:200, 150:250]
    assert _bar_crosses_column(page, patch, 150, 250, 100)


def test_bar_confined_to_the_column_is_the_character_yi():
    from open_guji_cv.clustering.extractor import _bar_crosses_column
    page = _page_with_bar(cross=False)
    patch = page[100:200, 150:250]
    assert not _bar_crosses_column(page, patch, 150, 250, 100)


def test_bar_crossing_only_one_side_is_not_a_frame_line():
    """只有一侧继续走的，可能是邻字笔画搭过来，不能就判版框。"""
    import numpy as np
    from open_guji_cv.clustering.extractor import _bar_crosses_column
    page = np.full((300, 400), 255, np.uint8)
    page[140:150, 0:246] = 0            # 只往左穿出去
    patch = page[100:200, 150:250]
    assert not _bar_crosses_column(page, patch, 150, 250, 100)


def test_extract_page_flags_a_cell_sitting_on_the_frame_line():
    import numpy as np
    from open_guji_cv.clustering.extractor import CharExtractor
    page = np.full((300, 400), 235, np.uint8)
    page[40:100, 170:230] = 25          # 第 1 格：正常的字
    page[190:202, 0:400] = 25           # 第 2 格：整版横穿的版框横线
    grid = {"columns": [{"index": 1, "left_x": 150.0, "right_x": 250.0,
                         "cells": [{"type": "char", "index": 0,
                                    "y_top": 30.0, "y_bottom": 130.0},
                                   {"type": "char", "index": 1,
                                    "y_top": 150.0, "y_bottom": 250.0}]}]}
    flags = {i.idx: i.flags for i, _ in CharExtractor().extract_page(
        page, grid, "b", "1")}
    assert "frame_bars" in flags.get(1, []), flags
    assert "frame_bars" not in flags.get(0, []), flags


# ── 横向截断：墨的重心偏离格心 ────────────────────────────

def test_off_center_fires_when_the_glyph_sits_at_the_edge():
    """横向被切时字整个被推到格位一侧——边缘墨量未必高，但重心明显偏。"""
    from open_guji_cv.clustering.extractor import _defect_flags
    g = _blank(H=120, W=120)
    g[30:90, 84:118] = 0            # 字只剩右边一条
    assert "off_center" in _defect_flags(g)


def test_off_center_quiet_on_a_centred_glyph():
    from open_guji_cv.clustering.extractor import _defect_flags
    g = _blank(H=120, W=120)
    g[30:90, 32:88] = 0
    assert "off_center" not in _defect_flags(g)


def test_off_center_quiet_on_a_centred_narrow_stroke():
    """窄字（一、卜）居中放着不该报——判据是**偏心**，不是窄。"""
    from open_guji_cv.clustering.extractor import _defect_flags
    g = _blank(H=120, W=120)
    g[56:64, 50:70] = 0
    assert "off_center" not in _defect_flags(g)


def test_off_center_immune_to_extra_whitespace():
    """左右多裁等量空白不改变重心相对位置。"""
    from open_guji_cv.clustering.extractor import _off_center_frac
    import numpy as np
    tight = np.full((120, 120), 255, np.uint8); tight[30:90, 40:80] = 0
    padded = np.full((120, 200), 255, np.uint8); padded[30:90, 80:120] = 0
    assert abs(_off_center_frac(tight) - _off_center_frac(padded)) < 0.01


def test_off_center_empty_patch_is_zero():
    import numpy as np
    from open_guji_cv.clustering.extractor import _off_center_frac
    assert _off_center_frac(np.full((60, 60), 255, np.uint8)) == 0.0
