# -*- coding: utf-8 -*-
"""`seed_admit.ref_topk_follow`（史記 2026-11-03，P 类「机器字≠整理本」）：整理本字在库前 5 名且 cov 接近首位 → 按整理本放。判据纯函数。"""
from __future__ import annotations

from open_guji_cv.steps.seed_admit import SeedAdmitParams, ref_topk_decide

SEM = lambda c: c


def dec(**kw):
    base = dict(char="傳", ref="博", cands=[("傳", 0.958), ("傅", 0.95), ("博", 0.942)], verdict="unsure", guard=None,
                doubts=["库 unsure(cov=0.958)", "上下文 margin 不足(0.5)"], evidence={}, semantic=SEM)
    base.update(kw)
    return ref_topk_decide(**base)


def test_param_default_off_not_in_dump():
    assert SeedAdmitParams().ref_topk_follow is False
    assert "ref_topk_follow" not in SeedAdmitParams().model_dump()
    assert SeedAdmitParams(ref_topk_follow=True).model_dump()["ref_topk_follow"] is True


def test_ref_in_top5_close_cov_follows_ref_and_reports_rank():
    assert dec() == 3


def test_blockers():
    assert dec(cands=[("傳", 0.958), ("傅", 0.95), ("博", 0.80)]) == 0          # cov 差太大
    assert dec(cands=[("傳", 0.958), ("傅", 0.95)]) == 0                         # 整理本字不在候选里
    assert dec(char="博") == 0                                                    # 库首位已是整理本字（另有通道）
    assert dec(verdict="diff") == 0
    assert dec(guard={"x": 1}) == 0
    assert dec(doubts=["occluded_x"]) == 0                                        # 白名单外的疑问
    assert dec(char="一", ref="二", cands=[("一", 0.95), ("二", 0.94)]) == 0       # 有专门解法的字族不碰
    assert dec(evidence={"group": {"id": "g", "solvers": [{"solver": "x", "char": "傳"}]}}) == 0
