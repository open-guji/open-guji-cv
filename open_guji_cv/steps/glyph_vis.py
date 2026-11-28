"""3e 看图大模型（条件）`glyph_vis`（2026-11-28，CV3；接口草案经 CV4 审定）。

3a 字形库、3b 形近字组方法都**给不出好结论**的少数格，把字块图连同候选字交给大模型，只按刻形判「像哪个候选」。
绝大多数格不跑。**只看图**：提示词不写书名、不给前后文、不给整理本（`groups/vis_img.py`）。**不定字、不放行、不出 p**：
结论原样进收尾 `glyph_analyzer` 的 `FinalRec.vis` 与被选候选的 `evidence.v`，第四步怎么用归第四步（第四步现役 L4
`groups/vis_llm.py`、`vis_ruling`、`ask`、`evidence.vis_ctx` 一行没动）。

## 书配置

    params:
      glyph_vis:
        enabled: true           # 缺省 false＝不跑（StepSpec.enabled_by），各书产物不变；要先开 3b glyph_near
        groups: [zy, yz, men, wj, guanm, chuo, yh, xuan]   # 哪些 3b 组的格可以问；缺省＝第四步现役 registry.VIS_GROUPS；"*"＝本书 3b 全部组
        guard: false            # 3b 伪组 _guard（near_knn 护栏格）也可问
        model: ""               # 模型配置值；空＝只读缓存、不调模型，没命中的出 ask（离线队列）
        effort: low
        prompt: vis-img-1       # 提示词 id（groups/vis_img.PROMPTS）
        patch: char_patch       # char_patch（与第四步 L4 同一张）| raw（原图灰度裁块）
        cand_topk: 5            # 候选＝触发组的组字 ∪ 3a 前 cand_topk 名 ∪ 3b 方法给出的字
        trig_near_abstain: true
        trig_near_split: true
        trig_near_margin: 0.2   # 概率口径方法 sims 首位−次位 < 此值；0＝不看
        trig_a_margin: 0.03     # 3a 非 same、前两名都在组里且分差 < 此值；0＝不看
        trig_p_min: 0.0         # 组有校准表时组内最高 p < 此值；0＝不看
        skip_half: null         # 夹注 a/b 半格不问；null＝跟书配置 seed_admit.group_flow_llm_skip_half
        max_per_page: 20        # 每页最多几格没命中缓存的（要问／待问）；超出记 skipped:cap；0＝不限
        accept_models: []       # 读缓存时另认哪些模型值（对话判的写 session:<名>）；空＝只认 model
        accept_legacy: false    # 认 rekey 来的旧 vis1 答案（看过前后文，仅供 A/B）

**阈值缺省是拍的**（`trig_near_margin`、`trig_a_margin`、`max_per_page`）：待殿本、全唐文各数一册触发量后再定。

## 触发（「3a／3b 不够好」）

对 3b 触发了 `groups` 里某组的格，任一条成立就问；格上记 `trigger: [记号…]`（CV4 拿它对照第四步 L4 触发格）：

| 记号 | 条件 |
|---|---|
| `near_abstain` | 该组所有方法都弃权（方法字＝证据 `char`；没这个键取 sims 首位；都没有＝弃权；组没挂方法也算） |
| `near_split` | 该组非弃权方法给的字（按组 `fold` 归一）不全同 |
| `near_margin` | 该组概率口径方法（`PROB_METHODS`）sims 按 `fold` 合并后首位−次位 < `trig_near_margin` |
| `a_margin` | 3a 非 same，前两名（归一后不同字）都在组里，分差 < `trig_a_margin` |
| `p_low` | 组里第一个出校准 p 的方法（同收尾），最高 p < `trig_p_min` |

排除：3a `same` 且所有非弃权方法与 3a 首位同字（全弃权也算，3a 有把握又没人反对）——不列；
半格（`skip_half`）→ `skipped:half`；字块读不到 → `skipped:patch_missing`；超 `max_per_page` → `skipped:cap`
（按 near_abstain ＞ near_split ＞ 其余、再按读序排，缓存命中的不占名额）。
几个组都触发时 `group` 取按组 id 第一个，`groups` 全列，候选取并集。只管主切法格（同 3b）。

## 缓存与在线

缓存在 `feedback/vis_glyph.py`（`<feedback>/vis_glyph/`，kind `vis_glyph`，不是人裁、不算钉），键
`(img_sha, prompt_sha, 候选集合, model)` 四样全对才命中；读只认 `model`＋`accept_models`。
**缓存内容不进指纹**：导入一批新答案后从 `glyph_vis` 起 `--force`；页头 `cache_pin` 记当时缓存的哈希（只记录）。
真调模型只在 `GUJI_LLM_ONLINE=1` 且有 `GUJI_ANTHROPIC_API_KEY` 时（`ctx_llm._client()`），且 `model` 非空；
否则没命中的格 `status=pending`，带 `ask`。在线问出错、拒答记 `status=error`（`why` 是错误码），不落缓存。
**开在线写缓存之前，manager 侧同步口径（vis_glyph 目录、event_level、u_stamp、GATE_EXEMPT_KINDS）须已合。**
"""
from __future__ import annotations

