"""C1 进库准入（`seed_admit`）的备选切法挑列：主切法与备选切法两套都准入后按列挑一份（`alt_select=admit`）。

CV4 整理 P1a（2026-11-28）从 seed_admit.py **原样搬来，不改行为**。
"""

from __future__ import annotations

from ..products.kinds.recog import PageAdmit
from contextvars import ContextVar



#: alt_cut 准入后定列（`AlignRefParams.alt_select="admit"`，2026-11-04，A22 评审过）
ALT_ADMIT_MIN_GAIN = 2        # 备选那遍这一列待审格至少少这么多


ALT_CV_MIN_CELLS = 6          # 正文整字格不到这么多的列不比墨高一致性


ALT_CV_RATIO = 1.2            # 备选那份墨高变异系数 ≤ 主切法 × 这个


ALT_CV_MAX = 0.35             # 且 ≤ 这个


#: 换列要不要求「有字形背书的放行格不比主切法少」。125 页 A/B（11-04）：要求时待审 740→734，不要求 740→695；
#: 不要求时多放的 55 格看图 51 对（多走 coord_fallback/witnesses_coord，半色调、褪色页为主）。
#: 用户 11-04 定要求（B）：换列不让整理本当主证据。
ALT_REQUIRE_BACKED = True


#: 首格切坏守卫（只拦、不放）：备选那份首个正文整字格墨高 > 本列其余正文整字格墨高中位数 × 这个，就不换（03:65:7 一类）
ALT_FIRST_CELL_MAX = 1.6


#: 有字形背书的放行通道（只凭整理本＋证人的 witnesses_coord、follow_ref 不算）
_BACKED = frozenset({"match_ref", "match_solo", "match_solo_ocr", "match_solo_5b", "match_num_run", "match_solo_adapt", "match_solo_cal", "match_lead_5b", "iron", "seal", "group_flow", "ref_lib_coord"})


#: 选列那两遍准入不跑 `p_ref`（换列不让整理本当主证据）：p_ref 在后面几条跟整理本的通道之前把待审格取整理本字，
#: 两遍放得不对称，选列就跟着变（史記 r19 离线开 p_ref：06:26:1 主切法一格两字「陳索」、备选格网切对，开 p_ref 后不换；
#: 1.77 把 p_ref 格按待审算又多换了几列，因为这些格不开 p_ref 时由后面的通道放）。SJ 11-08。
_NO_P_REF: "ContextVar[bool]" = ContextVar("seed_admit_no_p_ref", default=False)


def _opt_product(ctx, kind: str, page: int):
    try:
        return ctx.product(kind, page)
    except Exception:                          # noqa: BLE001
        return None


def _col_stats(adm: PageAdmit, col: int, ref) -> tuple[int, int, int]:
    """一列的（待审格数、有字形背书的放行格数、与坐标字冲突的放行格数）。"""
    c = adm.column(col)
    coord = {(r.slot, r.sub or ""): r.ref_char for r in (getattr(ref, "coord", None) or []) if r.col == col}
    review = backed = conflict = 0
    for r in (c.chars if c else []):
        if r.admit:
            via = (r.evidence.get("lane") or {}).get("via") if isinstance(r.evidence.get("lane"), dict) else None
            if r.channel in _BACKED or (r.channel == "coord_fallback" and via == "lib_coord_primary"):
                backed += 1
            rc = coord.get((r.slot, r.sub or ""))
            if rc and r.char and r.char != rc:
                conflict += 1
        elif "excluded" not in r.evidence:
            review += 1
    return review, backed, conflict


