"""C1 进库准入（`seed_admit`）的整理本／无参照放行通道与降审护栏各遍（CV4 整理 PR3c 2026-11-26 从 seed_admit.py 原样搬来）。

次序仍由 `seed_admit.SeedAdmitStep._run_page` 定，**改次序＝改产物**。
"""

from __future__ import annotations

from .seed_admit_params import SeedAdmitParams  # noqa: F401  注解用

import re
from ..core.step import RunContext
from ..utils.gap import GAP_CHARS, is_gap
from ..utils.ji_yi_si import FAMILY as _JYS
from .seed_admit_params import _RARE_REF_COORD_MIN_COV, _SEAL_LIB_COV
from .seed_admit_common import (  # noqa: F401
    REFERENCE_TRUST_COV,
    REFERENCE_TRUST_GAP,
    REFERENCE_TRUST_TOPK_GAP,
    _LANE_GARBLE,
    _LANE_HARD,
    _LANE_R1_CLASSES,
    _LANE_REF_REVIEW,
    _REF_LIB_COORD_DOUBTS,
    _REF_LIB_COORD_SKIP,
    _RivalFacts,
    _SEEN_HARD,
    _VIS_RULING_HARD,
    _blind_ref_behind,
    _coord_codepoint_norm,
    _demote,
    _direct_variant_edge,
    _fold_hold,
    _group_img_dissent,
    _hard_blocked,
    _irregular_ref_gap,
    _is_consensus_same,
    _is_han,
    _is_hanzi,
    _lane_class,
    _lane_variant_rank,
    _log,
    _parse_follow_ref,
    _parse_follow_ref_seen,
    _parse_pua_rules,
    _rare_ref_coord_ok,
    _rare_ref_nf_ok,
    _raw_same_char,
    _seal_lib_same,
    _seal_page_shifted,
    _seal_variant_norm,
    _shape_first_lib,
    _shape_first_ok,
    _unbound_shifted,
)


def rare_ref_decide(*, doubts, guard, verdict, lib_char, lib_top, ref, op, rare_top, are_variants,
                    allow_near_form: bool = False) -> str | None:
    """规则 A（`SeedAdmitParams.rare_ref`）的判据，纯函数（离线评测与线上共用）。→ 放行字（=整理本字）或 None。

    `lib_char`：库判 same 时的字（否则 None）；`lib_top`：库首位（same 取 char，否则候选第一名）；
    `rare_top`：5-b 首位；`are_variants(a, b)`：两字有无直接异体关系。"""
    if op != "replace" or not ref or ref in _JYS or not rare_top or rare_top != ref:
        return None
    if _hard_blocked(doubts, guard, allow_near_form):
        return None
    if verdict == "same" and lib_char and lib_char != ref:
        return None                       # 库明确认成了别的字
    if lib_top and lib_top != ref and are_variants(lib_top, ref):
        return None                       # 库首位是整理本字的异体：形取谁说不准，留给人
    return ref


def _rare_ref_pass(out: list, mmap: dict, amap: dict, rtop: dict,
                   coord: dict[str, str] | None = None, variant_topk: int = 3,
                   keep_ref_review: bool = False, nf: tuple | None = None,
                   coord_min_cov: float = _RARE_REF_COORD_MIN_COV, group_top_ok: bool = False) -> int:
    """规则 A 放行通道 `rare_ref`：只把**仍待审**的格升为放行，不改任何已放行格。→ 升级格数。

    `coord` 不给：只看现役对位（`amap`）里的格。`coord` 给了（`rare_ref_coord`，排在审路之后另跑一遍）：
    只看现役对位里**没有**的格，拿坐标对位字当整理本字（护栏见 `_rare_ref_coord_ok`）。
    `keep_ref_review`（＝`lane_keep_ref_review`）：护栏拿整理本字拦下的格（`_LANE_REF_REVIEW`）不按整理本字放回，
    同审路（vol18:115:6:3 刻「本」、整理本与 5-b 都作「木」、字组文意判「本」，旧版 rare_ref 放成「木」）。"""
    from ..variants import look_alike as are_variants   # C 对也拦（字对关系表删了 C 边，护栏不能跟着松）
    group_chars: frozenset[str] = frozenset()
    if coord:
        from ..groups.registry import GROUPS
        group_chars = frozenset(c for g in GROUPS.values() for c in g.members)
    n = 0
    for col in out:
        for rec in col.chars or []:
            if rec.admit or rec.provenance == "human" or rec.channel == "human":
                continue
            if keep_ref_review and set(rec.doubts or []) & _LANE_REF_REVIEW:
                continue
            m = mmap.get(rec.id)
            al = amap.get(rec.id)
            top5 = rtop.get(rec.id)
            if m is None or not top5:
                continue
            lib_top = (m.char if m.verdict == "same" and m.char
                       else (m.candidates[0][0] if m.candidates else None))
            via = None
            if coord is not None:
                if al is not None:
                    continue
                co = coord.get(rec.id)
                if not co or not _rare_ref_coord_ok(co, lib_top, list(m.candidates or []), rec.doubts,
                                                    variant_topk, are_variants, group_chars, m.cov, coord_min_cov,
                                                    group_top_ok):
                    continue
                al, via = (co, "replace"), "coord"      # 坐标对位字与库首位不同才有意义，按 replace 段判
            elif al is None:
                continue
            nf_ok = bool(nf and via == "coord" and _rare_ref_nf_ok(
                al[0], list(m.candidates or []), nf[0].get(al[0], 0), nf[1], nf[2], are_variants, nf[3]))
            ch = rare_ref_decide(doubts=rec.doubts, guard=m.guard, verdict=m.verdict,
                                 lib_char=m.char if m.verdict == "same" else None, lib_top=lib_top,
                                 ref=al[0], op=al[1], rare_top=top5[0], are_variants=are_variants,
                                 allow_near_form=nf_ok)
            if ch is None or _fold_hold(rec, ch):
                continue
            nf_used = nf_ok and "near_form" in (rec.doubts or [])
            rec.admit, rec.channel, rec.provenance, rec.char = True, "rare_ref", "rare_ref", ch
            rec.doubts = []
            rec.evidence = {**rec.evidence, "rare_ref": {
                "rare": top5[0], "ref": al[0], "lib": lib_top, "cov": m.cov, **({"via": via} if via else {}),
                **({"near_form_relaxed": True} if nf_used else {})}}
            n += 1
    return n


def rare_sparse_decide(*, ref: str | None, cands: list, n_lib: int, doubts, guard, verdict, lib_char, lib_top,
                       max_n: int, lead_min: float, variant: bool, are_variants,
                       group_chars: frozenset = frozenset()) -> tuple[str, float] | None:
    """规则 A 少刻例支（`SeedAdmitParams.rare_ref_sparse`）的判据，纯函数。`cands`＝5-b 候选 [(字, 分, 来源)…]，按融合名次。
    → (放行字＝整理本字, 领先量) 或 None。"""
    if not ref or is_gap(ref) or ref in _JYS or not _is_hanzi(ref) or not cands:
        return None
    if n_lib > max_n:
        return None
    if _hard_blocked(doubts or [], guard):
        return None
    if verdict == "same" and lib_char and lib_char != ref:
        return None
    if ref in group_chars or (lib_top and lib_top in group_chars):
        return None
    if any(isinstance(d, str) and d.startswith(("group_flow", "shadow_veto")) for d in doubts or ()):
        return None

    def mine(c: str) -> bool:
        return c == ref or bool(variant and ord(ref) >= 0x20000 and c and are_variants(ref, c))

    top_c, top_s, top_src = cands[0]
    if not mine(top_c):
        return None
    rivals = [sc for c, sc, src in cands[1:] if src == top_src and not mine(c)]
    if not rivals:
        return None                       # 没有同来源的对手：领先量说不清，不放
    lead = float(top_s) - max(float(x) for x in rivals)
    return (ref, round(lead, 4)) if lead >= lead_min else None


