"""C1 进库准入（`seed_admit`）的字组流程（第四步 4d `group_decision`）：group_flow、看图判裁定、折叠组、近形 p、人裁字形表。

CV4 整理 P1a（2026-11-28）从 seed_admit.py **原样搬来，不改行为**。
"""

from __future__ import annotations

from . import seed_admit_common as _C
from ..utils.gap import GAP_CHARS
from .decide import _opt, coord_refs
from .seed_admit_common import PatchUnavailable
from .seed_admit_common import _LANE_GARBLE
from .seed_admit_common import _LANE_HARD
from .seed_admit_common import _RARE_REF_HARD
from .seed_admit_common import _VIS_RULING_HARD
from .seed_admit_common import _demote
from .seed_admit_common import _hard_blocked
from .seed_admit_common import _log
from functools import lru_cache










def _group_members(gid) -> frozenset:
    from ..groups.registry import FLOW_GROUPS
    spec = FLOW_GROUPS.get(gid) if gid else None
    return spec.members if spec is not None else frozenset()


def _group_variant(gid) -> bool:
    from ..groups.registry import FLOW_GROUPS
    spec = FLOW_GROUPS.get(gid) if gid else None
    return spec is not None and spec.kind == "variant"


def _provisional_forms(gid) -> frozenset:
    from ..groups.registry import PROVISIONAL
    pv = PROVISIONAL.get(gid) if gid else None
    return pv.forms if pv is not None else frozenset()


def _clf_ctx(seq: list, amap: dict, i: int, step: int, width: int = 30) -> str:
    """第 i 格前（step=-1）/后（step=1）至多 width 字，读序；只用邻格**已放行**的字，否则用整理本对位字，再没有记「□」。
    与离线 G0 快照的取法一致（`research/char_groups/build.py`：未放行格用整理本字补）。"""
    out: list[str] = []
    j = i + step
    while 0 <= j < len(seq) and len(out) < width:
        # 只用已放行的字：待审格的 `char` 是库 top1 默认字（`_pick_char`），可能是乱码，不是读法
        out.append((seq[j].char if seq[j].admit else None) or (amap.get(seq[j].id) or (None, None))[0] or "□")
        j += step
    return "".join(reversed(out)) if step < 0 else "".join(out)


def _resolve_group_flow_paths(p) -> None:
    """`group_flow` 的表路径：相对路径按工作区解释；没给时找工作区约定位置
    （字频 `config/groups/freq.json`、文意 L2 表 `config/groups/l2/<组>.json`），找不到就空着（该解法弃权）。
    路径不进参数哈希，表内容哈希进 `group_flow_fingerprint`。"""
    from pathlib import Path
    from ..core.workspace import REPO_ROOT, data_root, workspace_root
    from ..groups.registry import FLOW_GROUPS as GROUPS
    base = workspace_root() or REPO_ROOT
    cfg = (data_root() or REPO_ROOT) / "config" / "groups"     # 迁到中心库后在数据目录（GUJI-608）

    def _abs(v: str) -> str:
        q = Path(v).expanduser()
        return str(q if q.is_absolute() else base / q)
    freq = _abs(p.group_flow_freq) if p.group_flow_freq else ""
    if not freq and (cfg / "freq.json").exists():
        freq = str(cfg / "freq.json")
    tables = {g: _abs(v) for g, v in p.group_flow_tables.items()}
    for g in p.group_flow:
        if "ctx" in GROUPS[g].flow.solvers and g not in tables:
            t = cfg / "l2" / f"{g}.json"
            if t.exists():
                tables[g] = str(t)
    models = {g: _abs(v) for g, v in p.group_flow_models.items()}
    for g in p.group_flow:
        if "ctx" in GROUPS[g].flow.solvers and g not in models:
            t = cfg / "l2model" / f"{g}.json"
            if t.exists():
                models[g] = str(t)
    object.__setattr__(p, "group_flow_freq", freq)
    object.__setattr__(p, "group_flow_tables", tables)
    object.__setattr__(p, "group_flow_models", models)
    rs = _abs(p.group_flow_rr_shape) if p.group_flow_rr_shape else ""
    if not rs and "rr" in p.group_flow and (cfg / "rr_shape.json").exists():
        rs = str(cfg / "rr_shape.json")
    object.__setattr__(p, "group_flow_rr_shape", rs)
    ws = _abs(p.group_flow_wu_shape) if p.group_flow_wu_shape else ""
    if not ws and "wu" in p.group_flow and (cfg / "wu_shape.json").exists():
        ws = str(cfg / "wu_shape.json")
    object.__setattr__(p, "group_flow_wu_shape", ws)
    hs = _abs(p.group_flow_hou_shape) if p.group_flow_hou_shape else ""
    if not hs and "hou" in p.group_flow and (cfg / "hou_shape.json").exists():
        hs = str(cfg / "hou_shape.json")
    object.__setattr__(p, "group_flow_hou_shape", hs)
    if p.group_flow_part_shape:                  # 相对路径先找数据目录（config/groups/part_shape.json，随中心库走），再找工作区
        _q = Path(p.group_flow_part_shape).expanduser()
        _dr = data_root()
        object.__setattr__(p, "group_flow_part_shape",
                           str(_dr / _q) if not _q.is_absolute() and _dr is not None and (_dr / _q).exists() else _abs(p.group_flow_part_shape))
    if p.group_flow_pair_shape:
        object.__setattr__(p, "group_flow_pair_shape", _abs(p.group_flow_pair_shape))
    if p.group_flow_pair_shapes:                 # 相对路径先找数据目录（模型随中心库走：config/groups/pair_shape_<组>.json），再找工作区
        droot = data_root()

        def _abs_data(v: str) -> str:
            q = Path(v).expanduser()
            if not q.is_absolute() and droot is not None and (droot / q).exists():
                return str(droot / q)
            return _abs(v)
        object.__setattr__(p, "group_flow_pair_shapes", {k: _abs_data(v) for k, v in p.group_flow_pair_shapes.items()})
    bk = {g: _abs(v) for g, v in p.group_flow_book_knn.items()}
    for g in p.group_flow:
        t = cfg / "book_knn" / f"{g}.json"
        if g not in bk and t.exists():
            bk[g] = str(t)
    object.__setattr__(p, "group_flow_book_knn", bk)
    nk = _abs(p.group_flow_near_knn) if p.group_flow_near_knn else ""
    if not nk and (cfg / "near_knn.json").exists():
        nk = str(cfg / "near_knn.json")
    object.__setattr__(p, "group_flow_near_knn", nk)


