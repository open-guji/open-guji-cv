"""C1 进库准入（`seed_admit`）的字形判官各遍（rr／wu／hou／part／pair_shape、stroke_veto、book_knn、near_knn；CV4 整理 PR3c 2026-11-26 从 seed_admit.py 原样搬来）。
"""

from __future__ import annotations

from . import seed_admit_common as _C
from .seed_admit_common import (  # noqa: F401
    PatchUnavailable,
    _HOU,
    _NEAR_CODES,
    _RR,
    _RR_SHAPE_HARD,
    _WU,
    _demote,
    _direct_variant_edge,
)


def _rr_shape_pass(p, out: list, amap: dict, ctx=None, page: int = 0, patch_missing: dict | None = None) -> int:
    """入人八 书级刻形判法（`groups.rr_shape`，`SeedAdmitParams.group_flow_rr_shape`）。紧接 group_flow。→ 放行数净增。

    - 待审格（字组 rr 的格，或库首位／整理本是 人入八）：刻形给字 → 放行成该字（channel `rr_shape`），不看整理本；
    - 已放行的 人入八 格：刻形给了组里另一个字 → 改字（`evidence.fixed_from` 留原字）；刻形弃权 → 不动；
    - 人裁格、硬护栏格不碰；刻形弃权（组外字、几何不明、分差小）的待审格照旧送审。
    sheldon 2026-11-02 定「字形说了算，越过整理本」（全唐文；模型按册留出 对 2,445 错 0 弃 24）。"""
    from ..groups import rr_shape
    model = rr_shape.load(p.group_flow_rr_shape)
    miss = patch_missing if patch_missing is not None else {}
    near_on = "rr_shape" in (getattr(p, "group_flow_near_from_3b", None) or ()) and ctx is not None
    near = _near_from_3b(ctx, page, "rr_shape", p.group_flow_rr_shape) if near_on else {}
    alt = ctx.alt_cols(page) if near_on and hasattr(ctx, "alt_cols") else frozenset()
    tally = {"3b": 0, "local": 0, "alt": 0}
    delta = 0
    for c in out:
        for r in c.chars or []:
            ev = r.evidence or {}
            if r.provenance == "human" or r.channel == "human":
                continue
            ds = list(r.doubts or [])
            if any(d in _RR_SHAPE_HARD or d.startswith("护栏:") for d in ds) or ev.get("guard") in ("never_match", "conflict", "timeout"):
                continue
            gid = (ev.get("group") or {}).get("id")
            ref = (amap.get(r.id) or (None,))[0]
            if r.admit:
                if r.char not in _RR:
                    continue
            elif not (gid == "rr" or r.char in _RR or ref in _RR):
                continue
            v = near.get(r.id) if c.col not in alt else None
            if v is not None:
                tally["3b"] += 1
            else:
                if near_on:
                    tally["alt" if c.col in alt else "local"] += 1
                try:
                    img = _C._page_patch(ctx, page, c.col, r.slot, r.sub)
                except PatchUnavailable:
                    if p.patch_missing != "skip":
                        raise
                    miss.setdefault(r.id, []).append("rr_shape")
                    continue
                v = rr_shape.judge(img, model)
            trail = {k: v[k] for k in ("char", "why", "nn", "score", "geo") if k in v}
            if v["char"] is None:
                if not r.admit:
                    r.evidence = {**ev, "rr_shape": trail}
                continue
            if r.admit:
                if v["char"] != r.char:
                    r.evidence = {**ev, "rr_shape": trail, "fixed_from": {"channel": r.channel, "char": r.char}}
                    r.char, r.channel = v["char"], "rr_shape"
                continue
            r.evidence = {**ev, "rr_shape": trail, "lifted_from": {"char": r.char, "doubts": ds}}
            r.char, r.admit, r.channel, r.provenance, r.doubts = v["char"], True, "rr_shape", "match", []
            delta += 1
    if near_on and hasattr(ctx, "log"):
        _log_tally(ctx, page, "rr_shape", tally)
    return delta


