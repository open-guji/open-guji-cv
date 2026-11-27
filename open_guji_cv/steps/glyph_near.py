"""3b 形近字组分析 `glyph_near`（2026-11-27，第三步重构第一块；设计见 ai-team《第三步识字重构设计》）。

3a `glyph_match` 给了候选与相似度之后，**只对触发了形近字组的格**再做一遍字形分析：按书配置里这个组登记的方法
（`groups.near_methods`）给组内每个字一个新的分，外加证据。**不定字、不放行、不改 3a 的结果**；分怎么校准成 p、
怎么和别的证据合，归收尾 `glyph_analyzer`；放不放行归第四步。

## 书配置

    params:
      glyph_near:
        groups:
          gong:                                   # 组 id
            chars: [宫, 宮, 官]
            fold: {宮: 宫}                         # 异体不分：触发判断时当同一个字（可缺）
            methods: {cnn_small: models/glyph_near_gong}   # 方法名 → 模型目录（相对路径先找数据目录、再找仓根）
            trigger: member                       # member：3a 首位在组里就跑；close（缺省）：首位在组里且组内另一字分差 ≤ delta
            delta: 0.03
            topk: 3                               # close 看 3a 前几名

`groups` 空（缺省）＝这一步不跑（`StepSpec.enabled_by`），各书产物不受影响。

## 字块

方法吃的是**原图灰度裁块**（`ctx.raw_page` ＋ `core.anchor.crop_patch(…, bbox_page)`），不是 `char_patch` 缓存里的
二值图：宫官小 CNN 是在灰度裁块上训的（殿本 vol02 49 格复核：与训练时留出概率最大差 0.019，0.5 两侧一致 49/49）。

## 指纹

`methods_sha`（自动填）＝各组各方法模型目录里全部文件的 sha256，进参数指纹：换模型、换校准表，本步与收尾过期。
"""
from __future__ import annotations

from pydantic import BaseModel

from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.read import ColumnNear, NearMethodOut, NearRec, PageNear


class GlyphNearParams(BaseModel):
    groups: dict = {}
    """{组 id: {chars, fold, methods, trigger, delta, topk}}，见模块头。空＝不跑。"""
    methods_sha: str = ""
    """自动填：各组各方法的模型目录指纹（`near_methods.method_fingerprint`），yaml 里不用写。"""

    def model_post_init(self, _ctx) -> None:
        if self.groups and not self.methods_sha:
            from ..groups.near_methods import method_fingerprint
            parts = [f"{g}:{method_fingerprint(n, d)}"
                     for g, spec in sorted(self.groups.items())
                     for n, d in sorted(((spec or {}).get("methods") or {}).items())]
            object.__setattr__(self, "methods_sha", ";".join(parts))


def _canon(c: str, fold: dict) -> str:
    return fold.get(c, c)


def trigger_group(cands: list, top_char: str | None, groups: dict) -> tuple[str, str] | None:
    """3a 的候选 [(字, 分)…]（按分降序）→ (组 id, 触发方式)；哪个组都不触发返回 None。按组 id 排序取第一个触发的。"""
    ranked = [(str(c), float(s)) for c, s in (cands or [])]
    top = ranked[0][0] if ranked else top_char
    if not top:
        return None
    top_s = ranked[0][1] if ranked else 1.0
    for gid in sorted(groups):
        g = groups[gid] or {}
        fold = dict(g.get("fold") or {})
        members = {_canon(c, fold) for c in (g.get("chars") or [])}
        if _canon(top, fold) not in members:
            continue
        if str(g.get("trigger") or "close") == "member":
            return gid, "member"
        delta = float(g.get("delta", 0.03))
        topk = int(g.get("topk", 3))
        rivals = [c for c, s in ranked[1:topk]
                  if _canon(c, fold) in members and _canon(c, fold) != _canon(top, fold) and top_s - s <= delta]
        if rivals:
            return gid, "close"
    return None


@register_step
class GlyphNearStep(Step):
    spec = StepSpec(
        id="glyph_near", title="3b 形近字组分析", version="0.1", unit="cell",
        consumes=("glyph_match", "char_index"), produces=("glyph_near",),
        params=GlyphNearParams,
        needs=("model",),
        code_deps=("open_guji_cv.groups.near_methods",),
        enabled_by="groups",
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: GlyphNearParams = ctx.params_for(self)  # type: ignore[assignment]
        if not p.groups:
            return {"glyph_near": PageNear(page=page, methods_sha=p.methods_sha)}
        from ..core.anchor import crop_patch
        from ..groups.near_methods import load_method

        match = ctx.product("glyph_match", page)
        chars = ctx.product("char_index", page)
        bbox = {r.id: r.bbox_page for cc in chars.columns for r in cc.chars}

        hits: list[tuple[int, object, str, str]] = []          # (列, MatchRec, 组, 触发方式)
        for cm in match.columns:
            for r in cm.chars:
                t = trigger_group(r.candidates, r.char, p.groups)
                if t and bbox.get(r.id) is not None:
                    hits.append((cm.col, r, *t))

        recs: dict[str, NearRec] = {}
        if hits:
            raw = ctx.raw_page(page)
            by_group: dict[str, list[tuple[object, object]]] = {}
            for col, r, gid, how in hits:
                patch = crop_patch(raw, bbox[r.id])
                recs[r.id] = NearRec(id=r.id, slot=r.slot, sub=r.sub, group=gid, trigger=how)
                if patch is not None and patch.size:
                    by_group.setdefault(gid, []).append((r, patch))
            for gid, items in by_group.items():
                for name, mdir in sorted(((p.groups[gid] or {}).get("methods") or {}).items()):
                    m = load_method(name, mdir)
                    outs = m.score([pt for _, pt in items], ctx.book.id)
                    for (r, _), o in zip(items, outs):
                        recs[r.id].methods.append(NearMethodOut(method=f"{name}:{gid}", sims=o["sims"],
                                                                evidence=o.get("evidence") or {}))
        cols = []
        for cm in match.columns:
            got = [recs[r.id] for r in cm.chars if r.id in recs]
            if got:
                cols.append(ColumnNear(col=cm.col, chars=got))
        return {"glyph_near": PageNear(page=page, methods_sha=p.methods_sha, columns=cols)}
