"""M5 上下文概率排序：列 lattice + beam search（语义层打分，字形层输出）。

score = λ·log P_ocr(char) + (1-λ)·log P_lm(semantic | semantic_context)

- LM 只见语义层；同槽位多候选映射到同一 semantic 时 LM 分相同，
  排序由字形层 P_ocr 裁决 —— 语言模型无权改判异体字形。
- 后验从 beam 假设集归一化近似；margin = p(1st) - p(2nd)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .lm import BaseLM

BEAM_WIDTH = 8
LAMBDA = 0.55
UNK = "<unk>"
UNK_LOGP = math.log(1e-4)

# 可疑标记阈值
MARGIN_THRESHOLD = 0.25


@dataclass
class SlotCandidate:
    char: str            # 字形层（精确异体字形）
    semantic: str        # 语义层（正字）
    p_ocr: float


@dataclass
class Slot:
    """lattice 中的一个字位。"""
    instance_id: str
    cluster_id: str | None
    candidates: list[SlotCandidate]
    flags: list[str] = field(default_factory=list)   # singleton / damaged 等


@dataclass
class SlotResult:
    instance_id: str
    cluster_id: str | None
    posterior: list[tuple[str, float]]   # [(char, p)]，降序
    margin: float
    best: str
    best_semantic: str
    suspect_reasons: list[str]


@dataclass
class _Hyp:
    logp: float
    chars: list[str]
    semantics: list[str]


def beam_search(slots: list[Slot], lm: BaseLM,
                lam: float = LAMBDA, beam_width: int = BEAM_WIDTH,
                context_size: int = 4) -> list[SlotResult]:
    """对一条槽位序列（一列或跨列拼接）解码。纯函数。"""
    beams: list[_Hyp] = [_Hyp(0.0, [], [])]

    for slot in slots:
        cands = slot.candidates or [SlotCandidate(UNK, UNK, 0.0)]
        expanded: list[_Hyp] = []
        for hyp in beams:
            ctx = tuple(hyp.semantics[-context_size:])
            for cand in cands:
                p_ocr = max(cand.p_ocr, 1e-6)
                lm_lp = UNK_LOGP if cand.char == UNK else lm.logp(cand.semantic, ctx)
                score = lam * math.log(p_ocr) + (1.0 - lam) * lm_lp
                expanded.append(_Hyp(hyp.logp + score,
                                     hyp.chars + [cand.char],
                                     hyp.semantics + [cand.semantic]))
        expanded.sort(key=lambda h: -h.logp)
        beams = expanded[:beam_width]

    # 从最终 beam 反推每槽位的后验近似
    if not beams:
        return []
    max_lp = max(h.logp for h in beams)
    weights = [math.exp(h.logp - max_lp) for h in beams]
    total_w = sum(weights)

    results: list[SlotResult] = []
    sem_of: dict[str, str] = {}
    for slot_i, slot in enumerate(slots):
        mass: dict[str, float] = {}
        for hyp, w in zip(beams, weights):
            ch = hyp.chars[slot_i]
            mass[ch] = mass.get(ch, 0.0) + w
            sem_of[ch] = hyp.semantics[slot_i]
        posterior = sorted(((c, w / total_w) for c, w in mass.items()),
                           key=lambda x: -x[1])
        margin = posterior[0][1] - (posterior[1][1] if len(posterior) > 1 else 0.0)
        best = posterior[0][0]

        reasons = list(slot.flags)
        if margin < MARGIN_THRESHOLD:
            reasons.append("low_margin")
        ocr_best = max(slot.candidates, key=lambda c: c.p_ocr).char \
            if slot.candidates else UNK
        if best != ocr_best and slot.candidates:
            reasons.append("lm_ocr_conflict")

        results.append(SlotResult(
            instance_id=slot.instance_id,
            cluster_id=slot.cluster_id,
            posterior=[(c, round(p, 4)) for c, p in posterior],
            margin=round(margin, 4),
            best=best,
            best_semantic=sem_of.get(best, best),
            suspect_reasons=reasons,
        ))
    return results


def check_cluster_consistency(results: list[SlotResult]) -> None:
    """同簇实例后验最优字不一致 → 追加 cluster_inconsistent（就地修改）。

    这是簇污染的强信号，审查优先级最高。
    """
    best_by_cluster: dict[str, set[str]] = {}
    for r in results:
        if r.cluster_id:
            best_by_cluster.setdefault(r.cluster_id, set()).add(r.best)
    for r in results:
        if r.cluster_id and len(best_by_cluster.get(r.cluster_id, set())) > 1:
            if "cluster_inconsistent" not in r.suspect_reasons:
                r.suspect_reasons.append("cluster_inconsistent")