def _log_tally(ctx, page: int, method: str, tally: dict) -> None:
    ctx.log(f"seed_admit p{page}: {method} 判法结果 读 3b {tally['3b']}｜本地现算：3b 没触发 {tally['local']}、"
            f"备选切法列 {tally['alt']}")


def _near_from_3b(ctx, page: int, method: str, model_path: str) -> dict:
    """3b `glyph_near` 里某个看图方法的原样判法结果：{格 id: 证据（去掉 `method` 键）}（CV4 11-28，第四步重构 4d 接 3b）。

    只收主切法格（3b 只算主切法；备选切法列调用方退回本地现算）、证据里没有 `error` 的格。
    3b 用的模型必须与本步书级参数指的是同一份（比 `near_methods.method_fingerprint`），不一致报错，不混用。
    读不到 3b 产物（没跑、没开组）→ 空表，全部本地现算。"""
    try:
        pn = ctx.product("glyph_near", page)
    except Exception:                      # noqa: BLE001 —— 可选上游：没有就全部本地现算
        return {}
    got: dict = {}
    for cn in getattr(pn, "columns", None) or []:
        for nr in cn.chars or []:
            for mo in nr.methods or []:
                if mo.method.split(":", 1)[0] != method:
                    continue
                ev = mo.evidence or {}
                if "error" in ev or "why" not in ev:
                    continue
                got[nr.id] = {k: v for k, v in ev.items() if k != "method"}
    if got:
        from ..groups.near_methods import method_fingerprint
        want = method_fingerprint(method, model_path)
        have = {x.split(":", 1)[1] for x in (pn.methods_sha or "").split(";") if ":" in x}
        if want not in have:
            raise ValueError(f"seed_admit p{page}：3b glyph_near 的 {method} 模型与书级参数指的不是同一份"
                             f"（本步 {want}；3b {pn.methods_sha or '空'}），先让两边指同一个模型再跑")
    return got


def _wu_shape_pass(p, out: list, amap: dict, ctx=None, page: int = 0, patch_missing: dict | None = None) -> int:
    """嗚鳴 书级刻形判法（`groups.wu_shape`，`SeedAdmitParams.group_flow_wu_shape`）。紧接 rr_shape。→ 放行数净增。

    同 `_rr_shape_pass`：刻形说了算、越过整理本与文意（sheldon 11-13「嗚/鳴 归形近不同义组，拆部件 100% 自动区分」，
    11-14 嗚鳴17格按刻形点）。只判本格字（库首位）是 嗚鳴 的格：待审格刻形给字 → 放行（channel `wu_shape`）；
    整理本／字组／库前几名里有 嗚鳴 都不算（总览 11-14 审：对不齐时格里可能是别的字；全唐文 t1 实测库前 3 名放进来的 21 格
    全是 鴨鵝鳩塢鴟 这类右边也是 鳥／烏 的字，网只看右半、照样给 p≈1，3 格错放成 鳴）；
    已放行的 嗚鳴 格刻形给了另一个字 → 改字（`evidence.fixed_from`）；弃权不动；人裁格、硬护栏格不碰。"""
    from ..groups import wu_shape
    model = wu_shape.load(p.group_flow_wu_shape)
    miss = patch_missing if patch_missing is not None else {}
    near_on = "wu_shape" in (getattr(p, "group_flow_near_from_3b", None) or ()) and ctx is not None
    near = _near_from_3b(ctx, page, "wu_shape", p.group_flow_wu_shape) if near_on else {}
    alt = ctx.alt_cols(page) if near_on and hasattr(ctx, "alt_cols") else frozenset()
    tally = {"3b": 0, "local": 0, "alt": 0}
    delta = 0
    for c in out:
        for r in c.chars or []:
            ev = r.evidence or {}
            if r.provenance == "human" or r.channel == "human":
                continue
            ds = list(r.doubts or [])
            if any(d in _RR_SHAPE_HARD or d.startswith("护栏:") for d in ds) or ev.get("guard") in ("never_match", "conflict", "timeout"):
                continue
            if r.char not in _WU:
                continue
            v = near.get(r.id) if c.col not in alt else None
            if v is not None:
                tally["3b"] += 1
            else:
                if near_on:
                    tally["alt" if c.col in alt else "local"] += 1
                try:
                    img = _C._page_patch(ctx, page, c.col, r.slot, r.sub)
                except PatchUnavailable:
                    if p.patch_missing != "skip":
                        raise
                    miss.setdefault(r.id, []).append("wu_shape")
                    continue
                v = wu_shape.judge(img, model)
            if v["char"] is None:
                if not r.admit:
                    r.evidence = {**ev, "wu_shape": v}
                continue
            if r.admit:
                if v["char"] != r.char:
                    r.evidence = {**ev, "wu_shape": v, "fixed_from": {"channel": r.channel, "char": r.char}}
                    r.char, r.channel = v["char"], "wu_shape"
                continue
            r.evidence = {**ev, "wu_shape": v, "lifted_from": {"char": r.char, "doubts": ds}}
            r.char, r.admit, r.channel, r.provenance, r.doubts = v["char"], True, "wu_shape", "match", []
            delta += 1
    if near_on and hasattr(ctx, "log"):
        _log_tally(ctx, page, "wu_shape", tally)
    return delta


