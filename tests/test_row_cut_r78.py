"""史記 r78 切点开关（A22 2026-11-17）：`cut_gap_keep_glyph`、`cut_white_row`。数据自造。"""
import cv2
import numpy as np

from open_guji_cv.impl.keben import row_boundaries as rb

P = 100.0   # 格高


def _cc(ink):
    return cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)[1:3]


def _splits(ink):
    lab, st = _cc(ink)
    return lambda cur, new: rb._gap_move_hurts(lab, st, cur, new, P)


def _c(kind, y=None):
    return rb.SeamCandidate(kind=kind, y=y, seam_ink=0, dev_max=0)


def _hook_pair():
    """上字身 y20–90（x15–40）；另一块是细钩：横 y60–62（x20–82）接竖 x80–82 一直伸到 y160（像戈钩尖）；下字 y166–226。
    直线 y170 压着下字头（不在白缝里）；y115 那条整片在大白里，只压钩 2 像素（过 clean），却把钩劈成两截。"""
    ink = np.zeros((240, 100), bool)
    ink[20:90, 15:40] = True
    ink[60:62, 42:82] = True
    ink[60:160, 80:82] = True
    ink[166:226, 10:60] = True
    return ink


def test_gap_keep_glyph_refuses_line_into_hook():
    ink = _hook_pair()
    straight = _c("straight")
    inner = _c("period_dn", [115] * ink.shape[1])
    cands = [straight, inner]
    assert rb._gap_guard(cands, 0, "rule", ink, 170.0, P, 0.08) == (1, "gap")          # 不开护栏：换到劈钩那条
    assert rb._gap_guard(cands, 0, "rule", ink, 170.0, P, 0.08, splits=_splits(ink)) == (0, "rule")


def test_gap_keep_glyph_refuses_lifting_upper_strokes():
    """上字下部是几小块（像彡，每块都小于单字门槛），y120–160；新线抬到 y115 会把它们一起划给下格，跨 0.4 格，不换。
    往下挪把下字字头划给上格不拦；抬一点（跨 <0.35 格，如把上格里的下字字头还给下格）也不拦。"""
    ink = np.zeros((260, 100), bool)
    ink[20:110, 20:80] = True
    for y0 in (120, 134, 148):
        ink[y0:y0 + 10, 30:60] = True
    ink[175:240, 20:80] = True
    lab, st = _cc(ink)
    assert rb._gap_move_hurts(lab, st, np.full(100, 168), np.full(100, 115), P)
    assert not rb._gap_move_hurts(lab, st, np.full(100, 115), np.full(100, 168), P)
    assert not rb._gap_move_hurts(lab, st, np.full(100, 168), np.full(100, 140), P)


def _tail_pair(white_gap=True):
    """上字身 x20–46（y10–90）；捺尾一块：横 y70–80（x50–90）接竖 x70–90 伸到 y128；下字 y135–200。
    直线 y100 劈开捺尾那块；y128–134 整行白。"""
    ink = np.zeros((220, 100), bool)
    ink[10:90, 20:46] = True
    ink[70:80, 50:90] = True
    ink[70:128, 70:90] = True
    ink[135:200, 15:55] = True
    if not white_gap:
        ink[127:136, 50:72] = True             # 两字粘连
    return ink


def test_white_row_moves_to_gap():
    ink = _tail_pair()
    up, dn = type("C", (), {"y0": 0.0})(), type("C", (), {"y1": 220.0})()
    cands, ch, by = rb._white_row([_c("straight")], 0, "rule", ink, _cc(ink), 100.0, P, 0.35, up, dn)
    assert by == "white" and cands[ch].kind == "white_row"
    assert 128 <= cands[ch].y[0] <= 134 and len(set(cands[ch].y)) == 1


def test_white_row_off_human_noisy():
    ink = _tail_pair()
    up, dn = type("C", (), {"y0": 0.0})(), type("C", (), {"y1": 220.0})()
    assert rb._white_row([_c("straight")], 0, "rule", ink, _cc(ink), 100.0, P, 0.0, up, dn)[2] == "rule"
    assert rb._white_row([_c("straight")], 0, "human", ink, _cc(ink), 100.0, P, 0.35, up, dn)[2] == "human"
    stuck = _tail_pair(white_gap=False)
    assert rb._white_row([_c("straight")], 0, "rule", stuck, _cc(stuck), 100.0, P, 0.35, up, dn)[2] == "rule"


def test_white_row_guards_inner_gap():
    """下字是「二」：上横 y118–126（x60–95）、下横 y170–180。上字竖尾自成一块（x45–55，y70–125），与上横不相碰但上下交叠，
    中间没有整行白；直线 y100 劈开竖尾，唯一整行白在二的两横之间——挪过去竖尾归上了，但二的上横会整块换到上格，不换。"""
    ink = np.zeros((220, 100), bool)
    ink[10:90, 25:40] = True
    ink[70:125, 45:55] = True            # 竖尾（自成一块）
    ink[118:126, 60:95] = True           # 二 上横
    ink[170:180, 5:95] = True            # 二 下横
    up, dn = type("C", (), {"y0": 0.0})(), type("C", (), {"y1": 230.0})()
    cands = [_c("straight")]
    lab, st = _cc(ink)
    assert len(rb._split_glyphs(lab, st, np.full(100, 100), P)) == 1   # 直线劈开竖尾
    r = rb._white_row(cands, 0, "rule", ink, (lab, st), 100.0, P, 0.5, up, dn)
    assert r[2] == "rule"


def test_cut_repair_expands_to_same_params():
    """`cut_repair: true` 一行＝史記 k24–k26 五个切点开关原值（A22 U2，2026-11-18）；单写的项照单写的，开关本身不进 dump。"""
    from open_guji_cv.steps.row_segment import CUT_REPAIR, RowSegmentParams
    a = RowSegmentParams(cut_repair=True)
    assert a.model_dump() == RowSegmentParams(**CUT_REPAIR).model_dump()
    assert RowSegmentParams(cut_repair=True, cut_free_seam=0.2).cut_free_seam == 0.2
    assert "cut_repair" not in RowSegmentParams().model_dump()


def test_split_blobs_lives_in_seg():
    """劈字判据抽进 `seg.seam`（A22 U2）：row_boundaries 的旧名照用、结果相同。"""
    import open_guji_cv.seg.seam as sm
    assert rb._split_glyphs.__doc__ and sm.split_blobs is not None
    assert rb.FREE_SEAM_FRAC == sm.SPLIT_FRAC and rb.FREE_SEAM_SIDE == sm.SIDE_TOL
