"""C1 进库准入（`seed_admit`）的定字：选刻形、铁证、独证、文意异议、码位表、书级钩子取数（收尾 `char_decide` 的前半）。

CV4 整理 P1a（2026-11-28）从 seed_admit.py **原样搬来，不改行为**。
"""

from __future__ import annotations

from . import seed_admit_common as _C
from ..core.step import RunContext
from ..products.kinds.recog import AdmitRec
from ..products.kinds.recog import PageMatch
from ..utils.gap import GAP_CHARS
from ..utils.gap import is_gap
from ..utils.image_io import imread as cv_imread
from .seed_admit_common import PatchUnavailable
from .seed_admit_common import _LANE_HARD
from .seed_admit_common import _demote
from .seed_admit_common import _direct_variant_edge
from .seed_admit_common import _is_consensus_same
from .seed_admit_common import _is_hanzi
from .seed_admit_groups import _ruling_han
from .seed_admit_groups import _vis_cache
from .seed_admit_params import SeedAdmitParams
from functools import lru_cache



def _codepoint_exempt(rec, book, no_exempt: tuple = ()) -> bool:
    """放行字落册码位的例外：这对字已有按刻形拆判的字组（`registry.SHAPE_GROUPS`，如 變𠮓 bian），
    码位归一只是兜底（「暂归一」），人裁的刻形、该组判出的刻形照录，不归一。
    vol04:197:7:3 人裁 變 被工作区 變→𠮓 改回 𠮓（A32 10-25 报），bian 组判出的 變 也一样被改回（A24 10-25）。"""
    tgt = book.canonical_char(rec.char)
    if tgt == rec.char:
        return False
    if ((rec.evidence or {}).get("hou_shape") or {}).get("char") == rec.char:
        return True                       # 候𠋫 书级刻形判法判出的 候 照录，不归 𠋫
    gids = _shape_split(rec.char, tgt) - frozenset(no_exempt)     # 书级 `codepoint_no_exempt`：这些拆判组的码位归一不留例外
    if not gids:
        return False
    if rec.channel == "human" or rec.provenance == "human":
        return True
    grp = (rec.evidence or {}).get("group") or {}
    return grp.get("id") in gids and grp.get("pick") == rec.char


@lru_cache(maxsize=256)
def _shape_split(a: str, b: str) -> frozenset[str]:
    """把 a、b 拆成两个字判的字组 id。两形同在一族（`FlowSpec.families`，如 guan 的 宫宮：族内只按库形最近取，
    宮→宫 是 sheldon 定的暂归一）不算拆判。"""
    from ..groups.registry import SHAPE_GROUPS
    return frozenset(g for g, s in SHAPE_GROUPS.items() if a in s.members and b in s.members
                     and not any(a in f and b in f for f in s.flow.families))


_JUAN_FORMS = frozenset("卷巻")


_JUAN_DOUBTS = frozenset({"replace_align", "context_vs_ref"})


_NUMERALS = frozenset("一二三四五六七八九十百千幾")


def _after_number(prev: AdmitRec, amap: dict, dmap: dict, mmap: dict) -> bool:
    """前一格（正文）的字是数字？取已定的字，没定就看整理本对齐字、再看库 top1。"""
    ch = prev.char
    if not ch and prev.id in amap:
        ch = amap[prev.id][0]
    if not ch and prev.id in dmap:
        ch = dmap[prev.id].char
    if not ch and prev.id in mmap:
        ch = mmap[prev.id].char
    return bool(ch) and ch in _NUMERALS


_KEBEN_COUNTS: dict = {}


def _keben_counts(db_path: str) -> dict[str, int]:
    """字形库里每个字的刻例（exemplar）数，`rare_ref_nf` 用；按库路径＋mtime 缓存。读不了＝空表（调用方当没有这路放宽）。"""
    import sqlite3
    try:
        from pathlib import Path
        key = (db_path, Path(db_path).stat().st_mtime_ns)
    except OSError:
        return {}
    hit = _KEBEN_COUNTS.get(key)
    if hit is not None:
        return hit
    out: dict[str, int] = {}
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as c:
            for ch, n in c.execute("SELECT g.char, COUNT(*) FROM exemplars e JOIN glyphs g USING(glyph_id) GROUP BY g.char"):
                out[str(ch)] = int(n or 0)
    except Exception:
        return {}
    _KEBEN_COUNTS.clear()
    _KEBEN_COUNTS[key] = out
    return out


_TRUSTED_COUNTS: dict = {}


def _trusted_keben_counts(db_path: str) -> dict[str, int]:
    """字 → 可信刻例数（人裁＋有参照互证；借库、solo、来源不明的不算，`clustering.keben_counts`），
    `solo_5b_min_n` 读它（参校本属性 C1，A23 #1275／#1276；无参照放行不自喂）。按库路径＋mtime 缓存；读不了＝空表（通道不放）。"""
    from pathlib import Path
    try:
        key = (db_path, Path(db_path).stat().st_mtime_ns)
    except OSError:
        return {}
    hit = _TRUSTED_COUNTS.get(key)
    if hit is not None:
        return hit
    from ..clustering.keben_counts import trusted_keben_counts
    out = trusted_keben_counts(db_path)
    _TRUSTED_COUNTS.clear()
    _TRUSTED_COUNTS[key] = out
    return out