def _hou_shape_pass(p, out: list, ctx=None, page: int = 0, patch_missing: dict | None = None,
                    only_unjudged: bool = False) -> int:
    """候𠋫 书级刻形判法（`groups.hou_shape`，`SeedAdmitParams.group_flow_hou_shape`）。紧接 wu_shape。→ 0（只改字、不改放行）。

    全唐文书级码位 候→𠋫（照刻形），可书里也刻真 候（033 册起居多；sheldon 11-19 点选 182 格定标签）。
    只碰**已放行**、字是 候／𠋫 的非人裁格：刻形给了字就照录（`evidence.hou_shape`），给 候 的格到最后码位归一那步不归 𠋫
    （`_codepoint_exempt`），改了字记 `evidence.fixed_from`。待审格不补放：库首位是 候𠋫 的待审格可能其实是 侯（亻右边也只一短笔），
    几何量分不开 侯／候，补放留给原通道与人审。弃权（量在中间）不动。"""
    from ..groups import hou_shape
    model = hou_shape.load(p.group_flow_hou_shape)
    miss = patch_missing if patch_missing is not None else {}
    near_on = "hou_shape" in (getattr(p, "group_flow_near_from_3b", None) or ()) and ctx is not None
    near = _near_from_3b(ctx, page, "hou_shape", p.group_flow_hou_shape) if near_on else {}
    alt = ctx.alt_cols(page) if near_on and hasattr(ctx, "alt_cols") else frozenset()
    tally = {"3b": 0, "local": 0, "alt": 0}
    for c in out:
        for r in c.chars or []:
            if not r.admit or r.char not in _HOU or r.provenance == "human" or r.channel == "human":
                continue
            if only_unjudged and "hou_shape" in (r.evidence or {}):
                continue
            v = near.get(r.id) if c.col not in alt else None
            if v is not None:
                tally["3b"] += 1
            else:
                if near_on:
                    tally["alt" if c.col in alt else "local"] += 1
                try:
                    img = _C._page_patch(ctx, page, c.col, r.slot, r.sub)
                except PatchUnavailable:
                    if p.patch_missing != "skip":
                        raise
                    miss.setdefault(r.id, []).append("hou_shape")
                    continue
                v = hou_shape.judge(img, model)
            ev = r.evidence or {}
            if v["char"] is None:
                r.evidence = {**ev, "hou_shape": v}
                continue
            if v["char"] != r.char:
                ev = {**ev, "fixed_from": {"channel": r.channel, "char": r.char}}
                r.char = v["char"]
            r.evidence = {**ev, "hou_shape": v}
    if near_on and hasattr(ctx, "log"):
        _log_tally(ctx, page, "hou_shape", tally)
    return 0