def _rare_ref_sparse_pass(p: "SeedAdmitParams", out: list, mmap: dict, amap: dict, rare, coord: dict[str, str],
                          keben: dict[str, int]) -> int:
    """规则 A 少刻例支：只把**仍待审**的格升为放行。→ 升级格数。见 `SeedAdmitParams.rare_ref_sparse`。"""
    if rare is None:
        return 0
    from ..groups.registry import GROUPS
    from ..variants import are_variants
    group_chars = frozenset(c for g in GROUPS.values() for c in g.members)
    rmap = {r.id: [(c.char, c.score, getattr(c, "font", None)) for c in r.candidates if c.char]
            for cc in rare.columns for r in cc.chars}
    n = 0
    for col in out:
        for rec in col.chars or []:
            if rec.admit or rec.provenance == "human" or rec.channel == "human":
                continue
            if set(rec.doubts or []) & _LANE_REF_REVIEW:
                continue                  # 同规则 A：护栏拿整理本字拦下的格不按整理本字放回
            m = mmap.get(rec.id)
            cands = rmap.get(rec.id)
            if m is None or not cands:
                continue
            al = amap.get(rec.id)
            ref, via = (al[0], "sparse") if al is not None else (coord.get(rec.id), "sparse_coord")
            lib_top = m.char if m.verdict == "same" and m.char else (m.candidates[0][0] if m.candidates else None)
            got = rare_sparse_decide(ref=ref, cands=cands, n_lib=keben.get(ref or "", 0), doubts=rec.doubts,
                                     guard=m.guard, verdict=m.verdict, lib_char=m.char if m.verdict == "same" else None,
                                     lib_top=lib_top, max_n=p.rare_ref_sparse_max_n, lead_min=p.rare_ref_sparse_lead,
                                     variant=True, are_variants=are_variants, group_chars=group_chars)
            if got is None:
                continue
            ch, lead = got
            if _fold_hold(rec, ch):
                continue
            rec.admit, rec.channel, rec.provenance, rec.char = True, "rare_ref", "rare_ref", ch
            rec.doubts = []
            rec.evidence = {**rec.evidence, "rare_ref": {
                "rare": cands[0][0], "ref": ch, "lib": lib_top, "cov": m.cov, "via": via, "lead": lead,
                "n_lib": keben.get(ch, 0)}}
            n += 1
    return n


def solo_5b_decide(*, cands: list, rare_top: str | None, n_lib: dict | int, doubts, guard, cov_min: float,
                   gap_min: float, min_n: int, are_variants, group_chars, near_form_chars,
                   same_char: str | None = None, cov_min_same: float | None = None) -> tuple[str, float, float] | None:
    """`SeedAdmitParams.solo_5b_cov` 的判据，纯函数（离线评测与线上共用）。`cands`：库候选 [(字, cov)]；
    `n_lib`：刻例数表（字→例数）或库首位的例数。→ (放行字, cov, gap) 或 None。"""
    if not cands or not rare_top:
        return None
    ranked = sorted(cands, key=lambda t: -t[1])
    top, cov1 = ranked[0]
    if cov_min_same is not None and same_char is not None and same_char == top:
        cov_min = min(cov_min, cov_min_same)      # 库已判 same 的格降一档（solo_5b_same_cov）
    if (not top or is_gap(top) or top in _JYS or not _is_hanzi(top) or top in group_chars
            or top in near_form_chars or float(cov1) < cov_min):
        return None
    if guard is not None or _hard_blocked(doubts or [], guard):
        return None
    if len(ranked) > 1 and ranked[1][0] in near_form_chars:
        return None

    def same(c: str) -> bool:
        return c == top or bool(are_variants(c, top))

    if not same(rare_top):
        return None
    n = n_lib.get(top, 0) if isinstance(n_lib, dict) else int(n_lib)
    if n < min_n:
        return None
    rivals = [float(v) for c, v in ranked[1:] if c and not same(c)]
    gap = float(cov1) - (max(rivals) if rivals else 0.0)
    if gap < gap_min:
        return None
    return top, float(cov1), round(gap, 4)


def _solo_5b_pass(p: "SeedAdmitParams", out: list, mmap: dict, amap: dict, rare, coord: dict[str, str],
                  keben: dict[str, int],
                  mmap_raw: dict | None = None, lacuna_only: bool = False) -> int:
    """无参照格「库首位＋5-b 作证」：只把**仍待审**、无任何整理本对位的格升为放行。→ 升级格数。见 `SeedAdmitParams.solo_5b_cov`。

    `mmap_raw`：`consensus_fallback` 退档前的 glyph_match 记录。无参照格没有整理本字，共识升档的 same
    一律被退回 unsure，`solo_5b_same_cov` 要认的正是这批「库原判 same」，所以按退档前的记录看。
    `lacuna_only`：本页有参校本且 `solo_5b_scope=no_ref`，只放坐标对位为缺字（`GAP_CHARS`）的格。"""
    if rare is None:
        return 0
    from ..clustering.seeding import NEAR_FORM_CHARS
    from ..groups.registry import GROUPS
    from ..variants import are_variants
    group_chars = frozenset(c for g in GROUPS.values() for c in g.members)
    rmap = {r.id: r.candidates[0].char for cc in rare.columns for r in cc.chars if r.candidates and r.candidates[0].char}
    n = 0
    for col in out:
        for rec in col.chars or []:
            if rec.admit or rec.provenance == "human" or rec.channel == "human":
                continue
            if rec.id in amap or (coord.get(rec.id) or "") not in ("", *GAP_CHARS):
                continue                  # 有整理本对位的格归别的通道
            if lacuna_only and (coord.get(rec.id) or "") not in GAP_CHARS:
                continue                  # solo_5b_scope=no_ref：有参校本的页上只放参校本标了缺字的位
            m = mmap.get(rec.id)
            if m is None or not m.candidates:
                continue
            got = solo_5b_decide(cands=list(m.candidates), rare_top=rmap.get(rec.id), n_lib=keben,
                                 doubts=rec.doubts, guard=m.guard, cov_min=p.solo_5b_cov, gap_min=p.solo_5b_gap,
                                 min_n=p.solo_5b_min_n, are_variants=are_variants, group_chars=group_chars,
                                 near_form_chars=NEAR_FORM_CHARS,
                                 same_char=_raw_same_char(m, mmap_raw),
                                 cov_min_same=p.solo_5b_same_cov)
            if got is None:
                continue
            ch, cov1, gap = got
            rec.admit, rec.channel, rec.provenance, rec.char = True, "match_solo_5b", "match_solo_5b", ch
            rec.doubts = []
            # 无参照页放行的格不进字形库（C4 不自喂）：入库会抬高同字的刻例数与 cov，错标越放越笃定
            rec.evidence = {**rec.evidence, "no_glyph_lib": True, "solo_5b": {
                "lib": ch, "cov": round(cov1, 4), "gap": gap, "rare": rmap.get(rec.id), "n_trusted": keben.get(ch, 0)}}
            n += 1
    return n


def consensus_lib_decide(*, raw, doubts, cov_min: float, group_review: bool = False) -> str | None:
    """`SeedAdmitParams.consensus_lib_cov` 的判据，纯函数。`raw`：共识退档前的 glyph_match 记录；
    `group_review`：形近字组已判留审（如 一/二 组弃权，f4 027:154:6:1 是黑条）→ 不放。
    不要求整理本字＝库字：f4 实放 81 格里 55 格整理本是别字（剌/刺、寖/寢 等整理本错）、23 格无整理本字，看图都是库对。→ 放行字或 None。"""
    if group_review:
        return None
    if raw is None or not _is_consensus_same(raw) or not raw.char or not raw.candidates:
        return None
    top, cov1 = max(raw.candidates, key=lambda t: t[1])
    ch = raw.char
    if top != ch or float(cov1) < cov_min or float(raw.cov or 0.0) < cov_min:
        return None
    if is_gap(ch) or ch in _JYS or not _is_hanzi(ch):
        return None
    if raw.guard is not None or _hard_blocked(doubts or [], raw.guard):
        return None
    return ch


def _consensus_lib_pass(p: "SeedAdmitParams", out: list, mmap_raw: dict, amap: dict | None = None,
                        coord: dict | None = None) -> int:
    """共识升档 same 的库字放行：只把**仍待审**的格升为放行。→ 升级格数。见 `SeedAdmitParams.consensus_lib_cov`。"""
    n = 0
    for col in out:
        for rec in col.chars or []:
            if rec.admit or rec.provenance == "human" or rec.channel == "human":
                continue
            raw = mmap_raw.get(rec.id)
            ref = ((amap or {}).get(rec.id) or (None, None))[0] or (coord or {}).get(rec.id)
            grp = (rec.evidence or {}).get("group")
            ch = consensus_lib_decide(raw=raw, doubts=rec.doubts, cov_min=p.consensus_lib_cov,
                                      group_review=isinstance(grp, dict) and grp.get("decision") == "review")
            if ch is None:
                continue
            rec.admit, rec.channel, rec.provenance, rec.char = True, "consensus_lib", "consensus_lib", ch
            rec.doubts = []
            rec.evidence = {**rec.evidence, "no_glyph_lib": True, "consensus_lib": {
                "lib": ch, "ref": ref, "cov": round(float(raw.cov or 0.0), 4), "via": raw.via}}
            n += 1
    return n