def _ink_cv(chars, col: int) -> tuple[float | None, int]:
    """一列正文整字格（不含夹注半格、抬头格、空格）的墨高变异系数与格数。"""
    import statistics
    cc = next((c for c in (getattr(chars, "columns", None) or []) if c.col == col), None)
    hs = [r.bbox_page[3] - r.bbox_page[1] for r in (cc.chars if cc else [])
          if not getattr(r, "sub", None) and getattr(r, "slot", 0) >= 1 and getattr(r, "patch_key", None)
          and getattr(r, "bbox_page", None)]
    if len(hs) < ALT_CV_MIN_CELLS:
        return None, len(hs)
    m = statistics.fmean(hs)
    return (statistics.pstdev(hs) / m if m else None), len(hs)


def _first_cell_tall(chars, col: int) -> bool:
    """备选那份这一列首个正文整字格墨高是否超过其余正文整字格中位数的 `ALT_FIRST_CELL_MAX` 倍（其余不到 3 格不判）。"""
    import statistics
    cc = next((c for c in (getattr(chars, "columns", None) or []) if c.col == col), None)
    rs = sorted((r for r in (cc.chars if cc else [])
                 if not getattr(r, "sub", None) and getattr(r, "slot", 0) >= 1 and getattr(r, "patch_key", None)
                 and getattr(r, "bbox_page", None)), key=lambda r: r.slot)
    if len(rs) < 4:
        return False
    hs = [r.bbox_page[3] - r.bbox_page[1] for r in rs]
    med = statistics.median(hs[1:])
    return med > 0 and hs[0] > ALT_FIRST_CELL_MAX * med


def _unmatched(adm: PageAdmit, col: int, ref) -> int:
    """一列里没有坐标对位字的格数（不含排除格）：坐标对位字在 `ref.coord` 里按格 id 查。"""
    have = {r.id for r in (getattr(ref, "coord", None) or []) if r.col == col}
    c = adm.column(col)
    return sum(1 for r in (c.chars if c else []) if r.id not in have and "excluded" not in r.evidence)


ALT_TEXT_EQ_GAIN = 2         # 不分行参照页：备选那份这一列与参照文字 equal 的字至少多这么多


ALT_TEXT_RATE_SLACK = 0.05   # 不分行参照页：备选那份这一列放行率比主切法低这么多以内


def _admit_rate(adm: PageAdmit, col: int) -> float:
    """一列放行格占非排除格的比例。"""
    c = adm.column(col)
    rs = [r for r in (c.chars if c else []) if "excluded" not in r.evidence]
    return sum(1 for r in rs if r.admit) / len(rs) if rs else 0.0


def _eq_count(ref, col: int) -> int:
    """一列里对齐到参照文字、且是 equal 段的字数（`align_ref.chars`）。"""
    return sum(1 for r in (getattr(ref, "chars", None) or []) if r.col == col and r.align_op == "equal")


def _note_spans(chars, col: int) -> list[tuple[float, float]]:
    """一列雙行小注格（有 sub 的格）的页内 y 范围，按格号并成一段段。"""
    cc = next((c for c in (getattr(chars, "columns", None) or []) if c.col == col), None)
    ys = sorted((r.bbox_page[1], r.bbox_page[3]) for r in (cc.chars if cc else [])
                if getattr(r, "sub", None) and getattr(r, "bbox_page", None))
    out: list[list[float]] = []
    for y0, y1 in ys:
        if out and y0 <= out[-1][1]:
            out[-1][1] = max(out[-1][1], y1)
        else:
            out.append([y0, y1])
    return [(a, b) for a, b in out]


