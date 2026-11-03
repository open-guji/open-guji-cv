# -*- coding: utf-8 -*-
"""`seed_admit.ref_garble_follow`（史記 2026-11-03，第 4 轮 L 类乱码闸 44 格）：乱码闸拦下的格按参校本放，判据纯函数＋通道。"""
from __future__ import annotations

from types import SimpleNamespace as NS

from open_guji_cv.steps.seed_admit import SeedAdmitParams, _ref_garble_pass, ref_garble_decide

SEM = lambda c: c


def dec(**kw):
    base = dict(char="訟", ref="訓", cands=[("訟", 0.853)], verdict="unsure", guard=None,
                doubts=["库 unsure(cov=0.853)", "ctx_garble_shape"], evidence={}, semantic=SEM,
                cov_lo=0.85, cov_hi=0.90, col_healthy=True, block_ok=True)
    base.update(kw)
    return ref_garble_decide(**base)


def test_param_default_off_not_in_dump():
    d = SeedAdmitParams().model_dump()
    assert SeedAdmitParams().ref_garble_follow is False
    assert not [k for k in d if k.startswith("ref_garble")]
    assert SeedAdmitParams(ref_garble_follow=True).model_dump()["ref_garble_follow"] is True


def test_garble_cell_follows_ref():
    assert dec() is True


def test_blockers():
    assert dec(doubts=["库 unsure(cov=0.853)"]) is False                          # 不是乱码闸拦的
    assert dec(doubts=["库 unsure(cov=0.853)", "ctx_garble_shape", "occluded_x"]) is False   # 白名单外的疑问
    assert dec(cands=[("訟", 0.84)]) is False and dec(cands=[("訟", 0.90)]) is False  # cov 区间 [0.85, 0.90)
    assert dec(cands=[("訓", 0.88)]) is False                                      # 库首位已是整理本字（另有通道）
    assert dec(col_healthy=False) is False and dec(block_ok=False) is False
    assert dec(verdict="diff") is False and dec(guard={"x": 1}) is False
    assert dec(ref="") is False and dec(ref="〓") is False
    assert dec(ref="日", char="目", cands=[("目", 0.88)]) is False                  # 有专门解法的字族不碰
    assert dec(evidence={"human_unbound": {"char": "頭"}}) is False
    assert dec(evidence={"group": {"id": "g", "solvers": [{"solver": "x", "char": "訟"}]}}) is False


def _rec(i, char, admit=False, doubts=()):
    return NS(id=i, char=char, admit=admit, channel=None, provenance="", doubts=list(doubts), evidence={})


def test_pass_admits_with_trace_and_requires_healthy_column_and_good_block():
    p = SeedAdmitParams(reference_trust="very_high", ref_garble_follow=True)
    chars = [_rec(f"b:1:1:{k}", c, admit=True) for k, c in enumerate("甲乙丙丁", 1)]
    tgt = _rec("b:1:1:9", "訟", doubts=["库 unsure(cov=0.853)", "ctx_garble_shape"])
    col = NS(chars=chars + [tgt])
    coord = {r.id: r.char for r in chars} | {tgt.id: "訓"}
    mmap = {tgt.id: NS(candidates=[("訟", 0.853)], verdict="unsure", guard=None)}
    good = NS(ink_ratio=0.2, height=60, width=58)
    imap = {r.id: good for r in chars} | {tgt.id: good}
    vmap = NS(semantic=SEM)
    assert _ref_garble_pass(p, [col], mmap, {}, coord, vmap, imap) == 1
    assert (tgt.admit, tgt.char, tgt.channel, tgt.provenance) == (True, "訓", "ref_garble", "ref_garble")
    assert tgt.evidence["lane"]["ref_only"] is True and tgt.evidence["lane"]["machine"] == "訟"
    # 字块坏（墨量异常）→ 不放
    tgt2 = _rec("b:1:1:8", "訟", doubts=["库 unsure(cov=0.853)", "ctx_garble_shape"])
    col2 = NS(chars=chars + [tgt2])
    coord2 = coord | {tgt2.id: "訓"}
    mmap2 = {tgt2.id: mmap[tgt.id]}
    imap2 = imap | {tgt2.id: NS(ink_ratio=0.8, height=60, width=58)}
    assert _ref_garble_pass(p, [col2], mmap2, {}, coord2, vmap, imap2) == 0
    # 列内有一格放行字≠对位字 → 列不健康，不放
    bad = [_rec(f"b:1:1:{k}", c, admit=True) for k, c in enumerate("甲乙丙丁", 1)]
    coord3 = {r.id: r.char for r in bad} | {bad[0].id: "他", tgt2.id: "訓"}
    col3 = NS(chars=bad + [tgt2])
    assert _ref_garble_pass(p, [col3], mmap2, {}, coord3, vmap, {r.id: good for r in bad} | {tgt2.id: good}) == 0