def ref_lib_5b_veto_decide(char: str, rare: list, score: float, lead: float) -> tuple[str, float, float] | None:
    """`SeedAdmitParams.ref_lib_5b_veto` 的判据，纯函数。`rare`：5-b 候选 [(字, 分)]（5-b 原序）。
    → (5-b 首位, 分, 领先量)＝要否决；None＝不否决。"""
    if not rare or not char:
        return None
    r0, s0 = rare[0][0], float(rare[0][1])
    if not r0 or r0 == char or is_gap(r0) or not _is_hanzi(r0) or s0 < score:
        return None
    ld = s0 - max((float(s) for d, s in rare[1:] if d != r0), default=0.0)
    return (r0, round(s0, 4), round(ld, 4)) if ld >= lead else None


def _ref_lib_5b_veto_pass(p: "SeedAdmitParams", out: list, rare) -> int:
    """`ref_lib` 放行格里 5-b 明确偏向别的字的退回人审。→ 退回格数。见 `SeedAdmitParams.ref_lib_5b_veto`。"""
    if rare is None:
        return 0
    rlist = {r.id: [(x.char, x.score) for x in r.candidates] for cc in rare.columns for r in cc.chars if r.candidates}
    n = 0
    for col in out:
        for rec in col.chars or []:
            if not rec.admit or rec.channel != "ref_lib":
                continue
            got = ref_lib_5b_veto_decide(rec.char, rlist.get(rec.id) or [], p.ref_lib_5b_veto, p.ref_lib_5b_veto_lead)
            if got is None:
                continue
            r0, s0, ld = got
            rec.admit, rec.channel, rec.provenance = False, None, ""
            rec.doubts = [*(rec.doubts or []), "ref_lib_5b_veto"]
            rec.evidence = {**rec.evidence, "ref_lib_5b_veto": {"rare": r0, "score": s0, "lead": ld}}
            n += 1
    return n


def _human_unbound_pass(ctx: RunContext, page: int, out: list, lost: dict,
                        amap: dict | None = None) -> int:
    """人裁绑丢闸（只降级，放在所有通道与各遍之后）。→ 降级格数。见 `SeedAdmitParams.human_unbound_review`。

    `lost`：`{原编号: {"char", "status", "event", ...}}`，绑定后不采信的人裁。本格放行的字与人裁不同 →
    退回待审；相同 → 照常放行。两种都在 evidence 上挂 `human_unbound`，没放行的格也挂（给审的人看旧裁决）。"""
    n = 0
    hits: list[str] = []
    for col in out:
        for rec in col.chars or []:
            h = lost.get(rec.id)
            if h is None or rec.provenance == "human" or rec.channel == "human":
                continue
            rec.evidence = {**(rec.evidence or {}),
                            "human_unbound": {k: h.get(k) for k in ("char", "status", "event")}}
            sh = _unbound_shifted(rec, h, amap) if (amap and rec.admit) else None
            if sh is not None:
                rec.evidence["human_unbound"]["shift_ok"] = sh
                continue
            if rec.admit and rec.char != h.get("char"):
                _demote(rec, "human_unbound")
                hits.append(f"{rec.id} 人裁「{h.get('char')}」/放行「{rec.char}」({h.get('status')})")
                rec.admit, rec.channel, rec.provenance = False, None, ""
                rec.doubts = list(dict.fromkeys(list(rec.doubts or []) + ["human_unbound"]))
                n += 1
    if hits:
        _log.warning("seed_admit p%s: %d 格人裁绑丢、机器放行了别的字，已退回待审：%s",
                     page, len(hits), "；".join(hits))
        ctx.log(f"⚠ seed_admit p{page}: 人裁绑丢 {len(hits)} 格，机器放行的字与人裁不同，已退回待审"
                f"（doubt human_unbound）：{'；'.join(hits)}")
    return n


def _evict_review_pass(ctx: RunContext, page: int, out: list, cells: dict) -> int:
    """撤库重审闸（只降级）。→ 降级格数。见 `SeedAdmitParams.evict_review`。人裁过的格（channel/provenance=human）不拦。"""
    n = 0
    hits: list[str] = []
    for col in out:
        for rec in col.chars or []:
            h = cells.get(rec.id)
            if h is None or rec.provenance == "human" or rec.channel == "human":
                continue
            rec.evidence = {**(rec.evidence or {}), "evict_review": {k: h.get(k) for k in ("char", "event")},
                            "seg_kind": "evict_review"}
            rec.doubts = list(dict.fromkeys(list(rec.doubts or []) + ["evict_review"]))
            if rec.admit:
                _demote(rec, "evict_review")
                hits.append(f"{rec.id}「{rec.char}」")
                rec.admit, rec.channel, rec.provenance = False, None, ""
                n += 1
    if hits:
        ctx.log(f"seed_admit p{page}: 撤库重审 {len(hits)} 格退回待审（doubt evict_review）：{'；'.join(hits)}")
    return n


_SRB_FROM_MAX_GAP = 0.03   # symbol_ref_blank_from：○ 与库首位（口囗□日四）的 cov 差上限（SJ 17/40/41 册实测 0.003–0.02）


def _symbol_ref_blank_pass(p: "SeedAdmitParams", out: list, mmap: dict, coord: dict) -> int:
    """符号字块遇整理本空格位（`symbol_ref_blank`）：库首位是册里点名的符号、cov 够、对位说此位是空格 → 放行为该符号（升）。
    → 新放行格数。放在 `symbol_review` 之后，把它降下去的那批圈号接回来。"""
    syms = frozenset(p.symbol_ref_blank)
    frm = frozenset(p.symbol_ref_blank_from)
    n = 0
    for col in out:
        col_cov = sum(1 for r in col.chars or [] if coord.get(r.id) is not None) if p.symbol_ref_gap else 0
        for rec in col.chars or []:
            if rec.provenance == "human" or rec.channel == "human":
                continue
            ds = {d for d in (rec.doubts or []) if isinstance(d, str)}
            if "occluded" in ds or "excluded" in ds or (rec.evidence or {}).get("occluded"):
                continue
            c0 = coord.get(rec.id)
            gap = c0 is None and p.symbol_ref_gap and col_cov >= p.symbol_ref_gap_min_col
            if c0 != "" and not gap:
                continue
            from_ok = bool(rec.char) and rec.char not in syms and rec.char in frm
            if rec.char and rec.char not in syms and not from_ok:
                continue
            m = mmap.get(rec.id)
            cands = list(getattr(m, "candidates", None) or [])
            thr = p.symbol_ref_gap_cov if gap else p.symbol_ref_blank_cov
            if from_ok:
                # `symbol_ref_blank_from`：本格字被误判成 口囗□日四（圈号 ○ 的图），库首位也是它、○ 在库前三名、cov 够、与首位差不超过 _SRB_FROM_MAX_GAP
                top3 = cands[:3]
                if not top3 or top3[0][0] not in frm or float(top3[0][1]) < thr - _SRB_FROM_MAX_GAP:
                    continue
                hit = next(((c, float(v)) for c, v in top3 if c in syms and float(v) >= thr and float(top3[0][1]) - float(v) <= _SRB_FROM_MAX_GAP), None)
                if hit is None:
                    continue
                sym, cov = hit
            else:
                if not cands or cands[0][0] not in syms or float(cands[0][1]) < thr:
                    continue
                sym, cov = cands[0][0], float(cands[0][1])
            _demote(rec, "symbol_ref_blank")
            ev = dict(rec.evidence or {})
            ev["lane"] = {"lane": "symbol_ref_blank", "lib": sym, "cov": round(cov, 4),
                          "prev_doubts": list(rec.doubts or []), **({"via": "gap"} if gap else {}),
                          **({"from": rec.char} if from_ok else {})}
            ev.pop("symbol", None)
            rec.evidence = ev
            rec.admit, rec.channel, rec.provenance, rec.char = True, "symbol_ref_blank", "match", sym
            rec.doubts = ["lane_symbol_ref_blank"]
            n += 1
    return n