def _note_region_ok(main: PageAdmit, alt: PageAdmit, col: int, ref_main, ref_alt, chars_main, chars_alt) -> bool:
    """`alt_note_region`：备选有小注格、主切法在小注范围里放行的字备选也放行，小注范围外待审不多、冲突不多。"""
    spans = _note_spans(chars_alt, col)
    if not spans:
        return False

    def inside(chars, rec_ok):
        cc = next((c for c in (getattr(chars, "columns", None) or []) if c.col == col), None)
        keys = set()
        for r in (cc.chars if cc else []):
            bb = getattr(r, "bbox_page", None)
            if bb and rec_ok(r) and any(a <= (bb[1] + bb[3]) / 2 <= b for a, b in spans):
                keys.add((r.slot, getattr(r, "sub", None) or ""))
        return keys
    in_main = inside(chars_main, lambda r: True)
    if any(sub for _s, sub in in_main):  # 主切法在这里已认出小注：不是「并成大字」那种错，照常比
        return False
    in_alt = inside(chars_alt, lambda r: getattr(r, "sub", None))
    cm, ca = main.column(col), alt.column(col)
    if not in_main or cm is None or ca is None:
        return False
    from collections import Counter
    got_m = Counter(r.char for r in cm.chars if r.admit and (r.slot, r.sub or "") in in_main)
    got_a = Counter(r.char for r in ca.chars if r.admit and (r.slot, r.sub or "") in in_alt)
    if got_m - got_a:                    # 主切法在小注范围里放出的字，备选那份也得放出来
        return False

    return _outside_not_worse(main, alt, col, ref_main, ref_alt, in_main, in_alt)


def _outside_not_worse(main: PageAdmit, alt: PageAdmit, col: int, ref_main, ref_alt, in_main, in_alt) -> bool:
    """两遍各去掉换切的那段格，其余格备选那遍待审不多、与坐标字冲突不多。"""
    def outside(adm, ref, skip):
        coord = {(r.slot, r.sub or ""): r.ref_char for r in (getattr(ref, "coord", None) or []) if r.col == col}
        rv = cf = 0
        for r in adm.column(col).chars:
            if (r.slot, r.sub or "") in skip or "excluded" in r.evidence:
                continue
            if not r.admit:
                rv += 1
            elif coord.get((r.slot, r.sub or "")) and r.char != coord[(r.slot, r.sub or "")]:
                cf += 1
        return rv, cf
    rm, km = outside(main, ref_main, in_main)
    ra, ka = outside(alt, ref_alt, in_alt)
    return ra <= rm and ka <= km


def _big_region_ok(main: PageAdmit, alt: PageAdmit, col: int, ref_main, ref_alt, chars_main, chars_alt) -> bool:
    """`alt_note_region` 反方向：主切法把一个大字劈成了 a/b 小注（左右结构的「脉」劈成「永」「月」，两半常常也是字、照样放行），
    备选同一处是一个大字格。备选那些大字格全放行、其余格不更差，就换（脉经 01 41:1、39:6）。"""
    def cols(chars):
        return next((c for c in (getattr(chars, "columns", None) or []) if c.col == col), None)
    cm_, ca_ = cols(chars_main), cols(chars_alt)
    cm, ca = main.column(col), alt.column(col)
    if cm_ is None or ca_ is None or cm is None or ca is None:
        return False
    pairs: dict[int, list] = {}
    for r in cm_.chars:
        if getattr(r, "sub", None) and getattr(r, "bbox_page", None):
            pairs.setdefault(r.slot, []).append(r)
    bigs = [r for r in ca_.chars if not getattr(r, "sub", None) and getattr(r, "bbox_page", None) and r.slot >= 1]
    in_main, in_alt = set(), set()
    for slot, rs in pairs.items():
        if {getattr(r, "sub", None) for r in rs} != {"a", "b"}:
            continue
        y0, y1 = min(r.bbox_page[1] for r in rs), max(r.bbox_page[3] for r in rs)
        for b in bigs:
            ov = min(y1, b.bbox_page[3]) - max(y0, b.bbox_page[1])
            if ov > 0.7 * (y1 - y0) and ov > 0.7 * (b.bbox_page[3] - b.bbox_page[1]):
                in_main |= {(slot, r.sub) for r in rs}
                in_alt.add((b.slot, ""))
    if not in_alt:
        return False
    if not all(r.admit for r in ca.chars if (r.slot, r.sub or "") in in_alt):
        return False
    return _outside_not_worse(main, alt, col, ref_main, ref_alt, in_main, in_alt)


