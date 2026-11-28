"""C1 进库准入（`seed_admit`）的「格况」判定（第四步 4c `cell_state`）：这一格有没有字、被印章／墨点／切坏／符号占了没有。

判完怎么放行仍由收尾（`seed_admit.SeedAdmitStep`）定。CV4 整理 P1a（2026-11-28）从 seed_admit.py、seed_admit_lanes.py **原样搬来，不改行为**。
"""

from __future__ import annotations

from ..core.step import RunContext
from ..products.kinds.recog import PageAlignRef
from ..products.kinds.recog import PageMatch
from ..utils.gap import is_gap
from .decide import _opt
from .seed_admit_common import _LANE_HARD
from .seed_admit_common import _demote
from .seed_admit_params import SeedAdmitParams
import re



_JIAZHU_UNEVEN_RE = re.compile(r"jiazhu_uneven:(\d+)-(\d+)")


def _jiazhu_uneven_pass(ctx: RunContext, page: int, out: list, mmap: dict | None = None,
                        amap: dict | None = None, coord: dict | None = None) -> int:
    """雙行小注分法不均闸（只降级）。→ 降级格数。

    Step3 雙行小注逐步切（书级钩子 `impl/keben/jiazhu_step`，史記书仓覆盖）按整理本分法切、两行分法不是 ⌈N/2⌉／⌊N/2⌋ 的段，
    列旗记 `jiazhu_uneven:<首格>-<末格>`；段内的夹注格（sub a／b）送审，doubt 码 `jiazhu_uneven`、
    `evidence.seg_kind=jiazhu_uneven`（待审归 seg_defect，细分 jiazhu_uneven，review/reasons.py，A31 11-04 定）。
    已放行、且放行字＝字形库首选＝整理本字（三者一致，图上有字形证据）的格不降（第 10 轮整列送审 8 列 276 格、其中 210 格三者一致，11-04 收窄）。
    没有这面列旗（开关关、别的书）时什么都不做。备选格网（alt_columns）的列旗一并认：换了列的格也送审。人裁不动。"""
    cells = _opt(ctx, "cells", page)
    if cells is None:
        return 0
    spans: dict[int, list[tuple[int, int]]] = {}
    for cc in list(cells.columns) + list(getattr(cells, "alt_columns", None) or []):
        for fl in cc.flags or []:
            m = _JIAZHU_UNEVEN_RE.match(fl)
            if m:
                spans.setdefault(cc.col, []).append((int(m.group(1)), int(m.group(2))))
    if not spans:
        return 0
    n = 0
    for col in out:
        sp = spans.get(col.col)
        if not sp:
            continue
        for rec in col.chars or []:
            if rec.sub not in ("a", "b") or not any(a <= rec.slot <= b for a, b in sp):
                continue
            if rec.provenance == "human" or rec.channel == "human":
                continue
            if rec.admit and _jiazhu_three_agree(rec, (mmap or {}).get(rec.id), amap or {}, coord or {}):
                continue                      # 放行字＝库首选＝整理本字：图上有字形证据说这格切对了，不降（第 10 轮 8 列 210 格，11-04）
            if "jiazhu_uneven" not in (rec.doubts or []):
                rec.doubts = list(rec.doubts or []) + ["jiazhu_uneven"]
            rec.evidence = {**(rec.evidence or {}), "seg_kind": "jiazhu_uneven"}
            if rec.admit:
                _demote(rec, "jiazhu_uneven")
                rec.admit, rec.channel, rec.provenance = False, None, ""
                n += 1
    return n


def _jiazhu_three_agree(rec, m, amap: dict, coord: dict) -> bool:
    """放行字、字形库首选、整理本字（现役对位，没有就坐标对位）三者相同。"""
    top = (m.candidates[0][0] if m is not None and m.candidates else None)
    ref = (amap.get(rec.id) or (None, None))[0] or coord.get(rec.id)
    return bool(rec.char) and top == rec.char and ref == rec.char


