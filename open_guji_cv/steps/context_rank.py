"""按上下文排序 `context_rank`（候选字线所说的 4b）（2026-11-27，候选字线；CV3；规格见 Claude Doc「候选字线：待审格格式、3c／4b 接口与 benchmark」第四节）。

给每个**还没定的格**（3a 不是 same）把候选按「图像分＋w·填空语义分」重排，记进产物 `context_rank`。
**只排序、不放行、不改任何别的步骤的产物**——`context_decide` 的门槛化定字、`seed_admit` 的准入都不读它；
它给审阅卡片排按钮、给人看「上下文觉得是哪个」。

## 池与分

- 池：收尾 `glyph_analyzer` 的 `cands`（3a ∪ 3b ∪ 3c 前 10；每个字的图像分取 `evidence.a.sim`、`evidence.c.sim` 的大者）；
  没开收尾就用 3a 的候选。
- 前后文：本页按阅读顺序（列序 col 升序，列内 `sort_by_reading`），左右各 24 字，**本格不放进去**。邻格的字取
  `context_decide` 的定字，没定就取它的第一候选，再没有取 3a 第一候选，都没有记 `□`（填空模型当 [UNK]）。
  只用本页，不接前后页。
- 融合与语义分口径见 `clustering/ctx_fill`；w 缺省 0.005。

## 量法与已知口径差

测试集 `char-candidates`（`guji eval run @cands`）里前后文来自现行主版**最终文本**，比这里机器猜的邻格字干净，数字偏乐观；
`--ctx-noise` 在评测里给邻字加噪（11-27 实测，甲层全部首位／前 3，原序 56.3／82.4）：
冻结前后文 76.5／89.0，邻字错 10% 76.0／89.0，错 20% 74.9／88.5；乙层卡片新前 3 命中 90.7→90.4→89.7（旧按钮 80.4）。
伤害率 3.3%→3.7%→4.5%。邻字错 20% 增益也只掉约 2 个点，产线邻格错率远低于这个数。
**伤害率**（图像首位已对、重排后被换掉）在测试集上约 3–5%，难格约 11%。所以消费方（卡片、manager `cands/1`）
不要把本步首位当定字，只在图像分接近时拿它排前几个按钮。

缺省关（`enabled`）。填空模型缺失（没装 torch／transformers、权重拉不到）→ 每格 `ran=False, why=no_lm`，不炸。
"""
from __future__ import annotations

from pydantic import BaseModel

from ..clustering import ctx_fill
from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.decide import ColumnCtx, CtxRec, PageCtx
from ..utils.jiazhu_order import sort_by_reading


class ContextRankParams(BaseModel):
    enabled: bool = False
    """开不开 4b 排序（书级）。缺省关。"""
    w: float = ctx_fill.DEFAULT_W
    """融合权重：融合分＝图像分＋w·填空语义分。"""
    topk: int = 10
    """每格留几个候选。"""
    model: str = ""
    """填空模型与权重版本，**自动填**（`ctx_fill.model_version`），进参数指纹。"""

    def model_post_init(self, _ctx) -> None:
        if self.enabled and not self.model:
            object.__setattr__(self, "model", ctx_fill.model_version(self.w))


def _opt(ctx: RunContext, kind: str, page: int):
    try:
        return ctx.product(kind, page)
    except Exception:  # noqa: BLE001 —— 可选上游缺了就当没有
        return None


def pool_of(match_rec, final_rec) -> list[tuple[str, float]]:
    """一格的候选池：[(字, 图像分)]，保序、去重。有收尾产物用收尾，否则用 3a 候选。"""
    out: dict[str, float] = {}
    if final_rec is not None and final_rec.cands:
        for fc in final_rec.cands:
            ev = fc.evidence or {}
            sims = [float(ev[k]["sim"]) for k in ("a", "c") if k in ev and ev[k].get("sim") is not None]
            if sims:
                out[fc.char] = max(sims)
    else:
        for c, s in match_rec.candidates:
            out[c] = float(s)
        if match_rec.char and match_rec.char not in out:
            out[match_rec.char] = float(match_rec.cov or 0.0)
    return list(out.items())