def _pick_alt_cols(cand, main: PageAdmit, alt: PageAdmit, ref_main, ref_alt, chars_main, chars_alt,
                   require_matched: bool = False, backed_gain: int = 0, note_region: bool = False) -> list[int]:
    """逐列比两遍准入（错格闸已在 align_ref 剔过候选）：待审少 ≥ `ALT_ADMIT_MIN_GAIN`；与坐标字冲突的放行格不多；
    正文整字格墨高一致（够 `ALT_CV_MIN_CELLS` 格才比）；`ALT_REQUIRE_BACKED` 时有字形背书的放行格也不能少；
    备选首格不能过高（`ALT_FIRST_CELL_MAX`）。"""
    out = []
    for col in cand:
        if note_region and (_note_region_ok(main, alt, col, ref_main, ref_alt, chars_main, chars_alt)
                            or _big_region_ok(main, alt, col, ref_main, ref_alt, chars_main, chars_alt)):
            out.append(col)
            continue
        rm, bm, km = _col_stats(main, col, ref_main)
        ra, ba, ka = _col_stats(alt, col, ref_alt)
        cv_a, _ = _ink_cv(chars_alt, col)
        cv_m, _ = _ink_cv(chars_main, col)
        by_text = False
        if getattr(ref_main, "ref_kind", None) == "text":
            # 不分行参照页（没有坐标字）：放行率不能降（02 24:2 整列真小注换成大字格，格少了待审也少，放行率 13/40→0/20）；
            # 备选那份这一列与参照文字逐字相合（equal）的多出 ALT_TEXT_EQ_GAIN、待审不多，也换——大字被劈成小注时半字
            # 常常也是字、照样放行（「肺」→「月」「巿」），只比待审数挑不出来（脉经 02 31:3 待审 3→2）
            if _admit_rate(alt, col) < _admit_rate(main, col) - ALT_TEXT_RATE_SLACK:
                continue
            em, ea = _eq_count(ref_main, col), _eq_count(ref_alt, col)
            by_text = ea >= em + ALT_TEXT_EQ_GAIN and ra <= rm and ka <= km
        # 待审只少 1 格时，字形背书多出 backed_gain 也换（缺省 0 关）
        by_backed = backed_gain > 0 and ra <= rm - 1 and ba >= bm + backed_gain and ka <= km
        if not by_text and not by_backed and not (
                ra <= rm - ALT_ADMIT_MIN_GAIN and (ba >= bm or not ALT_REQUIRE_BACKED) and ka <= km):
            continue
        if cv_a is not None and cv_m is not None and (cv_a > cv_m * ALT_CV_RATIO or cv_a > ALT_CV_MAX):
            continue
        if _first_cell_tall(chars_alt, col):
            continue
        if require_matched and _unmatched(alt, col, ref_alt) > _unmatched(main, col, ref_main):
            continue
        out.append(col)
    return out


def _merge_admit(main: PageAdmit, alt: PageAdmit, chosen) -> PageAdmit:
    """主切法那遍为底，`chosen` 列换成备选那遍的；页计数按列差补。"""
    if not chosen:
        return main
    ch = set(chosen)

    def cnt(adm, col):
        c = adm.column(col)
        rs = c.chars if c else []
        ex = sum(1 for r in rs if "excluded" in r.evidence)
        au = sum(1 for r in rs if r.admit)
        return au, len(rs) - au - ex, ex
    n_auto, n_review, n_ex = main.n_auto, main.n_review, main.n_excluded
    for col in ch:
        a1, r1, e1 = cnt(main, col)
        a2, r2, e2 = cnt(alt, col)
        n_auto += a2 - a1
        n_review += r2 - r1
        n_ex += e2 - e1
    cols = [alt.column(c.col) if c.col in ch and alt.column(c.col) is not None else c for c in main.columns]
    return PageAdmit(page=main.page, n_auto=n_auto, n_review=n_review, n_excluded=n_ex,
                     columns=cols, alt_cols=sorted(ch))
