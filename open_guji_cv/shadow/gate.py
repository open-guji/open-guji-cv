# -*- coding: utf-8 -*-
"""影子放行闸：对一格出 veto 决定（只降级，不升级）。

规则（`seed_admit` 的 `shadow_veto` 开启时，对**现行规则已放行**的格逐格调用）：

1. 弃权（**不降级**）：无候选 / 现字缺失 / 本格自身在字形库里（防泄漏，见 `signals`）/ 任何异常。
2. 影子选了**不同的字**（己已巳合并后比较）且把握度 ≥ `conf` → veto（reason=differs）。
3. 可选：影子对这一格的最大把握度 < `low_conf`（>0 才启用）→ veto（reason=low_conf）。
   缺省关：低把握降级会多审很多格，要看 HANDOFF 里的实测再开。

人裁通道、印章遮挡等硬护栏都在 seed_admit 里、模型之外；本模块拿不到也改不了它们。
"""
from __future__ import annotations

from dataclasses import dataclass

from .model import ShadowModel
from .signals import CellEvidence, SignalContext, build_rows, jmerge, self_in_lib


@dataclass
class ShadowVerdict:
    veto: bool
    reason: str                 # differs | low_conf | agree | abstain:<why>
    pick: str | None = None
    conf: float | None = None
    cur_conf: float | None = None

    def evidence(self, model: ShadowModel, conf_thr: float, low_conf: float) -> dict:
        return {"reason": self.reason, "pick": self.pick,
                "conf": None if self.conf is None else round(self.conf, 4),
                "cur_conf": None if self.cur_conf is None else round(self.cur_conf, 4),
                "model": model.version, "signals": model.meta.get("signal_version"),
                "conf_thr": conf_thr, **({"low_conf": low_conf} if low_conf else {})}


class ShadowGate:
    def __init__(self, model: ShadowModel, ctx: SignalContext, conf: float, low_conf: float = 0.0):
        self.model, self.ctx, self.conf, self.low_conf = model, ctx, conf, low_conf

    def judge(self, ev: CellEvidence) -> ShadowVerdict:
        try:
            return self._judge(ev)
        except Exception as e:                      # 信号异常 → 弃权，绝不因模型出错改产物
            return ShadowVerdict(False, f"abstain:error:{type(e).__name__}")

    def _judge(self, ev: CellEvidence) -> ShadowVerdict:
        if not ev.cur:
            return ShadowVerdict(False, "abstain:no_cur")
        if self_in_lib(ev, self.ctx):
            return ShadowVerdict(False, "abstain:self_in_lib")
        rows = build_rows(ev, self.ctx, self.model.meta.get("signal_version", "1"))
        if not rows:
            return ShadowVerdict(False, "abstain:no_candidates")
        sc = self.model.scores(rows)
        tot = max(sum(sc), 1e-9)
        best = max(range(len(rows)), key=lambda i: sc[i])
        pick, conf = rows[best]["cand"], sc[best] / tot
        cur = jmerge(ev.cur)
        cur_conf = next((s / tot for r, s in zip(rows, sc) if r["cand"] == cur), 0.0)
        if pick != cur and conf >= self.conf:
            return ShadowVerdict(True, "differs", pick, conf, cur_conf)
        if self.low_conf > 0 and conf < self.low_conf:
            return ShadowVerdict(True, "low_conf", pick, conf, cur_conf)
        return ShadowVerdict(False, "agree" if pick == cur else "differs_below_thr", pick, conf, cur_conf)


@dataclass
class PromoteVerdict:
    promote: bool
    reason: str                 # promote | below_thr | no_backing | jys | abstain:<why>
    pick: str | None = None
    conf: float | None = None
    backed_by: tuple = ()       # ("ref", "lib") 中有哪几路独立背书

    def evidence(self, model: ShadowModel, conf_thr: float) -> dict:
        return {"reason": self.reason, "pick": self.pick,
                "conf": None if self.conf is None else round(self.conf, 4),
                "backed_by": list(self.backed_by), "model": model.version,
                "signals": model.meta.get("signal_version"), "conf_thr": conf_thr}


def promote_judge(gate: ShadowGate, ev: CellEvidence, conf_thr: float, check_self: bool = True) -> PromoteVerdict:
    """影子升级：待审格上，影子首选**等于整理本字或库首位**（至少一路独立背书）且把握度 ≥ 门槛 → 放行。

    背书之外的首选（影子自己从 5-b／别处挑出来的字）一律不放——影子再有把握也只是在「库」「整理本」
    两路已有的提名里仲裁，不凭空提名。己已巳不经这里（读法归 `_resolve_ji_yi_si`）。信号缺失／本格自身在库里／异常 → 弃权。
    `check_self=False` 仅供离线评测（人裁格全在库里，评测要摘本格自身的库信号，`build_rows` 的 `human_n` 已摘）。"""
    try:
        if check_self and self_in_lib(ev, gate.ctx):
            return PromoteVerdict(False, "abstain:self_in_lib")
        rows = build_rows(ev, gate.ctx, gate.model.meta.get("signal_version", "1"))
        if not rows:
            return PromoteVerdict(False, "abstain:no_candidates")
        sc = gate.model.scores(rows)
        tot = max(sum(sc), 1e-9)
        best = max(range(len(rows)), key=lambda i: sc[i])
        pick, conf = rows[best]["cand"], sc[best] / tot
        return decide_promote(pick, conf, ev, conf_thr)
    except Exception as e:                          # 信号异常 → 弃权
        return PromoteVerdict(False, f"abstain:error:{type(e).__name__}")


def decide_promote(pick: str, conf: float, ev: CellEvidence, conf_thr: float) -> PromoteVerdict:
    """把握度之后的纯判据（线上、离线评测共用）。"""
    if pick == "己":
        return PromoteVerdict(False, "jys", pick, conf)
    lib_top = max(ev.lib, key=lambda t: t[1])[0] if ev.lib else None
    backed = tuple(n for n, ok in (("ref", bool(ev.ref) and jmerge(ev.ref) == pick),
                                   ("lib", bool(lib_top) and jmerge(lib_top) == pick)) if ok)
    if not backed:
        return PromoteVerdict(False, "no_backing", pick, conf)
    if conf < conf_thr:
        return PromoteVerdict(False, "below_thr", pick, conf, backed)
    return PromoteVerdict(True, "promote", pick, conf, backed)
