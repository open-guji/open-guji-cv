"""Step3 候选池裁判（utils/cut_select.py）与 segment_column 的接线回归。

2026-09-14：候选池 {直线, 窄走廊, 宽走廊} 里几乎总有对的，错在选；U-Net v2 给每条候选打
置信加权一致率、取最高者（overview 05 卡实验六～七）。这里测三件事：
- owner_from_seam / ckpt_fingerprint 的口径；
- segment_column 的接线：裁判改选 → chosen / chosen_by / agree 落到候选上，seam_* 随之写或不写；
  裁判返回 None 或没有裁判时行为与旧规则逐位相同；人裁回流仍压过裁判；
- 真权重冒烟（有 torch 且权重在时）：对两个上下分离的墨块，贴着分界的缝比切进墨块的缝分数高。
"""
from __future__ import annotations

import numpy as np
import pytest

from open_guji_cv.utils import row_boundaries as RB
from open_guji_cv.utils.cut_select import DEFAULT_CKPT, ckpt_fingerprint, owner_from_seam

# 与 tests/test_row_boundaries.py 的合成列同一套几何
COL_W, SLOT_H, N_SLOTS, GRID_Y0, RULE_W = 185, 110, 21, 10, 4


def _touching_column(bridge_slots=(5, 6)):
    """Step 2 那样的列图：每格一个墨块（70 行高，格缝 40 行）；`bridge_slots` 的上下两格之间用**两根错位的竖条**
    连起来——左条从上格底伸到缝的下半、右条从缝的上半伸到下格顶，于是格缝里每一行都有墨（行投影没有谷，
    DP 只能把格线切在缝中间、直线穿墨），但存在一条零墨折线：左边从左条下面过、右边从右条上面过，
    偏移约 16–20 px（≥10，不会被「窄走廊零墨且贴线」那条收缩规则收成单候选）。池 = {直线, 窄走廊}。"""
    h = GRID_Y0 + N_SLOTS * SLOT_H + 20
    img = np.full((h, COL_W), 255, dtype=np.uint8)
    img[:, :RULE_W] = 0
    img[:, -RULE_W:] = 0
    img[0:4, :] = 0
    img[h - 4:, :] = 0
    for k in range(N_SLOTS):
        y0 = GRID_Y0 + k * SLOT_H + 20
        img[y0:y0 + 70, 37:148] = 0
    a, b = bridge_slots
    ya = GRID_Y0 + (a - 1) * SLOT_H + 20 + 70          # 上格墨块底（缝顶）
    yb = GRID_Y0 + (b - 1) * SLOT_H + 20                # 下格墨块顶（缝底）= ya + 40
    img[ya:yb - 5, 55:75] = 0                            # 左条：缝顶 → 缝底上方 5 行
    img[ya + 5:yb, 115:135] = 0                          # 右条：缝顶下方 5 行 → 缝底
    return img


class _FakeJudge:
    """按 kind 给定分数；记录被问过几次。"""

    def __init__(self, prefer: dict[str, float] | None):
        self.prefer = prefer
        self.calls = 0

    def __init__(self, prefer: dict[str, float] | None, dis: dict[str, int] | None = None):  # noqa: F811
        self.prefer = prefer
        self.dis = dis or {}
        self.calls = 0

    def assess(self, col_gray, x_lo, x_hi, y0, y1, y_line, seams, ink_threshold=128):
        self.calls += 1
        if self.prefer is None:
            return None
        # seams[i] 为 None = 直线；其余按长度识别不了 kind，这里靠调用方候选顺序：直线恒在池首
        sc, dis = [], []
        for sm in seams:
            key = "straight" if sm is None else "seam"
            sc.append(self.prefer[key])
            dis.append(self.dis.get(key, 0))
        return sc, dis

    def scores(self, *a, **kw):
        r = self.assess(*a, **kw)
        return None if r is None else r[0]


def _cut(r, slot_above=5):
    return next(cp for cp in r.cut_candidates if cp.slot_above == slot_above)


def test_owner_from_seam_splits_ink_by_row_against_seam():
    ink = np.zeros((6, 3), np.uint8)
    ink[1, :] = 1
    ink[4, :] = 1
    seam = np.array([3, 3, 5])           # 第三列的缝更低：第 4 行在它之上 → 归上
    o = owner_from_seam(ink, seam)
    assert o[1].tolist() == [1, 1, 1] and o[4].tolist() == [2, 2, 1]
    assert (o[0] == 0).all() and (o[2] == 0).all()