_LIB_CHANNELS = ("match_", "dual", "iron")


def _symbol_review_pass(ctx: RunContext, page: int, p: "SeedAdmitParams", out: list, mmap: dict,
                        human_shapes: dict) -> int:
    """特殊符号送审（只降级，放在各补放遍之后、human_unbound 之前）。→ 降级格数。见 `SeedAdmitParams.symbol_review`。"""
    from collections import Counter

    from .align_ref import rare_topk_map
    from ..hanzi.symbols import is_symbol
    rtop = rare_topk_map(_opt(ctx, "rare_candidates", page), 1)
    n_human = Counter(c for c in human_shapes.values() if is_symbol(c))
    n = 0
    for col in out:
        for rec in col.chars or []:
            if rec.provenance == "human" or rec.channel == "human":
                continue
            m = mmap.get(rec.id)
            lib_top = getattr(m, "char", None) if m is not None else None
            rare_top = (rtop.get(rec.id) or [None])[0]
            hint = [c for c in (rec.char, lib_top, rare_top) if c and is_symbol(c)]
            if not hint:
                continue
            ch_ = rec.channel or ""
            if rec.admit and rec.char and is_symbol(rec.char):
                down = not (ch_.startswith(_LIB_CHANNELS) and n_human[rec.char] >= p.symbol_min_human)
            else:
                down = rec.admit and ch_.startswith("context")
            if down:
                _demote(rec, "symbol_review")
                rec.admit, rec.channel, rec.provenance = False, None, ""
                n += 1
            if not rec.admit:
                rec.doubts = list(dict.fromkeys(list(rec.doubts or []) + ["symbol"]))
                rec.evidence = {**(rec.evidence or {}), "symbol": hint[0]}
    if n:
        ctx.log(f"seed_admit p{page}: 特殊符号送审 {n} 格（doubt symbol）")
    return n


#: 盖章空栏判空不碰的强通道（context 不在内：vol04 p220 那个经 context 误放行的「一」要能改掉）
_SEAL_STRONG = frozenset({"match_ref", "match_solo", "witness3", "match_margin", "iron"})


def _seal_blank_flip(out: list, seal: dict, coord: dict) -> int:
    """盖章空栏判空的格级保险（`seal_blank_page`，道 B 规格 overview#493）。→ 从放行挪走的格数。

    `seal` 是 `occlusion.page_seal_blank` 的候选格（印框内、重叠够）。候选格同时满足下列三条才挪：
    ①坐标对位无字（缺失或空串；`〓` 占位算有字）；②未被强通道放行（`_SEAL_STRONG`）；③非人裁、非排除、
    不是已被密度遮挡闸（`occluded`）管着的格。挪法：`admit=False`、`char=None`、doubts 记 `occluded`、
    evidence 记 `occluded.via=coord_blank、ref_blank=True`——与 `_review_lanes_pass` 的 coord_blank 分支接上。
    只改格、不改别的；不做任何判空，判非字由 lane 的 `lane_seal` 来做。"""
    if not seal:
        return 0
    demoted = 0
    for col in out:
        for rec in col.chars or []:
            hit = seal.get((col.col, rec.slot, rec.sub or ""))
            if hit is None or rec.channel == "human" or rec.provenance == "human":
                continue
            doubts = set(rec.doubts or [])
            if "excluded" in doubts or "occluded" in doubts:
                continue
            if rec.admit and rec.channel in _SEAL_STRONG:
                continue
            if coord.get(rec.id):                # 坐标对位有字（非空串）：不是空栏
                continue
            if rec.admit:
                demoted += 1
            _demote(rec, "seal_blank_flip")
            rec.admit, rec.channel, rec.char, rec.provenance = False, None, None, ""
            rec.doubts = sorted(doubts | {"occluded"})
            rec.evidence = {**(rec.evidence or {}),
                            "occluded": {"via": "coord_blank", "ref_blank": True,
                                         "seal_blank": hit["seal_score"], "overlap": hit["overlap"]}}
    return demoted