def _l3_groups(p) -> tuple:
    from ..groups.flow import rules_path
    if not p.group_flow_llm_model:
        return ()
    return tuple(g for g in p.group_flow_llm_groups
                 if g in p.group_flow and rules_path(g).with_name("prompt.md").exists())


_L3_ONLINE: dict = {}


_FLOW_MOUNT_LOGGED: list = []     # 本进程只记一次文意挂载情况（见 _flow_config）


def _l3_online(p) -> dict:
    """文意 L3 在线各组的 {system, ver, rulings}：提示词按本书变量填好（`prompt_template`），问过的窗口存成大模型裁定事件
    （`feedback/rulings`，按窗口内容查，见 `groups/ctx_llm`）。"""
    from ..core.workspace import REPO_ROOT, data_root
    from ..groups.flow import rules_path
    from ..groups.prompt_template import book_prompt_vars, load_rendered_prompt
    gs = _l3_groups(p)
    root = data_root() or REPO_ROOT
    key = (gs, str(root))
    if key not in _L3_ONLINE:
        bv = book_prompt_vars()
        d = {}
        for g in gs:
            try:
                meta, body = load_rendered_prompt(rules_path(g).with_name("prompt.md"), bv)
            except KeyError:              # 本书没给提示词变量（book_prompt.json）：这组不问
                continue
            d[g] = {"system": body, "ver": meta.get("ver", "")}
        if d:                  # 问过的窗口存成裁定事件（feedback/rulings，同人裁事件库），下次先查它
            from ..feedback.rulings import RulingCache, RulingStore
            rc = RulingCache(RulingStore())
            for o in d.values():
                o["rulings"] = rc
        _L3_ONLINE[key] = d
    return _L3_ONLINE[key]


_VIS_CACHE: list = []


def _vis_cache():
    """字块图像＋文意 L4 的缓存：同文意 L3，落裁定库（按组、字块哈希、前后文）。"""
    if not _VIS_CACHE:
        from ..feedback.rulings import RulingCache, RulingStore
        _VIS_CACHE.append(RulingCache(RulingStore()))
    return _VIS_CACHE[0]


def _l3_fingerprint(p) -> str:
    import hashlib
    h = hashlib.sha256(f"{p.group_flow_llm_model}|{p.group_flow_llm_effort}|False|{','.join(p.group_flow_llm_panel)}|{','.join(p.group_flow_llm_panel_groups)}".encode())
    for g, o in sorted(_l3_online(p).items()):
        h.update(f"|{g}|{o['ver']}|".encode() + o["system"].encode("utf-8"))
    return h.hexdigest()[:16]


#: 字组统一流程不碰的格：硬护栏（同规则 A）＋待审补放不碰的＋乱码护栏＋排除、非字、超时；形近护栏除外（见 `blocked`）
_GROUP_FLOW_OWN_GUARDS = frozenset({"never_match", "conflict"})


_GROUP_FLOW_OWN_DOUBTS = frozenset({"near_form"} | {f"护栏:{g}" for g in _GROUP_FLOW_OWN_GUARDS})


_GROUP_FLOW_HARD = ((frozenset(_RARE_REF_HARD) | _LANE_HARD | _LANE_GARBLE | {"excluded", "glyph_timeout"})
                    - _GROUP_FLOW_OWN_DOUBTS)


#: 看图判裁定（`feedback/rulings`，group=O）：提示词版本、A24 名下的子类、不碰的疑问
from ..feedback.rulings import VIS_RULING_GROUP as _VIS_RULING_GROUP, VIS_RULING_SPECS as _RULING_SPECS   # noqa: E402  写入校验同一份


_VIS_RULING_VER = _RULING_SPECS[0][0]


_VIS_RULING_SUBCLASSES = _RULING_SPECS[0][1]


#: 整理本缺字（〓）按新图源文本层取字／私用码「一码一字」表（`research/a24/pua_src`，A24 2026-11-03），提示词版本 → 收的子类
#: ctx-m1＝只读文意终审（A24 2026-11-04，两路独立会话双 high＋字形分或≥2 来源，按组定越不越过整理本；`admit_ok` 写入时已判），Z＝字组格、N＝形近护栏格
_VIS_RULING_SPECS = _RULING_SPECS


_VIS_HALF_BAD = frozenset({"clipped", "frame_residue"})   # vis_ruling_half 下带这些切分疑点的半格不放


def _ruling_han(c) -> bool:
    """裁定字须是汉字（统一表意文字各区＋兼容表意）：汉字区以外的码位、私用码、符号、占位一律不放（Ext J 的 U+323B0–3347F 是 Unicode 17 的真汉字，算）
    （A31 11-05：不能让非汉字经 vis_ruling 通道放行；比 `_is_han` 严，后者连私用码也算）。"""
    if not c or len(c) != 1:
        return False
    o = ord(c)
    return (0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0x20000 <= o <= 0x323AF
            or 0x323B0 <= o <= 0x3347F or 0x2F800 <= o <= 0x2FA1F)


def _override_ok(groups, a: str, b: str) -> bool:
    """a、b 同属 `groups` 里的某个字组（成员含两字）。"""
    from ..groups.registry import FLOW_GROUPS
    return any(g in FLOW_GROUPS and a in FLOW_GROUPS[g].members and b in FLOW_GROUPS[g].members for g in groups)


def _anchor_cells_sha(ctx, page: int) -> str | None:
    """格锚点后备键用的本页 cells_sha；裁定库里没有带 cells_sha 的裁定就不算（返回 None，行为与没有锚点时完全一样）。"""
    if ctx is None or not _vis_cache().store_.has_anchors():
        return None
    from ..feedback.rulings import page_cells_sha
    return page_cells_sha(ctx.book.id, page, ctx.store)