def _part_shape_pass(p, out: list, amap: dict, ctx=None, page: int = 0, patch_missing: dict | None = None) -> int:
    """书级部件刻形判法（`groups.part_shape`，`SeedAdmitParams.group_flow_part_shape`）。紧接 wu_shape。→ 放行数净增。

    语义同 `_wu_shape_pass`（刻形说了算、只判本格字＝库首位落在某一对里的格、整理本／字组／库前几名不作数）：
    待审格刻形给字 → 放行（channel `part_shape`）；已放行格刻形给了这一对里的另一个字 → 改字（`evidence.fixed_from`）；
    弃权不动；人裁格、硬护栏格不碰。一个模型挂多对，按本格字找对。"""
    from ..groups import part_shape
    model = part_shape.load(p.group_flow_part_shape)
    miss = patch_missing if patch_missing is not None else {}
    delta = 0
    for c in out:
        for r in c.chars or []:
            ev = r.evidence or {}
            if r.provenance == "human" or r.channel == "human":
                continue
            ds = list(r.doubts or [])
            if any(d in _RR_SHAPE_HARD or d.startswith("护栏:") for d in ds) or ev.get("guard") in ("never_match", "conflict", "timeout"):
                continue
            if r.char not in model["_chars"]:
                continue
            pair = part_shape.pair_of(model, r.char)
            try:
                img = _C._page_patch(ctx, page, c.col, r.slot, r.sub)
            except PatchUnavailable:
                if p.patch_missing != "skip":
                    raise
                miss.setdefault(r.id, []).append("part_shape")
                continue
            v = part_shape.judge(img, pair)
            if v["char"] is None:
                if not r.admit:
                    r.evidence = {**ev, "part_shape": v}
                continue
            if r.admit:
                if v["char"] != r.char:
                    r.evidence = {**ev, "part_shape": v, "fixed_from": {"channel": r.channel, "char": r.char}}
                    r.char, r.channel = v["char"], "part_shape"
                continue
            r.evidence = {**ev, "part_shape": v, "lifted_from": {"char": r.char, "doubts": ds}}
            r.char, r.admit, r.channel, r.provenance, r.doubts = v["char"], True, "part_shape", "match", []
            delta += 1
    return delta


