"""Step6 上下文裁决：库候选 + OCR 候选 + 同列前文 → 定字。

包的是 `clustering/context_step`（策略注册表）+ `recognize_flow.fuse_priors`
（两路候选融合）+ `seeding.build_seed_lm`（本书 3-gram 0.9 + 通用 0.1 线性
插值）。**算法一行没改。**

## 两条铁律（换任何模型都不许破，抄自 context_step 模块头）

1. **字形层不可改写**：只在候选集合内重排，不得引入候选外的字。参考文本与
   语料多为正字化文本，放开这条就会把本版的异体用字「改正」掉，破坏字形库
   的真实性。
2. **门槛化，不做全局重排**：`context-correction` 集 1681 真实槽位实测，对
   含库匹配证据的强先验做**无条件重排在任何 λ 下净亏**（λ=0.95 仍救 17/坏 34）；
   语义 margin 过阈才动手（生产阈 0.70：303 条实审全对）。拿不准就保持基线。

## 为什么产物要带语料指纹

LM 是从语料训的，语料换了同一批候选的裁决就会变，而代码/参数/上游产物一个
都没动——同 `glyph_match` 带库指纹是一回事（那一步的模块头有完整论证）。
`corpus_fingerprint` 因此进参数、参与 `params_hash`。

## 上下文取法

同列**前文**：按**阅读顺序**（`utils/jiazhu_order.sort_by_reading`，与
`row_boundaries.reading_order` 同源）取本列已定字位里最近的若干个。没有夹注
的列，读序就是 slot 升序；有夹注时一段内先读 a 子列全部、再读 b 子列全部，
**不能按 (slot, sub) 排**——那样两行小字会交错成「兩採淮進鹽本政」，前向
n-gram 必然给不出 margin（2026-09-06 实测与修复）。
LM 是前向 n-gram，只看前文。跨列不接（`reading_order` 的输入就是一列），
列首字位因此没有上下文，退化成纯先验融合——`ContextResult.decision.
used_context` 会注明。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel

from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.recog import (ColumnDecision, DecisionRec,
                                    PageDecision, PageMatch, PageOcr)
from ..utils.jiazhu_order import sort_by_reading

DEFAULT_CORPUS = "corpus/zongmu_wuyingdian_reference.txt"


def corpus_fingerprint(paths: list[str]) -> str:
    """语料的轻量指纹：每份 (name, mtime_ns, size) 的哈希。见模块头。"""
    parts = []
    for s in paths:
        p = Path(s)
        if p.exists():
            st = p.stat()
            parts.append(f"{p.name}:{st.st_mtime_ns}:{st.st_size}")
        else:
            parts.append(f"{p.name}:missing")
    if not parts:
        return "nocorpus"
    return hashlib.sha256("|".join(sorted(parts)).encode()).hexdigest()[:16]


class ContextDecideParams(BaseModel):
    corpus: str = DEFAULT_CORPUS
    general_corpus_dir: str = "corpus/external"
    corpus_fingerprint: str = ""
    """语料指纹，留空自动填——理由同 `glyph_match` 的库指纹。"""
    strategy: str = "gated_ngram"     # context_step.STRATEGIES 里的名字
    margin_gate: float = 0.70         # 门槛化的阈；生产值，303 条实审全对
    variants: str = ""                # 异体表路径；空 = VariantMap 默认
    context_window: int = 6           # 同列前文取几个字
    max_ranked: int = 5               # 往产物里存几个候选

    def _corpus_paths(self) -> list[str]:
        out = [self.corpus]
        d = Path(self.general_corpus_dir)
        if d.is_dir():
            out += [str(p) for p in sorted(d.glob("*.txt"))]
        return out

    def model_post_init(self, _ctx) -> None:
        if not self.corpus_fingerprint:
            object.__setattr__(self, "corpus_fingerprint",
                               corpus_fingerprint(self._corpus_paths()))

@register_step
class ContextDecideStep(Step):
    spec = StepSpec(
        id="context_decide", title="Step6 上下文裁决", version="1.0", unit="cell",
        consumes=("glyph_match", "ocr_candidates"), produces=("context_decision",),
        params=ContextDecideParams,
        needs=("corpus",),
        code_deps=("open_guji_cv.clustering.context_step",
                   "open_guji_cv.clustering.recognize_flow",
                   "open_guji_cv.clustering.lm",
                   "open_guji_cv.utils.jiazhu_order"),
    )

    def _decider(self, p: ContextDecideParams):
        """策略 + LM。按 (策略, 语料指纹) 缓存——一次 run 里几十页共用，
        每页重训 LM 要几十秒。"""
        key = (p.strategy, p.corpus_fingerprint, p.margin_gate, p.variants)
        cached = getattr(self, "_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        from ..clustering.context_step import build_strategy
        from ..clustering.seeding import build_seed_lm
        from ..clustering.variants import VariantMap
        paths = p._corpus_paths()
        book_text = Path(paths[0]).read_text(encoding="utf-8") if Path(paths[0]).exists() else ""
        lm = build_seed_lm(book_text, general_corpus=paths[1:])
        # `semantic_fn` 是**语义归一**（异体归到同一语义），生产同源：
        # semantic_margin 靠它让「珎/珍」这类同语义异体不摊薄 margin，
        # 而字形层仍取图上的精确异体（charset_and_lm.md §四）。
        vmap = VariantMap.load(p.variants or None)
        decider = build_strategy(p.strategy, lm=lm, semantic_fn=vmap.semantic)
        self._cache = (key, decider)      # type: ignore[attr-defined]
        return decider

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        from ..clustering.recognize_flow import fuse_priors
        p: ContextDecideParams = ctx.params_for(self)  # type: ignore[assignment]
        match: PageMatch = ctx.product("glyph_match", page)
        try:
            ocr: PageOcr | None = ctx.product("ocr_candidates", page)
        except Exception:
            ocr = None                     # 没装引擎时只用库候选，不炸
        decider = self._decider(p)

        omap = ({r.id: r for cc in ocr.columns for r in cc.chars}
                if ocr is not None else {})
        out: list[ColumnDecision] = []
        for cc in match.columns:
            if not cc.ok:
                out.append(ColumnDecision(col=cc.col, ok=False, error=cc.error))
                continue
            recs: list[DecisionRec] = []
            decided: list[tuple[int, str]] = []      # (slot, 定字)，同列前文
            # ⚠️ **按阅读顺序**，不是 (slot, sub)（2026-09-06 修）。夹注一段里
            # a/b 两个子列各是一行小字，(slot, sub) 排出来是交错的：
            #     兩(17a) 採(17b) 淮(18a) 進(18b) 鹽(19a) 本(19b) 政(20a)
            # 前向 n-gram 看到「兩採淮進鹽本政」当然给不出 margin——实测 22 条
            # 夹注人审里 13 条库 top == OCR top、本该 dual 放行，全被「上下文
            # margin 不足」拦下。正确读序是 兩淮鹽政 採進本（先 a 全部再 b 全部）。
            # 规则与 row_boundaries.reading_order 同源，见 utils/jiazhu_order。
            for r in sort_by_reading(cc.chars):
                # same 档直接继承——库匹配的 precision 是 1.0000 硬约束，
                # 让 LM 去重排它只会净亏（context_step 铁律 2）。
                if r.verdict == "same" and r.char:
                    recs.append(DecisionRec(id=r.id, slot=r.slot, sub=r.sub,
                                            char=r.char, margin=1.0, source="db_same",
                                            ranked=[(r.char, 1.0)]))
                    decided.append((r.slot, r.char))
                    continue
                o = omap.get(r.id)
                priors = fuse_priors(list(r.candidates),
                                     list(o.topk) if o else [],
                                     s2t=False)      # OCR 那边已经扩过 s2t
                if not priors:
                    recs.append(DecisionRec(id=r.id, slot=r.slot, sub=r.sub,
                                            source="none"))
                    continue
                context = tuple(c for _s, c in decided[-p.context_window:])
                res = decider.decide(priors, context=context)
                # **门槛化**：margin 不过阈就弃权，落回人审（铁律 2）
                ok = res.margin >= p.margin_gate
                recs.append(DecisionRec(
                    id=r.id, slot=r.slot, sub=r.sub,
                    char=res.surface if ok else None,
                    margin=round(float(res.margin), 4),
                    source="context" if ok else "prior",
                    used_context=bool(getattr(res.decision, "used_context", False)),
                    ranked=[(c, round(float(v), 4))
                            for c, v in getattr(res.decision, "ranked", [])[:p.max_ranked]]))
                if ok and res.surface:
                    decided.append((r.slot, res.surface))
            out.append(ColumnDecision(col=cc.col, ok=True, chars=recs))
        return {"context_decision": PageDecision(
            page=page, strategy=p.strategy,
            corpus_fingerprint=p.corpus_fingerprint, columns=out)}
