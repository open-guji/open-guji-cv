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