def _lane_witnesses(book, p: "SeedAdmitParams") -> list:
    """R1/R4 用的证人（质量降序，`steps.align_ref` 那份进程级缓存），全部用（原 `lane_witnesses` 筛选无书用，2026-11-23 删）。"""
    from .align_ref import _witnesses_for_book
    return list(_witnesses_for_book(book))


def _pua_pin(ctx) -> int | None:
    """册钉的 PUA 码表共享层版本（`Book.pua_table_pin`）；没钉或没有 ctx 给 None（读本书码表）。"""
    return getattr(getattr(ctx, "book", None), "pua_table_pin", None)


def _pua_code_pass(out: list, amap: dict, store=None, table=None, p=None, pin=None) -> tuple[int, int, int]:
    """按私用码表放字（`SeedAdmitParams.pua_code_table`）。→ (改字格数, 遍后仍不一致格数, 降审格数)。

    格→码对应来自裁定库 `src-2`（按格号取，见 `RulingStore.cell_codes`）；对位字 `ref` 与现对位不同的不认（重切后格号可能挪了）。
    ① 非人裁已放行、放行字≠码表字 → 改成码表字（通道 `code_table`，provenance `match`）；② 一码多字的码：放行字在族内 → 不动，
    族外 → 降审（doubt `src_code_conflict`；`True` 关则只计数）；③ 人裁格不动，只计入「仍不一致」；
    ④ 未放行格不动。码表字须是汉字。（原⑤ `pua_code_keep_channels` 无书用，2026-11-23 删。）"""
    from ..utils.pua_v2_codes import load_table
    if store is None:
        store = _vis_cache().store_
    cc = store.cell_codes()
    if not cc:
        return 0, 0, 0
    if table is None:
        from ..core.workspace import ws_config_dir
        table = load_table(ws_config_dir(), pin=pin)
    codes, fams = table
    fam_demote = True
    fix = mism = dem = 0
    for col in out:
        for r in col.chars:
            info = cc.get(r.id)
            if not info or not r.admit or (r.doubts and "excluded" in r.doubts):
                continue
            T = codes.get(info["code"])
            fam = fams.get(info["code"])
            if (not T and not fam) or (T and not _ruling_han(T)) or (info.get("ref") or "") != ((amap.get(r.id) or (None,))[0] or ""):
                continue
            T = T or ""                              # 纯多字码（表里只登族、没有单字）：只管族外降审，不改字
            if r.char == T or (fam and r.char in fam):
                continue
            if r.provenance == "human" or r.channel == "human":
                mism += 1
                continue
            if fam and not fam_demote:
                mism += 1
                continue
            if fam:                                  # 族外字：码表字也不是铁证，退回人审
                _demote(r, "src_code_conflict")
                r.evidence = {**(r.evidence or {}), "src_code_conflict": {"code": info["code"], "char": T, "family": "".join(sorted(fam))}}
                r.admit, r.channel, r.provenance = False, None, ""
                r.doubts = list(dict.fromkeys(list(r.doubts or []) + ["src_code_conflict"]))
                dem += 1
                continue
            r.evidence = {**(r.evidence or {}), "code_table": {"code": info["code"], "char": T, "was": r.char, "was_channel": r.channel}}
            r.char, r.channel, r.provenance = T, "code_table", "match"
            fix += 1
    return fix, mism, dem


def _pua_code_admit_pass(out: list, amap: dict, mmap: dict, store=None, table=None, p=None, pin=None) -> int:
    """`SeedAdmitParams.pua_code_admit`：未放行格按私用码表＋库首位互证放行。→ 放行格数。

    只升不降：只碰 admit=False、非人裁、不在排除名单、没遮挡、没有硬疑问（`_LANE_HARD`）的格。格→码同 `_pua_code_pass`
    （裁定库 `src-2`，对位字 `ref` 与现对位不同的不认）；码表字须是汉字；库首位须是码表字（一码多字则族内任一字）、
    cov ≥ `p.pua_code_admit_cov`、库没判 diff、无护栏。放的字取库首位（族内字按刻形，不按码改）。"""
    from ..utils.pua_v2_codes import load_table
    if store is None:
        store = _vis_cache().store_
    cc = store.cell_codes()
    if not cc:
        return 0
    if table is None:
        from ..core.workspace import ws_config_dir
        table = load_table(ws_config_dir(), pin=pin)
    codes, fams = table
    all_T = set(codes.values())
    min_cov = float(getattr(p, "pua_code_admit_cov", 0.85) if p is not None else 0.85)
    n = 0
    for col in out:
        for r in col.chars:
            ds = {d for d in (r.doubts or []) if isinstance(d, str)}
            if (r.admit or r.provenance == "human" or r.channel == "human"
                    or "excluded" in ds or "occluded" in ds or ds & _LANE_HARD):
                continue
            info = cc.get(r.id)
            if not info or (info.get("ref") or "") != ((amap.get(r.id) or (None,))[0] or ""):
                continue
            T, fam = codes.get(info["code"]), fams.get(info["code"])
            other_T = {c for c in all_T if c != T}
            # 族里若有别的码的表字，那是文本层把形近的不同字合用一码（F1001 乖垂埀：乖是 EA36、埀是 EA39），
            # 库首位落到这种字不算互证（第 7 轮 vol26:30:7:11 等 3 格「垂四十年」「垂紳正笏」放成了乖，A24 11-08）
            ok = ({T} if T and _ruling_han(T) else set()) | {x for x in (fam or ()) if x == T or x not in other_T}
            if not ok:
                continue
            m = mmap.get(r.id)
            if not m or not m.candidates or getattr(m, "guard", None) is not None or getattr(m, "verdict", None) == "diff":
                continue
            top, cov = m.candidates[0][0], float(m.candidates[0][1])
            if top not in ok or cov < min_cov:
                continue
            r.evidence = {**(r.evidence or {}), "code_table": {"code": info["code"], "char": T or "".join(sorted(fam or ())),
                                                               "admit": True, "lib": top, "cov": round(cov, 4),
                                                               "prev_doubts": list(r.doubts or [])}}
            r.admit, r.char, r.channel, r.provenance = True, top, "code_table", "match"
            r.doubts = ["code_table_admit"]
            n += 1
    return n


