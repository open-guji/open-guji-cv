"""_split_touching_curve（P2 #12 曲线切分原型）的合成粘连单测。

真实量级参照 vol01：格高 ~117px、列宽 ~150px。
"""
import numpy as np
import cv2

from open_guji_cv.clustering.extractor import (
    _min_ink_path, _split_touching, _split_touching_curve)

CELL_H = 117.0
COL_W = 150.0


def _cells(n=3, h=CELL_H):
    return [(i, i * h, (i + 1) * h) for i in range(n)]


def _comp_count(binary, min_area=100):
    n, _lab, st, _ = cv2.connectedComponentsWithStats(
        binary.astype(np.uint8), 8)
    return sum(1 for k in range(1, n) if st[k, 4] >= min_area)


def test_min_ink_path_follows_zero_channel():
    """路径应沿零代价的弯曲通道走，而不是直穿墨墙。"""
    B, W = 30, 80
    cost = np.ones((B, W))
    ch = 5 + (np.arange(W) // 8) % 3      # 台阶式弯道（每步 |dy|<=1 可达）
    channel_rows = 5 + np.cumsum(np.clip(np.diff(np.concatenate([[0], ch])), -1, 1))
    for x in range(W):
        cost[int(channel_rows[x]), x] = 0.0
    path = _min_ink_path(cost)
    assert float(cost[path, np.arange(W)].sum()) == 0.0


def _two_chars_touching(seam_shift=0):
    """两个实心方块字，在格线附近被一条竖桥粘住。seam_shift 让最细处偏离格线。"""
    H, W = int(3 * CELL_H), int(COL_W)
    b = np.zeros((H, W), np.uint8)
    g = int(CELL_H)                                   # 0/1 格线
    b[20:g - 12, 25:125] = 1                          # 上字（0 格）
    b[g + 12:int(2 * CELL_H) - 20, 25:125] = 1        # 下字（1 格）
    b[g - 12:g + 12, 70 + seam_shift:78 + seam_shift] = 1   # 粘桥（宽 8px）
    return b, g


def test_curve_splits_bridged_pair():
    b, g = _two_chars_touching()
    out = _split_touching_curve(b, _cells(), CELL_H, COL_W)
    assert _comp_count(b) == 1
    assert _comp_count(out) == 2
    # 两块各归各格：上块不越过 g+2、下块不越过 g-2 太多
    n, lab, st, _ = cv2.connectedComponentsWithStats(out, 8)
    tops = sorted((st[k, 1], st[k, 1] + st[k, 3]) for k in range(1, n)
                  if st[k, 4] >= 100)
    assert tops[0][1] <= g + 14      # 上块底 ≈ 桥内切口
    assert tops[1][0] >= g - 14


def test_curve_handles_fragment_adhesion():
    """碎片粘连（修/集病灶）：上一字主体独立、只有一条尾巴粘到下一字。

    直线版会被 MIN_PIECE（按连通体顶算上半块）拦住或把刀压到格线下方；
    曲线版的 frag 分支应在格线 ±SPLIT_FRAG_WIN 内断开，下一字顶部不被切走。
    """
    H, W = int(3 * CELL_H), int(COL_W)
    b = np.zeros((H, W), np.uint8)
    g = int(CELL_H)
    b[15:g - 40, 25:125] = 1                    # 上字主体（独立连通体）
    b[g - 44:g, 40:46] = 1                      # 上字尾巴（碎片，探到格线）
    b[g:int(2 * CELL_H) - 20, 25:125] = 1       # 下字（顶到格线，与尾巴相连）
    fused_h = (int(2 * CELL_H) - 20) - (g - 44)
    assert fused_h > 1.05 * CELL_H              # 确认属于 split 工作面
    out = _split_touching_curve(b, _cells(), CELL_H, COL_W)
    n, lab, st, _ = cv2.connectedComponentsWithStats(out, 8)
    comps = [(st[k, 1], st[k, 3], st[k, 4]) for k in range(1, n)
             if st[k, 4] >= 500]
    # 下字应完整保留：存在一个大块，顶不低于 g+3（顶部没被切走一条）
    lower = [c for c in comps if c[0] >= g - 2]
    assert lower, f"下字没了: {comps}"
    assert min(c[0] for c in lower) <= g + 3
    # 尾巴与下字断开：不再有跨 g 两侧各 >200px 的连通体
    for k in range(1, n):
        y, h_, a = st[k, 1], st[k, 3], st[k, 4]
        if a < 200 or not (y < g < y + h_):
            continue
        comp = lab == k
        assert min(int(comp[:g - 2].sum()), int(comp[g + 2:].sum())) < 200


def test_curve_keeps_thick_junction_for_hard_cut():
    """颈部过粗（超 NECK_ABS×列宽预算）时不动刀，留给按格线硬切。"""
    H, W = int(3 * CELL_H), int(COL_W)
    b = np.zeros((H, W), np.uint8)
    g = int(CELL_H)
    b[20:int(2 * CELL_H) - 20, 20:130] = 1      # 一整根实心柱贯穿两格
    out = _split_touching_curve(b, _cells(), CELL_H, COL_W)
    assert _comp_count(out) == 1                # 未被切开


def test_curve_matches_straight_on_clean_column():
    """无粘连的正常列（每格一个独立块）两个版本都不应动任何像素。"""
    H, W = int(3 * CELL_H), int(COL_W)
    b = np.zeros((H, W), np.uint8)
    for i in range(3):
        t = int(i * CELL_H)
        b[t + 15:t + int(CELL_H) - 15, 25:125] = 1
    out_s = _split_touching(b, _cells(), CELL_H, COL_W)
    out_c = _split_touching_curve(b, _cells(), CELL_H, COL_W)
    assert (out_s == b).all()
    assert (out_c == b).all()