def _pair_shape_pass(p, out: list, amap: dict, ctx=None, page: int = 0, patch_missing: dict | None = None,
                     coord: dict | None = None, model_path: str | None = None, veto: bool = False,
                     nm_5b: dict | None = None) -> int:
    """书级两字刻形二选一（`groups.pair_shape`，`SeedAdmitParams.group_flow_pair_shape`）。紧接 rr_shape。→ 放行数净增。

    只补放待审格：库首位或整理本字是模型两个字之一；模型给的字必须＝整理本字或＝库首位（不引入第三个字、不单凭整理本）。
    整理本（或坐标对位）是这两字以外的第三个字时不判（全唐文 r16：库首位王、整理本三，被王玉模型放成王）。
    已放行格不动，人裁格、硬护栏格不碰；模型弃权（组外、字块怪、分值低）的格照旧送审。通道 `pair_shape`，
    `evidence.pair_shape` 留 nn／score。

    `model_path`：多对模型（`group_flow_pair_shapes`）逐对调用时给；缺省读 `group_flow_pair_shape`。
    `veto`：已放行（非人裁）且放行字是这两字之一的格，模型（带 `veto_thr`）以 |分值|≥veto_thr 判成另一字、组外判别也过 →
    降回待审，doubt `pair_shape_veto`（全唐文 r15：库＋整理本一起把「荆山之玉」「衞伯玉」放成王）。→ 放行数净增（降的算负）。
    `nm_5b`：{字位: 5-b 首位}（`group_flow_pair_shape_nm_5b` 开时给）。护栏 never_match 的格 5-b 首位落在这一对里也判，
    `evidence.pair_shape.nm_5b` 留 5-b 首位；None＝never_match 格照旧不碰。"""
    from ..groups import pair_shape
    model = pair_shape.load(model_path or p.group_flow_pair_shape)
    pair = frozenset(model["chars"])
    miss = patch_missing if patch_missing is not None else {}
    veto_thr = model.get("veto_thr") if veto else None
    delta = 0
    for c in out:
        for r in c.chars or []:
            if r.provenance == "human" or r.channel == "human":
                continue
            if r.admit:
                if not veto_thr or r.char not in pair:
                    continue
                try:
                    img = _C._page_patch(ctx, page, c.col, r.slot, r.sub)
                except PatchUnavailable:
                    if p.patch_missing != "skip":
                        raise
                    miss.setdefault(r.id, []).append("pair_shape")
                    continue
                v = pair_shape.judge(img, model)
                if v["char"] and v["char"] != r.char and abs(v.get("score") or 0.0) >= veto_thr:
                    _demote(r, "pair_shape_veto")
                    r.evidence = {**(r.evidence or {}), "pair_shape": {k: v[k] for k in ("char", "why", "score", "other", "margin", "top") if k in v}}
                    r.admit, r.channel, r.provenance = False, None, ""
                    r.doubts = list(r.doubts or []) + ["pair_shape_veto"]
                    delta -= 1
                continue
            ev = r.evidence or {}
            ds = list(r.doubts or [])
            # 形近护栏 conflict（库首位与整理本两字相冲）正是本解法要判的格，放开；never_match／timeout 及其他硬疑问不碰
            # （`nm_5b` 给了且 5-b 首位落在这一对里时 never_match 也判）
            nm = nm_5b is not None and ev.get("guard") == "never_match" and nm_5b.get(r.id) in pair
            if any(d in _RR_SHAPE_HARD or d.startswith("护栏:") and d != "护栏:conflict"
                   and not (nm and d == "护栏:never_match") for d in ds) \
                    or (ev.get("guard") in ("never_match", "timeout") and not nm):
                continue
            if "human_unbound" in ev or "human_unbound" in ds:      # 人裁绑丢的格不碰（人裁与对位的冲突交人审）
                continue
            ref = (amap.get(r.id) or (None,))[0] or (coord or {}).get(r.id)     # 现役对位缺这一格时用坐标对位字
            if r.char not in pair and ref not in pair:
                continue
            if ref and ref not in pair:                               # 整理本是第三个字（三/王）：争的不是这两字，不判
                continue
            gp = (ev.get("group") or {}).get("pick")                  # 字组流程已给了别的字（解算有分歧）：不越过
            if gp and gp in pair:
                continue
            try:
                img = _C._page_patch(ctx, page, c.col, r.slot, r.sub)
            except PatchUnavailable:
                if p.patch_missing != "skip":
                    raise
                miss.setdefault(r.id, []).append("pair_shape")
                continue
            v = pair_shape.judge(img, model)
            trail = {k: v[k] for k in ("char", "why", "nn", "score", "other", "margin", "top") if k in v}
            if nm:
                trail["nm_5b"] = nm_5b.get(r.id)
            if v["char"] is None or v["char"] not in (ref, r.char):
                r.evidence = {**ev, "pair_shape": trail}
                continue
            r.evidence = {**ev, "pair_shape": trail, "lifted_from": {"char": r.char, "doubts": ds}}
            r.char, r.admit, r.channel, r.provenance, r.doubts = v["char"], True, "pair_shape", "match", []
            delta += 1
    return delta


