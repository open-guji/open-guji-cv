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
            methods: {cnn_small: models/glyph_near_gong}   # 方法名 → 模型目录（相对路径先找数据目录、再找仓根）；
                                                  # 一份文件挂多对的方法写 {path, pair}，如 {part_shape: {path: config/groups/part_shape.json, pair: [剌, 刺]}}；
                                                  # 一份文件挂几组的写 {path, group}，如 {stroke_veto: {path: config/groups/stroke_veto.json, group: jys}}
            trigger: member                       # member：3a 首位在组里就跑；close（缺省）：首位在组里且组内另一字分差 ≤ delta；
                                                  # cands：3a 首位或候选前 topk 名里有组内任一字就跑（从第四步搬来的判法用它罩住 4d 的触发格）
            delta: 0.03
            topk: 3                               # close 看 3a 前几名（缺省 3）；cands 看前几名（缺省 5，＝glyph_match.max_candidates 缺省）

### 护栏触发：保留伪组 `_guard`（`trigger: guard`，near_knn 用，2026-11-28）

    params:
      glyph_near:
        groups:
          _guard: {trigger: guard, gap: true, methods: {near_knn: config/groups/near_knn.json}}

near_knn 判的不是某个字组，而是第四步的**形近护栏格**，所以挂在保留伪组 `_guard` 上（不写 `chars`／`ref`；`trigger: guard`
只给它用，它也只能用这个，写错报错；登记表 `expand_refs` 遇到带 `ref` 的 `_` 开头组报错）。按 3a `MatchRec` 照现役
`_near_knn_pass` 挑格，`NearRec.trigger` 记是哪一路：

- `guard`：3a 护栏 `guard` 是 `conflict`／`never_match`（第四步 `evidence.guard` 就是它）；
- `near_form`：3a 首位字＋候选前三名里有手工形近表（`NEVER_MATCH_FAMILIES`）的字（第四步 `near_form` 疑问同一口径）；
- `gap`（`gap: true` 才有）：3a 没判 same（库没把握）。现役 `near_knn_gap` 收「库首位≠整理本」的待审格，3b 看不到整理本，按「库没把握」罩。

第四步另两种疑问（`solo_confusable`、`iron_confusable_ref`）和「字组流程归了组」的格 3b 看不到，4d 本地现算并计数。
`methods_sha` 里是 `_guard:near_knn=<库钉版指纹>`。

`groups` 空（缺省）＝这一步不跑（`StepSpec.enabled_by`），各书产物不受影响。

### 引用形近字组登记表（`ref`，2026-11-28 接上）

    params:
      glyph_near:
        groups:
          rr: {ref: rr, trigger: cands, methods: {rr_shape: config/groups/rr_shape.json}}

`ref` 指 `config/near_groups/v2.json` 里的组 id，`chars`／`fold`（和登记表里这本书的 `books.<书>.glyph_near`）从表里来，
同组里另写的键盖过表（`near_registry.expand_refs`，按本册 id 展开，在 `book_params` 里做，指纹与 run_page 同一份）。
**一个 `ref` 都没写的书参数原样不动**，参数哈希逐位不变。

### 守登记表的 `handling.methods`（2026-11-28，Sheldon 定「每组自定处理方式」）

每组允许用哪些看图方法登记在表里（`handling.methods`，人定值在 `config/near_groups/handling.json`；日曰、己已巳为 []＝不做字形区分）。
`book_params` 里按 `near_registry.resolve` 核：书配置给某组挂了不在它 `handling.methods` 里的方法——写了 `ref` 按 `ref` 的组，
没写 `ref` 按 `chars` 对到包含这几个字的成员最少的组（哪组都不包含、或保留伪组 `_guard`，不核）。
过渡期（`near_registry.STRICT_METHODS = False`）**警告、跳过该方法并计数**（一组挂的方法全被跳过就整组不跑）：跳过的记进产物 `PageNear.skipped_methods`（「组:方法」，
空的不落盘）、日志 warning；`methods_sha` 按跳过后的方法重算。各书配置清干净后改成报错。没有要跳过的书参数原样不动。

## 一格多组（2026-11-28，CV3／CV4 定）

一格可以同时触发几个组（如 `trigger: cands` 的组字有重叠、或前几名候选分属两个组），**每个组各出一条 `NearRec`**
（同格 id、`group` 不同，列里按格序再按组 id 排）。之前一格只进按组 id 排第一个触发的组。读口（`products/kinds/read.py`）：

- `PageNear.by_id()`：`{格 id: NearRec}`，一格一条，取按组 id 排第一个的（＝之前的行为，老读者不改也照旧）；
- `PageNear.by_id_all()`：`{格 id: [NearRec…]}`，每个组一条、按组 id 排；
- `PageNear.get(格 id, 组)`：某格某组那条，没触发 → None。

