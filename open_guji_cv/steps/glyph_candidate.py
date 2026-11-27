"""3c 按图给候选 `glyph_candidate`（2026-11-27，第三步重构；CV3，规格见 Claude Doc「候选字线：待审格格式、3c／4b 接口与 benchmark」第三节）。

只看字块图：把字块图过 r5 向量网络，对**全字表**（EmbPack 约 10.2 万字、含扩 B 以后）的字体模板向量取余弦，
取前 `topk` 个。**不看上下文、不判放行、不改别的小步的结果**；分怎么变成 p、怎么和 3a／3b 合，归收尾 `glyph_analyzer`。

## 为什么这样做

测试集 `char-candidates` 的基线（2026-11-27，甲层难格 5,342）：现行 3b `rare_candidates` 首位 54.7%／前 10 87.8%，
r5 向量单路全字表 76.9%／95.6%；扩 B 以后的字 3b 首位只有 1.5%（升级档在多数格不触发），全字表单路 16.2%／前 10 76.7%。
所以去掉分类头与 RRF 融合、不再分基集与升级档，一律对全字表。试过的负结果：CSLS 式去枢纽性校正全线更差（首位 −1 点、前 10 −1 点）。

## 异体族展开

取首位 5 个字的异体族成员（`hanzi.db.family`），按它们自己的图像余弦排好，插在前 10 之后、其余之前，总数仍是 `topk`。
扩 B 以后的字前 30 命中 80.1%→93.5%、前 50 88.9%→95.2%，其他层不降；`fam_of` 记并入关系，供收尾只当证据看。

## 缺省关

`enabled: false`（缺省）＝不跑（`StepSpec.enabled_by`），各书产物不受影响；打开后产物进收尾的 `evidence.c`。
"""
from __future__ import annotations

from pydantic import BaseModel

from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.chars import CharRec, PageChars
from ..products.kinds.read import CandRec, ColumnCand, PageCand

_PACK: dict = {}


class GlyphCandidateParams(BaseModel):
    enabled: bool = False
    """开不开 3c（书级）。缺省关。"""
    topk: int = 50
    """每格留几个候选（含并进来的异体族成员）。"""
    fam_top: int = 5
    """取图像前几名的异体族并进来；0＝不展开。"""
    fam_after: int = 10
    """异体族成员插在图像前几名之后。"""
    model: str = ""
    """向量模型与字表包的版本，**自动填**（`model_version`），yaml 里不用写；进参数指纹。"""

    def model_post_init(self, _ctx) -> None:
        if self.enabled and not self.model:
            object.__setattr__(self, "model", model_version())


def model_version() -> str:
    from ..clustering.cnn_candidates import fingerprint
    from ..clustering.emb_pack import current_spec, find
    m = find(current_spec())
    return f"r5@{fingerprint()[:8]}+{m['version'] if m else 'nopack'}"


def _load():
    """进程级缓存：(CnnCandidates, 归一化模板矩阵 float32, 字表, 字→行号, 族查询函数)。"""
    if not _PACK:
        import numpy as np

        from ..clustering.cnn_candidates import shared
        from ..clustering.emb_pack import load_current
        from ..hanzi.db import shared as hanzi
        cnn = shared()
        pack = load_current(download=True)
        if not cnn.available or pack is None:
            raise RuntimeError("3c glyph_candidate：r5 权重或全字表向量包不可用（guji cache pull-rare-index）")
        m = pack.mat.astype(np.float32)
        m /= (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)
        hz = hanzi()
        fam_cache: dict = {}

        def family(c: str) -> list[str]:
            if c not in fam_cache:
                try:
                    fam_cache[c] = list(hz.family(c).keys())
                except Exception:  # noqa: BLE001 —— 族查不到就当没有，不拖累候选
                    fam_cache[c] = []
            return fam_cache[c]

        _PACK.update(cnn=cnn, mat=m, chars=pack.chars, index=pack.index, family=family)
    return _PACK


def rank_cell(sims, chars: list[str], index: dict, family, topk: int = 50, fam_top: int = 5,
              fam_after: int = 10) -> tuple[list[list], dict[str, str]]:
    """一格的余弦向量 sims（对 chars 逐字）→ (候选 [[字, 分]…], fam_of)。纯函数，测试直接调。"""
    import numpy as np
    n = min(len(sims), max(topk * 4, 200))
    top = np.argpartition(-sims, n - 1)[:n] if len(sims) > n else np.arange(len(sims))
    top = top[np.argsort(-sims[top])]
    base = [(chars[j], float(sims[j])) for j in top]
    head = base[:fam_after]
    seen = {c for c, _ in head}
    fam_of: dict[str, str] = {}
    fam_members: list[tuple[str, float]] = []
    for c, _ in base[:fam_top]:
        for m in family(c):
            if m in seen:
                continue
            j = index.get(m)
            if j is None:
                continue
            seen.add(m)
            fam_members.append((m, float(sims[j])))
            fam_of[m] = c
    fam_members.sort(key=lambda t: -t[1])
    rest = [(c, s) for c, s in base[fam_after:] if c not in seen]
    out = (head + fam_members + rest)[:topk]
    keep = {c for c, _ in out}
    return [[c, round(s, 4)] for c, s in out], {k: v for k, v in fam_of.items() if k in keep}


@register_step
class GlyphCandidateStep(Step):
    spec = StepSpec(
        id="glyph_candidate", title="3c 按图候选", version="0.1", unit="cell",
        consumes=("char_index", "char_patch"), produces=("glyph_candidate",),
        params=GlyphCandidateParams,
        needs=("model",),
        code_deps=("open_guji_cv.clustering.cnn_candidates", "open_guji_cv.clustering.emb_pack",
                   "open_guji_cv.clustering.normalize", "open_guji_cv.hanzi.db"),
        enabled_by="enabled",
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        import numpy as np

        from ..clustering.normalize import normalize_patch
        p: GlyphCandidateParams = ctx.params_for(self)  # type: ignore[assignment]
        chars: PageChars = ctx.product("char_index", page)
        queue: list[tuple[int, CharRec]] = []
        imgs: list = []
        col_recs: dict[int, list[CandRec]] = {}
        for cc in chars.columns:
            if not cc.ok:
                continue
            col_recs[cc.col] = []
            for r in cc.chars:
                if r.cell_type != "char" or not r.patch_key:
                    continue
                try:
                    imgs.append(normalize_patch(ctx.image("char_patch", r.patch_key)))
                except Exception:  # noqa: BLE001 —— 单格图读不出：留一条 ran=False，不拖累整页
                    col_recs[cc.col].append(CandRec(id=r.id, slot=r.slot, sub=r.sub, ran=False))
                    continue
                queue.append((cc.col, r))
        if imgs:
            L = _load()
            q = L["cnn"].embed(imgs)
            sims = q @ L["mat"].T
            for (col, r), s in zip(queue, sims):
                cands, fam_of = rank_cell(np.asarray(s), L["chars"], L["index"], L["family"],
                                          p.topk, p.fam_top, p.fam_after)
                col_recs[col].append(CandRec(id=r.id, slot=r.slot, sub=r.sub, cands=cands, fam_of=fam_of))
        cols = [ColumnCand(col=cc.col, chars=col_recs.get(cc.col, [])) for cc in chars.columns if cc.ok]
        return {"glyph_candidate": PageCand(page=page, model=p.model, columns=cols)}