@lru_cache(maxsize=4)
def _iron_context(db_path: str, norm_stroke: int | None):
    """铁证闸的匹配上下文：只吃人裁实例的内存匹配器 + 人裁字集合 + 形近表 + 按字分组的
    人裁实例 id（供判别器成对复核取原始字块）。跨页/跨 run 缓存（同 `_human_shapes`），
    只在 db_path/norm_stroke 换了才重建——一本书一次，不是一页一次。"""
    from ..clustering.confusable import partners as _confusable_partners
    from ..clustering.glyph_db import GlyphDB
    from ..clustering.iron_evidence import human_matcher
    matcher, _n = human_matcher(db_path, norm_stroke)
    human_chars_set = set(matcher._chars)
    partners_map = _confusable_partners()
    db = GlyphDB(db_path)
    human_ids: dict[str, list[str]] = {}
    for ch, iid in db.conn.execute(
            """SELECT g.char, e.instance_id FROM exemplars e JOIN glyphs g ON g.glyph_id=e.glyph_id
               JOIN instances i ON i.instance_id=e.instance_id WHERE i.label_status='human'"""):
        human_ids.setdefault(ch, []).append(iid.replace("v2:", ""))
    return matcher, human_chars_set, partners_map, human_ids


def _iron_page_scale(book, page: int, match: PageMatch, on_missing=None) -> float:
    """书级判别器归一尺度（`iron_evidence.book_scale_from_patches`）：从**这一页**的字块
    原图取中位边长——影子验收（research/shadow_admit/iron_shadow.py）验证过
    的口径是抽样几百个字块算一次全书通用值，这里改成逐页现算（一页的字数通常也有
    几百个，够稳），免得要在 `run_page` 的单页边界之外维护跨页状态。"""
    from ..clustering.iron_evidence import book_scale_from_patches
    patches = []
    for cc in match.columns:
        if not cc.ok:
            continue
        for r in cc.chars:
            try:
                patches.append(_C._page_patch(book, page, cc.col, r.slot, r.sub))
            except PatchUnavailable:
                if on_missing is None:          # 缺省（patch_missing=error）：停页
                    raise
                on_missing(r.id)                # skip：尺度用读得到的那些算，缺的记账
    return book_scale_from_patches(patches)


@lru_cache(maxsize=4)
def _store_conn(db_path: str):
    import sqlite3
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)