def best_char(match_rec, dec_rec) -> str:
    """邻格的字：context_decide 定字 → 它的第一候选 → 3a 定字／第一候选 → □。"""
    if dec_rec is not None:
        if dec_rec.char:
            return dec_rec.char
        if dec_rec.ranked:
            return dec_rec.ranked[0][0]
    if match_rec.char:
        return match_rec.char
    if match_rec.candidates:
        return match_rec.candidates[0][0]
    return ctx_fill.MISSING


def page_seq(match, dec_by: dict) -> list[tuple[int, object, str]]:
    """本页读序：[(列号, 3a 记录, 邻格字)]。列序 col 升序，列内 `sort_by_reading`。"""
    seq: list = []
    for cm in sorted((c for c in match.columns if c.ok), key=lambda c: c.col):
        for r in sort_by_reading(cm.chars):
            seq.append((cm.col, r, best_char(r, dec_by.get(r.id))))
    return seq


def neighbor_texts(match, dec=None) -> dict[str, tuple[str, str]]:
    """本页每格的 {格 id: (左文, 右文)}，本格不在里面；窗口截取交给填空模型（`ctx_fill.WINDOW`）。
    manager 给已发册的待审卡现算候选时用（`guji audit cands`），与本步同一份读序和邻格取字规则。"""
    dec_by = {r.id: r for c in dec.columns for r in c.chars} if dec is not None else {}
    seq = page_seq(match, dec_by)
    text = [t for _, _, t in seq]
    return {r.id: ("".join(text[:i]), "".join(text[i + 1:])) for i, (_c, r, _t) in enumerate(seq)}


def rank_cell(pool: list[tuple[str, float]], sem: dict[str, float] | None, w: float, topk: int) -> list[list]:
    fused = ctx_fill.fuse(pool, sem or {}, w)[:topk]
    return [[c, round(f, 4), round(dict(pool)[c], 4), None if lp is None else round(lp, 3)] for c, f, lp in fused]


@register_step
class ContextRankStep(Step):
    spec = StepSpec(
        id="context_rank", title="按上下文排序（候选）", version="0.1", unit="cell",
        consumes=("glyph_match",), optional_consumes=("glyph_analyzer", "context_decision"),
        produces=("context_rank",),
        params=ContextRankParams,
        needs=("model",),
        code_deps=("open_guji_cv.clustering.ctx_fill", "open_guji_cv.utils.jiazhu_order"),
        enabled_by="enabled",
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: ContextRankParams = ctx.params_for(self)  # type: ignore[assignment]
        match = ctx.product("glyph_match", page)
        fin = _opt(ctx, "glyph_analyzer", page)
        dec = _opt(ctx, "context_decision", page)
        fin_by = fin.by_id() if fin is not None else {}
        dec_by = ({r.id: r for c in dec.columns for r in c.chars} if dec is not None else {})
        lm = ctx_fill.shared()

        seq = page_seq(match, dec_by)
        text = [t for _, _, t in seq]
        recs: dict[int, list[CtxRec]] = {}
        for i, (col, r, _t) in enumerate(seq):
            rec = CtxRec(id=r.id, slot=r.slot, sub=r.sub, ran=False)
            if r.verdict == "same" and r.char:
                rec.why = "same"
            else:
                pool = pool_of(r, fin_by.get(r.id))
                if len(pool) < 2:
                    rec.why = "pool<2"
                elif lm is None:
                    rec.why = "no_lm"
                else:
                    sem = lm.sem("".join(text[:i]), "".join(text[i + 1:]), [c for c, _ in pool])
                    if sem is None:
                        rec.why = "no_mask"
                    else:
                        rec.ran = True
                        rec.ranked = rank_cell(pool, sem, p.w, p.topk)
            recs.setdefault(col, []).append(rec)
        cols = [ColumnCtx(col=c, chars=v) for c, v in sorted(recs.items())]
        return {"context_rank": PageCtx(page=page, model=p.model, columns=cols)}
