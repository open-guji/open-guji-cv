"""Step5-b OCR 候选：字块 → RapidOCR CTC top-k（含简→繁扩展）。

包的是 `clustering/candidates.RapidOcrSource`（PP-OCRv4 ONNX，直接读 rec 的
CTC softmax 取主导时间步 top-k）+ `traditional_candidates`（简→繁扩展）。
**算法一行没改。**

## 这一步的产出只是候选，不是定字

OCR 在这批书上的可靠性有实测底：`char-ocr` 金标 1404 条 top1 **88.75%**，
而**置信度不可信**——`glyph_db_first_design.md §7.3` 记着「人/入」那条给了
0.95 仍是错的。所以 seeding 的十条自动准入通道里，OCR 的 prob **不参与任何
自动判断**，只供审查候选与 `match_solo_ocr` 的字符背书。这一步照此定位：
产出 top-k 候选交给下游融合，不做任何裁决。

## 为什么要 s2t 扩展

PP-OCR 是简体模型（字典 6280 字，无繁体扩展区），对繁体刻本有**系统性**缺口：
本书整理本实测 **11.03% 的字次**根本不在字表里，缺的还不是生僻字，是
說(2518) 則(2009) 謂(1446) 論(1044) 這类各上千次的繁体常用字。简→繁扩展把
不可达率压到 1.79%，再加 Unihan 异体到 1.20%（`charset_and_lm.md §一`）。
剩下那 1.20%（彖 詁 筮 帙 歟）字典式扩展够不着，只能靠字形匹配——那是
`glyph_match` 那一步的事。

## 引擎缺席时不炸

`needs=("engine",)` 让控制台把这一步标成 blocked 而不是让人点了才失败；
真跑起来引擎导入不了时，整页产出空候选并在 `engine` 字段留痕，不抛异常
——下游（融合、上下文）本来就要能处理「这一位没有 OCR 候选」。
"""

from __future__ import annotations

from pydantic import BaseModel

from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.chars import PageChars
from ..products.kinds.recog import ColumnOcr, OcrRec, PageOcr


class OcrCandidatesParams(BaseModel):
    topk: int = 5
    scale: float = 3.0          # 送进 rec 之前的放大倍数（RapidOcrSource 默认）
    s2t: bool = True            # 简→繁扩展，见模块头
    max_out: int = 8            # 扩展后每个字位最多存几个候选
    engine: str = "paddle"      # paddle（PP-OCRv5 server，15,907 字）| rapid（PP-OCRv4 mobile，6,278 字）
    """引擎名进 params_hash——换引擎产物必须过期。

    2026-09-05 横评：v5 比 v4 高 10 个点（93.5% vs 83.5%，异体算对 96.5%），字典大
    2.5 倍（整理本字种不可达 2.5% vs 39.5%）。三批页重跑准确率全 100%，人审不降
    （残余是己已巳/生僻字/挤排页）——价值在候选质量与字典覆盖。用户 2026-09-05
    定：默认切到 v5。v5 走独立进程 worker（见 candidates.PaddleOcrSource）。"""


@register_step
class OcrCandidatesStep(Step):
    spec = StepSpec(
        id="ocr_candidates", title="Step5 OCR 候选", version="1.0", unit="cell",
        consumes=("char_index", "char_patch"), produces=("ocr_candidates",),
        params=OcrCandidatesParams,
        needs=("engine",),
        code_deps=("open_guji_cv.clustering.candidates",),
    )

    def _source(self, p: OcrCandidatesParams):
        key = (p.engine, p.scale, p.s2t, p.topk)
        cached = getattr(self, "_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        if p.engine == "paddle":
            from ..clustering.candidates import PaddleOcrSource
            src = PaddleOcrSource(s2t=p.s2t, topk=p.topk)
        else:
            from ..clustering.candidates import RapidOcrSource
            src = RapidOcrSource(scale=p.scale, s2t=p.s2t, topk=p.topk)
        src._ensure()
        self._cache = (key, src)          # type: ignore[attr-defined]
        return src

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: OcrCandidatesParams = ctx.params_for(self)  # type: ignore[assignment]
        chars: PageChars = ctx.product("char_index", page)
        try:
            src = self._source(p)
            engine = "rapidocr"
        except Exception as e:            # 引擎不在就整页空候选，不炸（见模块头）
            return {"ocr_candidates": PageOcr(
                page=page, engine=f"unavailable:{type(e).__name__}",
                columns=[ColumnOcr(col=cc.col, ok=False, error=str(e))
                         for cc in chars.columns])}

        from ..clustering.candidates import traditional_candidates
        out: list[ColumnOcr] = []
        for cc in chars.columns:
            if not cc.ok:
                out.append(ColumnOcr(col=cc.col, ok=False, error=cc.error))
                continue
            recs: list[OcrRec] = []
            for r in cc.chars:
                if r.cell_type != "char" or not r.patch_key:
                    continue
                try:
                    img = ctx.image("char_patch", r.patch_key)
                    raw = src.rec_topk(img)
                except Exception:
                    recs.append(OcrRec(id=r.id, slot=r.slot, sub=r.sub, engine=engine))
                    continue
                if p.s2t:
                    merged: dict[str, float] = {}
                    for ch, prob in raw:
                        for cand, w in traditional_candidates(ch):
                            merged[cand] = max(merged.get(cand, 0.0), prob * w)
                    topk = sorted(merged.items(), key=lambda t: -t[1])[:p.max_out]
                else:
                    topk = [(c, float(v)) for c, v in raw[:p.max_out]]
                recs.append(OcrRec(id=r.id, slot=r.slot, sub=r.sub, engine=engine,
                                   topk=[(c, round(float(v), 4)) for c, v in topk]))
            out.append(ColumnOcr(col=cc.col, ok=True, chars=recs))
        return {"ocr_candidates": PageOcr(page=page, engine=p.engine, columns=out)}
