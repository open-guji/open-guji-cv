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

### 引用形近字组登记表（`ref`，2026-11-28 接上）

    params:
      glyph_near:
        groups:
          rr: {ref: rr, trigger: member, methods: {rr_shape: config/groups/rr_shape.json}}

`ref` 指 `config/near_groups/v2.json` 里的组 id，`chars`／`fold`（和登记表里这本书的 `books.<书>.glyph_near`）从表里来，
同组里另写的键盖过表（`near_registry.expand_refs`，按本册 id 展开，在 `book_params` 里做，指纹与 run_page 同一份）。
**一个 `ref` 都没写的书参数原样不动**，参数哈希逐位不变。

## 字块

方法吃哪种图由方法的 `patch` 定（`near_methods` 模块头）：
- `raw`（缺省，cnn_small）：**原图灰度裁块**（`ctx.raw_page` ＋ `core.anchor.crop_patch(…, bbox_page)`），不是 `char_patch`
  缓存里的二值图：宫官小 CNN 是在灰度裁块上训的（殿本 vol02 49 格复核：与训练时留出概率最大差 0.019，0.5 两侧一致 49/49）。
- `char_patch`（rr_shape 等从第四步搬来的判法）：`ctx.image("char_patch", patch_key)`，与第四步 seed_admit 读的同一张。
  读不到的格不抛错，这个方法给 `{sims: {}, evidence: {error: "patch_missing", detail}}`。

方法的 `score` 认 `ctx`／`cells` 的就一起传（本书库、3a 候选要用的方法）；`cells` 每格带 3a 首位与候选。

## 指纹

`methods_sha`（自动填）＝各组各方法模型目录里全部文件的 sha256，进参数指纹：换模型、换校准表，本步与收尾过期。
"""
from __future__ import annotations

from pydantic import BaseModel

from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.read import ColumnNear, NearMethodOut, NearRec, PageNear


def _expand(p: "GlyphNearParams", book: str | None) -> "GlyphNearParams":
    """书配置里带 `ref` 的组按登记表展开、重算 `methods_sha`；一个 `ref` 都没有原样返回同一个对象。"""
    from ..groups.near_registry import expand_refs
    g = expand_refs(p.groups, book)
    if g is p.groups:
        return p
    return type(p)(**{**{k: getattr(p, k) for k in type(p).model_fields}, "groups": g, "methods_sha": ""})


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
        consumes=("glyph_match", "char_index", "char_patch"), produces=("glyph_near",),
        params=GlyphNearParams,
        needs=("model",),
        code_deps=("open_guji_cv.groups.near_methods", "open_guji_cv.groups.near_registry",
                   "open_guji_cv.groups.rr_shape"),
        enabled_by="groups",
    )

    def book_params(self, p: GlyphNearParams, ctx: RunContext) -> GlyphNearParams:
        """按本册展开书配置里的 `ref`（见模块头）。"""
        return _expand(p, ctx.book.id)

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: GlyphNearParams = ctx.params_for(self)  # type: ignore[assignment]
        if not p.groups:
            return {"glyph_near": PageNear(page=page, methods_sha=p.methods_sha)}
        from ..core.anchor import crop_patch
        from ..groups.near_methods import load_method, score

        match = ctx.product("glyph_match", page)
        chars = ctx.product("char_index", page)
        crec = {r.id: r for cc in chars.columns for r in cc.chars}

        hits: list[tuple[int, object, str, str]] = []          # (列, MatchRec, 组, 触发方式)
        for cm in match.columns:
            for r in cm.chars:
                t = trigger_group(r.candidates, r.char, p.groups)
                if t and crec.get(r.id) is not None and crec[r.id].bbox_page is not None:
                    hits.append((cm.col, r, *t))

        recs: dict[str, NearRec] = {}
        if hits:
            methods = {gid: [(name, load_method(name, mdir))
                             for name, mdir in sorted(((p.groups[gid] or {}).get("methods") or {}).items())]
                       for gid in {h[2] for h in hits}}
            need_raw = any(getattr(m, "patch", "raw") == "raw" for ms in methods.values() for _, m in ms)
            raw = ctx.raw_page(page) if need_raw else None
            by_group: dict[str, list[tuple[int, object, object]]] = {}    # 组 → [(列, MatchRec, 原图裁块|None)]
            for col, r, gid, how in hits:
                patch = crop_patch(raw, crec[r.id].bbox_page) if raw is not None else None
                recs[r.id] = NearRec(id=r.id, slot=r.slot, sub=r.sub, group=gid, trigger=how)
                by_group.setdefault(gid, []).append((col, r, patch if patch is not None and patch.size else None))
            for gid, items in by_group.items():
                for name, m in methods[gid]:
                    use, missing = self._patches(ctx, page, m, items, crec)
                    if use:
                        cells = [self._cell(page, it[0], it[1], crec[it[1].id]) for it, _ in use]
                        outs = score(m, [pt for _, pt in use], ctx.book.id, ctx=ctx, cells=cells)
                        for ((_, r, _), _), o in zip(use, outs):
                            recs[r.id].methods.append(NearMethodOut(method=f"{name}:{gid}", sims=o["sims"],
                                                                    evidence=o.get("evidence") or {}))
                    for r, why in missing:
                        recs[r.id].methods.append(NearMethodOut(method=f"{name}:{gid}",
                                                                evidence={"error": "patch_missing", "detail": why}))
        cols = []
        for cm in match.columns:
            got = [recs[r.id] for r in cm.chars if r.id in recs]
            if got:
                cols.append(ColumnNear(col=cm.col, chars=got))
        return {"glyph_near": PageNear(page=page, methods_sha=p.methods_sha, columns=cols)}

    @staticmethod
    def _patches(ctx: RunContext, page: int, m, items: list, crec: dict) -> tuple[list, list]:
        """按方法要的图（`m.patch`）给字块 → ([(item, 图)], [(MatchRec, 读不到的原因)])。
        `raw`：原图裁块，裁不出的格跳过（同 11-27 第一版）；`char_patch`：切字缓存字块图，读不到的记下来。"""
        kind = getattr(m, "patch", "raw")
        if kind == "raw":
            return [(it, it[2]) for it in items if it[2] is not None], []
        if kind != "char_patch":
            raise ValueError(f"glyph_near：方法 {type(m).__name__} 要的字块图 {kind!r} 不认识（raw／char_patch）")
        use, missing = [], []
        for it in items:
            col, r, _ = it
            key = crec[r.id].patch_key or cell_patch_key(page, col, r.slot, r.sub)
            try:
                use.append((it, ctx.image("char_patch", key)))
            except Exception as e:  # noqa: BLE001 —— 不吞：写进这一格的证据
                missing.append((r, f"{key}: {type(e).__name__}: {e}"))
        return use, missing

    @staticmethod
    def _cell(page: int, col: int, r, c) -> dict:
        return {"id": r.id, "page": page, "col": col, "slot": r.slot, "sub": r.sub,
                "patch_key": c.patch_key or cell_patch_key(page, col, r.slot, r.sub),
                "char": r.char, "candidates": [(str(ch), float(v)) for ch, v in (r.candidates or [])]}


def cell_patch_key(page: int, col: int, slot: int, sub: str | None) -> str:
    """char_index 没给 `patch_key` 时的字块缓存键（同 seed_admit `_page_patch`）。"""
    return f"p{page:04d}c{col:02d}s{slot}{sub or ''}"