from pydantic import BaseModel

from ..core.spec import StepSpec
from ..core.step import STEPS, RunContext, Step, register_step
from ..products.kinds.read import ColumnVis, PageVis, VisRec

MODEL = "glyph-vis/0"
MARKS = ("near_abstain", "near_split", "near_margin", "a_margin", "p_low")
#: sims 是概率口径的 3b 方法（near_margin 只看它们；book_knn／near_knn 是距离／票数，stroke_veto 是对数似然）
PROB_METHODS = frozenset({"cnn_small", "wu_shape", "hou_shape", "part_shape", "pair_shape", "rr_shape"})
GUARD_GROUP = "_guard"


#: 缺省可问的组＝第四步现役 `groups.registry.VIS_GROUPS`（抄一份，不 import registry：免得 registry 进本步指纹；
#: `tests/test_glyph_vis.py` 守着两边相同）
DEFAULT_GROUPS = ("zy", "yz", "men", "wj", "guanm", "chuo", "yh", "xuan")


class GlyphVisParams(BaseModel):
    enabled: bool = False
    """开不开（书级）。缺省关。"""
    groups: list[str] | str = list(DEFAULT_GROUPS)
    """可问的 3b 组；缺省＝第四步现役 `registry.VIS_GROUPS`；`"*"`＝本书 3b 全部组（`book_params` 里展开后进指纹）。"""
    guard: bool = False
    model: str = ""
    """模型配置值；空＝只读缓存、不调模型。"""
    effort: str = "low"
    prompt: str = "vis-img-1"
    patch: str = "char_patch"
    cand_topk: int = 5
    trig_near_abstain: bool = True
    trig_near_split: bool = True
    trig_near_margin: float = 0.2
    """缺省拍的，待殿本、全唐文各数一册触发量后再定。"""
    trig_a_margin: float = 0.03
    """缺省拍的，同上。"""
    trig_p_min: float = 0.0
    skip_half: bool | None = None
    """None＝跟书配置 `seed_admit.group_flow_llm_skip_half`（`book_params` 里落成布尔）。"""
    max_per_page: int = 20
    """缺省拍的，同上。0＝不限。"""
    accept_models: list[str] = []
    accept_legacy: bool = False

    def model_post_init(self, _ctx) -> None:
        from ..groups.vis_img import PROMPTS
        if self.prompt not in PROMPTS:
            raise ValueError(f"glyph_vis：提示词 {self.prompt!r} 没登记（groups/vis_img.PROMPTS：{sorted(PROMPTS)}）")
        if self.patch not in ("char_patch", "raw"):
            raise ValueError(f"glyph_vis：patch 只认 char_patch／raw，拿到 {self.patch!r}")
        if isinstance(self.groups, str) and self.groups != "*":
            raise ValueError(f"glyph_vis：groups 写组 id 列表或 \"*\"，拿到 {self.groups!r}")


# ── 触发 ─────────────────────────────────────────────────────────────