`trigger_groups()` 给全部触发的组；`trigger_group()` 仍只给第一个。

## 字块

方法吃哪种图由方法的 `patch` 定（`near_methods` 模块头）：
- `raw`（缺省，cnn_small）：**原图灰度裁块**（`ctx.raw_page` ＋ `core.anchor.crop_patch(…, bbox_page)`），不是 `char_patch`
  缓存里的二值图：宫官小 CNN 是在灰度裁块上训的（殿本 vol02 49 格复核：与训练时留出概率最大差 0.019，0.5 两侧一致 49/49）。
- `char_patch`（rr_shape 等从第四步搬来的判法）：`ctx.image("char_patch", patch_key)`，与第四步 seed_admit 读的同一张。
  读不到的格不抛错，这个方法给 `{sims: {}, evidence: {error: "patch_missing", detail}}`。

方法的 `score` 认 `ctx`／`cells` 的就一起传（本书库、3a 候选要用的方法）；`cells` 每格带 3a 首位与候选。

**只管主切法格**：3b 按 `glyph_match.columns`／`char_index` 走，备选切法列（`glyph_match.alt_columns`）不跑；
4d 读备选列时本地现算（CV3／CV4 11-28 定）。

## 给 4d 的（2026-11-28，CV4《4d 接 3b 看图方法-接口要求》）

- 方法证据原样落进 `NearMethodOut.evidence`（rr_shape：`{char, why, nn, score, geo}`，与 `rr_shape.judge()` 同键同值、同舍入；
  wu_shape／hou_shape：`{char, why, p|v}`＝`judge()` 整个返回值），外加 `method`，收尾把它抄进每格 `near.methods[方法名]`；
- stroke_veto：`{group, **judge()}`（`cls` 是类名，jys 的 已／巳 一类 `已巳`）；4d 降审时写的 `{group, cls, llr, x}` 用
  `near_methods.stroke_veto_trail` 从证据得出，降不降、`channels` 过滤留在 4d；
- book_knn 只出前段（A 档结论与原始量，外加 `b_ok`），B 档（要整理本对位字）由 4d 调 `near_methods.book_knn_settle` 定；
  库钉版指纹 `near_methods.lib_fingerprint` 进 `methods_sha`，4d 调同一个函数比；
- near_knn 出与候选无关的全库量（`full`／`full_votes`／`nn`／`out_of_book`）和 3a 首位＋候选每个字各自的前 k 个近邻距离（`dists`），
  4d 拿自己的候选调 `near_methods.near_knn_settle` 重判；候选比票、ref_gate、skip_chars／skip_groups、异体边、gap 出口闸都留在 4d；
- 本页跑过的方法用的模型版本记在 `PageNear.models`（`{"方法:组": 方法.model_sha}`），收尾也抄进 `near.methods[方法名].model`。

## 指纹

