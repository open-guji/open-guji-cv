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

## 【2026-09-10】线上外部大模型：只调候选顺序，不自动放行

承接 `Step6-上下文裁决/方案-外部LLM.md`（离线评测已证明 `oracle_llm`
策略接答案表能把 `top1_gain` 从 +1.31% 提到 +3.99%）。本节把外部大模型
从「离线答案表」升级成「处理每册时线上真问」，用户 2026-09-10 定的政策
（`overview` 会话记录）：

1. **只在 `gated_ngram` 过不了 `margin_gate` 时才问**——省成本，且
   ngram 已经稳赢的位问了也白问（评测集选题同一条纪律）；
2. **答案只用来调候选顺序（`ranked` 重排 + `llm_suggestion` 字段），
   不自动放行**：`char` 仍然只在 `context` 门槛过了才设，`source` 语义
   不变。是否要开自动放行是**下一步的决定，不是本次的默认行为**——
   本次刻意不做，等 `llm_online_calls` 日志攒够真实调用量、跟人审结果
   对上算出线上正确率再说；
3. **默认关闭**（`enable_online_llm=False`）：这是要花钱的线上调用，
   不能因为跑一次 `context_decide` 就默默产生 API 账单，必须显式开。

线上调用复用 `clustering/llm_context.py` 的 `LLMContextJudge`/
`prompt_with_candidates`/`parse_answer`，**不重新发明**。每次调用（无论
候选内命中与否）都追加写一行到 `output/llm_online_calls/<book>.jsonl`，
字段口径与离线评测报告的 `rows` 一致，供 `scripts/measure_llm_online_
accuracy.py` 后续跟人审的反馈事件（`feedback/events.py`，按 cell id 关联）
拼出「线上真实正确率」。

`context_after` 与离线评测的**教师强制**（拼接金标）不同——生产时还不
知道后文的真实字，只能用本列剩余字位的**原始候选 top1**（未经裁决）拼，
是弱于评测集的近似，已在日志与函数文档里注明，避免拿线上正确率数字
直接跟离线 27~47% 比。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from pydantic import BaseModel

from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.recog import (ColumnDecision, DecisionRec,
                                    PageDecision, PageMatch, PageOcr)
from ..utils.jiazhu_order import sort_by_reading

DEFAULT_CORPUS = "corpus/zongmu_wuyingdian_reference.txt"
DEFAULT_LLM_LOG_DIR = "output/llm_online_calls"