def _cell_book(cid: str | None) -> str | None:
    """格号的册前缀（`vol31:12:3:4a` → `vol31`）。"""
    return cid.split(":", 1)[0] if cid and ":" in cid else None


def _uid_map(p, ctx, page: int) -> dict | None:
    """`ruling_by_u` 用的本页 {格号: u}（字格身份账按本页当前 cells_sha 查）。开关关、裁定库里没有带 u 的裁定、账里没这一页这次切分
    → None（不读账、不算 sha，行为与开关关时完全一样）。"""
    if not getattr(p, "ruling_by_u", False) or ctx is None:
        return None
    st = _vis_cache().store_
    if not st.has_u():
        return None
    from ..feedback.rulings import page_cells_sha
    sha = page_cells_sha(ctx.book.id, page, ctx.store)
    return st.uid_ledger().lookup(ctx.book.id, page, sha) or None


def _anchor_cand_ok(ch: str, cid: str, ref: str | None, mmap: dict | None) -> bool:
    """格锚点命中的附加条件：裁定字＝整理本对位字，或在这格库候选里。"""
    if ref and ch == ref:
        return True
    m = (mmap or {}).get(cid)
    return bool(m and any(c[0] == ch for c in (m.candidates or [])))


def _vis_ruling_pass(p, out: list, amap: dict, store=None, cells_sha: str | None = None, mmap: dict | None = None,
                     umap: dict | None = None) -> int:
    """无组格的看图判裁定（`SeedAdmitParams.vis_rulings`）：待审格按前后文窗口（与 `ctx_hash` 同口径，宽 20）查裁定库，
    命中高把握可放的裁定 → 放行成裁定的字（通道 `vis_ruling`，provenance `match`，`evidence.vis_ruling` 留裁定摘要）。
    另：已放行格命中 `route=code_conflict` 的 src-1 裁定（同一私用码在源文本里是另一个字）→ 降回待审（见下）。
    → 放行格净增数（新放行减降审；调用方据此改页头 n_auto/n_review，v0.6.2 漏减降审致页头与格数不符）。窗口先整页算好再改格（相邻漏字格互为上下文，边改边算会让窗口变样、键对不上）。"""
    from ..groups.context import WIDTH
    from ..utils.jiazhu_order import sort_by_reading
    store = store if store is not None else _vis_cache().store_
    seq = [r for c in sorted(out, key=lambda c: c.col) for r in sort_by_reading(c.chars)
           if not (r.doubts and "excluded" in r.doubts)]
    todo, adm = [], []
    for i, r in enumerate(seq):
        if r.provenance == "human" or r.channel == "human":
            continue
        if _VIS_RULING_HARD & {d for d in (r.doubts or []) if isinstance(d, str)} or (r.evidence or {}).get("occluded"):
            continue
        (adm if r.admit else todo).append((r, _clf_ctx(seq, amap, i, -1, WIDTH), _clf_ctx(seq, amap, i, 1, WIDTH)))
    n = 0
    # 降审：已放行（非人裁）格的窗口命中 src-1 的 code_conflict 裁定（该码的唯一字≠现放行字，admit_ok=False）→ 降回待审，
    # doubt `src_code_conflict`。从净增数里减掉；放行遍在后，同格不会被本遍降下来又放回去（它已是 admit 才进 adm）。
    for r, left, right in adm:
        v = store.get(_VIS_RULING_GROUP, "src-1", left, right)
        if (not v or v.get("route") != "code_conflict" or v.get("admit_ok") or v.get("conf") != "high"
                or v.get("subclass") != "PUA" or not v.get("char") or v["char"] == r.char
                or (v.get("ref") or "") != ((amap.get(r.id) or (None,))[0] or "")):
            continue
        _demote(r, "src_code_conflict")
        r.evidence = {**(r.evidence or {}), "src_code_conflict": {k: v.get(k) for k in ("char", "why", "cell", "src")}}
        r.admit, r.channel, r.provenance = False, None, ""
        r.doubts = list(dict.fromkeys(list(r.doubts or []) + ["src_code_conflict"]))
        n -= 1
    ovr = p.ruling_override_groups
    extra = frozenset(x.strip() for x in (getattr(p, "vis_ruling_ctx_subclasses", "") or "").split(",") if x.strip())
    specs = tuple((ver, subs | extra) if ver == "ctx-m1" else (ver, subs) for ver, subs in _VIS_RULING_SPECS) if extra else _VIS_RULING_SPECS
    skip_half = getattr(p, "group_flow_llm_skip_half", False) and not getattr(p, "vis_ruling_half", False)
    half_ok = getattr(p, "group_flow_llm_skip_half", False) and getattr(p, "vis_ruling_half", False)
    rget = getattr(store, "get_equiv", store.get)
    loose = getattr(p, "ruling_anchor_loose", False)
    for r, left, right in todo:
        # 当场记下本遍的窗口（裁定键）：产物是整遍跑完的状态，后面几遍放行／降审的邻格会让从产物重算的窗口与这里不同，
        # manager 写终审裁定键、rulings-hits 补键直接用这个（A33 11-20，全唐文 027:59:4:7）。
        r.evidence = {**(r.evidence or {}), "vis_ctx": {"left": left, "right": right,
                                                        "ref": (amap.get(r.id) or (None,))[0] or ""}}
        is_half = (r.id or "")[-1:] in ("a", "b")
        if half_ok and is_half and any(isinstance(d, str) and (d in _VIS_HALF_BAD or d.startswith(("jiazhu_", "split_")))
                                        for d in (r.doubts or [])):
            continue                                 # 半格本身带切分疑点：不放（A22 评估 11-12）
        if skip_half and (r.id or "")[-1:] in ("a", "b"):
            continue                                 # 夹注半格不靠终审裁定放行（等金标证据再开）
        # 精确键没中再查版本等价表（`RulingStore.get_equiv`，GM4／CV4 11-24）；护栏照旧，白名单按目标版本 vt 判
        hit = next(((ver, x) for ver, subs in specs
                    for x in [rget(_VIS_RULING_GROUP, ver, left, right)]
                    if x and x.get("admit_ok") and x.get("conf") == "high" and x.get("char") and not x.get("other")
                    and _ruling_han(x["char"]) and x.get("subclass") in subs), None)
        ref_ = (amap.get(r.id) or (None,))[0]
        if hit is None and cells_sha:
            # 格锚点后备键（GM4／CV4 11-24，裁定键长期方案③）：窗口键都没中 → 格号＋写裁定时 cells_sha＋ref 全对，
            # 且裁定字在库候选里或＝整理本字；其余护栏同上
            if loose:
                ancs = [(ver, subs, store.get_anchor(_VIS_RULING_GROUP, ver, r.id, cells_sha, ref_, left, right, loose=True))
                        for ver, subs in specs]
                cf = [x for _, _, x in ancs if x and x.get("ruling_conflict")]
                if cf:
                    r.evidence = {**(r.evidence or {}), "ruling_conflict": cf[0]["rows"]}   # 同格多条裁定字不同：不放行
                    continue
                hit = next(((ver, x) for ver, subs, x in ancs
                            if x and x.get("admit_ok") and x.get("conf") == "high" and x.get("char") and not x.get("other")
                            and _ruling_han(x["char"]) and x.get("subclass") in subs and _anchor_cand_ok(x["char"], r.id, ref_, mmap)), None)
            else:
                hit = next(((ver, x) for ver, subs in specs
                            for x in [store.get_anchor(_VIS_RULING_GROUP, ver, r.id, cells_sha, ref_, left, right)]
                            if x and x.get("admit_ok") and x.get("conf") == "high" and x.get("char") and not x.get("other")
                            and _ruling_han(x["char"]) and x.get("subclass") in subs and _anchor_cand_ok(x["char"], r.id, ref_, mmap)), None)
        if hit is None and umap and umap.get(r.id):
            # 按字格永久编号 u 查（书级 `ruling_by_u`，CV0 T3 11-24）：窗口键、等价、锚点都没中 → 同册同 u 的裁定（宽松档口径），
            # 裁定字在库候选或＝整理本字；其余护栏同上，ref 一致等照旧在下面核
            ubs = [(ver, subs, store.get_by_u(_VIS_RULING_GROUP, ver, _cell_book(r.id), umap[r.id], left, right)) for ver, subs in specs]
            cf = [x for _, _, x in ubs if x and x.get("ruling_conflict")]
            if cf:
                r.evidence = {**(r.evidence or {}), "ruling_conflict": cf[0]["rows"]}   # 同 u 多条裁定字不同：不放行
                continue
            hit = next(((ver, x) for ver, subs, x in ubs
                        if x and x.get("admit_ok") and x.get("conf") == "high" and x.get("char") and not x.get("other")
                        and _ruling_han(x["char"]) and x.get("subclass") in subs and _anchor_cand_ok(x["char"], r.id, ref_, mmap)), None)
        vt, v = hit if hit else (None, None)
        if not v:
            f = store.get(_VIS_RULING_GROUP, "ctx-m1", left, right)
            if f and f.get("gate") == "ref_lead_fail" and (f.get("ref") or "") == (ref_ or ""):
                r.evidence = {**(r.evidence or {}), "ref_lead_fail": f.get("ref_lead") or {}}   # 终审 ref_lead 证人没过：留审，记下供统计
            continue
        if (v.get("ref") or "") != (ref_ or ""):
            continue                                 # 整理本对位字变了：不是当初看的那一格
        if half_ok and is_half and (v.get("cell") != r.id or v["char"] != ref_):
            continue                                 # 半格：裁定的格号须＝当前格号（重切后不落到别的图），且字＝整理本字（不走白名单越过）
        if ovr is not None and vt == "ctx-m1" and ref_ and v["char"] != ref_ and not _override_ok(ovr, v["char"], ref_):
            continue                                 # 越过整理本：字与整理本字不同属白名单字组 → 留审
        ds = list(r.doubts or [])
        vr = {k: v.get(k) for k in ("char", "conf", "why", "model", "prompt_ver", "cell", "subclass", "route")}
        # 终审 ref_lead 证人放行：via=ref_lead（层、领先量）；ruling_key／ruling_ver 只在非窗口精确命中时有
        vr.update({k: v[k] for k in ("via", "ref_lead", "ruling_key", "ruling_ver") if v.get(k)})
        if v.get("ruling_key") == "u":
            vr.update({"u": v.get("u"), "win_sides": v.get("win_sides")})   # 按 u 命中：u 与前后 2 字哪侧相同
        elif v.get("ruling_key") == "anchor":
            if v.get("win_sides"):
                vr["win_sides"] = v["win_sides"]     # 宽松档：前后 2 字哪侧相同
            else:
                vr["window_diff"] = v.get("window_diff")
        r.evidence = {**(r.evidence or {}), "vis_ruling": vr,
                      "lifted_from": {"char": r.char, "doubts": ds}}
        if half_ok and is_half:
            r.evidence["half"] = True                # 统计用，字形库可据此排除
        r.char, r.admit, r.channel, r.provenance, r.doubts = v["char"], True, "vis_ruling", "match", []
        n += 1
    return n