`methods_sha`（自动填）＝各组各方法模型目录里全部文件的 sha256，进参数指纹：换模型、换校准表，本步与收尾过期。
`{path, pair}` 写法的方法另把 pair 并进指纹、`{path, group}` 写法另把组名并进指纹（`near_methods.method_fingerprint`；
字符串写法的指纹逐位不变）。
"""
from __future__ import annotations

from pydantic import BaseModel, PrivateAttr

from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.read import ColumnNear, NearMethodOut, NearRec, PageNear


def _expand(p: "GlyphNearParams", book: str | None) -> "GlyphNearParams":
    """书配置里带 `ref` 的组按登记表展开、去掉登记表 `handling.methods` 以外的方法（过渡期警告跳过，见模块头）、重算
    `methods_sha`；一个 `ref` 都没有、也没有要跳过的方法时原样返回同一个对象。"""
    from ..groups.near_registry import resolve
    g, skipped = resolve(p.groups, book)
    if g is p.groups:
        return p
    q = type(p)(**{**{k: getattr(p, k) for k in type(p).model_fields}, "groups": g, "methods_sha": ""})
    q._skipped = tuple(f"{n}:{m}" for n, _, m in skipped)
    return q


class GlyphNearParams(BaseModel):
    groups: dict = {}
    """{组 id: {chars, fold, methods, trigger, delta, topk}}，见模块头。空＝不跑。"""
    methods_sha: str = ""
    """自动填：各组各方法的模型目录指纹（`near_methods.method_fingerprint`），yaml 里不用写。"""
    _skipped: tuple = PrivateAttr(default=())
    """`book_params` 按登记表 `handling.methods` 跳过的「组:方法」（不进参数指纹；run_page 抄进 `PageNear.skipped_methods`）。"""

    def model_post_init(self, _ctx) -> None:
        for gid, spec in (self.groups or {}).items():
            how = str((spec or {}).get("trigger") or "close")
            if (gid == GUARD_GROUP) != (how == "guard"):
                raise ValueError(f"glyph_near：`trigger: guard` 只给保留伪组 {GUARD_GROUP!r} 用，{GUARD_GROUP!r} 也只能用它"
                                 f"（组 {gid!r} 写的是 trigger: {how}）")
            if gid == GUARD_GROUP and ((spec or {}).get("chars") or (spec or {}).get("ref")):
                raise ValueError(f"glyph_near：伪组 {GUARD_GROUP!r} 不按组字触发，不写 chars／ref")
        if self.groups and not self.methods_sha:
            from ..groups.near_methods import method_fingerprint
            parts = [f"{g}:{method_fingerprint(n, d)}"
                     for g, spec in sorted(self.groups.items())
                     for n, d in sorted(((spec or {}).get("methods") or {}).items())]
            object.__setattr__(self, "methods_sha", ";".join(parts))


GUARD_GROUP = "_guard"
"""保留伪组 id：`trigger: guard` 的方法（near_knn）挂在它上面，不对应登记表里的组（`expand_refs` 遇到带 `ref` 的报错）。"""
GUARD_KINDS = ("conflict", "never_match")


def _near_form_chars() -> frozenset:
    """第四步 `near_form` 疑问的字表（`seed_admit` 里 `NEAR_FORM_CHARS`＝手工形近表 `NEVER_MATCH_FAMILIES` 的字）。"""
    from ..clustering.match import NEVER_MATCH_FAMILIES
    return frozenset(c for pair in NEVER_MATCH_FAMILIES for c in pair)


def _guard_how(ranked: list, top_char: str | None, g: dict, rec) -> str | None:
    """`trigger: guard`（见模块头）：3a 护栏 conflict／never_match → `guard`；首位＋前三名里有手工形近表的字 → `near_form`；
    `gap: true` 时 3a 没判 same → `gap`；都不是 → None。"""
    if rec is not None and getattr(rec, "guard", None) in GUARD_KINDS:
        return "guard"
    if ({c for c, _ in ranked[:3]} | ({top_char} if top_char else set())) & _near_form_chars():
        return "near_form"
    if g.get("gap") and rec is not None and getattr(rec, "verdict", None) != "same":
        return "gap"
    return None


def _canon(c: str, fold: dict) -> str:
    return fold.get(c, c)


def trigger_group(cands: list, top_char: str | None, groups: dict, rec=None) -> tuple[str, str] | None:
    """3a 的候选 [(字, 分)…]（按分降序）→ (组 id, 触发方式)；哪个组都不触发返回 None。按组 id 排序取第一个触发的
    （一格多组之前 3b 只认这一个；现在 3b 用 `trigger_groups`，这个留给只要一个组的读者）。"""
    got = trigger_groups(cands, top_char, groups, rec)
    return got[0] if got else None


def trigger_groups(cands: list, top_char: str | None, groups: dict, rec=None) -> list[tuple[str, str]]:
    """3a 的候选 [(字, 分)…]（按分降序）→ 触发的每个组 [(组 id, 触发方式)…]，按组 id 排序；哪个组都不触发返回 []。
    `rec`：这格的 3a `MatchRec`，`trigger: guard` 要看它的护栏与判档（不给时只按形近表字判）。"""
    ranked = [(str(c), float(s)) for c, s in (cands or [])]
    top = ranked[0][0] if ranked else top_char
    if not top:
        return []
    top_s = ranked[0][1] if ranked else 1.0
    out: list[tuple[str, str]] = []
    for gid in sorted(groups):
        g = groups[gid] or {}
        fold = dict(g.get("fold") or {})
        members = {_canon(c, fold) for c in (g.get("chars") or [])}
        mode = str(g.get("trigger") or "close")
        if mode == "guard":
            how = _guard_how(ranked, top_char, g, rec)
            if how:
                out.append((gid, how))
            continue
        if mode == "cands":
            pool = {_canon(c, fold) for c, _ in ranked[:int(g.get("topk", 5))]}
            pool |= {_canon(c, fold) for c in (top, top_char) if c}
            if pool & members:
                out.append((gid, "cands"))
            continue
        if _canon(top, fold) not in members:
            continue
        if mode == "member":
            out.append((gid, "member"))
            continue
        delta = float(g.get("delta", 0.03))
        topk = int(g.get("topk", 3))
        rivals = [c for c, s in ranked[1:topk]
                  if _canon(c, fold) in members and _canon(c, fold) != _canon(top, fold) and top_s - s <= delta]
        if rivals:
            out.append((gid, "close"))
    return out


@register_step
class GlyphNearStep(Step):
    spec = StepSpec(
        id="glyph_near", title="3b 形近字组分析", version="0.2", unit="cell",
        consumes=("glyph_match", "char_index", "char_patch"), produces=("glyph_near",),
        params=GlyphNearParams,
        needs=("model",),
        code_deps=("open_guji_cv.groups.near_methods", "open_guji_cv.groups.near_registry",
                   "open_guji_cv.groups.book_knn", "open_guji_cv.groups.near_knn", "open_guji_cv.clustering.match",
                   "open_guji_cv.groups.hou_shape", "open_guji_cv.groups.pair_shape", "open_guji_cv.groups.part_shape",
                   "open_guji_cv.groups.rr_shape", "open_guji_cv.groups.stroke_veto", "open_guji_cv.groups.wu_shape",
                   "open_guji_cv.strokes", "open_guji_cv.strokes._ink", "open_guji_cv.strokes.features",
                   "open_guji_cv.strokes.register", "open_guji_cv.strokes.template"),
        enabled_by="groups",
    )

    def book_params(self, p: GlyphNearParams, ctx: RunContext) -> GlyphNearParams:
        """按本册展开书配置里的 `ref`（见模块头）。"""
        return _expand(p, ctx.book.id)

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: GlyphNearParams = ctx.params_for(self)  # type: ignore[assignment]
        skipped = list(p._skipped)
        if not p.groups:
            return {"glyph_near": PageNear(page=page, methods_sha=p.methods_sha, skipped_methods=skipped)}
        from ..core.anchor import crop_patch
        from ..groups.near_methods import load_method, score

        match = ctx.product("glyph_match", page)
        chars = ctx.product("char_index", page)
        crec = {r.id: r for cc in chars.columns for r in cc.chars}

        hits: list[tuple[int, object, str, str]] = []          # (列, MatchRec, 组, 触发方式)；一格触发几个组就几条
        for cm in match.columns:
            for r in cm.chars:
                if crec.get(r.id) is None or crec[r.id].bbox_page is None:
                    continue
                for t in trigger_groups(r.candidates, r.char, p.groups, r):
                    hits.append((cm.col, r, *t))

        recs: dict[tuple[str, str], NearRec] = {}               # (格 id, 组) → NearRec
        models: dict[str, str] = {}
        if hits:
            methods = {gid: [(name, load_method(name, mdir))
                             for name, mdir in sorted(((p.groups[gid] or {}).get("methods") or {}).items())]
                       for gid in {h[2] for h in hits}}
            need_raw = any(getattr(m, "patch", "raw") == "raw" for ms in methods.values() for _, m in ms)
            raw = ctx.raw_page(page) if need_raw else None
            crops: dict[str, object] = {}                       # 格 id → 原图裁块（几个组共用一块）
            by_group: dict[str, list[tuple[int, object, object]]] = {}    # 组 → [(列, MatchRec, 原图裁块|None)]
            for col, r, gid, how in hits:
                if r.id not in crops:
                    patch = crop_patch(raw, crec[r.id].bbox_page) if raw is not None else None
                    crops[r.id] = patch if patch is not None and patch.size else None
                recs[(r.id, gid)] = NearRec(id=r.id, slot=r.slot, sub=r.sub, group=gid, trigger=how)
                by_group.setdefault(gid, []).append((col, r, crops[r.id]))
            for gid, items in sorted(by_group.items()):
                for name, m in methods[gid]:
                    use, missing = self._patches(ctx, page, m, items, crec)
                    models[f"{name}:{gid}"] = str(getattr(m, "model_sha", "") or m.fingerprint())
                    if use:
                        cells = [self._cell(page, it[0], it[1], crec[it[1].id]) for it, _ in use]
                        outs = score(m, [pt for _, pt in use], ctx.book.id, ctx=ctx, cells=cells)
                        for ((_, r, _), _), o in zip(use, outs):
                            recs[(r.id, gid)].methods.append(NearMethodOut(method=f"{name}:{gid}", sims=o["sims"],
                                                                           evidence=o.get("evidence") or {}))
                    for r, why in missing:
                        recs[(r.id, gid)].methods.append(NearMethodOut(method=f"{name}:{gid}",
                                                                       evidence={"error": "patch_missing", "detail": why}))
        cols = []
        for cm in match.columns:
            got = [recs[(r.id, g)] for r in cm.chars for g in sorted(p.groups) if (r.id, g) in recs]
            if got:
                cols.append(ColumnNear(col=cm.col, chars=got))
        return {"glyph_near": PageNear(page=page, methods_sha=p.methods_sha, columns=cols, models=models,
                                       skipped_methods=skipped)}

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