def test_ckpt_fingerprint_empty_for_missing_file(tmp_path):
    assert ckpt_fingerprint(tmp_path / "nope.pt") == ""
    if DEFAULT_CKPT.exists():
        assert len(ckpt_fingerprint()) == 12


def test_segment_column_pool_has_two_candidates_and_rule_picks_the_seam():
    """基线（无裁判）：池 = {直线, 零墨折线}，现役规则选折线（零墨、偏移 ≥10 不被收缩），写 seam_*。"""
    img = _touching_column()
    r = RB.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS)
    cp = _cut(r)
    kinds = [c.kind for c in cp.candidates]
    assert kinds[0] == "straight" and len(kinds) == 2 and kinds[1].startswith("seam_")
    assert cp.candidates[1].seam_ink == 0 and cp.candidates[1].dev_max >= 10
    assert cp.chosen == 1 and cp.chosen_by == "rule"
    assert all(c.agree is None for c in cp.candidates)
    up = next(c for c in r.cells if c.slot == 5)
    assert up.seam_bottom is not None


def test_judge_can_flip_to_straight_and_records_agree_and_chosen_by():
    img = _touching_column()
    j = _FakeJudge({"straight": 0.95, "seam": 0.90})        # 裁判更认直线
    r = RB.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS, cut_judge=j)
    cp = _cut(r)
    assert j.calls >= 1
    assert cp.candidates[cp.chosen].kind == "straight" and cp.chosen_by == "unet"
    assert [c.agree for c in cp.candidates] == [0.95, 0.90]
    up = next(c for c in r.cells if c.slot == 5)
    dn = next(c for c in r.cells if c.slot == 6)
    assert up.seam_bottom is None and dn.seam_top is None   # 改选直线后不再写 seam_*


def test_judge_agreeing_with_rule_keeps_rule_choice_and_records_agree():
    img = _touching_column()
    j = _FakeJudge({"straight": 0.80, "seam": 0.99})
    r = RB.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS, cut_judge=j)
    cp = _cut(r)
    assert cp.chosen == 1 and cp.candidates[1].kind.startswith("seam_") and cp.chosen_by == "rule"
    assert [c.agree for c in cp.candidates] == [0.80, 0.99]     # 裁判跑过的痕迹
    up = next(c for c in r.cells if c.slot == 5)
    assert up.seam_bottom is not None


def test_judge_tie_or_small_margin_keeps_rule_choice():
    img = _touching_column()
    r = RB.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS, cut_judge=_FakeJudge({"straight": 0.9, "seam": 0.9}))
    cp = _cut(r)
    assert cp.chosen == 1 and cp.chosen_by == "rule"
    # 差距不到门槛（JUDGE_MARGIN=0.005）也不改选
    r = RB.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS, cut_judge=_FakeJudge({"straight": 0.903, "seam": 0.9}))
    cp = _cut(r)
    assert cp.chosen == 1 and cp.chosen_by == "rule"


def test_judge_returning_none_falls_back_to_rule_bitwise():
    img = _touching_column()
    base = RB.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS)
    r = RB.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS, cut_judge=_FakeJudge(None))
    cp0, cp1 = _cut(base), _cut(r)
    assert cp1.chosen == cp0.chosen and cp1.chosen_by == "rule"
    assert [c.kind for c in cp1.candidates] == [c.kind for c in cp0.candidates]
    assert base.boundaries == r.boundaries


def test_human_resolution_overrides_judge():
    img = _touching_column()
    j = _FakeJudge({"straight": 0.80, "seam": 0.99})       # 裁判想选折线
    r = RB.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS, cut_judge=j,
                          resolved_cuts={5: "straight"})    # 人说直线
    cp = _cut(r)
    assert len(cp.candidates) == 1 and cp.candidates[0].kind == "straight"
    assert cp.chosen == 0 and cp.chosen_by == "human"


@pytest.mark.skipif(not DEFAULT_CKPT.exists(), reason="没有 U-Net 权重")
def test_real_judge_prefers_seam_that_respects_two_blobs():
    torch = pytest.importorskip("torch")  # noqa: F841
    from open_guji_cv.utils.cut_select import get_judge
    judge = get_judge()
    assert judge is not None
    # 两个墨块：上块 10..60 行、下块 80..130 行，中间 20 行空白；一条缝走空白（y=70），
    # 另一条切进上块（y=40）——判读不需要字形，只看归属一致性
    col = np.full((150, 120), 255, np.uint8)
    col[10:60, 20:100] = 0
    col[80:130, 20:100] = 0
    good = np.full(120, 70)
    bad = np.full(120, 40)
    sc = judge.scores(col, 0, 120, 0, 150, 70.0, [None, good, bad])
    assert sc is not None and len(sc) == 3
    assert sc[1] > sc[2] and sc[0] == sc[1]          # 直线 y=70 与 good 同一条线