def _pua_rule_pass(p: "SeedAdmitParams", out: list, mmap: dict, amap: dict, coord: dict) -> int:
    """整理本缺字特殊规则（`pua_rules`）。→ 放行格数。

    只升不降：只碰 admit=False、非人裁、不在排除名单、没有硬疑问（`_LANE_HARD`）、不是印章区的格。
    条件：整理本这一位是 〓（坐标对位字，没有坐标对位时看现役对位字）；库首位字在表里、cov ≥ `pua_rule_cov`、
    库没判 diff、没有护栏（never_match／conflict）。字取表里的录入字，通道 `pua_rule`。"""
    rules = _parse_pua_rules(p.pua_rules)
    if not rules:
        return 0
    n = 0
    for col in out:
        for rec in col.chars or []:
            ds = set(rec.doubts or [])
            if (rec.admit or rec.channel == "human" or rec.provenance == "human"
                    or "excluded" in ds or "occluded" in ds or ds & _LANE_HARD):
                continue
            ref = coord.get(rec.id)
            if ref is None:
                ref = (amap.get(rec.id) or (None,))[0]
            if not is_gap(ref):
                continue
            m = mmap.get(rec.id)
            if not m or not m.candidates or getattr(m, "guard", None) is not None:
                continue
            if getattr(m, "verdict", None) == "diff":
                continue
            top, cov = m.candidates[0][0], float(m.candidates[0][1])
            char = rules.get(top)
            if char is None or cov < p.pua_rule_cov:
                continue
            rec.admit, rec.channel, rec.provenance, rec.char = True, "pua_rule", "pua_rule", char
            rec.evidence = {**(rec.evidence or {}),
                            "lane": {"lane": "pua_rule", "lib": top, "cov": round(cov, 4), "ref": ref,
                                     "prev_doubts": list(rec.doubts or [])}}
            rec.doubts = ["lane_pua_rule"]
            n += 1
    return n


def ref_topk_decide(*, char, ref, cands, verdict, guard, doubts, evidence, semantic, shape_ok=frozenset(),
                    gap_max: float = REFERENCE_TRUST_TOPK_GAP) -> int:
    """`ref_topk_follow` 的判据，纯函数。待审格：库首位≠整理本字、整理本字在前 5 名且 cov 差 ≤ `gap_max` →
    返回整理本字在候选里的名次（2–5），否则 0。"""
    if not char or not ref or is_gap(ref) or char == ref or char in _REF_LIB_COORD_SKIP or ref in _REF_LIB_COORD_SKIP:
        return 0
    if char in _JYS or ref in _JYS or guard is not None or verdict == "diff" or not cands:
        return 0
    ds = [d for d in (doubts or []) if isinstance(d, str)]
    if any(not d.startswith(_REF_LIB_COORD_DOUBTS) for d in ds):
        return 0
    names = [c for c, _v in cands[:5]]
    if ref not in names or names[0] == ref:
        return 0
    if float(cands[0][1]) - float(cands[names.index(ref)][1]) > gap_max:
        return 0
    ev = evidence or {}
    h = ev.get("human_unbound")
    if h and h.get("char") != ref:
        return 0
    g = ev.get("group") or {}
    for t in g.get("solvers") or []:
        c = t.get("char")
        if c and c != ref and not (str(t.get("solver", "")) == "ids" and (semantic(c) == semantic(ref)
                                                                         or g.get("id") in shape_ok)):
            return 0
    return names.index(ref) + 1


def _ref_topk_pass(p: "SeedAdmitParams", out: list, mmap: dict, amap: dict, coord: dict, vmap) -> int:
    """`ref_topk_follow`：库首位是形近字、整理本字在前 5 名且 cov 接近 → 按整理本放。→ 放行格数。"""
    n = 0
    ok_groups = p._rt_shape_ref_ok()
    for col in out:
        hit = tot = 0
        for r in col.chars or []:
            if r.admit and r.char:
                rf = coord.get(r.id) or (amap.get(r.id) or (None,))[0]
                if rf and not is_gap(rf):
                    tot += 1
                    hit += r.char == rf
        if not (tot >= 3 and hit / tot >= 0.8):
            continue
        for rec in col.chars or []:
            if rec.admit or rec.channel == "human" or rec.provenance == "human":
                continue
            ds = set(rec.doubts or [])
            if "excluded" in ds or "occluded" in ds:
                continue
            ref = coord.get(rec.id) or (amap.get(rec.id) or (None,))[0]
            m = mmap.get(rec.id)
            if not m or not ref:
                continue
            rank = ref_topk_decide(char=rec.char, ref=ref, cands=list(m.candidates or []),
                                   verdict=getattr(m, "verdict", None), guard=getattr(m, "guard", None),
                                   doubts=rec.doubts, evidence=rec.evidence, semantic=vmap.semantic,
                                   shape_ok=ok_groups)
            if not rank:
                continue
            top, cov = m.candidates[0][0], float(m.candidates[0][1])
            rec.char = ref
            rec.admit, rec.channel, rec.provenance = True, "ref_lib_coord", "match"
            rec.evidence = {**(rec.evidence or {}),
                            "lane": {"lane": "ref_lib_coord", "lib": top, "cov": round(cov, 4), "ref": ref,
                                     "topk_rank": rank, "prev_doubts": list(rec.doubts or [])}}
            rec.doubts = ["lane_ref_lib_coord"]
            n += 1
    return n


def ref_lib_coord_decide(*, char, ref, cands, verdict, guard, doubts, evidence, semantic, cov_min: float,
                         gap_min: float, shape_ok=frozenset(), blind_ok: bool = False,
                         blind_cov_max: float = 0.975) -> bool:
    """`ref_lib_coord` 的判据，纯函数（离线回放与线上共用）。待审格是否按整理本字放行。
    `blind_ok`（调用方已验过本列对位健康）：库首位不是整理本字、但格带 `ctx_guard_ref`（库认不出、文意又与整理本不同）、
    库首位 cov < `blind_cov_max`（库没有强烈说是别的字）→ 也按整理本放。"""
    if not char or not ref or is_gap(ref) or char != ref or char in _REF_LIB_COORD_SKIP or char in _JYS or not _is_han(ref):
        return False
    ds = [d for d in (doubts or []) if isinstance(d, str)]
    if any(not d.startswith(_REF_LIB_COORD_DOUBTS) for d in ds):
        return False
    if guard is not None or verdict == "diff" or not cands:
        return False
    top = float(cands[0][1])
    if cands[0][0] != ref:
        if not (blind_ok and "ctx_guard_ref" in ds and top < blind_cov_max):
            return False
    else:
        if top < cov_min:
            return False
        if any(semantic(c) != semantic(ref) and top - float(v) < gap_min for c, v in cands[1:6]):
            return False
    ev = evidence or {}
    h = ev.get("human_unbound")
    if h and h.get("char") != char:
        return False
    g = ev.get("group") or {}
    for t in g.get("solvers") or []:
        c = t.get("char")
        if c and c != char and not (str(t.get("solver", "")) == "ids" and (semantic(c) == semantic(ref)
                                                                         or g.get("id") in shape_ok)):
            return False
    return True


def _ref_lib_coord_pass(p: "SeedAdmitParams", out: list, mmap: dict, amap: dict, coord: dict, vmap) -> int:
    """按整理本放行：坐标对位字（没有时看现役对位字）＝库首位＝本格字（`ref_lib_coord`）。→ 放行格数。判据见 `ref_lib_coord_decide`。"""
    n = 0
    ok_groups = p._rt_shape_ref_ok()
    if p._rt_rank() >= 1:
        cov_min, gap_min = REFERENCE_TRUST_COV, REFERENCE_TRUST_GAP
    else:                                    # 只开 `ref_lib_coord`（殿本）：用它自己更严的门槛
        cov_min, gap_min = p.ref_lib_coord_cov, p.ref_lib_coord_gap
    for col in out:
        blind_ok = False
        if p._rt_rank() >= 2:
            # 本列对位健康：列内已放行格里字＝整理本字的占比 ≥ 0.8（至少 3 格）——坐标对位没有整体错位
            hit = tot = 0
            for r in col.chars or []:
                if r.admit and r.char:
                    rf = coord.get(r.id) or (amap.get(r.id) or (None,))[0]
                    if rf and not is_gap(rf):
                        tot += 1
                        hit += r.char == rf
            blind_ok = tot >= 3 and hit / tot >= 0.8
        for rec in col.chars or []:
            if rec.admit or rec.channel == "human" or rec.provenance == "human":
                continue
            ds = set(rec.doubts or [])
            if "excluded" in ds or "occluded" in ds:
                continue
            ref = coord.get(rec.id)
            if not ref:
                ref = (amap.get(rec.id) or (None,))[0]
            m = mmap.get(rec.id)
            if not m or not ref:
                continue
            if not ref_lib_coord_decide(char=rec.char, ref=ref, cands=list(m.candidates or []),
                                        verdict=getattr(m, "verdict", None), guard=getattr(m, "guard", None),
                                        doubts=rec.doubts, evidence=rec.evidence, semantic=vmap.semantic,
                                        cov_min=cov_min, gap_min=gap_min,
                                        shape_ok=ok_groups, blind_ok=blind_ok):
                continue
            top, cov = m.candidates[0][0], float(m.candidates[0][1])
            rec.admit, rec.channel, rec.provenance = True, "ref_lib_coord", "match"
            rec.evidence = {**(rec.evidence or {}),
                            "lane": {"lane": "ref_lib_coord", "lib": top, "cov": round(cov, 4), "ref": ref,
                                     **({"blind": True} if top != ref else {}),
                                     "prev_doubts": list(rec.doubts or [])}}
            rec.doubts = ["lane_ref_lib_coord"]
            n += 1
    return n


