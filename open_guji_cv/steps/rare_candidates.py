"""Step5-b 生僻字候选：字块 → 字体模板 + CNN 分类 + CNN embedding 的 RRF 融合 top-k。

包的是 `clustering.rare_panel.rare_for_batch`（两档字表位次合并 + 三源
RRF，批处理版），**融合算法一行没改**——它是 `/api/rare` 审字卡片背后那
套引擎，此前只在界面上按需调用；库匹配 / OCR / 整理本三路都已经是正式
Step，生僻字这路补齐后四路才在同一层，Step6 融合与 Step7 通道才能直接
读它，不必再各自单独接 `clustering.cnn_candidates`（`match_solo_cnn`
通道就是这么单独接的一次）。

## 指纹要带 checkpoint 与模板集

CNN checkpoint、康熙白名单、字统网模板都是**外部可变状态**——换模型或
换模板，同一张字块图给出的候选会变，而 Step 的代码、参数、上游产物一个
都没动。跟 `glyph_match` 的 `db_fingerprint` 同一个道理：把
`cnn_candidates.full_fingerprint()`（checkpoint mtime + 模板集 stamp）摘进
`RareCandidatesParams`，产物就会在换模型/换模板时自动 stale。

## checkpoint 缺席时不炸

`needs=("model",)` 让控制台把这一步标成 blocked 而不是让人点了才失败；
真跑起来 CNN 不可用时 `rare_for_batch` 静默退回纯字体候选（`cnn.available`
为 False 时批处理的 CNN 两路传空列表，见 `rare_panel.rare_for_batch`），
这一步照此不抛异常，只是候选质量降级、并在 `model_fingerprint` 里留痕
（`cnn_candidates.fingerprint()` 查不到 checkpoint 时回 "nockpt"）。

## 为什么整页一次批处理，不逐字调用（2026-09-10）

真跑书才暴露的两轮性能问题，都是「逐字调用」这一个模式惹的：

1. **CNN embedding 索引缓存漏了记忆化**——`_emb_index` 逐字都重新走一遍
   外部模板目录扫描，单页 88s（已在 `cnn_candidates.py` 修，见其模块头）；
2. **五路检索本身也是逐字调用**——即使索引缓存对了，模板矩阵/网络权重
   整页不变，逐字分别做矩阵-向量乘法/网络前向，没吃到 BLAS/torch 批处理
   的红利。改成 `rare_for_batch`（`font_candidates.candidates_batch` +
   `cnn_candidates.topk_batch`/`emb_topk_batch`）后 vol01 单页 179 字
   6.35s→1.5s（4.25×，叠加第 1 条的 10× 一共约 42×）。

结果与逐字调用 `rare_for` 逐条比对为位级相同（同一份归一化、同一套索引，
只是批处理 IO），批处理不改变任何候选或排名。
"""

from __future__ import annotations

from pydantic import BaseModel

from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.chars import CharRec, PageChars
from ..products.kinds.recog import ColumnRare, PageRare, RareCand, RareRec


class RareCandidatesParams(BaseModel):
    k: int = 10


@register_step
class RareCandidatesStep(Step):
    spec = StepSpec(
        id="rare_candidates", title="Step5-b 生僻字候选", version="1.0", unit="cell",
        consumes=("char_index", "char_patch"), produces=("rare_candidates",),
        params=RareCandidatesParams,
        needs=("model",),
        code_deps=("open_guji_cv.clustering.rare_panel",
                   "open_guji_cv.clustering.cnn_candidates",
                   "open_guji_cv.clustering.font_candidates"),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        from ..clustering.cnn_candidates import full_fingerprint
        from ..clustering.rare_panel import rare_for_batch

        p: RareCandidatesParams = ctx.params_for(self)  # type: ignore[assignment]
        chars: PageChars = ctx.product("char_index", page)

        # 先收集整页要查的字块，图读不出来的单独记下来（不拖累整页批处理）——
        # `ctx.image` 失败通常是这一格图块本身有问题，隔离到单条 RareRec
        # 留白，语义与旧版逐字 try/except 一致。col_recs 按 chars.columns
        # 的原始顺序建，最后拼 out 时保持这个顺序不乱。
        queue: list[tuple[int, CharRec]] = []
        col_recs: dict[int, list[RareRec]] = {}
        imgs: list = []
        for cc in chars.columns:
            if not cc.ok:
                continue
            col_recs[cc.col] = []
            for r in cc.chars:
                if r.cell_type != "char" or not r.patch_key:
                    continue
                try:
                    img = ctx.image("char_patch", r.patch_key)
                except Exception:
                    col_recs[cc.col].append(RareRec(id=r.id, slot=r.slot, sub=r.sub))
                    continue
                queue.append((cc.col, r))
                imgs.append(img)

        hits_list = rare_for_batch(imgs, p.k) if imgs else []
        for (col, r), hits in zip(queue, hits_list):
            col_recs[col].append(RareRec(
                id=r.id, slot=r.slot, sub=r.sub,
                candidates=[RareCand(char=h["char"], score=h["score"], font=h["font"])
                            for h in hits]))

        out = [ColumnRare(col=cc.col, ok=cc.ok, error=cc.error,
                          chars=col_recs.get(cc.col, []) if cc.ok else [])
               for cc in chars.columns]
        return {"rare_candidates": PageRare(
            page=page, model_fingerprint=full_fingerprint(), columns=out)}