#: `fold_aspect` 判窄字／宽字的组与字（组 id → (窄字, 宽字)）
_FOLD_ASPECT_PAIRS = {"ry": ("日", "曰")}


def _fold_pass(p, out: list, amap: dict, mmap: dict | None = None, store=None, coord: dict | None = None,
               wh: dict | None = None, dmap: dict | None = None, cells_sha: str | None = None, umap: dict | None = None) -> int:
    """折叠组（`SeedAdmitParams.fold_groups`）：待审格的字组在名单里、整理本字在组内 → 放整理本字。→ 放行数净增。
    护栏（缺省关）：`fold_ruling_first` 有本组裁定先用裁定字；`fold_lib_top_in_group` 库首位须在组内；
    扩展 `fold_coord_ref`（`coord` 由调用方给）：现役对位缺用坐标对位、未入组格按库首位入折叠组。
    字形宽高（`fold_aspect`，`wh` 由调用方给）按 `_FOLD_ASPECT_PAIRS` 判窄字／宽字；`fold_aspect_ctx_veto`（`dmap`＝context_decide）可否决。
    夹注 a/b 半格不处理（原 `fold_jiazhu`／`fold_aspect_jiazhu`／`fold_aspect_pairs`／`fold_aspect_ink` 无书开，2026-11-23 CV4 删）。
    框架与各书标定见 `doc/字组/折叠组.md`。"""
    from ..groups.registry import FLOW_GROUPS
    pairs = _FOLD_ASPECT_PAIRS
    wins: dict = {}
    no_ref = not p.fold_ref_char
    if p.fold_ruling_first or no_ref:
        from ..groups.context import WIDTH
        from ..utils.jiazhu_order import sort_by_reading
        seq = [r for c in sorted(out, key=lambda c: c.col) for r in sort_by_reading(c.chars)
               if not (r.doubts and "excluded" in r.doubts)]
        wins = {r.id: (_clf_ctx(seq, amap, i, -1, WIDTH), _clf_ctx(seq, amap, i, 1, WIDTH)) for i, r in enumerate(seq)}
        store = store if store is not None else _vis_cache().store_
        l3 = _l3_online(p)
    n = 0
    for c in out:
        for r in c.chars or []:
            half = (r.id or "")[-1:] in ("a", "b")
            if r.admit or r.provenance == "human" or r.channel == "human" or half:
                continue
            ds = {d for d in (r.doubts or []) if isinstance(d, str)}
            occ = "occluded" in ds or bool((r.evidence or {}).get("occluded"))
            if (_VIS_RULING_HARD - {"occluded"}) & ds or "excluded" in ds or (occ and not p.fold_occluded):
                continue
            gid = ((r.evidence or {}).get("group") or {}).get("id")
            ref = (amap.get(r.id) or (None,))[0]
            via_coord = False
            if occ:
                # 遮挡格：整理本字与库首位须同在一个折叠组里才归组（整理本字只判归组，不定字，见 `fold_occluded`）
                cand0 = (list(getattr(mmap.get(r.id) if mmap else None, "candidates", None) or [(None, 0.0)]))[0]
                top = cand0[0]
                lax = p.fold_occluded_lib_max_cov is not None and float(cand0[1] or 0.0) < p.fold_occluded_lib_max_cov
                gid = next((g for g in p.fold_groups if g in FLOW_GROUPS and ref in FLOW_GROUPS[g].members
                            and (lax or top in FLOW_GROUPS[g].members)), None)
                if gid is None:
                    continue
            if p.fold_coord_ref:
                if not ref and coord and coord.get(r.id) not in (None, "", *GAP_CHARS):
                    ref, via_coord = coord[r.id], True
                if gid is None and ref:
                    top = (list(getattr(mmap.get(r.id) if mmap else None, "candidates", None) or [(None,)]))[0][0]
                    gid = next((g for g in p.fold_groups if g in FLOW_GROUPS and top in FLOW_GROUPS[g].members
                                and ref in FLOW_GROUPS[g].members), None)
            if gid not in p.fold_groups or gid not in FLOW_GROUPS:
                continue
            mem = FLOW_GROUPS[gid].members
            if not no_ref and (not ref or ref not in mem):
                continue
            if p.fold_lib_top_in_group:
                cands = list(getattr(mmap.get(r.id) if mmap else None, "candidates", None) or [])
                if not cands or cands[0][0] not in mem:
                    continue
            ch, via, extra, veto = None, None, {}, None
            th = p.fold_aspect
            pair = pairs.get(gid)
            ar = None
            if th and pair and pair[0] in mem and pair[1] in mem:
                if wh and r.id in wh:
                    w, h = wh[r.id]
                    ar = w / h if (h and h > 0 and w) else None
            if ar is not None:
                if ar >= th[1]:
                    ch = pair[1]
                elif ar <= th[0]:
                    ch = pair[0]
                if ch is not None:
                    via, extra = "aspect", {"aspect": round(ar, 3)}
                    if p.fold_aspect_ctx_veto is not None:
                        other = pair[0] if ch == pair[1] else pair[1]
                        pr = dict(getattr((dmap or {}).get(r.id), "ranked", None) or []).get(other, 0.0)
                        g_ev = (r.evidence or {}).get("group") or {}
                        gt = next((t for t in g_ev.get("solvers") or [] if t.get("solver") == "ctx"), None) if g_ev.get("id") == gid else None
                        # 组内文意：L1 规则不算（殿本 H01 37 格错 15、史記 06:46「李奇曰」ry-ext-r1 误给日，SJ 11-08）；带概率的（L2）要到阈值
                        g_other = bool(gt and gt.get("char") == other and str(gt.get("why", "")).startswith("agree")
                                       and str(gt.get("via") or "ctx").split(":")[-1] != "ctx_l1"
                                       and (gt.get("p") is None or float(gt["p"]) >= p.fold_aspect_ctx_veto))
                        if pr >= p.fold_aspect_ctx_veto or g_other:
                            # 上下文排名或字组文意解法给了另一个字（名单页「日講官」没有 context_decide 排名，组内文意给日，SJ 11-08）
                            veto = {"aspect": round(ar, 3), "char": ch, "ctx": other, "prob": round(pr, 3),
                                    **({"group_ctx": gt.get("via") or "ctx"} if g_other else {})}
                            ch, via, extra = None, None, {}
            if ch is None and (p.fold_ruling_first or no_ref) and r.id in wins and gid in l3:
                v = getattr(store, "get_equiv", store.get)(gid, l3[gid]["ver"], *wins[r.id])
                if v is None and cells_sha:
                    # 格锚点后备键（裁定键长期方案③）：格号＋写裁定时 cells_sha＋整理本对位字全对，裁定字在库候选或＝对位字
                    aref = (amap.get(r.id) or (None,))[0]
                    if p.ruling_anchor_loose:
                        # 宽松档：只收 high（`_anchor_loose` 里筛）；同格多条字不同记 ruling_conflict 不放行
                        a = store.get_anchor(gid, l3[gid]["ver"], r.id, cells_sha, aref, *wins[r.id], loose=True)
                        if a and a.get("ruling_conflict"):
                            r.evidence = {**(r.evidence or {}), "ruling_conflict": a["rows"]}
                            a = None
                    else:
                        a = store.get_anchor(gid, l3[gid]["ver"], r.id, cells_sha, aref, *wins[r.id])
                    if a and a.get("char") and _anchor_cand_ok(a["char"], r.id, aref, mmap):
                        v = a
                if v is None and umap and umap.get(r.id):
                    # 按字格永久编号 u 查（书级 `ruling_by_u`，CV0 T3 11-24）：宽松档口径（只收 high），裁定字在库候选或＝对位字
                    aref = (amap.get(r.id) or (None,))[0]
                    a = store.get_by_u(gid, l3[gid]["ver"], _cell_book(r.id), umap[r.id], *wins[r.id])
                    if a and a.get("ruling_conflict"):
                        r.evidence = {**(r.evidence or {}), "ruling_conflict": a["rows"]}
                        a = None
                    if a and a.get("char") and _anchor_cand_ok(a["char"], r.id, aref, mmap):
                        v = a
                if v and v.get("char") in mem and v.get("conf") in ("high", "mid") and not v.get("other"):
                    ch, via = v["char"], "ruling"
                    extra = {k: v[k] for k in ("ruling_key", "ruling_ver") if v.get(k)}   # 版本等价／格锚点命中（GM4／CV4 11-24）
                    if v.get("ruling_key") == "u":
                        extra.update({"u": v.get("u"), "win_sides": v.get("win_sides")})
                    elif v.get("ruling_key") == "anchor":
                        if v.get("win_sides"):
                            extra["win_sides"] = v["win_sides"]
                        else:
                            extra["window_diff"] = v.get("window_diff")
            if ch is None and p.fold_ctx_vias:
                g_ev = (r.evidence or {}).get("group") or {}
                t = next((t for t in g_ev.get("solvers") or [] if t.get("solver") == "ctx"), None) if g_ev.get("id") == gid else None
                if (t and t.get("char") in mem and str(t.get("why", "")).startswith("agree")
                        and str(t.get("via") or "ctx").split(":")[-1] in p.fold_ctx_vias and (t.get("strong") or not p.fold_ctx_strong)):
                    ch, via, extra = t["char"], "ctx", {"ctx": t.get("via") or "ctx", **({"strong": True} if t.get("strong") else {})}
            if ch is None:
                if no_ref:
                    fp = {"group": gid, **({"ctx_veto": veto} if veto else {})}
                    r.evidence = {**(r.evidence or {}), "fold_pending": fp}   # 已归组、字待文意
                    continue
                ch, via = ref, "ref"
            fold = {"group": gid, "ref": ref, "via": via, **extra}
            if via_coord:
                fold["coord"] = True
            r.evidence = {**(r.evidence or {}), "fold": fold,
                          "lifted_from": {"char": r.char, "doubts": list(r.doubts or [])}}
            r.char, r.admit, r.channel, r.provenance, r.doubts = ch, True, "fold", "match", []
            n += 1
    return n