#: 1：`follow_ref` 表里有整理本形、本格字不是表里那一形时，仍按参校本取异体（cv#1438）。



def _header_formula_pass(ctx: RunContext, page: int, p: "SeedAdmitParams", out: list) -> int:
    """`lane_header_formula`：题列（列旗 `header_ref:<整理本行>`）整行是套语、字格数＝字数 → 未放行的格按整理本行逐字放行。→ 放行格数。"""
    cells = _opt(ctx, "cells", page)
    if cells is None:
        return 0
    formula = re.compile(p.lane_header_formula_re)
    lines: dict[int, str] = {}
    for cc in cells.columns:
        # 列端有格被判成框线／碎墨记空（layout_frame_junk）＝这一列格位与字对不上，数字数靠不住
        if any(fl.startswith("layout_frame_junk") for fl in cc.flags or []):
            continue
        for fl in cc.flags or []:
            if fl.startswith("header_ref:") and formula.fullmatch(fl[len("header_ref:"):]):
                lines[cc.col] = fl[len("header_ref:"):]
    n = 0
    for col in out:
        line = lines.get(col.col)
        if not line:
            continue
        recs = [r for r in (col.chars or []) if "excluded" not in (r.doubts or []) or r.char]
        try:
            recs.sort(key=lambda r: int(str(r.id).split(":")[3].rstrip("ab")))
        except (IndexError, ValueError):
            continue
        if len(recs) != len(line):
            continue
        # 已放行的格与整理本行同位字不一致：个别格是机器放错（一/二、九/十 近形，目錄页题列常见），按整理本改；
        # 超过三分之一不一致＝整列错位（字数碰巧相等），整列不动。人裁的格不碰。
        conflicts = sum(1 for r, ch in zip(recs, line)
                        if r.admit and r.char and r.char != ch and r.channel != "human" and r.provenance != "human")
        if conflicts * 3 > len(recs):
            continue
        for rec, ch in zip(recs, line):
            if rec.channel == "human" or rec.provenance == "human" or (rec.admit and rec.char == ch):
                continue
            ev = rec.evidence or {}
            prev_char, prev_admit = rec.char, rec.admit
            rec.admit, rec.channel, rec.provenance, rec.char = True, "header_formula", "align", ch
            rec.evidence = {**ev, "lane": {"lane": "header_formula", "line": line, "prev_admit": prev_admit,
                                           "prev_doubts": list(rec.doubts or []), "prev_char": prev_char},
                            "no_glyph_lib": True}
            rec.doubts = ["lane_header_formula"]
            n += 1 if not prev_admit else 0
    return n


