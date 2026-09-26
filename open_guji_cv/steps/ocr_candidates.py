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

## 引擎缺席 / 逐格大面积失败 → 整页判失败（2026-09-26 改）

`needs=("engine",)` 让控制台把这一步标成 blocked 而不是让人点了才失败——这条不变。
但**真跑起来**引擎导入不了、或初始化失败时，旧版本会整页产出空候选、`engine` 字段
标 `unavailable:…`，却仍然当一次**成功**的 run 落盘，引擎判它「新鲜」。Linux 服务器
PaddleOCR 起不来时就是这样静默出了一整轮空产物，看板还报新鲜，下游没有 OCR
旁证、凭先验出字出了错（overview 仓 `进度/Step9-结果整理/13-维基文库导出.md`）。

现在：**引擎拿不到直接抛异常**，让 `Engine._run_one_step` 按它本来就有的失败路径
记 `status="failed"`、不写产物——`guji status` 会老实报 `failed`，不是 `fresh`。
**逐格识别失败**（`rec_topk` 抛异常）不再悄悄吞掉：那一格的 `OcrRec.error` 留原因，
一页里失败格占比超过 `params.fail_threshold`（默认 5%）时，整页在收尾时也抛异常
判失败——个别字块崩不代表整页，但成片失败大概率是引擎本身出问题（内存不够、
模型半途挂了），不该被当正常产物放行。

下游 `align_ref`/`context_decide` 把 `ocr_candidates` 声明成 `optional_consumes`
（各自的 `_opt`/`try...except` 已经处理「这一页没有该产物」，见两处源码），
所以整页失败即「没有 OCR 候选」，不需要额外改动就能安全退化。
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
    fail_threshold: float = 0.05
    """逐格识别失败占比超过这个数，整页判失败（2026-09-26 加，见模块头）。
    分母是这一页里实际尝试识别的字位数（`cell_type == "char"` 且有 `patch_key`，
    含复用的），分子是抛异常的格数（含复用进来的、上一轮已经标了 `error` 的格）。
    个别字块崩（图块损坏、编码怪字）不该拖垮整页，成片崩大概率是引擎本身的事。"""


@register_step
class OcrCandidatesStep(Step):
    spec = StepSpec(
        id="ocr_candidates", title="Step5-c OCR 候选", version="1.0", unit="cell",
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
        # 引擎拿不到就让异常往上走（2026-09-26 改，见模块头）：`Engine._run_one_step`
        # 本来就会接住，记 status="failed"、不落产物——不再在这里自己吞掉伪装成
        # 一次"成功"的空产物。控制台的 blocked 置灰（`needs=("engine",)`）不受影响，
        # 那是跑之前的声明，这里是真跑起来才发现的失败。
        src = self._source(p)
        # 逐格记**实际**引擎（2026-09-26 修）：原先写死 "rapidocr"，默认早已是 paddle
        # （PP-OCRv5），产物里每格都标成 rapidocr，查「这批候选是哪个模型出的」会被误导
        engine = "paddle-ppocrv5" if p.engine == "paddle" else "rapidocr"

        from ..clustering.candidates import traditional_candidates
        # 格级复用（core/reuse.py）：本步没变、只是上游重写了时，几何没动的格搬旧记录。
        from ..core.reuse import cell_reuse, log_reuse
        reuse = cell_reuse(ctx, self, page, "ocr_candidates")
        n_reused = n_total = n_cell_fail = 0
        out: list[ColumnOcr] = []
        for cc in chars.columns:
            if not cc.ok:
                out.append(ColumnOcr(col=cc.col, ok=False, error=cc.error))
                continue
            recs: list[OcrRec] = []
            for r in cc.chars:
                if r.cell_type != "char" or not r.patch_key:
                    continue
                n_total += 1
                if r.id in reuse:
                    rec = reuse[r.id]
                    recs.append(rec)
                    n_reused += 1
                    if getattr(rec, "error", None):
                        n_cell_fail += 1          # 复用进来的旧失败照样算数，见 fail_threshold 说明
                    continue
                try:
                    img = ctx.image("char_patch", r.patch_key)
                    raw = src.rec_topk(img)
                except Exception as e:
                    n_cell_fail += 1
                    recs.append(OcrRec(id=r.id, slot=r.slot, sub=r.sub, engine=engine,
                                       error=f"{type(e).__name__}: {e}"))
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
        log_reuse(ctx, self, page, n_reused, n_total)
        if n_total and n_cell_fail / n_total > p.fail_threshold:
            # 成片格失败：整页判失败，不落产物（同样交给 Engine._run_one_step 记 failed）。
            raise RuntimeError(
                f"OCR 逐格失败率过高：{n_cell_fail}/{n_total} "
                f"({n_cell_fail / n_total:.1%}) 超过阈值 {p.fail_threshold:.0%}")
        return {"ocr_candidates": PageOcr(page=page, engine=p.engine, columns=out)}


def ocr_candidates_summary(book_id: str, pages: list[int] | None = None,
                           store=None) -> dict:
    """Step5-c 板块②聚合数字：引擎在线状态 + 候选覆盖率。

    07号任务卡判断 OCR 候选大概率不需要独立查询页——它是逐字全自动跑给下游
    融合用的中间产物（Step7 卡片已能看 top-2），不像 5-b 生僻字那样有「人查
    某个字位候选」的场景。本任务书（2026-09-11）核实这个判断仍成立，所以
    这里不建单点查询接口，只给板块②要的聚合数字。风格照抄
    `align_ref.align_ref_summary`。
    """
    from ..core.book import load_book
    from ..core.spec import page_key
    from ..products.store import ProductStore

    store = store or ProductStore()
    book = load_book(book_id)
    pages = pages if pages is not None else book.all_pages()
    n_pages = 0
    n_missing = 0
    n_unavailable = 0
    engines: dict[str, int] = {}
    n_chars = 0
    n_with_candidates = 0
    for pg in pages:
        po: PageOcr | None = store.read(book_id, "ocr_candidates", page_key(pg), "ocr_candidates")
        if po is None:
            # 2026-09-26 起，引擎缺席/逐格大面积失败让整页直接判失败、不落产物，
            # 这类页面也落在这里——跟「压根没跑过」的 missing 并一起报，要细分
            # 请查 `guji status`（该页会显示 failed 不是 missing）。
            n_missing += 1
            continue
        n_pages += 1
        if po.engine.startswith("unavailable:"):  # 老产物（改动前写的）才会有这个前缀
            n_unavailable += 1
        else:
            engines[po.engine] = engines.get(po.engine, 0) + 1
        for col in po.columns:
            if not col.ok:
                continue
            for r in col.chars:
                n_chars += 1
                if r.topk:
                    n_with_candidates += 1
    return {
        "n_pages": n_pages, "n_missing": n_missing, "n_unavailable": n_unavailable,
        "engines": engines,
        "n_chars": n_chars, "n_with_candidates": n_with_candidates,
        "coverage": round(n_with_candidates / n_chars, 4) if n_chars else None,
    }