def follow_ref_decide(*, admit: bool, channel, char, doubts, ref, cands, verdict, guard, ctx_char,
                      rules: dict, cov_min: float, gap_min: float, allow_occluded: bool = False,
                      rival_skip: frozenset = frozenset()) -> str | None:
    """`follow_ref` 的判据，纯函数（离线回放与线上共用）。→ "fix"（已放行格改回整理本形）、"admit"（待审格放行整理本形）或 None。
    `rival_skip`：算领先差时不当对手的字（书级钩子 `impl/keben/follow_ref_hooks.rival_skip` 给，缺省空＝只排除这一对）。"""
    other = rules.get(ref) if ref else None
    if other is None or channel == "human":
        return None
    if admit:
        return "fix" if char == other else None
    ds = set(doubts or [])
    if allow_occluded:                       # `occluded_variant_first`：异体规则先于印章
        ds.discard("occluded")
        doubts = [d for d in (doubts or []) if d != "occluded"]
    if "excluded" in ds or "occluded" in ds or ds & _LANE_HARD or ds & _LANE_GARBLE or _hard_blocked(doubts or [], guard):
        return None
    if verdict == "diff" or not cands:
        return None
    pair = {ref, other}
    top, cov = cands[0][0], float(cands[0][1])
    if top not in pair or cov < cov_min:
        return None
    rival = max((float(c) for ch, c in cands if ch not in pair and ch not in rival_skip), default=0.0)
    if cov - rival < gap_min:
        return None
    if ds & _LANE_REF_REVIEW and ctx_char not in pair:
        return None
    return "admit"


def seen_pair_decide(*, admit: bool, channel, char, doubts, ref, cands, verdict, guard, rules: dict,
                     cov_min: float, gap_min: float, allow_conflict: bool = False) -> str | None:
    """`follow_ref_seen` 的判据，纯函数。→ "admit"｜None。只管待审格；与 `follow_ref_decide` 的区别是不拦 near_form、
    group_flow_abstain、上下文 margin 不足、replace_align 这类「没有人给出别的字」的疑问。
    `rules`：{整理本形: {库里的另几形}}；库首位须是整理本形或其中一形，领先对外（整理本形、核实过的另几形之外）最好候选 ≥ gap_min。"""
    others = rules.get(ref) if ref else None
    if not others or admit or channel == "human":
        return None
    ds = set(doubts or [])
    pair = {ref} | set(others)
    if allow_conflict and guard == "conflict" and len(cands) >= 2 and len(pair) == 2 and {cands[0][0], cands[1][0]} == pair:
        ds = ds - {"护栏:conflict"}                # 两字字形一样、都判 same：交给整理本文意（`follow_ref_seen_conflict`）
        guard = None
    if ds & _SEEN_HARD or any(isinstance(d, str) and d.startswith("护栏:") for d in ds) or guard in ("never_match", "conflict", "timeout"):
        return None
    if verdict == "diff" or not cands:
        return None
    top, cov = cands[0][0], float(cands[0][1])
    if top not in pair or cov < cov_min:
        return None
    rival = max((float(c) for ch, c in cands if ch not in pair), default=0.0)
    if cov - rival < gap_min:
        return None
    return "admit"


def _follow_ref_pass(p: "SeedAdmitParams", out: list, mmap: dict, amap: dict, coord: dict, dmap: dict,
                     vmap=None, rival_hook=None) -> int:
    """照录整理本的异体对（`follow_ref`）。→ 新放行格数（改字的格不计数）。判据见 `follow_ref_decide`。
    `vmap` 给了（`follow_ref_variants`）：表里没有的整理本字，与本格字（已放行字／库首位）同义异体的也按一对处理。
    `rival_hook`：书级钩子 `follow_ref_hooks.rival_skip`（缺省 None＝不调），只对待审格调，见该模块。"""
    rules = _parse_follow_ref(p.follow_ref) if p.follow_ref else {}
    seen = _parse_follow_ref_seen(p.follow_ref_seen) if p.follow_ref_seen else {}
    if not rules and not seen and vmap is None:
        return 0
    n = 0
    for col in out:
        for rec in col.chars or []:
            if rec.provenance == "human":
                continue
            if ((rec.evidence or {}).get("lane") or {}).get("variant_rank") == "hook":
                continue        # 书级钩子 variant_rank 按刻形放的字（史記 圗兾凢来，Sheldon 11-16）：别再按整理本改回去
            ref = coord.get(rec.id)
            if not ref:
                ref = (amap.get(rec.id) or (None,))[0]
            m = mmap.get(rec.id)
            if ref in seen and not rec.admit and m is not None:
                if seen_pair_decide(admit=rec.admit, channel=rec.channel, char=rec.char, doubts=rec.doubts, ref=ref,
                                    cands=list(m.candidates or []), verdict=getattr(m, "verdict", None),
                                    guard=getattr(m, "guard", None), rules=seen,
                                    cov_min=p.follow_ref_cov, gap_min=p.follow_ref_gap,
                                    allow_conflict=p.follow_ref_seen_conflict) == "admit":
                    top, cov = m.candidates[0][0], float(m.candidates[0][1])
                    rec.admit, rec.channel, rec.provenance, rec.char = True, "follow_ref", "match", ref
                    rec.evidence = {**(rec.evidence or {}),
                                    "lane": {"lane": "follow_ref", "lib": top, "cov": round(cov, 4), "ref": ref, "via": "seen",
                                             "prev_doubts": list(rec.doubts or [])}}
                    rec.doubts = ["lane_follow_ref"]
                    n += 1
                    continue
            m = mmap.get(rec.id)
            here, via = rules, None
            if ref not in rules or (vmap is not None and not is_gap(ref)):
                # 表里没有这个整理本形：按参校本取异体（`follow_ref_variants`）。表里有、但本格的字不是表里那一形
                # （史記 r45：表加了 嵗=歳，嵗 的格放行字是 歲，表路只认 歳 不改）时同样走这条路，别让表项接管。
                if vmap is None or not ref or is_gap(ref):
                    continue
                other = rec.char if rec.admit else ((m.candidates or [(None,)])[0][0] if m else None)
                if ref in rules and (not other or other == rules[ref]):
                    pass                                   # 就是表里那一形：表路照旧
                elif not other or other == ref or vmap.semantic(other) != vmap.semantic(ref):
                    continue
                else:
                    here, via = {ref: other}, "variants"
            d = dmap.get(rec.id)
            cov_min, gap_min = p.follow_ref_cov, p.follow_ref_gap
            skip: frozenset = frozenset()
            if rival_hook is not None and not rec.admit and m is not None and rec.channel != "human" and ref in here:
                cands_l = [(ch, float(c)) for ch, c in (m.candidates or [])]
                got = rival_hook(ref=ref, lib=here[ref], cands=cands_l, via=via, facts=_RivalFacts(vmap))
                skip = frozenset(got or ()) - {ref, here[ref]}
            act = follow_ref_decide(admit=rec.admit, channel=rec.channel, char=rec.char, doubts=rec.doubts, ref=ref,
                                    cands=list(m.candidates or []) if m else [], verdict=getattr(m, "verdict", None),
                                    guard=getattr(m, "guard", None), ctx_char=getattr(d, "char", None), rules=here,
                                    cov_min=cov_min, gap_min=gap_min,
                                    allow_occluded=True, rival_skip=skip)
            if act == "fix":
                rec.evidence = {**(rec.evidence or {}), "follow_ref": {"from": rec.char, "ref": ref,
                                                                       **({"via": via} if via else {})}}
                rec.char = ref
            elif act == "admit":
                top, cov = m.candidates[0][0], float(m.candidates[0][1])
                rec.admit, rec.channel, rec.provenance, rec.char = True, "follow_ref", "match", ref
                rec.evidence = {**(rec.evidence or {}),
                                "lane": {"lane": "follow_ref", "lib": top, "cov": round(cov, 4), "ref": ref,
                                         **({"via": via} if via else {}),
                                         **({"rival_skip": hit} if (hit := sorted({ch for ch, _ in m.candidates or []
                                                                                   if ch in skip})) else {}),
                                         "prev_doubts": list(rec.doubts or [])}}
                rec.doubts = ["lane_follow_ref"]
                n += 1
    return n