def _occluded(ctx: RunContext, page: int, match: PageMatch, p: "SeedAdmitParams",
              amap: dict) -> dict[str, tuple[float, str | None, str]]:
    """本页被印章／大片污损遮住的格 → {字位 id: (密度, 默认字, 默认字来源)}。

    来源：`coord`（坐标对位的整理本字）/ `coord_blank`（坐标对位说是空格位，默认字 None）/
    `align`（现役对位字）/ `none`。读不到 Step3 字格或原图就当没有遮挡（返回空表）。"""
    from .occlusion import page_occluded
    hit = page_occluded(ctx, page, p)
    if not hit:
        return {}
    ref: PageAlignRef | None = _opt(ctx, "align_ref", page)
    coord = {c.id: c.ref_char for c in (ref.coord if ref else [])}
    past = set()
    if ref is not None:
        from .align_ref_coord import COORD_PAST_LEAF
        past = {int(k) for k, v in ref.coord_fallback.items() if v == COORD_PAST_LEAF}
    if p.occluded_ref_empty_blank and ref is not None:
        past |= {int(k) for k, v in ref.coord_fallback.items() if v == "整理本行为空"}
    manual = _manual_seal_cells(ctx, page) if p.occluded_manual_seal_blank else set()
    out: dict[str, tuple[float, str | None, str]] = {}
    for cc in match.columns:
        # 整理本这半叶没有这一列、现役对位也没给这一列任何字 → 整理本说这儿没字
        # （`occluded_seal_align_yield`：印纹上被现役对位硬配的字不算）
        blank_col = cc.col in past and not any(
            r.id in amap and not (p.occluded_seal_align_yield and (cc.col, r.slot, r.sub or "") in hit)
            for r in cc.chars)
        for r in cc.chars:
            dens = hit.get((cc.col, r.slot, r.sub or ""))
            if dens is None:
                continue
            seal_blank = (r.id not in coord
                          and ((blank_col and p.occluded_seal_align_yield)
                               or (cc.col, r.slot, r.sub or "") in manual)
                          and not _lib_reads_char(r, p.occluded_seal_keep_cov))
            if seal_blank:
                # 整理本说这儿没字／人定印框：印纹上的现役对位字不作默认字
                out[r.id] = (dens, None, "coord_blank")
            elif r.id in coord and is_gap(coord[r.id]):
                # 逐列本里没有码表的 PUA 生僻字占位：知道这儿有字、不知道是哪个
                out[r.id] = (dens, None, "coord_pua")
            elif r.id in coord:
                ch = coord[r.id]
                out[r.id] = (dens, ch or None, "coord" if ch else "coord_blank")
            elif r.id in amap:
                out[r.id] = (dens, amap[r.id][0], "align")
            elif blank_col:
                out[r.id] = (dens, None, "coord_blank")
            else:
                out[r.id] = (dens, None, "none")
    return out


def _lib_reads_char(r, keep_cov: float) -> bool:
    """库认得出这一格（判 same，或判 unsure 且首位相似度 ≥ `keep_cov`）：印压真字，不按印纹判空。"""
    if r.verdict == "same":
        return True
    top = max((float(c[1]) for c in (r.candidates or [])), default=float(r.cov or 0.0))
    return r.verdict == "unsure" and top >= keep_cov


def _manual_seal_cells(ctx: RunContext, page: int) -> set[tuple[int, int, str]]:
    """人定印框（`seals` 产物里 `source="manual"` 的印）压着的格 {(col, slot, sub)}；重叠门槛同遮挡判据
    （大印 `OCC_SEAL_OVERLAP`、小印 `OCC_CRISP_OVERLAP`）。没有 `seals` 产物或 Step3 字格就是空集。"""
    from .occlusion import OCC_CRISP_OVERLAP, OCC_SEAL_OVERLAP, seal_overlap_cells
    has = getattr(ctx, "has_product", None)
    if has is None or not has("seals", page):
        return set()
    seals = [s for s in ctx.product("seals", page).seals if s.source == "manual"]
    cells = _opt(ctx, "cells", page) if seals else None
    if cells is None:
        return set()
    return (set(seal_overlap_cells(cells, seals, "stain", OCC_SEAL_OVERLAP))
            | set(seal_overlap_cells(cells, seals, "crisp", OCC_CRISP_OVERLAP)))


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


# ── 字框几何闸 `seg_box_check`（CV2，2026-11-27，朱楓林集 MBJ 报）────────────────────────────────
#: 判据（单位：格高 period、页参考列宽 ref_w；双行小注半格只查过高）。MBJ 01 册 13,676 框实测（实验记录
#: 2026-11-27-网站标注与字框检查.md）：命中 15 框，13 框本来就在待审单里，自动放行里 2 框看图都是真错
#: （3:4:7 碎格放行成「一」、25:2:6「其二」劈成三框）。
SEG_BOX_FRAME_H, SEG_BOX_FRAME_W = 0.12, 0.6     # frame_line：扁长一条——框线／界行残段


SEG_BOX_SPECK = 0.25                             # speck：高、宽都小于它——墨点


SEG_BOX_SPLIT_H, SEG_BOX_SPLIT_W = 0.62, 0.85    # split_pair：半截字（高 [0.12, 0.62)、宽 <0.85）……