def method_char(mo) -> str | None:
    """3b 一个方法对一格给的字：证据里有 `char` 键就用它（None＝弃权）；没有取 sims 首位；都没有＝弃权。"""
    ev = mo.evidence or {}
    if ev.get("error"):
        return None
    if "char" in ev:
        return ev["char"] or None
    if mo.sims:
        return max(sorted(mo.sims), key=lambda c: mo.sims[c])
    return None


def _folded_sims(sims: dict, fold: dict) -> list[float]:
    out: dict[str, float] = {}
    for c, s in (sims or {}).items():
        k = fold.get(c, c)
        out[k] = max(out.get(k, float("-inf")), float(s))
    return sorted(out.values(), reverse=True)


def group_marks(nr, rec, spec: dict, p: GlyphVisParams, calibrators: dict | None = None) -> list[str]:
    """一格在一个组下命中的触发记号（按 `MARKS` 顺序）。"""
    fold = dict((spec or {}).get("fold") or {})
    members = {fold.get(c, c) for c in ((spec or {}).get("chars") or [])}
    chars = [method_char(mo) for mo in nr.methods]
    non = [c for c in chars if c]
    out = set()
    if p.trig_near_abstain and not non:
        out.add("near_abstain")
    if p.trig_near_split and len({fold.get(c, c) for c in non}) > 1:
        out.add("near_split")
    if p.trig_near_margin > 0:
        for mo in nr.methods:
            if mo.method.split(":", 1)[0] in PROB_METHODS:
                v = _folded_sims(mo.sims, fold)
                if len(v) >= 2 and v[0] - v[1] < p.trig_near_margin:
                    out.add("near_margin")
    if p.trig_a_margin > 0 and rec.verdict != "same":
        ranked = [(fold.get(str(c), str(c)), float(s)) for c, s in (rec.candidates or [])]
        if len(ranked) >= 2:
            (c0, s0), (c1, s1) = ranked[0], ranked[1]
            if c0 != c1 and c0 in members and c1 in members and s0 - s1 < p.trig_a_margin:
                out.add("a_margin")
    if p.trig_p_min > 0 and calibrators:
        for mo in nr.methods:
            m = calibrators.get(mo.method)
            ps = m.calibrate(mo.sims) if m is not None else None
            if ps:
                if max(ps.values()) < p.trig_p_min:
                    out.add("p_low")
                break
    return [m for m in MARKS if m in out]


def top_char(rec) -> str | None:
    if rec.verdict == "same" and rec.char:
        return rec.char
    return str(rec.candidates[0][0]) if rec.candidates else rec.char


def cell_trigger(rec, nears: list, gspecs: dict, p: GlyphVisParams, allowed: set,
                 calibrators: dict | None = None) -> dict | None:
    """一格 → `{group, groups, trigger, cands}`；不问（没触发、或被排除）→ None。`nears`：这格 3b 各组的 NearRec。"""
    nrs = sorted((n for n in (nears or []) if n.group in allowed), key=lambda n: n.group)
    if not nrs:
        return None
    if rec.verdict == "same":
        t = top_char(rec)
        others = [c for n in nrs for c in map(method_char, n.methods) if c]
        fold_all: dict = {}
        for n in nrs:
            fold_all.update((gspecs.get(n.group) or {}).get("fold") or {})
        if all(fold_all.get(c, c) == fold_all.get(t, t) for c in others):
            return None
    hit: list[tuple[str, list[str]]] = []
    for n in nrs:
        mk = group_marks(n, rec, gspecs.get(n.group) or {}, p, calibrators)
        if mk:
            hit.append((n.group, mk))
    if not hit:
        return None
    marks = {m for _, mk in hit for m in mk}
    groups = [g for g, _ in hit]
    cands = set()
    for g in groups:
        cands |= {str(c) for c in ((gspecs.get(g) or {}).get("chars") or [])}
    cands |= {str(c) for c, _ in (rec.candidates or [])[:p.cand_topk]}
    if not rec.candidates and rec.char:
        cands.add(rec.char)
    for n in nrs:
        if n.group in groups:
            cands |= {c for c in map(method_char, n.methods) if c}
    from ..groups.vis_img import sort_cands
    return {"group": groups[0], "groups": groups, "trigger": [m for m in MARKS if m in marks], "cands": sort_cands(cands)}