def test_seam_ok_resolution_collapses_to_the_rule_seam_not_the_judge_choice():
    """`seam_ok`（RESOLVED_CHOSEN）= 人当时看到的现役折线就对。裁判想改直线也不行，而且收敛到的必须是规则选的那条折线
    （2026-09-14 vol02 p33 实锤：裁判先改选、seam_ok 再收敛，就把裁判的选择当成了人裁）。"""
    from open_guji_cv.utils.row_boundaries import RESOLVED_CHOSEN, ResolvedCut
    img = _touching_column()
    base = _cut(RB.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS))
    rule_seam = base.candidates[base.chosen].y
    j = _FakeJudge({"straight": 0.99, "seam": 0.80})           # 裁判强烈想改直线
    r = RB.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS, cut_judge=j,
                          resolved_cuts={5: ResolvedCut(RESOLVED_CHOSEN)})
    cp = _cut(r)
    assert len(cp.candidates) == 1 and cp.candidates[0].y == rule_seam and cp.chosen_by == "human"
    assert cp.escalate is False                                 # 人是终审：探针照记 agree/dis_unet，但不升级


def test_seam_ok_with_polyline_collapses_to_the_matching_seam_not_the_current_choice():
    """`seam_ok` 带人看到的折线：池里与它一致的那条才是人裁的，哪怕规则这次选中了别的；
    池里没有一致的就不收敛（留给裁判）。2026-09-14 vol02 p33 c9 s18 实锤。"""
    from open_guji_cv.utils.row_boundaries import RESOLVED_CHOSEN, ResolvedCut, SeamCandidate, _apply_resolved_cut
    narrow = SeamCandidate("seam_narrow", y=[100] * 5 + [112] * 5, seam_ink=4, dev_max=12)
    wide = SeamCandidate("seam_wide", y=[100] * 5 + [121] * 5, seam_ink=2, dev_max=21)
    pool = [SeamCandidate("straight"), narrow, wide]
    poly_narrow = [[10, 100], [14, 100], [15, 112], [19, 112]]       # 人当时看到的是窄走廊那条
    rc = ResolvedCut(RESOLVED_CHOSEN, y_ref=None, seam_ref=poly_narrow)
    cands, chosen = _apply_resolved_cut(pool, chosen=2, resolved=rc, x_lo=10)   # 规则这次选了宽走廊
    assert [c.kind for c in cands] == ["seam_narrow"] and chosen == 0
    rc2 = ResolvedCut(RESOLVED_CHOSEN, y_ref=None, seam_ref=[[10, 100], [19, 140]])   # 池里没有这条
    cands, chosen = _apply_resolved_cut(pool, chosen=2, resolved=rc2, x_lo=10)
    assert cands == pool and chosen == 2
    # 没给 seam_ref（老裁决）沿用旧口径：收敛到现役选中
    cands, chosen = _apply_resolved_cut(pool, chosen=2, resolved=ResolvedCut(RESOLVED_CHOSEN), x_lo=10)
    assert [c.kind for c in cands] == ["seam_wide"]


def test_escalate_flag_set_when_chosen_disagrees_with_unet_by_a_big_blob():
    """L2′：所选切法与 U-Net 分歧块 ≥ ESCALATE_BLOB → escalate=True，但**选法不变**（只记录，交下游再审）。"""
    from open_guji_cv.utils.cut_select import ESCALATE_BLOB
    img = _touching_column()
    j = _FakeJudge({"straight": 0.80, "seam": 0.99}, dis={"seam": ESCALATE_BLOB + 50, "straight": 300})
    r = RB.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS, cut_judge=j)
    cp = _cut(r)
    assert cp.chosen == 1 and cp.chosen_by == "rule"            # 规则选的折线没被改
    assert cp.escalate is True and "dis_unet=" in (cp.escalate_reason or "")
    assert [c.dis_unet for c in cp.candidates] == [300, ESCALATE_BLOB + 50]
    j2 = _FakeJudge({"straight": 0.80, "seam": 0.99}, dis={"seam": 10, "straight": 300})
    cp2 = _cut(RB.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS, cut_judge=j2))
    assert cp2.escalate is False and cp2.escalate_reason is None