def _edge_pair_pass(p: "SeedAdmitParams", out: list, mmap: dict, amap: dict, coord: dict, dmap: dict) -> int:
    """异体边表自动暂归一（`edge_pair`）。→ 新放行格数。判据＝`follow_ref_decide`（待审格一支），对子由 `edge_pairs.is_auto_pair` 认。"""
    from ..groups.edge_pairs import is_auto_pair, pair_to, seam_pair
    n = 0
    for col in out:
        for rec in col.chars or []:
            if rec.admit or rec.provenance == "human" or rec.channel == "human":
                continue
            ref = coord.get(rec.id) or (amap.get(rec.id) or (None,))[0]
            m = mmap.get(rec.id)
            cands = list(m.candidates or []) if m else []
            if not ref or not cands:
                continue
            top, cov = cands[0][0], float(cands[0][1])
            if ref == top:
                continue
            gap_min, seam = p.edge_pair_gap, None
            if not is_auto_pair(ref, top):
                if not p.edge_pair_group_seam or (rec.evidence or {}).get("group"):
                    continue
                if p.replace_form == "review" and "replace_form" in (rec.doubts or []):
                    continue                     # 书要求改字层异体一律人审：补缝不越过
                seam = seam_pair(ref, top)
                if seam is None:
                    continue
                if seam == "near_form":
                    gap_min = max(gap_min, p.edge_pair_group_seam_nf_gap)
            d = dmap.get(rec.id)
            act = follow_ref_decide(admit=False, channel=rec.channel, char=rec.char, doubts=rec.doubts, ref=ref,
                                    cands=cands, verdict=getattr(m, "verdict", None), guard=getattr(m, "guard", None),
                                    ctx_char=getattr(d, "char", None), rules={ref: top},
                                    cov_min=p.edge_pair_cov, gap_min=gap_min,
                                    allow_occluded=True)
            if act != "admit":
                continue
            to = top if p.edge_pair_to == "lib" else ref if p.edge_pair_to == "ref" else pair_to(ref, top, lib_top=top)
            rec.admit, rec.channel, rec.provenance, rec.char = True, "edge_pair", "match", to
            rec.evidence = {**(rec.evidence or {}),
                            "lane": {"lane": "edge_pair", "lib": top, "cov": round(cov, 4), "ref": ref,
                                     "prev_doubts": list(rec.doubts or [])},
                            "edge_pair": {"decision": {"lib": "keben", "ref": "ref"}.get(p.edge_pair_to, "provisional"),
                                          "pair": [ref, top], "to": to,
                                          **({"seam": seam} if seam else {})}}
            rec.doubts = ["lane_edge_pair"]
            n += 1
    return n