def _rank(trigger: list[str]) -> int:
    return 0 if "near_abstain" in trigger else 1 if "near_split" in trigger else 2


def _client():
    """在线 client（`GUJI_LLM_ONLINE=1` 且有密钥）或 None。测试打桩换掉它。"""
    from ..groups.vis_img import client
    return client()


@register_step
class GlyphVisStep(Step):
    spec = StepSpec(
        id="glyph_vis", title="3e 看图大模型（条件）", version="0.1", unit="cell",
        consumes=("glyph_match", "glyph_near", "char_index", "char_patch"), produces=("glyph_vis",),
        params=GlyphVisParams,
        code_deps=("open_guji_cv.groups.vis_img", "open_guji_cv.feedback.vis_glyph", "open_guji_cv.groups.near_methods"),
        enabled_by="enabled",
    )

    def book_params(self, p: GlyphVisParams, ctx: RunContext) -> GlyphVisParams:
        """`groups: "*"` 按本书 3b 组展开；`skip_half: null` 落成书配置 `seed_admit.group_flow_llm_skip_half`。指纹与 run_page 同一份。"""
        upd: dict = {}
        if p.groups == "*":
            np_ = ctx.params_for(STEPS["glyph_near"])
            upd["groups"] = sorted(g for g in (getattr(np_, "groups", None) or {}) if g != GUARD_GROUP)
        if p.skip_half is None:
            try:
                sp = ctx.params_for(STEPS["seed_admit"])
                upd["skip_half"] = bool(getattr(sp, "group_flow_llm_skip_half", False))
            except Exception:  # noqa: BLE001 —— 没有 seed_admit 的管线：不跳
                upd["skip_half"] = False
        if not upd:
            return p
        return type(p)(**{**{k: getattr(p, k) for k in type(p).model_fields}, **upd})

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        from ..feedback.vis_glyph import answer_of, default_root, open_store
        from ..groups import vis_img as V

        p: GlyphVisParams = ctx.params_for(self)  # type: ignore[assignment]
        psha = V.prompt_sha(p.prompt)
        match = ctx.product("glyph_match", page)
        near = ctx.product("glyph_near", page)
        chars = ctx.product("char_index", page)
        crec = {r.id: r for cc in chars.columns for r in cc.chars}
        gspecs = dict(getattr(ctx.params_for(STEPS["glyph_near"]), "groups", None) or {})
        allowed = set(p.groups if isinstance(p.groups, list) else []) | ({GUARD_GROUP} if p.guard else set())
        calibrators = self._calibrators(gspecs, allowed) if p.trig_p_min > 0 else None
        near_by = near.by_id_all()

        todo = []                                   # (排序键, 列, MatchRec, 触发)
        for ci, cm in enumerate(match.columns):
            for si, r in enumerate(cm.chars):
                t = cell_trigger(r, near_by.get(r.id) or [], gspecs, p, allowed, calibrators)
                if t is not None and crec.get(r.id) is not None:
                    todo.append(((_rank(t["trigger"]), ci, si), cm.col, r, t))
        usage = {"calls": 0, "hits": 0, "pending": 0, "errors": 0, "skipped": 0, "in": 0, "out": 0}
        recs: dict[str, VisRec] = {}
        store = open_store(default_root()) if todo else None
        models = [m for m in [p.model, *p.accept_models] if m]
        client = _client() if (todo and p.model) else None
        raw = ctx.raw_page(page) if (todo and p.patch == "raw") else None
        misses = 0
        for _k, col, r, t in sorted(todo, key=lambda x: x[0]):
            v = VisRec(id=r.id, slot=r.slot, sub=r.sub, group=t["group"], groups=t["groups"] if len(t["groups"]) > 1 else [],
                       trigger=t["trigger"], cands=t["cands"], prompt_sha=psha)
            recs[r.id] = v
            if p.skip_half and (r.sub or "") in ("a", "b"):
                v.status = "skipped:half"
                usage["skipped"] += 1
                continue
            patch, why = self._patch(ctx, page, col, r, crec[r.id], p.patch, raw)
            if patch is None:
                v.status, v.why = "skipped:patch_missing", why
                usage["skipped"] += 1
                continue
            v.img_sha = sha = V.img_sha(patch)
            got = store.lookup(sha, psha, t["cands"], models)
            legacy = False
            if got is None and p.accept_legacy:
                lg = store.lookup_legacy(sha)
                if lg is not None and (lg.get("other") or lg.get("char") in t["cands"]):
                    got, legacy = lg, True
            if got is not None:
                ans = answer_of(got)
                v.status, v.cache_hit, v.legacy = "hit", True, legacy
                v.char, v.other = (None, True) if ans == V.OTHER else (ans, False)
                v.conf, v.why, v.model = got.get("conf"), got.get("why") or "", got.get("model") or ""
                if legacy:
                    v.prompt_sha = got.get("prompt_sha") or ""
                usage["hits"] += 1
                V.bump(vis_img_hits=1)
                continue
            if p.max_per_page and misses >= p.max_per_page:
                v.status = "skipped:cap"
                usage["skipped"] += 1
                continue
            misses += 1
            if client is None:
                v.status = "pending"
                v.model = p.model
                v.ask = {"img_sha": sha, "prompt": p.prompt, "prompt_sha": psha, "cands": t["cands"], "model": p.model}
                usage["pending"] += 1
                continue
            ans, tok, err = V.ask(client, patch, t["cands"], prompt=p.prompt, model=p.model, effort=p.effort)
            usage["calls"] += 1
            usage["in"] += int(tok.get("in") or 0)
            usage["out"] += int(tok.get("out") or 0)
            v.model = p.model
            if err:
                v.status, v.why = "error", err
                usage["errors"] += 1
                continue
            store.put(img_sha=sha, img_shape=V.gray(patch).shape, patch=p.patch, prompt=p.prompt, prompt_sha=psha,
                      cands=t["cands"], char=ans["char"], conf=ans["conf"], why=ans["why"], model=p.model, tok=tok, cell=r.id)
            v.status = "asked"
            v.char, v.other = (None, True) if ans["char"] == V.OTHER else (ans["char"], False)
            v.conf, v.why = ans["conf"], ans["why"]
        cols = []
        for cm in match.columns:
            got = [recs[r.id] for r in cm.chars if r.id in recs]
            if got:
                cols.append(ColumnVis(col=cm.col, chars=got))
        return {"glyph_vis": PageVis(page=page, model=MODEL, prompt=p.prompt, prompt_sha=psha,
                                     cache_pin=store.cache_pin() if store is not None else "", columns=cols,
                                     usage={k: v for k, v in usage.items() if v})}

    @staticmethod
    def _calibrators(gspecs: dict, allowed: set) -> dict:
        from ..groups.near_methods import load_method
        out = {}
        for gid in sorted(allowed):
            for name, mdir in ((gspecs.get(gid) or {}).get("methods") or {}).items():
                out[f"{name}:{gid}"] = load_method(name, mdir)
        return out

    @staticmethod
    def _patch(ctx: RunContext, page: int, col: int, r, c, kind: str, raw):
        """→ (字块｜None, 读不到的原因)。char_patch 同 3b／第四步的键；raw 是原图灰度裁块（同 3b cnn_small）。"""
        if kind == "raw":
            from ..core.anchor import crop_patch
            if raw is None or c.bbox_page is None:
                return None, "raw: 没有原图或字框"
            pt = crop_patch(raw, c.bbox_page)
            return (pt, "") if pt is not None and pt.size else (None, "raw: 裁块为空")
        key = c.patch_key or f"p{page:04d}c{col:02d}s{r.slot}{r.sub or ''}"     # 同 glyph_near.cell_patch_key、第四步 _page_patch
        try:
            return ctx.image("char_patch", key), ""
        except Exception as e:  # noqa: BLE001 —— 不吞：写进这一格
            return None, f"{key}: {type(e).__name__}: {e}"