def _log_llm_call(log_dir: str, book: str, row: dict) -> None:
    """追加一行到 `<log_dir>/<book>.jsonl`。只追加，不覆盖——同一本书
    多次跑会累积多条同 id 记录，测正确率时按 (id, ts) 去重/取最新即可，
    这里不做去重（去重是读侧的事，写侧只管别丢）。"""
    p = Path(log_dir) / f"{book}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


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

    # ── 线上外部大模型（见模块头【2026-09-10】），默认关闭 ──────────────
    enable_online_llm: bool = False   # 要花钱的线上调用，必须显式开
    llm_provider: str = "qwen"        # qwen | glm；qwen-plus 离线评测最优
    llm_model: str = ""               # 空 = provider 默认档（见 llm_context.ENDPOINTS）
    llm_context_chars: int = 10       # 上/下文各取多少字，同评测集口径
    llm_log_dir: str = DEFAULT_LLM_LOG_DIR

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

    def _llm_judge(self, p: ContextDecideParams):
        """`LLMContextJudge` 按 (provider, model) 缓存，同一次 run 共用一个
        实例（连带它的磁盘缓存/限流状态）。`enable_online_llm=False` 时
        不会被调用到——调用方（`run_page`）先判开关，这里只管构造。"""
        key = (p.llm_provider, p.llm_model)
        cached = getattr(self, "_llm_judge_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        from ..clustering.llm_context import LLMContextJudge
        judge = LLMContextJudge(p.llm_provider, model=p.llm_model or None,
                                cache_path=Path(p.llm_log_dir) / "_cache"
                                / f"{p.llm_provider}_{p.llm_model or 'default'}.json",
                                rate_limit_s=0.3)
        self._llm_judge_cache = (key, judge)   # type: ignore[attr-defined]
        return judge

    @staticmethod
    def _raw_top1(rec, omap: dict, fuse) -> str:
        """某字位（还没轮到裁决）的原始候选 top1——供 context_after 用。
        **不是**金标、**不是**已裁决字，只是当前证据下最可能的猜测，比离线
        评测的教师强制（拼接真实后文）弱，见模块头【2026-09-10】说明。"""
        o = omap.get(rec.id)
        priors = fuse(list(rec.candidates), list(o.topk) if o else [], s2t=False)
        if not priors:
            return ""
        return max(priors.items(), key=lambda kv: kv[1])[0]

    def _ask_llm_online(self, ctx: RunContext, p: ContextDecideParams, page: int,
                        r, priors: dict[str, float], ordered: list, i: int,
                        omap: dict, decided: list[tuple[int, str]]) -> str | None:
        """问一次外部大模型，记日志，返回解析出的字（不在候选内/解析失败
        则返回 None）。只在 `run_page` 里 margin 未过门槛时才被调用。"""
        from ..clustering.llm_context import prompt_with_candidates
        from ..clustering.recognize_flow import fuse_priors

        before = "".join(c for _s, c in decided[-p.llm_context_chars:])
        after_chars: list[str] = []
        for j in range(i + 1, len(ordered)):
            if len(after_chars) >= p.llm_context_chars:
                break
            ch = self._raw_top1(ordered[j], omap, fuse_priors)
            if ch:
                after_chars.append(ch)
        item = {"context_before": before[-p.llm_context_chars:],
               "context_after": "".join(after_chars),
               "candidates_chars": sorted(priors, key=lambda c: -priors[c])}
        prompt = prompt_with_candidates(item, ctx.book.title)

        try:
            judge = self._llm_judge(p)
        except Exception as e:      # NoAPIKeyError 等——显式开了在线调用却没
                                     # key，是配置错误，直接报错退出，不静默跳过
                                     # （子会话须知铁律：不许悄悄退化成纯 ngram）
            raise RuntimeError(
                f"enable_online_llm=True 但构造 {p.llm_provider} 调用层失败: {e}"
            ) from e

        t0 = time.time()
        answer = judge.ask(r.id, prompt)
        _log_llm_call(p.llm_log_dir, ctx.book.id, {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "id": r.id, "book": ctx.book.id, "page": page,
            "candidates_chars": item["candidates_chars"],
            "context_before": item["context_before"],
            "context_after": item["context_after"],
            "provider": answer.provider, "model": answer.model,
            "llm_raw_text": answer.raw_text, "llm_parsed_char": answer.parsed_char,
            "llm_parse_ok": answer.parse_ok,
            "llm_answer_in_candidates": bool(answer.parsed_char
                                             and answer.parsed_char in priors),
            "cached": answer.cached, "latency_s": round(answer.latency_s, 3),
            "prompt_tokens": answer.prompt_tokens,
            "completion_tokens": answer.completion_tokens,
            "error": answer.error,
            "wall_time_s": round(time.time() - t0, 3),
        })
        if answer.parse_ok and answer.parsed_char in priors:
            return answer.parsed_char
        return None

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
            ordered = sort_by_reading(cc.chars)
            for i, r in enumerate(ordered):
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
                ranked = [(c, round(float(v), 4))
                         for c, v in getattr(res.decision, "ranked", [])[:p.max_ranked]]
                llm_suggestion = None
                # 线上外部大模型：只在过不了门槛时问，只调 ranked 顺序，
                # 不碰 char/source（模块头【2026-09-10】，默认关闭）
                if not ok and p.enable_online_llm and len(priors) >= 2:
                    llm_suggestion = self._ask_llm_online(
                        ctx, p, page, r, priors, ordered, i, omap, decided)
                    if llm_suggestion and llm_suggestion in priors:
                        # LLM 建议的字可能排在原始 ranked 截断线之外（比如
                        # 候选第 6 名），重排后要再截一次，不然 ranked 会
                        # 悄悄超过 max_ranked
                        ranked = ([(llm_suggestion, priors[llm_suggestion])]
                                 + [(c, v) for c, v in ranked
                                    if c != llm_suggestion])[:p.max_ranked]
                recs.append(DecisionRec(
                    id=r.id, slot=r.slot, sub=r.sub,
                    char=res.surface if ok else None,
                    margin=round(float(res.margin), 4),
                    source="context" if ok else "prior",
                    used_context=bool(getattr(res.decision, "used_context", False)),
                    ranked=ranked,
                    llm_suggestion=llm_suggestion if llm_suggestion in priors else None))
                if ok and res.surface:
                    decided.append((r.slot, res.surface))
            out.append(ColumnDecision(col=cc.col, ok=True, chars=recs))
        return {"context_decision": PageDecision(
            page=page, strategy=p.strategy,
            corpus_fingerprint=p.corpus_fingerprint, columns=out)}