def _resolve_data_path(v: str) -> str:
    """书级模型路径：绝对路径照用；相对路径先找数据目录（随中心库走），再找工作区。"""
    from pathlib import Path
    from ..core.workspace import REPO_ROOT, data_root, workspace_root
    q = Path(v).expanduser()
    if q.is_absolute():
        return str(q)
    droot = data_root()
    if droot is not None and (droot / q).exists():
        return str(droot / q)
    return str((workspace_root() or REPO_ROOT) / q)


def _near_p_map(p, ctx, page: int) -> dict:
    """第三步收尾 `glyph_analyzer` 的组内校准概率：{格 id: {字: p}}（只收 p 不为 None 的候选）。没开 `group_flow_near_p` 或没产物 → 空。"""
    if not p.group_flow_near_p or ctx is None:
        return {}
    pf = _opt(ctx, "glyph_analyzer", page)
    if pf is None:
        return {}
    return {rec.id: {c.char: c.p for c in rec.cands if c.p is not None}
            for col in pf.columns for rec in col.chars if any(c.p is not None for c in rec.cands)}


def _entry_config(p):
    """只够 `groups.flow.entry` 用的 `FlowConfig`（4d `group_decision` 出入口归属用；CV4 P3c 2026-11-28）：取值与 `_flow_config` 里同名字段逐个相同，
    但不装文意表、裁定库缓存、字频这些入口不读的东西（`tests/test_group_decision.py` 核对两者入口读的字段一致）。"""
    from ..groups.flow import FlowConfig
    return FlowConfig(groups=tuple(p.group_flow), delta=p.group_flow_delta, min_cov=p.group_flow_min_cov, joint=True,
                      tolerate_extra={g: str(v) for g, v in p.group_flow_tolerate_extra.items()},
                      ref_alias=dict(p.group_flow_ref_alias), ref_free_groups=frozenset(p.group_flow_ref_free),
                      lift_ref_guard=True, provisional=p.group_flow_provisional, coord_outside_skip=True,
                      pv_ref_gap=p.group_flow_pv_ref_gap, pv_ref_cov=p.group_flow_pv_ref_cov,
                      provisional_to=dict(p.group_flow_provisional_to),
                      lift_shape_ref=p._rt_lift_shape_ref(),
                      top1_cov=p.group_flow_top1_cov)


