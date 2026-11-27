"""脉经 `row_segment.adopt_rel`：大分歧时按相对门槛改选扩池候选（2026-11-18）。数据自造。"""
from open_guji_cv.impl.keben import row_boundaries as rb
from open_guji_cv.seg.cut_select import ADOPT_REL_CAP, ADOPT_REL_MIN


def _c(kind, dis, ink):
    c = rb.SeamCandidate(kind=kind, y=None, seam_ink=ink, dev_max=0)
    c.dis_unet = dis
    return c


def _pool():
    # 前两条是原池（n_old=2），后两条是扩池来的
    return [_c("straight", ADOPT_REL_MIN + 500, 0), _c("seam_narrow", ADOPT_REL_MIN + 400, 5),
            _c("unet_seam", 120, 45), _c("period_up", 200, 3)]


def test_off_or_small_dis_noop():
    assert rb._adopt_rel_pick(_pool(), 2, ADOPT_REL_MIN + 500, 20, 0.0) is None
    assert rb._adopt_rel_pick(_pool(), 2, ADOPT_REL_MIN - 1, 20, 0.15) is None


def test_picks_lowest_dis_expanded():
    assert rb._adopt_rel_pick(_pool(), 2, ADOPT_REL_MIN + 500, 20, 0.15) == 2
    # 原池里的候选再低也不算（只认扩池来的）
    pool = _pool()
    pool[1].dis_unet = 1
    assert rb._adopt_rel_pick(pool, 2, ADOPT_REL_MIN + 500, 20, 0.15) == 2


def test_caps():
    pool = _pool()
    pool[2].dis_unet = ADOPT_REL_CAP + 1
    pool[3].dis_unet = ADOPT_REL_CAP + 1
    assert rb._adopt_rel_pick(pool, 2, 10 * ADOPT_REL_MIN, 20, 0.15) is None     # 绝对上限
    pool = _pool()
    assert rb._adopt_rel_pick(pool, 2, ADOPT_REL_MIN, 20, 0.05) is None          # 0.05×1500=75 < 120、200


def test_clean_line_only_inkless():
    assert rb._adopt_rel_pick(_pool(), 2, ADOPT_REL_MIN + 500, 0, 0.15) is None
    pool = _pool()
    pool[3].seam_ink = 0
    assert rb._adopt_rel_pick(pool, 2, ADOPT_REL_MIN + 500, 0, 0.15) == 3