def _stroke_veto_pass(p, out: list, ctx=None, page: int = 0, patch_missing: dict | None = None) -> int:
    """笔画反向护栏（`SeedAdmitParams.stroke_veto`，`groups.stroke_veto`）。→ 降回待审的格数。

    已放行、非人裁、放行字在模型某组里的格：笔画判给了类且≠放行字的类 → 降审，doubt `stroke_veto`。
    笔画弃权不动；字块读不到按 `patch_missing` 处理（skip 时记进 patch_missing、不动）。"""
    from ..groups import stroke_veto as sv
    model = sv.load(p.stroke_veto)
    miss = patch_missing if patch_missing is not None else {}
    n = 0
    for c in out:
        for r in c.chars or []:
            if not r.admit or r.provenance == "human" or r.channel == "human":
                continue
            gid, gm = sv.group_of(model, r.char or "")
            if gm is None or (gm.get("channels") and r.channel not in gm["channels"]):
                continue
            try:
                img = _C._page_patch(ctx, page, c.col, r.slot, r.sub)
            except PatchUnavailable:
                if p.patch_missing != "skip":
                    raise
                miss.setdefault(r.id, []).append("stroke_veto")
                continue
            v = sv.judge(img, gm)
            if v["cls"] is None or v["cls"] == gm["classes"][r.char]:
                continue
            _demote(r, "stroke_veto")
            r.evidence = {**(r.evidence or {}), "stroke_veto": {"group": gid, "cls": v["cls"], "llr": v.get("llr"), "x": v.get("x")}}
            r.admit, r.channel, r.provenance = False, None, ""
            r.doubts = list(r.doubts or []) + ["stroke_veto"]
            n += 1
    return n


def _book_knn_pass(p, out: list, amap: dict, ctx=None, page: int = 0, patch_missing: dict | None = None) -> int:
    """字组书级刻形近邻判法（`groups.book_knn`，`SeedAdmitParams.group_flow_book_knn`）。紧接 group_flow。→ 新放行格数。

    只看有库的组里仍待审的格：A 档（近邻票多、距离比够小）给字放行；B 档（票、比稍松）须整理本对位字同字才放（两证）。
    已放行格不动；人裁格、硬护栏格不碰（同 `_rr_shape_pass`）。通道 `book_knn`，`evidence.book_knn` 留票数、距离比与档。"""
    from ..groups import book_knn
    miss = patch_missing if patch_missing is not None else {}
    delta = 0
    for c in out:
        for r in c.chars or []:
            if r.admit or r.provenance == "human" or r.channel == "human":
                continue
            ev = r.evidence or {}
            gid = (ev.get("group") or {}).get("id")
            if gid not in p.group_flow_book_knn:
                continue
            ds = list(r.doubts or [])
            if any(d in _RR_SHAPE_HARD or d.startswith("护栏:") for d in ds) or ev.get("guard") in ("never_match", "conflict", "timeout"):
                continue
            try:
                img = _C._page_patch(ctx, page, c.col, r.slot, r.sub)
            except PatchUnavailable:
                if p.patch_missing != "skip":
                    raise
                miss.setdefault(r.id, []).append("book_knn")
                continue
            ref = (amap.get(r.id) or (None,))[0]
            v = book_knn.judge(img, book_knn.load(p.group_flow_book_knn[gid]), ref)
            trail = {k: v[k] for k in ("char", "why", "tier", "pick", "votes", "ratio", "nn") if k in v}
            if v["char"] is None:
                r.evidence = {**ev, "book_knn": trail}
                continue
            r.evidence = {**ev, "book_knn": trail, "lifted_from": {"char": r.char, "doubts": ds}}
            r.char, r.admit, r.channel, r.provenance, r.doubts = v["char"], True, "book_knn", "match", []
            delta += 1
    return delta