def _flow_config(p, ctx=None, page: int = 0):
    """字组统一流程的 `FlowConfig`（`_group_flow_pass` 与 4d `group_decision` 共用；CV4 P3c 2026-11-28 从 `_group_flow_pass` 原样抽出，不改取值）。"""
    from ..groups.flow import FlowConfig
    from ..groups.freq import load as _load_freq, load_vols as _load_vols
    return FlowConfig(groups=tuple(p.group_flow), delta=p.group_flow_delta, min_cov=p.group_flow_min_cov,
                     top1_cov=p.group_flow_top1_cov, freq_major=p.group_flow_freq_major,
                     freq_vols=_load_vols(p.group_flow_freq) if p.group_flow_freq else {},
                     freq_min_vols=p.group_flow_freq_min_vols,
                     freq_table=_load_freq(p.group_flow_freq) if p.group_flow_freq else {},
                     l2_tables=dict(p.group_flow_tables), l2_models=dict(p.group_flow_models), l2_drift=p.group_flow_l2_drift, joint=True,
                     tolerate_extra={g: str(v) for g, v in p.group_flow_tolerate_extra.items()},
                     lift_shape_ref=p._rt_lift_shape_ref(),
                     ref_alias=dict(p.group_flow_ref_alias),
                     near_p_min={g: ({c: float(x) for c, x in v.items()} if isinstance(v, dict) else float(v)) for g, v in p.group_flow_near_p.items()},
                     near_p=_near_p_map(p, ctx, page),
                     ref_free_groups=frozenset(p.group_flow_ref_free),
                     dissent_keep_form=True, same_writing_keep=frozenset(p.group_flow_same_writing_keep), review_fix_agree=frozenset(p.group_flow_review_fix_agree),
                     dissent_keep=frozenset(p.group_flow_dissent_keep), dissent_margin=p.group_flow_dissent_margin, dissent_l1=frozenset(p.group_flow_dissent_l1), ctx_agree=frozenset(p.group_flow_ctx_agree),
                     ref_pair=frozenset(p.group_flow_ref_pair), ref_pair_margin=p.group_flow_ref_pair_margin, ref_pair_coord=p.group_flow_ref_pair_coord,
                     lift_ref_veto=frozenset(p.group_flow_lift_ref_veto),
                     abstain_ref_ok=p._rt_abstain_ref_ok(),
                     shape_ref_ok=p._rt_shape_ref_ok(),
                     l3_online=_l3_online(p), l3_model=p.group_flow_llm_model, l3_effort=p.group_flow_llm_effort,
                     l3_skip_half=p.group_flow_llm_skip_half, ruling_first=frozenset(p.group_flow_ruling_first), l3_panel=tuple(p.group_flow_llm_panel), l3_panel_groups=tuple(p.group_flow_llm_panel_groups),
                     vis_model=(p.group_flow_llm_model if p.group_flow_vis and p.group_flow_llm_model else None),
                     vis_cache=_vis_cache(),
                     lift_ref_guard=True, provisional=p.group_flow_provisional,
                     coord_outside_skip=True,
                     provisional_to=dict(p.group_flow_provisional_to),
                     pv_ref_gap=p.group_flow_pv_ref_gap, pv_ref_cov=p.group_flow_pv_ref_cov,
                     # 文意 L2 表的键按码位归一再比：邻格放行字／整理本字只差书级码位时不算上下文变了
                     canon=(ctx.book.canonical_char if (ctx is not None and ctx.book.codepoints) else None))