SEG_BOX_SPLIT_NB, SEG_BOX_SPLIT_SUM = 0.9, 1.25  # ……邻框也不满一格（<0.9），两框合起来 <1.25 格——一字劈两框


SEG_BOX_TALL = 1.6                               # tall：一框高过 1.6 格——两字并一框或污渍


SEG_BOX_SLIVER = 0.35                            # sliver：Step3 格高 <0.35 格（同 row_segment_gate.sliver_ratio，L4 碎格）


#: 判据 → `evidence.seg_kind`（guji-manager review/reasons.SEG_KINDS 认的细分；不在表里的只记 `evidence.seg_box`）。
SEG_BOX_KIND = {"frame_line": "frame_residue", "tall": "merged", "split_pair": "clipped"}


SEG_BOX_CRITERIA = ("sliver", "frame_line", "speck", "split_pair", "tall")


def _g(x, k, d=None):
    return x.get(k, d) if isinstance(x, dict) else getattr(x, k, d)


def seg_box_defects(char_cols, period: float | None, ref_w: float | None,
                    cell_cols=None) -> dict[str, list[str]]:
    """字框几何不合理的格 → {格 id: [判据…]}。纯函数，产物（`char_index.columns`、`cells.columns`）或其 dict 都收。

    `char_cols` 逐列逐字框（`cell_type == "char"`）按格高 `period`、参考列宽 `ref_w` 判 frame_line／speck／split_pair／tall；
    `cell_cols`（Step3 `cells.columns`，可缺）补 sliver：格高 < `SEG_BOX_SLIVER`×本列 period 的正文格（职名列、小字格不查）。"""
    out: dict[str, list[str]] = {}
    if period and period > 0:
        rw = ref_w if ref_w and ref_w > 0 else None
        for c in char_cols or []:
            chars = [x for x in (_g(c, "chars") or []) if _g(x, "cell_type") == "char"]
            main = [x for x in chars if not _g(x, "sub")]
            for x in chars:
                h = float(_g(x, "height") or 0.0) / period
                w = (float(_g(x, "width") or 0.0) / rw) if rw else None
                why: list[str] = []
                if h > SEG_BOX_TALL:
                    why.append("tall")
                if not _g(x, "sub") and w is not None:
                    if h < SEG_BOX_FRAME_H and w >= SEG_BOX_FRAME_W:
                        why.append("frame_line")
                    elif h < SEG_BOX_SPECK and w < SEG_BOX_SPECK:
                        why.append("speck")
                    if SEG_BOX_FRAME_H <= h < SEG_BOX_SPLIT_H and w < SEG_BOX_SPLIT_W:
                        j = next((i for i, y in enumerate(main) if y is x), -1)
                        for k in (j - 1, j + 1):
                            if j < 0 or not 0 <= k < len(main):
                                continue
                            y = main[k]
                            bx, by = _g(x, "bbox_page"), _g(y, "bbox_page")
                            if not bx or not by or float(_g(y, "height") or 0.0) / period >= SEG_BOX_SPLIT_NB:
                                continue
                            if (max(bx[3], by[3]) - min(bx[1], by[1])) / period < SEG_BOX_SPLIT_SUM:
                                why.append("split_pair")
                                break
                if why:
                    out.setdefault(str(_g(x, "id")), []).extend(why)
    if cell_cols:
        ids = {(_g(c, "col"), _g(x, "slot")): str(_g(x, "id")) for c in (char_cols or [])
               for x in (_g(c, "chars") or []) if _g(x, "cell_type") == "char" and not _g(x, "sub")}
        for cc in cell_cols:
            per = _g(cc, "period") or 0
            if not _g(cc, "ok") or per <= 0 or "roster" in (_g(cc, "flags") or []):
                continue
            for cell in _g(cc, "cells") or []:
                if _g(cell, "sub"):
                    continue
                if (float(_g(cell, "y1")) - float(_g(cell, "y0"))) < SEG_BOX_SLIVER * per:
                    cid = ids.get((_g(cc, "col"), _g(cell, "slot")))
                    if cid and "sliver" not in out.get(cid, []):
                        out.setdefault(cid, []).append("sliver")
    return out


