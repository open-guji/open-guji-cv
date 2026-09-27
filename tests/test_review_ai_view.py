# -*- coding: utf-8 -*-
"""`review/cards.py::_ai_view`：Step6-AI 证据（`groups`/`ai`）→ 卡片精简视图。

纯函数，不碰 `load_book`/`align_book`，直接拿 `DecisionRec` 造。覆盖的正是
任务书-C-人审卡按AI预选 的验收点：**没有 `ai` 字段的书（四庫）卡片行为
与现在逐像素一致**——即 `dr.ai is None` / `dr.groups == []` 时两个视图都是
`None`，卡片不显示 AI 部分。
"""
from __future__ import annotations

from open_guji_cv.products.kinds.recog import (AiDropReason, AiEvidence,
                                               AiRankItem, DecisionRec,
                                               GroupRec)
from open_guji_cv.review.cards import _ai_view


def test_none_record_gives_none_views():
    assert _ai_view(None) == (None, None)


def test_record_without_ai_or_groups_gives_none_views():
    """老书（四庫）没接 Step6-AI：`groups`/`ai` 都是默认值，卡片不该显示 AI 部分。"""
    dr = DecisionRec(id="vol01:1:1:1", slot=1, char="器")
    groups, ai = _ai_view(dr)
    assert groups is None
    assert ai is None


def test_groups_only_no_ai():
    """图像共识时可能已经分了组，但这一格没问过 AI（不在 11% 里）。"""
    dr = DecisionRec(id="b:1:1:1", slot=1, char="旣",
                     groups=[GroupRec(id="A", members=["旣", "既"], why="異體")])
    groups, ai = _ai_view(dr)
    assert groups == [{"id": "A", "members": ["旣", "既"], "why": "異體"}]
    assert ai is None


def test_ai_evidence_passthrough():
    dr = DecisionRec(
        id="b:1:1:1", slot=1, char=None,
        groups=[GroupRec(id="A", members=["北"], why="")],
        ai=AiEvidence(
            runs=2, drop=["批", "非"],
            drop_why=[AiDropReason(c="批", why="批文之义，与北无关")],
            rank=[AiRankItem(group="A", p=0.97, why="固定书名北行日録")],
            confidence="高", need_human="", conflict_with_img=False,
            runs_top=["北", "北"],
            fingerprint={"model": "muse-spark-1.2"},
        ),
    )
    groups, ai = _ai_view(dr)
    assert groups == [{"id": "A", "members": ["北"], "why": ""}]
    assert ai == {
        "runs": 2, "drop": ["批", "非"],
        "drop_why": [{"c": "批", "why": "批文之义，与北无关"}],
        "rank": [{"group": "A", "p": 0.97, "why": "固定书名北行日録"}],
        "confidence": "高", "need_human": "", "conflict_with_img": False,
        "runs_top": ["北", "北"],
    }


def test_conflict_and_disagreement_flags_carry_through():
    """两个卡片要标的旗子（疑似讹字 / AI拿不准）都只是原样传字段，判定逻辑在前端。"""
    dr = DecisionRec(id="b:1:1:1", slot=1,
                     ai=AiEvidence(runs=2, conflict_with_img=True,
                                  runs_top=["器", "噐"]))
    _, ai = _ai_view(dr)
    assert ai["conflict_with_img"] is True
    assert ai["runs_top"] == ["器", "噐"]