def _group_flow_pass(p, out: list, amap: dict, mmap: dict, ctx=None, page: int = 0,
                     patch_missing: dict | None = None) -> int:
    """字组统一流程（`SeedAdmitParams.group_flow`）：见 `groups/flow.py`。→ 放行数净增（补放减降级）。"""
    from ..groups.context import WIDTH
    from ..groups.flow import FlowConfig, group_flow_pass
    from ..groups.freq import load as _load_freq, load_vols as _load_vols
    from ..groups.registry import FLOW_GROUPS as GROUPS
    from ..utils.jiazhu_order import sort_by_reading
    # 读序展平，剔除排除名单格（与建 L2 表的 `research/m7/ctx/l2_make_book.py` 同一取法，表键才对得上）
    seq = [r for c in sorted(out, key=lambda c: c.col) for r in sort_by_reading(c.chars)
           if not (r.doubts and "excluded" in r.doubts)]
    # 2026-10-31（A24 查 ctx_l2 没挂上）：本进程记一次文意各层的挂载情况（L2 小头、L3 在线、密钥有无），
    # 日志里一眼看得出 L2 小头／L3 在线有没有进来
    if not _FLOW_MOUNT_LOGGED:
        _FLOW_MOUNT_LOGGED.append(True)
        import os
        _log.warning("文意挂载：L2 小头 %s；L3 在线 %s；GUJI_ANTHROPIC_API_KEY %s", sorted(p.group_flow_models) or "无",
                     sorted(_l3_online(p)) or "无", "已设" if os.environ.get("GUJI_ANTHROPIC_API_KEY") else "未设")
    cfg = _flow_config(p, ctx, page)

    def blocked(r) -> bool:
        m = mmap.get(r.id)
        guard = getattr(m, "guard", None)
        # 形近护栏（匹配器 `never_match`／`conflict`、疑问 `near_form`）说的正是「几个字形近、字形定不了」——
        # 落在字组里的格本来就该归字组判，不当硬护栏（补放时 `flow.entry` 仍要求紧咬的候选都在组里）。
        if guard in _GROUP_FLOW_OWN_GUARDS:
            guard = None
        ds = [d for d in (r.doubts or []) if isinstance(d, str) and d not in _GROUP_FLOW_OWN_DOUBTS]
        # 异体形近规则先于印章：遮挡不当硬护栏（放行后核对见下）；写法待定（Z06）交给组的刻形解法定形，定不了仍留 form_open
        ds = [d for d in ds if d not in ("occluded", "form_open")]
        return _hard_blocked(ds, guard) or any(d in _GROUP_FLOW_HARD for d in ds)

    def cands_of(cid: str):
        m = mmap.get(cid)
        return list(m.candidates or []) if m is not None else []
    patch_fn = None
    if any(GROUPS[g].flow.needs_patch for g in p.group_flow):
        slots = {r.id: (c.col, r.slot, r.sub) for c in out for r in c.chars or []}
        recs = {r.id: r for c in out for r in c.chars or []}
        miss = patch_missing if patch_missing is not None else {}

        def patch_fn(cid: str):
            col, slot, sub = slots[cid]
            try:
                return _C._page_patch(ctx, page, col, slot, sub)
            except PatchUnavailable:
                if p.patch_missing != "skip":
                    raise
                miss.setdefault(cid, []).append("group_flow")
                recs[cid].evidence = {**(recs[cid].evidence or {}), "patch_missing": list(miss[cid])}
                return None
    canon = ctx.book.canonical_char if ctx is not None else (lambda c: c)
    # 遮挡格先留底：字组流程放行的字不等于默认字（整理本字）时退回（印章底下字形类解法不可靠）
    occ_snap = ({r.id: (r, r.admit, r.channel, r.provenance, r.char, list(r.doubts or []), dict(r.evidence or {}))
                 for r in seq if (r.evidence or {}).get("occluded") and not r.admit})
    res = group_flow_pass(seq, amap, cands_of, blocked, cfg,
                          ctx_fn=lambda s, i, step: _clf_ctx(s, amap, i, step, WIDTH),
                          patch_fn=patch_fn, canon=canon,
                          veto_refs=coord_refs(_opt(ctx, "align_ref", page)) if ctx is not None else None)
    net = res.lifted - res.demoted
    for rid, (r, admit0, ch0, pv0, char0, doubts0, ev0) in occ_snap.items():
        if not r.admit:                       # 没放成：原样退回，免得字组的复核疑问（`_LANE_HARD`）拦掉后面的 R5
            r.doubts, r.evidence = doubts0, ev0
            continue
        if r.char == char0:
            r.evidence = {**(r.evidence or {}), "occluded_variant_first": "group_flow"}
            continue
        r.admit, r.channel, r.provenance, r.char, r.doubts, r.evidence = admit0, ch0, pv0, char0, doubts0, ev0
        net -= 1
    return net