def _near_knn_pass(p, out: list, amap: dict, mmap: dict, ctx=None, page: int = 0,
                   patch_missing: dict | None = None, stage: str = "near") -> int:
    """形近护栏格的书级刻形近邻（`groups.near_knn`，`SeedAdmitParams.group_flow_near_knn`）。紧接 book_knn。→ 新放行格数。

    只补放待审格：形近护栏（guard conflict／never_match、疑问 near_form 等）或字组未定的格。候选＝本格字、整理本对位字、
    库首位（不引入第三个字）；候选里有模型 `skip_chars`（己已巳）、或两候选互为异体（码位线管）、或字组在 `skip_groups`、
    或字组已给了别的字 → 不碰。人裁格、硬疑问格不碰。通道 `near_knn`，`evidence.near_knn` 留票数、距离比、全库近邻。
    `near_knn_gap` 开时另收「库没把握、库首位≠整理本」的格（见该参数说明，出口闸＝等于整理本或同码位／异体组）。
    `stage`：`near`（紧接 book_knn，只判护栏格／字组格）；`gap`（各补放通道之后，只判 near_knn_gap 的格——
    排在前面会把 rare_ref／witness3 等本就会放、字也相同的两万多格抢成 near_knn 通道，全唐文 r10，11-05 挪后）。"""
    from ..groups import near_knn
    from ..groups.edge_pairs import _exclude as _edge_exclude
    model = near_knn.load(p.group_flow_near_knn)
    miss = patch_missing if patch_missing is not None else {}
    canon = ctx.book.canonical_char if (p.near_knn_gap and ctx is not None and ctx.book.codepoints) else None
    top3: list = []
    delta = 0
    for c in out:
        for r in c.chars or []:
            if r.admit or r.provenance == "human" or r.channel == "human":
                continue
            ev = r.evidence or {}
            ds = list(r.doubts or [])
            if "human_unbound" in ev or "human_unbound" in ds:
                continue
            if any(d in _RR_SHAPE_HARD for d in ds) or ev.get("guard") == "timeout":
                continue
            grp = ev.get("group") or {}
            near = ev.get("guard") in ("conflict", "never_match") or bool(_NEAR_CODES & set(ds))
            ref = (amap.get(r.id) or (None,))[0]
            m = mmap.get(r.id)
            gap = False
            if not (near or grp.get("id")):
                top3 = [c for c, _ in (getattr(m, "candidates", None) or [])[:3]] if stage == "gap" else []
                if not (ref and top3 and top3[0] != ref):
                    continue
                gap = True
            elif stage == "gap":
                continue
            if grp.get("id") in model["skip_groups"] or grp.get("pick"):
                continue
            cands = [x for x in dict.fromkeys((r.char, ref, *(top3 if gap else (getattr(m, "char", None),)))) if x]
            if len(cands) < 2 or model["skip_chars"] & set(cands):
                continue
            if not gap and any(_direct_variant_edge(a, b) and frozenset((a, b)) not in _edge_exclude()
                               for i, a in enumerate(cands) for b in cands[i + 1:]):   # 只认真异体边：只当形近／通假的边（NEVER_SOURCES，如 寵/龍）不挡字形判
                continue
            try:
                img = _C._page_patch(ctx, page, c.col, r.slot, r.sub)
            except PatchUnavailable:
                if p.patch_missing != "skip":
                    raise
                miss.setdefault(r.id, []).append("near_knn")
                continue
            v = near_knn.judge(img, model, cands)
            trail = {k: v[k] for k in ("char", "why", "pick", "votes", "ratio", "full", "full_votes", "nn") if k in v}
            if gap:
                trail["via"] = "near_gap"
                if v["char"] is not None and not (v["char"] == ref
                                                  or (_direct_variant_edge(v["char"], ref) and frozenset((v["char"], ref)) not in _edge_exclude())
                                                  or (canon is not None and canon(v["char"]) == canon(ref))):
                    trail["why"], v = "abstain:ref_gate", {**v, "char": None}
                    trail["char"] = None
            if v["char"] is None:
                r.evidence = {**ev, "near_knn": trail}
                continue
            r.evidence = {**ev, "near_knn": trail, "lifted_from": {"char": r.char, "doubts": ds}}
            r.char, r.admit, r.channel, r.provenance, r.doubts = v["char"], True, "near_knn", "match", []
            delta += 1
    return delta