def test_single_candidate_cut_is_also_probed_and_can_escalate():
    """单候选（例：文言 vol02:163:1:6，池里只有直线）也要过探针：U-Net 说差一大块就升级，选法仍是直线。"""
    from open_guji_cv.utils import row_boundaries as RBm
    from open_guji_cv.utils.cut_select import ESCALATE_BLOB
    # 用人裁把池收成单候选之外的办法：monkeypatch 让缝搜索不产出折线 → 只剩直线
    img = _touching_column()
    j = _FakeJudge({"straight": 0.80, "seam": 0.99}, dis={"straight": ESCALATE_BLOB + 1})
    import open_guji_cv.utils.seam as seam_mod
    orig = seam_mod.find_seam
    try:
        seam_mod.find_seam = lambda ink, y, band=20, **kw: __import__("numpy").full(ink.shape[1], y, dtype=int)
        r = RBm.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS, cut_judge=j)
    finally:
        seam_mod.find_seam = orig
    cp = _cut(r)
    assert len(cp.candidates) == 1 and cp.candidates[0].kind == "straight"
    assert cp.candidates[0].dis_unet == ESCALATE_BLOB + 1 and cp.escalate is True


def test_human_resolved_cut_never_escalates():
    img = _touching_column()
    j = _FakeJudge({"straight": 0.80, "seam": 0.99}, dis={"straight": 999, "seam": 999})
    r = RB.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS, cut_judge=j, resolved_cuts={5: "straight"})
    cp = _cut(r)
    assert cp.chosen_by == "human" and cp.escalate is False
    assert cp.candidates[0].dis_unet == 999                      # 但探针结果照记，供审计


def test_clean_line_between_short_and_tall_cells_with_full_ink_becomes_probe_cut(monkeypatch):
    """L0′：直线不穿墨（DP 切在字内空隙），但一矮一高且矮格墨满 → 建一个只有直线的切点、过探针；
    U-Net 分歧大就升级；选法仍是直线。文言 vol02:163:1:6 的形态：言的顶横被切给文，格线落在言内部的空隙。"""
    import numpy as np
    from open_guji_cv.utils import row_boundaries as RBm
    from open_guji_cv.utils.cut_select import ESCALATE_BLOB
    h = GRID_Y0 + N_SLOTS * SLOT_H + 20
    img = np.full((h, COL_W), 255, dtype=np.uint8)
    img[:, :RULE_W] = 0; img[:, -RULE_W:] = 0; img[0:4, :] = 0; img[h - 4:, :] = 0
    for k in range(N_SLOTS):
        y0 = GRID_Y0 + k * SLOT_H + 20
        img[y0:y0 + 70, 37:148] = 0
    # 第 6 格的字：顶横（8 行）在主体上方 30 行处，中间 22 行空白——像「言」
    y6 = GRID_Y0 + 5 * SLOT_H + 20
    img[y6:y6 + 70, 37:148] = 255
    img[y6 + 30:y6 + 70, 37:148] = 0          # 主体
    img[y6:y6 + 8, 50:135] = 0                # 顶横
    gap_y = y6 + 19                           # 顶横与主体之间的空隙行（干净）
    real_fit = RBm.fit_row_boundaries

    def pinned(*a, **kw):
        res = real_fit(*a, **kw)
        if res is not None:
            b = list(res.boundaries); b[5] = float(gap_y); res.boundaries = b
        return res
    monkeypatch.setattr(RBm, "fit_row_boundaries", pinned)
    j = _FakeJudge({"straight": 0.5, "seam": 0.5}, dis={"straight": ESCALATE_BLOB + 20})
    r = RBm.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS, ref_w=COL_W, cut_judge=j)
    cp = next(c for c in r.cut_candidates if c.slot_above == 5)
    assert cp.origin == "split_suspect" and cp.candidates[0].kind == "straight"
    assert cp.escalate is True and cp.escalate_reason.startswith("split_suspect")
    assert cp.chosen == 0 and cp.chosen_by == "rule"           # 升级后 L3 会补候选（period_up 等），但选法不动
    assert all(c.kind in ("straight", "unet_seam", "period_up", "period_dn") for c in cp.candidates)
    # 同样几何、U-Net 不觉得有问题 → 建了切点但不升级
    r2 = RBm.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS, ref_w=COL_W,
                            cut_judge=_FakeJudge({"straight": 0.5, "seam": 0.5}, dis={"straight": 5}))
    cp2 = next(c for c in r2.cut_candidates if c.slot_above == 5)
    assert cp2.origin == "split_suspect" and cp2.escalate is False