@lru_cache(maxsize=4)
def _human_relabeled_at(db_path: str) -> dict[str, str]:
    """库内审阅改标（`glyph_audit relabel`）重进的人裁刻例 → 入库时刻。`{裸 id: admitted_at}`。

    给 `bindings.rebind_library_shapes` 判「作废之后又改标重进」用：只认 `evidence.via == "glyph_audit"`，
    旧 confirm 事件重放进库的不算（那是被作废的旧裁决）。"""
    import json
    import sqlite3
    from pathlib import Path
    if not Path(db_path).exists():
        return {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        rows = conn.execute("SELECT instance_id, evidence, admitted_at FROM admissions "
                            "WHERE provenance='human' AND instance_id LIKE 'v2:%' "
                            "AND evidence LIKE '%glyph_audit%'").fetchall()
        conn.close()
    except sqlite3.Error:
        return {}
    out: dict[str, str] = {}
    for iid, ev, at in rows:
        try:
            via = (json.loads(ev) or {}).get("via") if ev else None
        except (TypeError, ValueError):
            via = None
        if via == "glyph_audit" and at:
            out[iid[3:]] = str(at)
    return out


@lru_cache(maxsize=4)
def _human_shapes(db_path: str) -> dict[str, str]:
    """字形库里人裁过的位 → 人裁的**字形**。`{裸 id: shape}`（去掉 v2: 前缀）。

    取 `provenance='human'` 的 admissions，字形从 glyphs 经 exemplars 取——
    `admissions.char` 存的是**释读**，己/已/巳 那三个字它与字形会分岔，
    拿它当字形会把「刻 巳 读 已」写成「刻 已」（09-06 那批 62 条脏数据就是这么来的）。

    ## ⚠️ 人裁会**过期**：切分改了，这一格就不是当初看的那一格

    「人裁一票定案」的前提是那一格没变。2026-09-08~11 那几批裁完之后 Step2/Step3 改过多轮
    （去框、候选池、U-Net 裁判），格重新分了、slot 号整体偏移，旧裁决就钉在了错误的格上：
    p75 列1 实测人裁 slot4=用 / 9=自 / 12=已，而重切后这三格的图是 互 / 左 / 言（逐格看图核对过，
    与整理本一致）。一旦钉住，`human` 压过库匹配与上下文，**整段跟着错**，且没有任何报错。

    vol02 全书查出 61 条这种「与列内上一位重字」的人裁位，撤掉其中与整理本不一致的 56 条后，
    全书一致率 97.43% → 97.61%、`sub.other` 335 → 288。撤法是把 `provenance` 改成
    `human_stale_<日期>`（不删账，本函数只认 `'human'`）。

    **这是个反复会犯的坑**：只要切分再改一次，现有人裁就可能再过期一批。检测签名见
    `scripts/check_stale_human.py`（人裁位与上一位重字 → 疑似错位），跑批后应该定期跑一次。

    ## ⚠️ 只认 `v2:` 前缀，v1 的记录一条都不能要

    库里 1,925 条人裁有 **1,021 条是 v1 的 id**（`book:page:col:idx`，idx 从 0、含
    margin 格），与 v2 的 `book:page:col:slot`（slot 从 1）**长得一模一样但指的不是
    同一格**——这正是 `glyphdb_admit` 当初给 v2 加前缀要隔离的东西
    （见该消费者 docstring「v2 的 id 必须加前缀，否则会污染 15332 条已有记录」）。
    第一版这里去掉前缀后不加区分地收，vol01 判据 A 当场从 100% 掉到 94.70%：
    `vol01:4:1:10` 判「編」而金标「三」，整列错开。
    """
    import sqlite3
    from pathlib import Path

    from ..feedback.mojibake import is_legal_shape
    if not Path(db_path).exists():
        return {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    try:
        from ..clustering.glyph_fp import HUMAN_SQL      # 与 human_fingerprint 同一条查询
        rows = conn.execute(HUMAN_SQL).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    # 字形字段合法性校验（2026-09-27，H 道乱码普查）：`glyphdb_admit` 写入口自
    # `b162e64` 起已经挡乱码（单字校验），但这道闸是那次改动之后才加的——库里
    # 可能留着更早年代写进去的坏数据（这里同样只挡、不吞：跳过并记 warning，
    # 不让老坏数据悄悄消失）。见 `feedback/mojibake.py`。
    out: dict[str, str] = {}
    for iid, ch in rows:
        if not ch:
            continue
        if not is_legal_shape(ch):
            _log.warning("_human_shapes: %s 字形字段不合法，跳过：%r", iid, ch)
            continue
        out[iid[3:]] = ch
    return out
