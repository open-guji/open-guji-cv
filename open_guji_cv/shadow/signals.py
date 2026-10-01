# -*- coding: utf-8 -*-
"""影子放行·逐格信号抽取（线上线下共用的单一口径）。

一格 → 若干行 `(字位, 候选)` 信号。候选集 = 库 top5 ∪ 5b top3 ∪ 整理本字 ∪ 现字（己已巳合并成「己」）。
特征 = `FEATURES`（12 个，与 `scripts/experiments/shadow_admit/vol03_eval.py` 的 F1N 同名同义）：

- 字形库（Step5-a 产物 `glyph_match.candidates`）：lib_cov / lib_in / lib_top1 / lib_margin / lib_top_cov / human_n / human_any
- 5b 生僻字：rare_score
- 整理本：ref_eq / ref_sem / ref_none（**不含 ref_op_equal**：该特征在 vol03 上语义反转，见 08-影子放行模型-计划 §十三）
- 形近：confusable

**第一阶段不带**：OCR 组（vol03 没有）、小笔画判别器（慢且要原图；消融显示全局影响小）、n_cands。

防泄漏（库信号摘除本格自身实例）：
- 训练侧（`extract.py`）对「有 `v2:` 人裁实例」的格读图重算并摘除自身；
- **线上不重算**（要原图+匹配器，太重）：本格自身在字形库里有实例（`v2:` 与不带前缀两种 id 都认）
  → `abstain("self_in_lib")`，**不出预测、不降级**。`human_n` 一律摘本格 id（两种前缀）。
  实测机器放行的格不进库，只有人裁格进库，而人裁格走 human 通道本来就不受影子管，所以这条弃权几乎零成本。
"""
from __future__ import annotations

from dataclasses import dataclass, field

SIGNAL_VERSION = "1"

FEATURES: tuple[str, ...] = (
    "lib_cov", "lib_in", "lib_top1", "lib_margin", "lib_top_cov", "human_n", "human_any",
    "rare_score", "ref_eq", "ref_sem", "ref_none", "confusable",
)

JYS = frozenset("己已巳")


def jmerge(c):
    """己已巳 合并成「己」（标签、候选、现字、整理本字一并合并，与训练口径一致）。"""
    return "己" if isinstance(c, str) and c in JYS else c


def norm_id(iid: str) -> str:
    return iid[3:] if iid.startswith("v2:") else iid


@dataclass
class CellEvidence:
    """一格的原始证据（来自上游产物，不读图）。"""
    id: str
    lib: list = field(default_factory=list)       # [(字, cov)]，Step5-a 候选
    rare: list = field(default_factory=list)      # [(字, score)]，Step5-b
    ref: str | None = None                        # 整理本对齐字
    cur: str | None = None                        # 现字（seed_admit 放行字）


@dataclass
class SignalContext:
    vm: object                                    # VariantMap（.semantic）
    partners: dict                                # 字 → 形近对手集合
    human_ids: dict                               # 字(己合并) → {人裁实例 id（无 v2: 前缀）}
    lib_ids: frozenset = frozenset()              # 字形库里所有刻例实例 id（无前缀）——判「本格自身在库里」


def candidates(ev: CellEvidence) -> tuple[list[str], dict, dict]:
    lib: dict[str, float] = {}
    for c, v in ev.lib:
        c = jmerge(c)
        lib[c] = max(lib.get(c, 0.0), float(v))
    rare: dict[str, float] = {}
    for c, v in ev.rare:
        c = jmerge(c)
        rare[c] = max(rare.get(c, 0.0), float(v))
    ref, cur = jmerge(ev.ref) if ev.ref else None, jmerge(ev.cur) if ev.cur else None
    lib_sorted = sorted(lib.items(), key=lambda t: -t[1])
    cands = list(dict.fromkeys(
        [c for c, _ in lib_sorted[:5]]
        + [c for c, _ in sorted(rare.items(), key=lambda t: -t[1])[:3]]
        + ([ref] if ref else []) + ([cur] if cur else [])))
    return cands, lib, rare


def build_rows(ev: CellEvidence, ctx: SignalContext) -> list[dict]:
    """→ 每个候选一行 `{"cand": 字, **FEATURES}`。无候选 → []。"""
    cands, lib, rare = candidates(ev)
    if not cands:
        return []
    ref = jmerge(ev.ref) if ev.ref else None
    lib_sorted = sorted(lib.items(), key=lambda t: -t[1])
    cset = set(cands)
    rows = []
    for c in cands:
        others = [v for x, v in lib.items() if x != c]
        hn = len([e for e in ctx.human_ids.get(c, ()) if e != norm_id(ev.id)])
        rows.append({
            "cand": c,
            "lib_cov": lib.get(c, 0.0), "lib_in": int(c in lib),
            "lib_top1": int(bool(lib_sorted) and lib_sorted[0][0] == c),
            "lib_margin": lib.get(c, 0.0) - (max(others) if others else 0.0),
            "lib_top_cov": lib_sorted[0][1] if lib_sorted else 0.0,
            "human_n": hn, "human_any": int(hn > 0),
            "rare_score": rare.get(c, 0.0),
            "ref_eq": int(ref == c),
            "ref_sem": int(bool(ref) and ref != c and ctx.vm.semantic(ref) == ctx.vm.semantic(c)),
            "ref_none": int(not ref),
            "confusable": int(bool(ctx.partners.get(c, frozenset()) & cset)),
        })
    return rows


def self_in_lib(ev: CellEvidence, ctx: SignalContext) -> bool:
    return norm_id(ev.id) in ctx.lib_ids


def load_context(db_path: str, variants: str | None = None) -> SignalContext:
    """从字形库（sqlite）读人裁实例与全部刻例 id；VariantMap / 形近表取默认。"""
    import sqlite3
    from ..clustering.confusable import partners as _partners
    from ..clustering.variants import VariantMap
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        human: dict[str, set] = {}
        lib_ids: set[str] = set()
        for ch, iid, st in db.execute(
                """SELECT g.char, e.instance_id, i.label_status FROM exemplars e
                   JOIN glyphs g ON g.glyph_id=e.glyph_id JOIN instances i ON i.instance_id=e.instance_id"""):
            lib_ids.add(norm_id(iid))
            if st == "human":
                human.setdefault(jmerge(ch), set()).add(norm_id(iid))
    finally:
        db.close()
    return SignalContext(vm=VariantMap.load(variants or None), partners=_partners(),
                         human_ids=human, lib_ids=frozenset(lib_ids))