def test_clean_line_between_normal_cells_builds_no_cut_point():
    """干净且格高正常的格线照旧不建切点（L0 直接放行），行为与改动前一致。"""
    img = _touching_column()
    r = RB.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS, cut_judge=_FakeJudge({"straight": 0.5, "seam": 0.5}))
    assert {cp.slot_above for cp in r.cut_candidates} == {5}      # 只有 5/6 那条粘连
    assert all(cp.origin == "touching" for cp in r.cut_candidates)


def test_guided_seam_from_owner_follows_the_partition():
    """两块墨：上块 U-Net 判上、下块判下，中间空 20 行 → 引导缝走在两块之间；下块顶部一条横被判成上字时，缝绕到它下面。"""
    import numpy as np
    from open_guji_cv.utils.cut_select import guided_seam_from_owner
    owner = np.zeros((150, 60), np.uint8)
    owner[10:60, 10:50] = 1
    owner[80:130, 10:50] = 2
    sm = guided_seam_from_owner(owner, 70)
    assert sm is not None and len(sm) == 60 and (60 <= sm).all() and (sm <= 80).all()
    owner[80:86, 10:50] = 1                       # 下块顶横其实属于上字
    sm2 = guided_seam_from_owner(owner, 70)
    assert (sm2[10:50] >= 86).all()               # 缝从横的下面过


def test_escalated_cut_gets_expanded_pool_but_selection_unchanged():
    """L3：升级的切点补 unet_seam / period_* 候选（带 agree、dis_unet），chosen 不动；没升级的池不变。"""
    import numpy as np
    from open_guji_cv.utils.cut_select import ESCALATE_BLOB

    class _J(_FakeJudge):
        def guided_seam(self, col_gray, x_lo, x_hi, y0, y1, y_line, ink_threshold=128, band=45):
            return np.full(x_hi - x_lo, int(round(y_line)) + 17)
    img = _touching_column()
    j = _J({"straight": 0.80, "seam": 0.99}, dis={"seam": ESCALATE_BLOB + 50, "straight": 300})
    r = RB.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS, cut_judge=j)
    cp = _cut(r)
    kinds = [c.kind for c in cp.candidates]
    assert cp.escalate is True and "unet_seam" in kinds
    assert cp.chosen == 1 and cp.candidates[cp.chosen].kind.startswith("seam_") and cp.chosen_by == "rule"
    ext = next(c for c in cp.candidates if c.kind == "unet_seam")
    assert ext.agree is not None and ext.dis_unet is not None and ext.dev_max == 17
    j2 = _J({"straight": 0.80, "seam": 0.99}, dis={"seam": 5, "straight": 300})
    cp2 = _cut(RB.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS, cut_judge=j2))
    assert cp2.escalate is False and "unet_seam" not in [c.kind for c in cp2.candidates]



def test_human_pick_of_an_l3_candidate_converges_after_expansion():
    """人裁指向 L3 扩池才生成的 kind（unet_seam）时，第 4 步收敛落空（那时池里没有它），
    扩池后要再试一次——否则人裁永远不生效（2026-09-15 实锤：147 条里 119 条没落地）。"""
    import numpy as np
    from open_guji_cv.utils.cut_select import ESCALATE_BLOB

    class _J(_FakeJudge):
        def guided_seam(self, col_gray, x_lo, x_hi, y0, y1, y_line, ink_threshold=128, band=45):
            return np.full(x_hi - x_lo, int(round(y_line)) + 17)
    img = _touching_column()
    j = _J({"straight": 0.80, "seam": 0.99}, dis={"seam": ESCALATE_BLOB + 50, "straight": 300})
    r = RB.segment_column(img, period=SLOT_H, n_body_slots=N_SLOTS, cut_judge=j,
                          resolved_cuts={5: "unet_seam"})
    cp = _cut(r)
    assert [c.kind for c in cp.candidates] == ["unet_seam"]      # 收敛到人选的那条
    assert cp.chosen == 0 and cp.chosen_by == "human"
    assert cp.escalate is False                                  # 人是终审，不再升级出卡
    up = next(c for c in r.cells if c.slot == 5)
    assert up.seam_bottom is not None                            # 折线候选被选中 → 写 seam_*
