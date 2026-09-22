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
`cnn_candidates.full_fingerprint()`（checkpoint mtime + 模板集 stamp + 字体集 stamp）摘进
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

from pathlib import Path

from pydantic import BaseModel

from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.chars import CharRec, PageChars
from ..products.kinds.recog import ColumnRare, PageRare, RareCand, RareRec


class RareCandidatesParams(BaseModel):
    k: int = 10
    struct_rerank: bool = False
    """融合后按部件袋头一致性重排前 30 名（`ids_struct.struct_rerank`）。缺省关：
    效果要先用 `scripts/eval_struct_rerank.py` 量（2026-09-21，M0 #3）。"""
    struct_probe: str = ""
    """结构头探针 checkpoint 路径（`scripts/probe_struct_heads.py` 训出来的那份）。
    空 = 不用探针。给了就把它的内容哈希并进 `model_fingerprint`（见下），换探针产物才过期。

    ⚠️ **补声明**（2026-09-21）：这个字段被 `model_post_init` 与 `run_page` 用了三处，
    但类里一直没有它——`RareCandidatesParams()` 直接抛
    `AttributeError: 'RareCandidatesParams' object has no attribute 'struct_probe'`，
    Step5-b 对谁都起不来（不止某本书）。pydantic 的 `model_post_init` 在校验之后跑，
    所以这个错只在**构造实例**时炸，import 阶段完全看不出来——`python -c "import …"`
    过得去，跑批才死。缺省 `""` 而不是 `None`：与 `struct_rerank` 同风格，且
    `p.struct_probe or None` 那处本就按假值处理。"""
    model_fingerprint: str = ""
    """候选栈的外部状态指纹（checkpoint + 外部模板集 + 模板字体集），**由
    `model_post_init` 自动填**，yaml 里不用写。它参与 `params_hash`，从而进产物
    指纹——换模型文件、换模板、往 `fonts/` 加减字体档，产物才会过期。

    2026-09-21 查出：模块头一直说「把 `full_fingerprint()` 摘进 RareCandidatesParams」，
    可参数类里从来只有 `k`——指纹只写进了产物体的 `PageRare.model_fingerprint`，而
    新鲜度判断（`core/engine._self_payload`）只看参数哈希 + 代码哈希 + `book_deps`，
    不读产物体。后果：**只要代码不动**（原地换 `best.pt`、`fonts/` 里加一套字体），
    `rare_candidates` 照报「新鲜」，跑出来的候选其实是旧模板的。r4 → r5 那次没露馅，
    是因为改了 `cnn_candidates.py` 里的默认路径、`code_deps` 的代码哈希顺带变了。
    照 `GlyphMatchParams.db_fingerprint` 的同一套写法补上。
    """

    def model_post_init(self, _ctx) -> None:
        if not self.model_fingerprint:
            from ..clustering.cnn_candidates import full_fingerprint
            fp = full_fingerprint()
            if self.struct_probe:
                import hashlib
                from pathlib import Path
                pp = Path(self.struct_probe)
                fp += ":probe=" + (hashlib.sha1(pp.read_bytes()).hexdigest()[:12] if pp.exists() else "missing")
            object.__setattr__(self, "model_fingerprint", fp)


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
        # `run_page` → `rare_for_batch` 读的是 `ctx.book.font`（`charset` 的
        # base/escalate/escalate_threshold/corpus/variants/allow，以及 `norm_stroke`），
        # 这些全都改变候选内容与排序，必须进指纹。
        #
        # 2026-09-17 踩到：把本册 `escalate_threshold` 从 0.85 改 0.95（换 r5 后
        # 重标，见 `books/bxgb.yaml` 那段注释）再跑，54 页**全部报「新鲜，跳过」**
        # ——阈值不在指纹里，产物于是停在旧阈值上，而状态显示一切正常。
        # 这类静默失效最贵：数字看着对，其实量的是旧配置。
        book_deps=("font",),
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
        # 格级复用（core/reuse.py）：几何没动的格搬旧记录，不进批处理队列。
        from ..core.reuse import cell_reuse, log_reuse
        reuse = cell_reuse(ctx, self, page, "rare_candidates")
        n_reused = n_total = 0
        for cc in chars.columns:
            if not cc.ok:
                continue
            col_recs[cc.col] = []
            for r in cc.chars:
                if r.cell_type != "char" or not r.patch_key:
                    continue
                n_total += 1
                if r.id in reuse:
                    col_recs[cc.col].append(reuse[r.id])
                    n_reused += 1
                    continue
                try:
                    img = ctx.image("char_patch", r.patch_key)
                except Exception:
                    col_recs[cc.col].append(RareRec(id=r.id, slot=r.slot, sub=r.sub))
                    continue
                queue.append((cc.col, r))
                imgs.append(img)

        # 字表按这册书的整理本算——Step5-b 此前也是写死刻本链那份语料，
        # 换书就 FileNotFoundError（北行日錄 1–10 页全部失败，2026-09-15）。
        #
        # 2026-09-15 再补一层：**这册书压根没有语料时要降级，不能炸**。
        # `book_corpus` 查不到会退回刻本链那份 `DEFAULT_CORPUS`，而那个文件
        # 只在四庫工作区里有；考補萃編（`references: []`，无证人整理本）第一次
        # 跑全链时 6 页全部 FileNotFoundError。生僻字候选是**可选的一路**
        # （方案 §四 Step5-b），没有字表就不出候选，让 Step6/7 照常走。
        from .align_ref import book_corpus
        corpus = book_corpus(ctx.book.id)
        if imgs and not Path(corpus).exists():
            ctx.log(f"Step5-b 跳过：本册没有可用字表语料（{corpus} 不存在），不出生僻字候选")
            imgs = []
        hits_list = rare_for_batch(imgs, p.k, corpus, ctx.book.id,
                                   struct_rerank=p.struct_rerank,
                                   struct_probe=p.struct_probe or None) if imgs else []
        for (col, r), hits in zip(queue, hits_list):
            col_recs[col].append(RareRec(
                id=r.id, slot=r.slot, sub=r.sub,
                candidates=[RareCand(char=h["char"], score=h["score"], font=h["font"])
                            for h in hits]))

        out = [ColumnRare(col=cc.col, ok=cc.ok, error=cc.error,
                          chars=col_recs.get(cc.col, []) if cc.ok else [])
               for cc in chars.columns]

        # 各路出了多少条候选（见 PageRare.sources）。embedding 是最强单源，
        # 它一死候选就退化成分类头独撑、classes 外的字全查不到，而这在产物里
        # 原本看不出来——北行日錄那一轮就是这么漏过去的，所以这里记一笔并出声。
        from collections import Counter
        srcs = Counter(c.font for cr in out for r in cr.chars for c in r.candidates)
        if hits_list and not srcs.get("emb"):
            ctx.log(f"⚠️ Step5-b p{page}：embedding 一条候选都没出（来源 {dict(srcs)}）"
                    f"——候选已退化为分类头独撑，classes 外的字会整个查不到，请查 emb 索引")

        log_reuse(ctx, self, page, n_reused, n_total)
        return {"rare_candidates": PageRare(
            page=page, model_fingerprint=full_fingerprint(),
            sources=dict(srcs), columns=out)}