def _store_ex_raw(db_path: str, cid: str):
    """`iron_ex_from_store`：人裁刻例 `cid`（`_iron_context.human_ids` 里去了 `v2:` 前缀的 id）在字形库里的图，
    裁回 canonical 图里原裁切那一块（背景是纯 255，原裁切区域里不全是 255）。库里没有 → None。"""
    import cv2
    import numpy as np
    row = _store_conn(db_path).execute(
        "SELECT patch_png FROM instances WHERE instance_id IN (?, ?) ORDER BY instance_id = ? DESC LIMIT 1",
        (f"v2:{cid}", cid, f"v2:{cid}")).fetchone()
    if row is None or row[0] is None:
        return None
    img = cv2.imdecode(np.frombuffer(row[0], np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise PatchUnavailable(f"字形库刻例图解不出来: {cid}")
    ys, xs = np.nonzero(img != 255)
    if len(ys) == 0:
        return None
    return img[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _iron_decide(book, page: int, col: int, r, iron_ctx, scale: float,
                 norm_stroke: int | None, missing: list | None = None,
                 store_db: str | None = None) -> str | None:
    """这一格铁证放行的字，放不了返回 None。`r` 是 `glyph_match` 产物里的逐格记录
    （`.id/.slot/.sub/.candidates/.verdict/.char/.cov`），候选集重算方式与
    `iron_shadow.py` 的批处理壳完全一致——两边现在都读同一个 `iron_with_disc`。
    `store_db`（`iron_ex_from_store`）：刻例图从这个字形库取，不读缓存。"""
    import cv2

    from ..clustering.iron_evidence import iron_with_disc
    from ..clustering.normalize import normalize_patch
    from ..products.cache import ImageCache
    cache = ImageCache()
    matcher, human_chars_set, partners_map, human_ids = iron_ctx
    img = _C._page_patch(book, page, col, r.slot, r.sub)
    res = matcher.match(normalize_patch(img, stroke_width=norm_stroke), exclude_id=f"v2:{r.id}")
    cands = [(c, float(v)) for c, v in res.candidates]
    if res.verdict == "same" and res.char and all(c != res.char for c, _ in cands):
        cands.insert(0, (res.char, float(res.cov)))
    cands.sort(key=lambda t: -t[1])

    raw_cache: dict[str, object] = {}

    def raw_of(cid: str):
        if cid not in raw_cache and store_db is not None:
            raw_cache[cid] = x = _store_ex_raw(store_db, cid)
            if x is None and missing is not None:
                missing.append(cid)
        if cid not in raw_cache:
            parts = cid.split(":")
            if parts and parts[0] == "v2":      # 人裁重键后的格号坐标，去前缀即可
                parts = parts[1:]
            # `v1:` 是旧管线的 idx 坐标、没经形状确认，不拿来当铁证对照图；
            # 其它认不出的形状也一律跳过（服务器 #40：v1: 人裁 id 让 vol03 p3/p74 崩）。
            if len(parts) != 4 or parts[0] == "v1" or not parts[3].rstrip("ab").isdigit() \
                    or not (parts[1].isdigit() and parts[2].isdigit()):
                raw_cache[cid] = None
                return None
            bk_, p_, c_, s_ = parts
            sub = s_[-1] if s_[-1] in "ab" else ""
            s_ = s_.rstrip("ab")
            # 对照图是别页/别册的人裁刻例，缓存里没有属正常（跳过这一例）；
            # 文件在却解不出来是坏缓存，照样报错（strict），不当「没有」处理。
            pth = cache.get(bk_, "char_patch", f"p{int(p_):04d}c{int(c_):02d}s{s_}{sub}")
            if pth is None and missing is not None:
                missing.append(cid)
            raw_cache[cid] = (None if pth is None
                              else cv_imread(str(pth), cv2.IMREAD_GRAYSCALE, strict=True))
        return raw_cache[cid]

    def ex_raws(ch: str):
        ids = [i for i in human_ids.get(ch, []) if i != r.id]
        return [x for i in ids[:8] if (x := raw_of(i)) is not None]

    winner, _top, _second, _why, _disc = iron_with_disc(
        cands, human_chars_set, partners_map, img, ex_raws, scale)
    return winner


def _solo_ctx_vetoed(dec, cands, vmap, thresh: float) -> bool:
    """`solo_ctx_veto`：上下文第一名与库 top1 语义不同、且概率 ≥ thresh（无 ranked／候选 = 不拦）。"""
    ranked = getattr(dec, "ranked", None)
    if not ranked or not cands:
        return False
    top, prob = ranked[0]
    lib = max(cands, key=lambda t: t[1])[0]
    return prob >= thresh and vmap.semantic(top) != vmap.semantic(lib)


_SOLO_COORD_NUMS = frozenset("一二三四五六七八九十廿卅")


def _same_column_exemplar(cell_id: str, matched_id) -> bool:
    """`solo_self_exemplar`：库里判 same 所凭的那条刻例就在**本页本列**（格号可以不同）。没有整理本背书（match_solo 系）时，
    这种「同一列自己的刻例」多半是前一轮切分里这一格（或邻格）自己存进库的，换切分后格号错位，自己跟自己比出 cov 0.999
    （殿本 vol01:88:6:9b 管→總：刻例 vol01:88:6:6b；vol02:150:3:14 鶴→號：刻例 vol02:150:3:13）。刻例号形如
    `v2:vol01:88:6:6b`／`v2~r2~vol02~145~5~7a`，取末四段 册／页／列／格。"""
    import re
    if not matched_id:
        return False
    a = re.split(r"[:~]", str(matched_id))
    b = str(cell_id).split(":")
    if len(a) < 4 or len(b) < 4:
        return False
    return a[-4] == b[-4] and a[-3] == b[-3] and a[-2] == b[-2]


def _solo_coord_dissented(r, vmap, coord: dict) -> bool:
    """`solo_coord_dissent`：坐标对位给了实字、与 match_solo 放行字语义不同 → True（要拦）。
    放行字＝库 same 取库字，否则库候选 top1（同 `_pick_char` 对 solo 通道的取法）。豁免见参数说明：
    坐标字非汉字（私用码／占位）、两边都是数字（坐标对位在数字处常漂）、语义同字（异体）。"""
    cr = coord.get(r.id)
    if cr in (None, "", *GAP_CHARS) or len(cr) != 1 or not _ruling_han(cr):
        return False
    cands = list(r.candidates or [])
    ch = r.char if r.verdict == "same" and r.char else (max(cands, key=lambda t: t[1])[0] if cands else None)
    if not ch or vmap.semantic(cr) == vmap.semantic(ch):
        return False
    return not (cr in _SOLO_COORD_NUMS and ch in _SOLO_COORD_NUMS)


def _lib_cov(cands, ch: str) -> float | None:
    return max((v for c, v in cands if c == ch), default=None)


def _context_variant_tie(dec, cands, vmap, ratio: float, lib_gap: float, canon=None) -> bool:
    """`context_variant_form_guard`：context 放行字在 ranked 里有语义同字、字面不同的对手（概率 ≥ ratio × 放行字概率），
    库形又分不开它俩 → True（context 不该在异体里选形）。"""
    ranked = getattr(dec, "ranked", None) or []
    ch = dec.char
    p1 = next((v for c, v in ranked if c == ch), None)
    if not p1:
        return False
    norm = canon or (lambda c: c)
    sem = vmap.semantic(ch)
    c1 = _lib_cov(cands or [], ch)
    for c, v in ranked:
        if c == ch or norm(c) == norm(ch) or vmap.semantic(c) != sem or v < ratio * p1:
            continue
        c2 = _lib_cov(cands or [], c)
        if c2 is None:
            continue                      # 对手不在库候选里：库形分得开
        if c1 is None or c1 - c2 < lib_gap:
            return True
    return False


def _context_lib_dissent(ch: str, cands, vmap, gap: float, absent_cov: float) -> bool:
    """`context_lib_dissent_gap`：库 top1 与 context 字语义不同，context 字（含同义异体）在库里落后 ≥ gap，
    或不在库候选里而 top1 cov ≥ absent_cov。没有库候选 = 不拦。"""
    if not cands:
        return False
    c1, v1 = max(cands, key=lambda t: t[1])
    sem = vmap.semantic(ch)
    if vmap.semantic(c1) == sem:
        return False
    vc = max((v for c, v in cands if vmap.semantic(c) == sem), default=None)
    return v1 >= absent_cov if vc is None else v1 - vc >= gap


def _iron_ctx_dissent(iron_char: str, dec, cands, vmap, prob: float, gap: float) -> bool:
    """`iron_ctx_guard`：上下文第一名与铁证字语义不同、概率 ≥ prob，且在库里与铁证字近平手。"""
    ranked = getattr(dec, "ranked", None) or []
    if not ranked:
        return False
    top, p = ranked[0]
    if p < prob or vmap.semantic(top) == vmap.semantic(iron_char):
        return False
    ci, ct = _lib_cov(cands or [], iron_char), _lib_cov(cands or [], top)
    return ci is not None and ct is not None and ci - ct < gap


#: match_solo 系：只靠库形状（± OCR/CNN 背书）放行、没有整理本的通道（`solo_ctx_veto` 等用；`solo_confusable_guard` 已于 W2 删）
_SOLO_CHANNELS = frozenset({"match_solo", "match_solo_ocr", "match_solo_5b", "match_num_run", "match_solo_adapt",
                            "match_solo_cal", "match_lead_5b"})


_CORPUS_CHANNELS = (None, "match_ref", "match_replace", "match_ref_weak", "match_margin",
                    # 整理本参与的通道（match_ref 2026-09-05 补、note_lexicon 2026-09-06 补）：
                    # 库没下 same 断言时拿整理本字当字形估计，且要走「义定形未定」的组内定形；
                    # 漏进这个元组，variant_form 整段跳过（刻本形被整理本形盖掉，判据 E 82/91 那次）。
                    "note_lexicon")


def _pick_char(ok: bool, channel: str | None, align_char: str | None,
               match_char: str | None, verdict: str,
               candidates: list) -> str | None:
    """决定这一位的**字**（刻本字形；2026-09-26 起没有「读法」）。

    same 档用库继承的字；整理本参与的通道、库又没下 same 断言时取整理本字；
    否则取**库候选 top1**——那正是 match_solo / match_solo_ocr 采信的东西。

    ## ⚠️ 库判 same 时整理本字不能覆盖

    第一版让整理本字直接覆盖，7 条异体字位被写成了整理本的形：刻本刻「㫖」存成「旨」、
    「彚」存成「彙」、「卽」存成「即」。字形库存的是刻本上实际刻的形（charset_and_lm.md §四）。

    ## ⚠️ `channel is None` 也是一条通道

    `dual` 档（align × OCR 双信号一致且零疑问）在 `admission_decision` 里是
    `return True, None`——**没有通道名**。所以按「这条通道用没用整理本」判，而不是列通道名。
    """
    char = match_char if verdict == "same" else None
    if ok and align_char and channel in _CORPUS_CHANNELS:
        # ⚠️ 库 unsure 时，**别拿库 top1 当字形**。
        #
        # unsure 的字面意思就是「库不知道这是什么」：实测 8 条 dual 位
        # （vol01:42:3:20 等）库 top1 与 top2 只差 0.0017~0.0023，而 align 与
        # OCR 两路独立证据都指向另一个字，且那个字**根本不在库的候选里**
        # （敷/顯/毫/昌）。此时把库的猜测写进 `char`，等于往字形库塞 8 个错
        # 例——下一页再遇到同形字就会继承这个错（charset_and_lm.md §四）。
        #
        # 库判 same 才有资格定字形（那是它下了断言）；unsure 时两路零同源证据
        # 一致，整理本字是更好的字形估计。异体位（㫖/旨、彚/彙）不受影响：
        # 库对它们判 same，char 仍照录刻本的形。
        if char is None:
            char = align_char
    if char is None and candidates:
        char = candidates[0][0]
    return char


def _consensus_fallback(match: PageMatch, amap: dict) -> PageMatch:
    """`consensus_fallback`：库字 ≠ 对位整理本字（或没有整理本字）的共识升档 same 退回 unsure（升档前的样子）。

    其余格对象原样不动（`is` 相同），没有要退的格时返回原 `match`。"""
    def back(r):
        if not _is_consensus_same(r):
            return r
        al = amap.get(r.id)
        if al is not None and al[0] and al[0] == r.char:
            return r
        return r.model_copy(update={"verdict": "unsure", "char": None, "matched_id": None, "via": None})

    cols, changed = [], False
    for cc in match.columns:
        if not cc.ok:
            cols.append(cc)
            continue
        chars = [back(r) for r in cc.chars]
        if any(a is not b for a, b in zip(chars, cc.chars)):
            changed = True
            cc = cc.model_copy(update={"chars": chars})
        cols.append(cc)
    return match.model_copy(update={"columns": cols}) if changed else match


_FOLLOW_REF_HOOKS = "open_guji_cv.impl.keben.follow_ref_hooks"


def _follow_ref_rival_hook(ctx: RunContext):
    """书级钩子 `impl/keben/follow_ref_hooks.rival_skip`（书仓 `code/` 覆盖才有；缺省 None）。"""
    import importlib
    from ..core.seg_set import resolve
    return getattr(importlib.import_module(resolve(ctx.book, _FOLLOW_REF_HOOKS)), "rival_skip", None)


def _lane_variant_hook(ctx: RunContext, name: str = "variant_norm"):
    """书级钩子 `impl/keben/follow_ref_hooks.<name>`（`variant_norm`／`variant_rank`；书仓 `code/` 覆盖才有；缺省 None）。
    书仓模块没写这个名字也当 None（11-13 前写的覆盖模块只有 rival_skip，11-16 前的没有 variant_rank）。"""
    import importlib
    from ..core.seg_set import resolve
    return getattr(importlib.import_module(resolve(ctx.book, _FOLLOW_REF_HOOKS)), name, None)


_ADMIT_LANES = "open_guji_cv.impl.keben.admit_lanes"


def _admit_lanes_hook(ctx: RunContext):
    """书级钩子 `impl/keben/admit_lanes.noref_lanes`；写了 `book_lanes` 而书仓 `code/` 没覆盖 → 拒跑（不悄悄当关）。"""
    import importlib
    from ..core.seg_set import resolve
    mod = resolve(ctx.book, _ADMIT_LANES)
    hook = getattr(importlib.import_module(mod), "noref_lanes", None)
    if hook is None:
        raise RuntimeError("seed_admit.book_lanes 写了取值，但本书书仓 code/ 没覆盖 keben.admit_lanes（noref_lanes）；"
                           "这些通道 2026-11-24 起只在书仓里，检查 code.yaml 的 overrides 与册配置 code: 号")
    return hook


class _AdmitFacts:
    """交给书级钩子 `admit_lanes.noref_lanes` 的只读工具（书级代码不许 import cv 内部模块）。见该模块头。"""

    def __init__(self, ctx: RunContext):
        from ..clustering.seeding import NEAR_FORM_CHARS
        from ..groups.registry import GROUPS
        from ..variants import are_variants, look_alike
        self.gap_chars = GAP_CHARS
        self.group_chars = frozenset(c for g in GROUPS.values() for c in g.members)
        self.near_form_chars = NEAR_FORM_CHARS
        self.are_variants = are_variants
        self.look_alike = look_alike
        self.is_gap = is_gap
        self.is_hanzi = _is_hanzi
        self.canonical_char = (ctx.book.canonical_char if ctx is not None and ctx.book.codepoints else None)

    @staticmethod
    def data_path(rel: str) -> str:
        return _resolve_book_lanes_data(rel)


def _resolve_book_lanes_data(rel: str) -> str:
    """`book_lanes.data` 的一项 → 绝对路径：绝对路径照用；相对路径先找数据目录、再找工作区。找不到＝空串。"""
    from pathlib import Path
    from ..core.workspace import REPO_ROOT, data_root, workspace_root
    q = Path(rel).expanduser()
    cands = [q] if q.is_absolute() else [(data_root() or REPO_ROOT) / q, (workspace_root() or REPO_ROOT) / q]
    return next((str(c) for c in cands if c.exists()), "")


def _approx_fingerprint(db_path: str) -> str:
    """近似字侧表的内容戳；库不存在、没有这张表、表空 → ""（见 `SeedAdmitParams.approx_gate`）。"""
    import hashlib
    import sqlite3
    from pathlib import Path
    if not db_path or not Path(db_path).exists():
        return ""
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as c:
            rows = c.execute("SELECT instance_id, label FROM approx_labels ORDER BY instance_id").fetchall()
    except sqlite3.Error:
        return ""
    if not rows:
        return ""
    return f"{len(rows)}:" + hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()[:12]


@lru_cache(maxsize=4)
def _approx_index_cached(db_path: str, _fp: str) -> tuple[dict[str, tuple], frozenset[str]]:
    """({近似例 id: (ids, note)}, {刻例全是近似例的字})。"""
    import sqlite3
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as c:
        ids = {r[0]: (r[1], r[2]) for r in c.execute(
            "SELECT instance_id, ids, note FROM approx_labels")}
        # 刻例全是近似例的字（按字头算，跨 edition 合并；字体域不算——它们不会是近似例，
        # 算进去反而让「全是近似」永远不成立）
        only = frozenset(r[0] for r in c.execute(
            "SELECT g.char FROM exemplars e JOIN glyphs g USING(glyph_id) "
            " WHERE g.edition_tag NOT LIKE 'font:%' GROUP BY g.char "
            "HAVING sum(e.instance_id IN (SELECT instance_id FROM approx_labels)) = count(*)"))
    return ids, only


def _approx_index(db_path: str) -> tuple[dict[str, tuple], frozenset[str]]:
    return _approx_index_cached(db_path, _approx_fingerprint(db_path))


def _approx_hit(r, char: str | None, apx_ids: dict[str, tuple], apx_only: frozenset[str]) -> dict | None:
    """这一格的字是不是**靠近似例**得来的（见 `SeedAdmitParams.approx_gate`）。

    是 → `evidence["approx"]` 那一段：`{"source": "matched", "via", "exemplar", "ids", "note"}`
    （`char_only` 时没有具体哪一例，`exemplar`/`ids`/`note` 为 None）；不是 → None。
    """
    if not char:
        return None
    if r.verdict == "same" and r.char == char and r.matched_id in apx_ids:
        ids, note = apx_ids[r.matched_id]
        return {"source": "matched", "via": "matched_id", "exemplar": r.matched_id,
                "ids": ids, "note": note}
    lib_top = r.char or (r.candidates[0][0] if r.candidates else None)
    if lib_top == char and char in apx_only:
        return {"source": "matched", "via": "char_only", "exemplar": None, "ids": None, "note": None}
    return None


class _CodepointMap:
    """VariantMap 的包装：书级 `codepoints:` 声明过的码位先归到册指定的码位再查语义
    （巻→卷 后 semantic(巻)==semantic(卷)）。没声明的字原样查。"""

    def __init__(self, base, book):
        self._base, self._book = base, book

    def semantic(self, char: str) -> str:
        return self._base.semantic(self._book.canonical_char(char))

    def __getattr__(self, name):
        return getattr(self._base, name)


def _parse_semantic_extra(spec: str) -> dict[str, str]:
    """`semantic_extra`「异体=正字,…」→ {异体: 正字}；两边都要是单字，写错直接报错（书配置写错别悄悄不生效）。"""
    out: dict[str, str] = {}
    for item in (x.strip() for x in spec.split(",")):
        if not item:
            continue
        a, sep, b = item.partition("=")
        a, b = a.strip(), b.strip()
        if not sep or len(a) != 1 or len(b) != 1 or a == b:
            raise ValueError(f"semantic_extra 写法不对：{item!r}（要「异体=正字」，两边各一个字）")
        out[a] = b
    return out


class _ExtraSemanticMap:
    """VariantMap 的包装：书级 `semantic_extra` 补的对先换到正字再查语义（圗→圖 后 semantic(圗)==semantic(圖)）。
    只管语义层，字形层（候选、放行字）照旧是刻形。"""

    def __init__(self, base, extra: dict[str, str]):
        self._base, self._extra = base, extra

    def semantic(self, char: str) -> str:
        return self._base.semantic(self._extra.get(char, char))

    def __getattr__(self, name):
        return getattr(self._base, name)


class _PairAwareMap:
    """VariantMap 的一次性包装：额外把几个形映到指定语义（本书人确认过的 T2 转换对）。
    只给 `admission_decision` 这一次调用用，不改全局语义表。"""

    def __init__(self, base, extra: dict[str, str]):
        self._base, self._extra = base, extra

    def semantic(self, char: str) -> str:
        return self._extra.get(char) or self._base.semantic(char)

    def __getattr__(self, name):
        return getattr(self._base, name)


def _image_ranks(book, page: int, col: int, slot: int, sub: str | None,
                 forms: list[str]) -> dict | None:
    """组内 closed-set 检索要看图：取 Step4 的 `char_patch`。**没图 → 抛 `PatchUnavailable`**
    （2026-10-05 前是 None，overview#407）；检索本身出错仍是 None。"""
    img = _C._page_patch(book, page, col, slot, sub)
    try:
        from ..clustering.normalize import normalize_patch
        from ..clustering.variant_form import image_ranks_for
        return image_ranks_for(normalize_patch(img), forms)
    except Exception:
        return None


def _confusable_char(ch: str) -> bool:
    """这个字在不在任何一张形近表里（按字，不看对手是否在候选里）。"""
    from ..clustering.confusable import partners
    from ..clustering.iron_evidence import extra_confusable_partners
    from ..clustering.seeding import NEAR_FORM_CHARS
    return (ch in NEAR_FORM_CHARS or ch in partners()
            or ch in extra_confusable_partners())


def _iron_confusable_witness(iron_char: str, witnesses, vmap) -> str | None:
    """`iron_confusable_guard` 用：证人里与铁证首选语义不同、又同在一张形近表里的那个字，
    没有返回 None。`〓`（逐列本的 PUA 占位）与空串（空格位）不算证人。"""
    from ..clustering.confusable import partners
    from ..clustering.iron_evidence import extra_confusable_partners
    near = partners().get(iron_char, frozenset()) | extra_confusable_partners().get(iron_char, frozenset())
    for w in witnesses:
        if w and not is_gap(w) and w in near and vmap.semantic(w) != vmap.semantic(iron_char):
            return w
    return None


def _iron_coord_dissent(iron_char: str, ref: str | None, vmap) -> bool:
    """`iron_coord_guard` 用：坐标对位字与铁证字语义不同、也没有直接异体边。空串（空格位）、`〓`、None 不算证人。"""
    if not ref or is_gap(ref) or ref == iron_char:
        return False
    if vmap.semantic(ref) == vmap.semantic(iron_char):
        return False
    return not _direct_variant_edge(iron_char, ref)


def _trusted_variant_edge(top: str, align_char: str, ledger, book) -> bool:
    """`ref_lib` 变体放行（库候选与整理本字字面不同、语义同）时，这条变体边可不可信。

    `vmap.semantic(top) == vmap.semantic(align_char)` 只说明两者在 `variants.auto.tsv`/
    `variants.tsv` 里被登记成了同一语义正字，**不等于这条边本身够硬**——`graph` 来源的
    条目多数是关系层某个词典单向登记（见 `SeedAdmitParams.ref_lib_variant_guard` 的
    docstring，`冶→治` 就是 twedu 单向边），拿它当「两字同义」的唯一依据会把形近而
    异义的字放过闸。可信边四选一：

    - **双向**：关系层（`open_guji_cv.variants`）两个方向都把对方登记成正字——
      `directed[top][align_char]` 与 `directed[align_char][top]` 都有条目，不是单向
      「异体→正字」的登记，是两个来源互认；
    - **人工审查确认表**：`config/dicts/variants.tsv`（手工表，文件头「种子条目：随人工
      审查确认逐步扩充」）登记过这一对，双向都查——**这条不能略**：该表 17 条里有 10 条
      在关系层查不到双向（为→爲、逰→遊、无→無、迴→回、囬→回、彚→彙、厯→歷、㫖→旨、
      𨽾→隸、櫽→檃），全部人工确认过，若只认双向会被本闸误拦，比不加闸还倒退；
    - **人裁**：本书用字账记过这一对的人工确认（`BookLedger.pair_confirmed`，刻本形/
      整理本形谁在前不确定，两个方向都查）；
    - **书级 codepoints**：本书 `codepoints:` 配置把两个码位统一成了同一个
      （`BookSpec.codepoint_equal`，书级实证，比字典更硬）。
    """
    from ..variants import regulars_of
    a_to_b = any(r == align_char for r, _tags in regulars_of(top))
    b_to_a = any(r == top for r, _tags in regulars_of(align_char))
    if a_to_b and b_to_a:
        return True
    if (top, align_char) in _hand_variant_pairs() or (align_char, top) in _hand_variant_pairs():
        return True
    if ledger.pair_confirmed(top, align_char) or ledger.pair_confirmed(align_char, top):
        return True
    if book.codepoint_equal(top, align_char):
        return True
    return False


def _variant_indirect(shape: str, align_char: str, ledger, book) -> bool:
    """库形 `shape` 与整理本字只经间接路径同义（字面不同、关系层无直接边、
    也没有人工表/人裁/书级 codepoints 认过这一对）——`variant_indirect_guard` 要拦的。

    调用方已保证两者 `semantic` 相同（通道本身就是靠这个放行的），这里不再比。"""
    if shape == align_char or _direct_variant_edge(shape, align_char):
        return False
    return not _trusted_variant_edge(shape, align_char, ledger, book)


@lru_cache(maxsize=1)
def _hand_variant_pairs() -> frozenset[tuple[str, str]]:
    """`config/dicts/variants.tsv`（人工表）的全部条目，`{(异体, 正字)}`。

    人工确认过的边不要求关系层双向——它本身就是比关系层更硬的证据（人工审查过，
    不是词典单向登记）。缺省表很小（17 条），一次读全，跨 run_page 调用缓存
    （同 `_human_shapes`/`_iron_context` 的做法，进程内不重读文件）。
    """
    from ..clustering.variants import DEFAULT_VARIANTS_PATH
    pairs: set[tuple[str, str]] = set()
    if DEFAULT_VARIANTS_PATH.exists():
        for line in DEFAULT_VARIANTS_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0] and parts[1]:
                pairs.add((parts[0], parts[1]))
    return frozenset(pairs)
