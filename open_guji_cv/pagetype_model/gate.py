# -*- coding: utf-8 -*-
"""页型模型闸：对一页出「非正文」判决（只拦不放；极少类 cover/label/blank 仍归现行规则）。

弃权（**不拦**）：没有 Step1 产物（列数<2）/ 灰度读不到 / 任何异常 / 现行规则已判 skip（不重复判）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .model import PageTypeModel
from .signals import extract


@dataclass
class PageTypeVerdict:
    nonbody: bool
    reason: str                       # nonbody | body | abstain:<why>
    scores: dict = field(default_factory=dict)

    def evidence(self, model: PageTypeModel) -> dict:
        return {"reason": self.reason, "scores": {k: round(v, 4) for k, v in self.scores.items()},
                "model": model.version, "signals": model.meta.get("signal_version")}


class PageTypeGate:
    def __init__(self, model: PageTypeModel):
        self.model = model

    def judge(self, gray, borders: dict | None) -> PageTypeVerdict:
        try:
            if not borders or len(borders.get("verticals") or []) < 2:
                return PageTypeVerdict(False, "abstain:no_borders")
            nb, sc = self.model.is_nonbody(extract(gray, borders))
            return PageTypeVerdict(nb, "nonbody" if nb else "body", sc)
        except Exception as e:           # 信号异常 → 弃权，绝不因模型出错改产物
            return PageTypeVerdict(False, f"abstain:error:{type(e).__name__}")