def _seg_box_pass(ctx: RunContext, page: int, out: list, kinds=SEG_BOX_CRITERIA) -> int:
    """字框几何闸（只降级，`SeedAdmitParams.seg_box_check`）。→ 降级格数。碎格、框线扁条、墨点、一字劈两框、过高框一律送审：
    doubt 码 `seg_defect`（待审原因归 seg_defect），`evidence.seg_box` 记判据、能对上 SEG_KINDS 的写 `evidence.seg_kind`。人裁不动。"""
    try:
        ci = ctx.product("char_index", page)
    except Exception:                     # noqa: BLE001
        return 0
    gate = cells = None
    for kind in ("gate_manifest", "cells"):
        try:
            v = ctx.product(kind, page)
        except Exception:                 # noqa: BLE001 —— 缺了照样判能判的
            v = None
        if kind == "gate_manifest":
            gate = v
        else:
            cells = v
    period, ref_w = _g(gate, "period"), _g(gate, "ref_w")
    if not period:
        pers = sorted(float(_g(cc, "period")) for cc in (_g(cells, "columns") or []) if _g(cc, "period"))
        period = pers[len(pers) // 2] if pers else None
    if not ref_w:
        ws = sorted(float(_g(x, "width") or 0) for c in _g(ci, "columns") or [] for x in _g(c, "chars") or []
                    if _g(x, "cell_type") == "char" and not _g(x, "sub"))
        ref_w = ws[len(ws) // 2] if ws else None
    on = set(kinds)
    bad = {k: w for k, why in seg_box_defects(_g(ci, "columns"), period, ref_w,
                                              _g(cells, "columns") if "sliver" in on else None).items()
           if (w := [x for x in why if x in on])}
    if not bad:
        return 0
    n = 0
    hits: list[str] = []
    for col in out:
        for rec in col.chars or []:
            why = bad.get(rec.id)
            if not why or rec.provenance == "human" or rec.channel == "human":
                continue
            ev = {**(rec.evidence or {}), "seg_box": list(why)}
            kind = next((SEG_BOX_KIND[w] for w in why if w in SEG_BOX_KIND), None)
            if kind:
                ev["seg_kind"] = kind
            rec.evidence = ev
            rec.doubts = list(dict.fromkeys(list(rec.doubts or []) + ["seg_defect"]))
            if rec.admit:
                _demote(rec, "seg_box_check")
                hits.append(f"{rec.id}「{rec.char}」{'/'.join(why)}")
                rec.admit, rec.channel, rec.provenance = False, None, ""
                n += 1
    if hits:
        ctx.log(f"seed_admit p{page}: 字框几何闸 {len(hits)} 格退回待审（doubt seg_defect）：{'；'.join(hits)}")
    return n


#: 墨点格与同列（横向有重叠的）非墨点字框纵向相距不到这么多×本页字宽中位数，就当切坏的半字（朱楓林集 53:5:8「夫」上一竖贴着下半，-10px；
#: 孤立墨点 ≥44px，两个相邻墨点 25:9:8/9 互不算）
SPECK_HALF_GAP = 0.2


def _speck_halves(char_cols) -> set[str]:
    """`ink_speck` 格里贴着同列别的字的（`SPECK_HALF_GAP`）：切坏的半字。→ 格 id 集合。"""
    ws = sorted(float(_g(x, "width") or 0) for c in char_cols for x in (_g(c, "chars") or [])
                if _g(x, "cell_type") == "char" and not _g(x, "sub"))
    if not ws:
        return set()
    lim = SPECK_HALF_GAP * ws[len(ws) // 2]
    out: set[str] = set()
    for c in char_cols:
        xs = [x for x in (_g(c, "chars") or []) if _g(x, "cell_type") == "char" and not _g(x, "sub") and _g(x, "bbox_page")]
        for x in xs:
            if "ink_speck" not in (_g(x, "flags") or []):
                continue
            b = _g(x, "bbox_page")
            for y in xs:
                if y is x or "ink_speck" in (_g(y, "flags") or []):
                    continue
                yb = _g(y, "bbox_page")
                if min(b[2], yb[2]) - max(b[0], yb[0]) > 0 and max(yb[1] - b[3], b[1] - yb[3]) < lim:
                    out.add(str(_g(x, "id")))
                    break
    return out


# ── 格级墨迹记号 `ink_marks`（CV2，2026-11-28，朱楓林集 MBJ 报）────────────────────────────────────
def _ink_mark_pass(ctx: RunContext, page: int, out: list, amap: dict) -> int:
    """`SeedAdmitParams.ink_marks`：读 Step4 格旗 `ink_seal`／`ink_speck`（`cell_shrink.ink_marks`）。→ 放行格数净增（可负）。

    「对位无字」＝逐字对位（`amap`，align_ref）里这格没有参校本字。印（旗 `ink_seal` 或已判 `occluded`）：对位无字 → 非字放行
    （通道 seal，同 `_review_lanes_pass` coord_blank 那支的写法）；有字 → 送审 occluded。墨点（旗 `ink_speck`）：对位无字 → 非字放行
    （通道 blank_ink，同 `_blank_ink_pass`）；有字 → 送审 seg_defect。人裁、排除名单上的格不动。"""
    try:
        ci = ctx.product("char_index", page)
    except Exception:                     # noqa: BLE001
        return 0
    flags = {str(_g(x, "id")): set(_g(x, "flags") or []) for c in (_g(ci, "columns") or []) for x in (_g(c, "chars") or [])}
    half = _speck_halves(_g(ci, "columns") or [])
    n = 0
    for col in out:
        for rec in col.chars or []:
            fl = flags.get(rec.id, set())
            doubts = set(rec.doubts or [])
            if rec.provenance == "human" or rec.channel == "human" or "excluded" in doubts:
                continue
            seal = "ink_seal" in fl or "occluded" in doubts
            speck = "ink_speck" in fl and not seal
            if not (seal or speck):
                continue
            ref = (amap.get(rec.id) or (None,))[0]
            ev = rec.evidence or {}
            if speck and rec.id in half:
                ev = {**ev, "speck_half": True}       # 贴着同列别的字：多是切坏的半字，不判非字
            if not ref and not (speck and rec.id in half):
                if rec.admit and rec.char is None and rec.channel in ("seal", "blank_ink"):
                    continue
                was = rec.admit
                lane, via = ("seal", "ink_seal") if seal else ("blank_ink", "ink_speck")
                rec.admit, rec.channel, rec.provenance, rec.char = True, lane, lane, None
                rec.evidence = {**ev, "lane": {"lane": lane, "via": via, "nonchar": True, "ref_blank": True,
                                               "prev_doubts": sorted(doubts)}, "no_glyph_lib": True}
                rec.doubts = ["lane_seal" if seal else "blank_ink"]
                n += 0 if was else 1
                continue
            if seal:
                if "occluded" in doubts and not rec.admit:
                    continue
                if rec.admit:
                    _demote(rec, "ink_marks")
                    n -= 1
                rec.admit, rec.channel, rec.provenance, rec.char = False, None, "", ref
                rec.evidence = {**ev, "occluded": ev.get("occluded") or {"via": "ink_seal"}}
                rec.doubts = sorted(doubts | {"occluded"})
            else:
                rec.evidence = {**ev, "seg_box": sorted(set(ev.get("seg_box") or []) | {"ink_speck"})}
                rec.doubts = list(dict.fromkeys([*(rec.doubts or []), "seg_defect"]))
                if rec.admit:
                    _demote(rec, "ink_marks")
                    rec.admit, rec.channel, rec.provenance = False, None, ""
                    n -= 1
    if n:
        ctx.log(f"seed_admit p{page}: 墨迹记号 放行净增 {n} 格")
    return n