def _review_lanes_pass(p: "SeedAdmitParams", out: list, mmap: dict, amap: dict, coord: dict,
                       vmap, witnesses_fn, canon=None, lib_n: dict | None = None, knn_veto=None,
                       variant_hook=None, rank_hook=None) -> int:
    """待审补放三通道（`lane_witness3`／`lane_coord`／`lane_seal`，overview#433）。→ 放行格数。

    `variant_hook`：书级钩子 `follow_ref_hooks.variant_norm`（缺省 None＝不调），`lane_variant_guard` 内建例外都不放时
    最后问一次，见该模块。`rank_hook`：书级钩子 `follow_ref_hooks.variant_rank`（缺省 None＝不调），`variant_hook`
    也不放时再问一次。
    只升不降：只碰 admit=False、非人裁、不在排除名单上的格；己/已/巳 一族一律跳过。
    `witnesses_fn()` → 证人列表（只在 R1/R4 真要看证人时才调，装载与锚定都是懒的）。"""
    from pathlib import Path

    from ..clustering.witness_cells import witness_readings
    from ..utils.jiazhu_order import sort_by_reading
    sem = vmap.semantic

    def same(*cs) -> bool:
        return all(cs) and len({sem(c) for c in cs}) == 1

    def variant_pair(a, b) -> bool:
        """已知异体对：语义同、字面不同（刻本原字 vs 整理本字）。"""
        return bool(a and b and a != b and sem(a) == sem(b))

    from ..groups.registry import GROUPS
    group_chars = frozenset(c for g in GROUPS.values() for c in g.members)

    def keep_rare(name, char, lib, co, lev) -> bool:
        """`lane_variant_keep_rare`：放的字＝坐标对位字＝库首位，且是少见异体、不属任何字组。"""
        return bool(name == "coord_fallback" and lev.get("via") == "lib_coord_primary"
                    and char and char == lib == co and sem(char) != char and char not in group_chars)

    def lib_top_of(rid):
        m = mmap.get(rid)
        return (m.char or (m.candidates[0][0] if m.candidates else None)) if m else None

    def guard_of(rid):
        m = mmap.get(rid)
        return getattr(m, "guard", None) if m else None

    cache: dict = {}

    def readings() -> list[tuple[str, dict]]:
        """[(证人文件名, {字位 id: 证人字})]，质量降序；第一次用到才算。"""
        if "r" not in cache:
            ws = witnesses_fn() if witnesses_fn else []
            seq = []
            for col in sorted(out, key=lambda c: c.col):
                for rec in sort_by_reading(col.chars or []):
                    if "excluded" in (rec.doubts or []) and rec.char is None:
                        continue
                    ch = rec.char or (amap.get(rec.id) or (None,))[0] or lib_top_of(rec.id)
                    if ch and len(ch) == 1:
                        seq.append((rec.id, ch))
            cache["r"] = [(Path(w.name).name, witness_readings(seq, w.text, w.index, vmap.normalize_text)) for w in ws]
        return cache["r"]

    seal_vias = {s.strip() for s in (p.lane_seal_via or "").split(",") if s.strip()}
    marks = [s.strip() for s in (p.lane_seal_title_marks or "").split(",") if s.strip()]
    formula = re.compile(p.lane_seal_title_formula) if p.lane_seal and p.lane_seal_title_formula else None
    title_norm = dict(zip(p.lane_seal_title_norm[0::2], p.lane_seal_title_norm[1::2]))
    title_cols, formula_cols = set(), set()
    title_bad: dict[int, set] = {}          # 题列容错：列号 → 与套语前缀不一致的格 id（不放）
    tol, pre = p.lane_seal_title_tolerance, p.lane_seal_title_prefix
    if p.lane_seal and (marks or formula):
        for col in out:
            srt = sort_by_reading(col.chars or [])
            s = "".join(coord.get(r.id) or "" for r in srt)
            if formula is not None and formula.fullmatch(s):
                formula_cols.add(col.col)
            elif (formula is not None and tol > 0 and pre and len(s) > len(pre)
                  and all(coord.get(r.id) for r in srt[:len(pre)])
                  and 0 < sum(a != b for a, b in zip(s, pre)) <= tol
                  and formula.fullmatch(pre + s[len(pre):])):
                formula_cols.add(col.col)
                title_bad[col.col] = {r.id for r, a, b in zip([r for r in srt if coord.get(r.id)], s, pre) if a != b}
            elif any(mk in s for mk in marks):
                title_cols.add(col.col)
    page_shift = p.lane_seal and _seal_page_shifted(out, mmap)

    garble_cols = {col.col for col in out for r in (col.chars or []) if set(r.doubts or []) & _LANE_GARBLE}
    n = 0
    for col in out:
        for rec in col.chars or []:
            if (rec.admit or rec.channel == "human" or rec.provenance == "human"
                    or "excluded" in (rec.doubts or []) or set(rec.doubts or []) & _LANE_HARD
                    or set(rec.doubts or []) & _LANE_REF_REVIEW):
                continue
            al = amap.get(rec.id)
            ref, op = (al[0], al[1]) if al else (None, None)
            co = coord.get(rec.id)
            if is_gap(co):                       # 逐列本的 PUA 生僻字占位：知道有字、不知道是哪个
                co = None
            lib = lib_top_of(rec.id)
            ev = rec.evidence or {}
            occ = ev.get("occluded")
            hit = None                           # (通道, 字, 证据)
            if occ:
                if not p.lane_seal or (rec.char and rec.char in _JYS):
                    continue
                if page_shift:
                    rec.evidence = {**ev, "lane_skip": {"lane": "seal", "why": "page_shift"}}
                    continue
                if col.col in formula_cols and rec.id in title_bad.get(col.col, ()):
                    rec.evidence = {**ev, "lane_skip": {"lane": "seal", "why": "title_mismatch"}}
                    continue
                if col.col in formula_cols and rec.char:
                    ch = title_norm.get(rec.char, rec.char)
                    lev = {"via": occ.get("via"), "title_formula": True}
                    if ch != rec.char:
                        lev["norm_from"] = rec.char
                    rec.admit, rec.channel, rec.provenance, rec.char = True, "seal", "seal", ch
                    rec.evidence = {**ev, "lane": {"lane": "seal", **lev, "prev_doubts": list(rec.doubts or [])},
                                    "no_glyph_lib": True}
                    rec.doubts = ["lane_seal"]
                    n += 1
                    continue
                if col.col in title_cols:
                    continue
                if occ.get("via") == "coord_blank" and occ.get("ref_blank") and rec.char is None:
                    hit = ("seal", None, {"via": "coord_blank", "nonchar": True})
                elif rec.char and occ.get("via") in seal_vias:
                    hit = ("seal", rec.char, {"via": occ.get("via")})
                if hit is not None and hit[1] and p.lane_seal_lib_veto:
                    m = mmap.get(rec.id)
                    top = (m.candidates[0] if m and m.candidates else None)
                    second = (m.candidates[1][0] if m and len(m.candidates or []) > 1 else None)
                    if (top and top[1] >= p.lane_seal_lib_veto and top[0] != hit[1]
                            and not variant_pair(top[0], hit[1])
                            and second != hit[1]
                            and not (lib_n is not None and lib_n.get(hit[1], 0) < p.lane_seal_lib_veto_min_n)):
                        rec.evidence = {**ev, "lane_skip": {"lane": "seal", "why": "lib_veto", "lib": top[0],
                                                            "cov": round(float(top[1]), 4)}}
                        continue
            else:
                cls = _lane_class(rec.doubts, ev, rec.char, ref, lib)
                if cls == "ji_yi_si" or co in _JYS or col.col in garble_cols:
                    continue
                if p.lane_witness3 and cls in _LANE_R1_CLASSES and op == "replace" and ref:
                    rs = readings()
                    wc = {name: r.get(rec.id) for name, r in rs}
                    if rs and not any(c in _JYS for c in wc.values() if c) and same(ref, co, *wc.values()):
                        if variant_pair(lib, ref):
                            _sf = _shape_first_lib(p, mmap.get(rec.id), lib, ref)
                            if _sf is not None:      # 表里是刻形同字异形、库首位把握够高：放库形（刻本原字）
                                hit = ("witness3", lib, {"cls": cls, "ref": ref, "coord": co, "lib": lib, "guard": guard_of(rec.id),
                                                         "witnesses": wc, "lib_form": {"from": ref, "cov": _sf, "via": "shape_first"}})
                            else:
                                rec.evidence = {**ev, "lane_skip": {"lane": "witness3", "why": "lib_variant", "lib": lib}}
                        elif knn_veto is not None and (kv := knn_veto(col.col, rec, lib, ref)):
                            rec.evidence = {**ev, "lane_skip": {"lane": "witness3", "why": "knn_veto", "lib": lib, **kv}}
                            rec.doubts = list(dict.fromkeys(list(rec.doubts or []) + ["witness3_knn_veto"]))
                        else:
                            hit = ("witness3", ref, {"cls": cls, "ref": ref, "coord": co, "lib": lib,
                                                     "guard": guard_of(rec.id), "witnesses": wc})
                elif p.lane_coord and cls == "other" and co:
                    rs = readings()
                    wc = {name: r.get(rec.id) for name, r in rs}
                    if any(c in _JYS for c in wc.values() if c):
                        continue
                    d = wc.get(rs[0][0]) if rs else None
                    if variant_pair(lib, co) and p.lane_coord_codepoint_variant and (
                            norm := _coord_codepoint_norm(p, mmap.get(rec.id), lib, co, canon)):
                        # 两形本书 codepoints 已归一：放哪个都落同一码位，不必看图定刻本形
                        hit = ("coord_fallback", norm, {"via": "lib_coord_codepoint", "coord": co, "lib": lib,
                                                         "variant_norm": "codepoint", "witnesses": wc})
                    elif variant_pair(lib, co):
                        # 库首位与坐标对位字是异体对：哪个是刻本形说不准（vol03 彝/𢑴 人裁取证人形，
                        # vol04 𨽾/𨽻 看图是库形），同 R1 的护栏，送审。
                        rec.evidence = {**ev, "lane_skip": {"lane": "coord_fallback", "why": "lib_variant", "lib": lib}}
                    elif same(lib, co, d):
                        hit = ("coord_fallback", lib, {"via": "lib_coord_primary", "coord": co, "lib": lib,
                                                       "witnesses": wc})
                    elif not _is_han(co) and lib != co:
                        # 坐标对位字不是汉字（ခ 之类对位错位／符号）、库首位是别的字：不取参校字，留审（史記 r12 03:114:2:20）
                        rec.evidence = {**ev, "lane_skip": {"lane": "coord_fallback", "why": "ref_non_han", "lib": lib, "coord": co}}
                    elif (p.lane_coord_blind_guard and lib != co and lib_n is not None
                          and lib_n.get(co, 0) >= p.lane_coord_blind_min_n
                          and _blind_ref_behind(mmap.get(rec.id), co, p.lane_coord_blind_lib_cov, p.lane_coord_blind_gap)):
                        rec.evidence = {**ev, "lane_skip": {"lane": "coord_fallback", "why": "ref_blind", "lib": lib, "coord": co}}
                    elif (rs and same(co, *wc.values()) and not variant_pair(lib, co)
                          and guard_of(rec.id) is None):
                        # 这一支没有字形背书（库首位是别的字），库再带护栏（never_match／conflict：
                        # 库明说「不是这个字」）就不放——vol04 60:9:9 库 一 cov 0.999、证人 二。
                        hit = ("coord_fallback", co, {"via": "witnesses_coord", "coord": co, "lib": lib,
                                                      "witnesses": wc})
            if hit is None:
                continue
            name, char, lev = hit
            if p.lane_lib_veto and char and name in ("witness3", "coord_fallback"):
                m = mmap.get(rec.id)
                top = (m.candidates[0] if m and m.candidates else None)
                if top and float(top[1]) >= p.lane_lib_veto and top[0] != char and not same(top[0], char):
                    if (p.lane_lib_veto_pairs and any(len(q) == 2 and {q[0], q[1]} == {top[0], char} for q in p.lane_lib_veto_pairs)) or (
                            p.lane_shape_first and _shape_first_ok(p, m, top[0], char, top[0])):
                        lev = {**lev, "lib_form": {"from": char, "cov": round(float(top[1]), 4)}}
                        char = top[0]                       # 照刻形：放库首位的形，不否决
                    else:
                        rec.evidence = {**ev, "lane_skip": {"lane": name, "why": "lib_veto", "lib": top[0],
                                                            "cov": round(float(top[1]), 4)}}
                        rec.doubts = list(dict.fromkeys(list(rec.doubts or []) + ["lane_lib_veto"]))
                        continue
            if p.lane_group_img_veto is not None and char and (
                    gv := _group_img_dissent(ev.get("group"), char, p.lane_group_img_veto)):
                rec.evidence = {**ev, "lane_skip": {"lane": name, "why": "group_img", **gv}}
                rec.doubts = list(dict.fromkeys(list(rec.doubts or []) + ["lane_group_img"]))
                continue
            if p.lane_variant_guard and char and not (p.lane_shape_first and lev.get("lib_form")):
                # 放的是库形（刻本原字，`lane_shape_first`）：不是把异体改成通用字，不必拦
                m = mmap.get(rec.id)
                forms = [rec.char] + [c for c, _ in ((m.candidates or [])[:max(p.lane_variant_topk, 0)] if m else [])]
                vf = next((f for f in forms if variant_pair(f, char)), None)
                if vf is not None and keep_rare(name, char, lib, co, lev):
                    lev = {**lev, "keep_rare": vf}
                elif vf is not None and name == "seal" and _seal_lib_same(m, char, _SEAL_LIB_COV):
                    lev = {**lev, "variant_first": vf}      # 库首位就是默认字：放的是库形，不是把异体改成通用字
                elif vf is not None and name == "seal" and (
                        norm := _seal_variant_norm(char, vf, canon)):
                    char, how = norm                        # 两形本书已定归一：放哪个都落同一码位
                    lev = {**lev, "variant_norm": how, "variant_from": vf}
                elif (vf is not None and lev.get("via") == "lib_coord_codepoint" and canon is not None
                      and canon(vf) == canon(char)):
                    pass                                    # 候选里的另一形本书已归到同一码位
                elif vf is not None and variant_hook is not None and (
                        vn := variant_hook(lane=name, char=char, form=vf, canon=canon, lib=lib)) and same(vn, char):
                    char = vn                               # 书级钩子：两形本书已归一（史記，follow_ref_hooks.variant_norm）
                    lev = {**lev, "variant_norm": "hook", "variant_from": vf}
                elif vf is not None and rank_hook is not None and (
                        vr := _lane_variant_rank(rank_hook, name, char, rec.char, m, p.lane_variant_topk, variant_pair, lib)
                ) and same(vr[0], char):
                    char = vr[0]                            # 书级钩子：异体只排库后几名（史記，follow_ref_hooks.variant_rank）
                    lev = {**lev, "variant_rank": "hook", "variant_from": vf, "variant_ranks": vr[1]}
                elif vf is not None:    # 图上可能是刻本异体：别把它改成通用字（#433）
                    rec.evidence = {**ev, "lane_skip": {"lane": name, "why": "cand_variant", "form": vf, "char": char}}
                    continue
            rec.admit, rec.channel, rec.provenance, rec.char = True, name, name, char
            rec.evidence = {**ev, "lane": {"lane": name, **lev, "prev_doubts": list(rec.doubts or [])},
                            "no_glyph_lib": True}
            rec.doubts = [f"lane_{name}"]
            n += 1
    return n


def _blank_ink_pass(p: "SeedAdmitParams", out: list, mmap: dict, coord: dict, conflict: frozenset, vmap) -> int:
    """`blank_ink_nonchar`：整理本空格位上有墨、库认不出的格判非字放行。→ 放行格数。只升不降。"""
    n = 0
    for col in out:
        recs = col.chars or []
        ref_n = agree = 0
        for rec in recs:
            ch = coord.get(rec.id)
            if not ch or is_gap(ch):
                continue
            ref_n += 1
            m = mmap.get(rec.id)
            top = (m.candidates[0][0] if m and m.candidates else None) or rec.char
            agree += int(bool(top) and vmap.semantic(top) == vmap.semantic(ch))
        if agree < p.blank_ink_col_min_agree or agree < p.blank_ink_col_min_frac * ref_n:
            continue
        for rec in recs:
            doubts = set(rec.doubts or [])
            if (rec.admit or rec.channel == "human" or rec.provenance == "human" or "excluded" in doubts
                    or "occluded" in doubts or doubts & _LANE_HARD):
                continue
            if coord.get(rec.id, None) != "" or rec.id in conflict:
                continue
            m = mmap.get(rec.id)
            if m is None:
                continue
            top = m.candidates[0] if m.candidates else None
            cov = float(top[1]) if top else 0.0
            if m.verdict == "same" or cov >= p.blank_ink_max_cov:
                continue
            ev = rec.evidence or {}
            rec.admit, rec.channel, rec.provenance, rec.char = True, "blank_ink", "blank_ink", None
            rec.evidence = {**ev, "lane": {"lane": "blank_ink", "nonchar": True, "ref_blank": True,
                                           "verdict": m.verdict, "lib": top[0] if top else None,
                                           "cov": round(cov, 4), "prev_doubts": sorted(doubts)},
                            "no_glyph_lib": True}
            rec.doubts = ["blank_ink"]
            n += 1
    return n


def _p_ref_pass(p, out: list, amap: dict, mmap: dict | None = None) -> int:
    """P 类取整理本字（`SeedAdmitParams.p_ref_admit`）。→ 放行数净增。

    （原 `p_ref_coord`：退到坐标对位的整理本字，P02 11-06 加、无书开，2026-11-23 CV4 删。）"""
    from ..groups.registry import FLOW_GROUPS
    in_group = {c for g in FLOW_GROUPS.values() for c in g.members}

    def ref_of(r):
        return (amap.get(r.id) or (None,))[0] or None

    def irregular_ok(r) -> bool:
        """`p_ref_irregular_gap`：整理本字是异体写法且字族 cov 贴近机器字 → 不看 `p_ref_max_cov`，整理本字在字组里也放（机器字不在组里，组流程没有对这格表态；第 7 轮 P01 里 46 格整理本字在 寳／𭔃／竒／囘／厯 等组内）。"""
        if p.p_ref_irregular_gap is None or mmap is None:
            return False
        m = mmap.get(r.id)
        gap = _irregular_ref_gap(r.char, ref_of(r), getattr(m, "candidates", None)) if m is not None else None
        return gap is not None and gap <= p.p_ref_irregular_gap

    def cand(r) -> bool:
        if r.admit or r.provenance == "human" or r.channel == "human" or ((r.id or "")[-1:] in ("a", "b") and not p.p_ref_jiazhu):
            return False
        ds = {d for d in (r.doubts or []) if isinstance(d, str)}
        if _VIS_RULING_HARD & ds or "occluded" in ds or "excluded" in ds or (r.evidence or {}).get("occluded"):
            return False
        if ((r.evidence or {}).get("group") or {}).get("id"):
            return False
        if p.p_ref_min_cov is not None:
            cov = (r.evidence or {}).get("cov")
            if "库里没有这个字" in ds or (isinstance(cov, (int, float)) and cov < p.p_ref_min_cov):
                return False            # 库认不出的格（多是切分坏格）不取整理本字，盖住切分错
        ref = ref_of(r)
        if not (ref and r.char and r.char != ref and r.char not in in_group and (ref not in in_group or irregular_ok(r))):
            return False
        return not (p.p_ref_skip_variant and _direct_variant_edge(r.char, ref))

    def cov_ok(r) -> bool:
        """`p_ref_max_cov`：机器字库覆盖率须低于它（相邻判断仍按不含这条的 cand，成片就是成片）。"""
        lim = p.p_ref_max_cov
        if lim is None:
            return True
        cov = (r.evidence or {}).get("cov")
        return isinstance(cov, (int, float)) and cov < lim

    n = 0
    for c in out:
        rs = sorted(c.chars or [], key=lambda r: (r.slot, r.sub or ""))
        flags = [cand(r) for r in rs]
        for i, r in enumerate(rs):
            if not flags[i] or not (cov_ok(r) or irregular_ok(r)):
                continue
            if not p.p_ref_adjacent and ((i > 0 and flags[i - 1]) or (i + 1 < len(rs) and flags[i + 1])):
                continue
            ref = ref_of(r)
            r.evidence = {**(r.evidence or {}), "p_ref": {"ref": ref, "machine": r.char, **({"irregular": True} if not cov_ok(r) else {}), "cov": (r.evidence or {}).get("cov")},
                          "lifted_from": {"char": r.char, "doubts": list(r.doubts or [])}}
            r.char, r.admit, r.channel, r.provenance, r.doubts = ref, True, "p_ref", "match", []
            n += 1
    return n


def _pair_form_pass(p, out: list, mmap: dict, ctx=None) -> int:
    """放行字按刻形改（`SeedAdmitParams.pair_form`，`groups.pair_clf` 的证据 `glyph_match.stage.pair`）。→ 改字的格数。

    只改字，不改 admit／通道／provenance。读第 5 步 5a.3 的证据行 `{pair, tier, p, lean, char?, cand, rank}`：`char` 只在把握过该对的
    门槛（档 ≥2）时才有。条件见参数说明；同一格里含放行字的几对给了不同的字就都不动（宁缺不错）。"""
    from ..groups import pair_attr
    table = {} if p.pair_form == "-" else pair_attr.load(p.pair_form)
    canon = ctx.book.canonical_char if (ctx is not None and getattr(ctx.book, "codepoints", None)) else None
    n = 0
    for col in out:
        for rec in col.chars or []:
            if not rec.admit or not rec.char or rec.provenance == "human" or rec.channel == "human":
                continue
            m = mmap.get(rec.id)
            rows = ((getattr(m, "stage", None) or {}).get("pair") or []) if m is not None else []
            want: dict[str, dict] = {}
            for r in rows:
                pr, ch = r.get("pair"), r.get("char")
                if not ch or len(pr or "") != 2 or rec.char not in pr or ch == rec.char or ch not in pr:
                    continue
                if pair_attr.attr_of(table, pr[0], pr[1]) != "shape":
                    continue
                want[ch] = r
            if len(want) != 1:
                continue
            new, row = next(iter(want.items()))
            if canon is not None and canon(new) != new:
                continue
            if p.pair_form != "-" and not (table.get(pair_attr.pair_key(*row["pair"])) or {}).get("variant"):
                # 异字对（表里没标 variant: true）：字形与放行字相反只记证据进复审，不自动改（Sheldon 11-18 同意）
                rec.evidence = {**(rec.evidence or {}), "pair_form_review": {"from": rec.char, "to": new, "pair": row["pair"], "p": row.get("p")}}
                continue
            rec.evidence = {**(rec.evidence or {}),
                            "pair_form": {"from": rec.char, "to": new, "pair": row["pair"], "tier": row.get("tier"),
                                          "p": row.get("p"), "rank": row.get("rank")}}
            rec.char = new
            n += 1
    return n
