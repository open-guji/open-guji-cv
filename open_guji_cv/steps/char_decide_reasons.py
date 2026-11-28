"""收尾（char_decide，现名 seed_admit）直接写每格的送审原因 `pending_reason`、`pending_reason_detail`、`form_src`。

CV4 P3a-2（2026-11-28，Sheldon 定：收尾总是最后，直接给放行／送审和原因）。判法**逐条搬自** guji-manager
`review/reasons.py`（`classify`，enum 真源 `review/pending_reasons.yaml`），产物读法也照 `book_cells`：同一批层
（align_ref／glyph_match／cell_shrink／row_segment／border_detect_gate／字形库）、同一个优先级顺序。

- **只写第四步名下的原因**（enum 副本 `ops/pending_reasons.json` 里 `owner == "CV4"` 的值，见 `FINAL_PENDING_REASONS`）。
  按优先级第一个命中的原因若归别人（切分 S、遮挡 D、库刻例 L02／L04、复审 X02–X04……），这格写 `None`：
  manager 自判类照旧覆盖，缺或 `unknown` 回退 `reasons_for_pending` 反推；过渡期两边都算，出差异表。
- 已放行的格、排除名单上的格一律 `None`。`form_src`（选形来源）每个非排除格都写。
- 不放行、不改字，只读本页的产物与 `PageAdmit`（`stamp_page`）；写进 `AdmitRec` 的三个字段（缺省 None，None 不落盘）。
- 判法有变，**先改 manager 的 reasons.py 与测试，再同步这里**，对照用 `scripts/diff_pending_reason.py`。

manager 看不到、这里看得到的差别（过渡期会进差异表）：列级「无参照」（`reference_profile` 的 `col_none`）这里认，manager 暂按整页。
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Callable

#: 本模块拿 `PendingReason` 的取值与优先级：cv 存的 manager enum 副本（测试核对两边一致）。
SPEC_PATH = Path(__file__).resolve().parents[1] / "ops" / "pending_reasons.json"
OWNER = "CV4"

#: 极难形近：机器字、整理本字、库首选全落在这几个字里
HARD_CHARS = frozenset("日曰己已巳")
#: 整理本字在字形库的刻例 ≤ 这个数算「刻例太少」
LIB_SPARSE = 2
PAGE_MIN, COL_MIN = 10, 5
COL_AGREE_MAX = 0.5
FRAG_REL, FRAG_ASPECT = 0.6, 0.35
_GARBLE = {"ctx_garble_shape", "shadow_veto", "ctx_garble_rare"}
_VARIANT = {"ref_lib_variant", "variant_indirect", "replace_form", "channel_off"}
PIN_REMAPPED_DOUBT = "manual_cells_remapped"
JIAZHU_UNEVEN = "jiazhu_uneven"
EVICT_REVIEW = "evict_review"
SELFCHECK_SRC = "seg_selfcheck"
GROUP_SETTLED = frozenset({"admit", "keep", "provisional"})
GROUP_SCENES = ("lift", "joint", "review")
HARD_GROUPS = frozenset({"jys", "ry"})
VARIANT_TIERS = frozenset({"T1", "T2"})
NOT_VARIANT_PAIRS = frozenset(frozenset(p) for p in ("兩雨", "味未", "玉王", "傅傳", "箸著", "住往", "奕弈", "寥𡚶"))
LIB_UNREC_COV, LIB_UNREC_GAP = 0.96, 0.01
REF_LIB_COORD_OK_CODES = frozenset({"ctx_guard_ref", "context_variant_form", "group_flow_abstain", "group_flow_joint",
                                    "group_flow_ref_dissent", "group_flow_coord_dissent", "human_unbound",
                                    "lane_coord_fallback", "near_form", "context_page_end"})
NOREF_NOTES = ("未配置整理本", "未配置证人", "整理本读不到", "本页无参照（配置）")
_EXTRA_SAME_WRITING = (frozenset("宫宮"),)
LIB_MISSING_KINDS = ("ref_blank", "all_zero", "own_zero_borrow_has", "own_has")


# ── enum 副本 ─────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def spec() -> dict:
    """`ops/pending_reasons.json`：`python -m guji_manager.review.pending_reason --json` 导出的精简副本
    （version、renamed、reasons{值: {code, owner, priority, route, reviewer, category}}）。"""
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def reason_names() -> tuple[str, ...]:
    return tuple(spec()["reasons"])


def final_reasons_set() -> frozenset[str]:
    """第四步名下的原因（owner == CV4）：收尾直接写的就是这些。"""
    return frozenset(k for k, v in spec()["reasons"].items() if v["owner"] == OWNER)


def _ordered() -> list[str]:
    rs = spec()["reasons"]
    return sorted((k for k in rs if k != "unknown"), key=lambda k: rs[k]["priority"])


# ── 格与上下文 ────────────────────────────────────────────────────────

def doubt_codes(doubts) -> list[str]:
    """`doubts` 里的码（小写标识符）；中文说明不取（同 manager `review/cards.doubt_codes`）。"""
    import re
    pat = re.compile(r"^[a-z][a-z0-9_]*$")
    return [d for d in (doubts or []) if isinstance(d, str) and pat.match(d)]


def ref_missing(ch: str | None) -> bool:
    """整理本这位是〓、▣、缅甸文占位或私用码。"""
    return bool(ch) and (ch in ("〓", "▣") or any(0x1000 <= ord(c) <= 0x109F or 0xE000 <= ord(c) <= 0xF8FF or ord(c) >= 0xF0000
                                           for c in ch))


@dataclass
class Cell:
    id: str
    char: str | None = None
    ref: str | None = None
    ref_op: str | None = None
    cands: list = field(default_factory=list)
    doubts: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    seg_kind: str | None = None
    pua_code: str | None = None
    src: str | None = None
    page_kind: str | None = None
    col_agree: float | None = None
    bleed: bool = False
    ref_by_design: bool = False
    frag: bool = False

    @property
    def codes(self) -> set[str]:
        return set(doubt_codes(self.doubts))

    @property
    def lib_miss(self) -> bool:
        return "lib_miss" in self.codes or any(isinstance(d, str) and d.startswith("库里没有") for d in self.doubts)

    @property
    def top(self) -> str | None:
        return self.cands[0][0] if self.cands else None

    @property
    def group(self) -> dict | None:
        return (self.evidence or {}).get("group")

    @property
    def has_ref(self) -> bool:
        return bool(self.ref) and not ref_missing(self.ref)


@dataclass
class Context:
    page_noref: Counter = field(default_factory=Counter)
    page_weak: Counter = field(default_factory=Counter)
    col_noref: Counter = field(default_factory=Counter)
    are_variants: Callable[[str, str], bool] | None = None
    edge_tier: Callable[[str, str], str | None] | None = None   # 异体边分型 T1／T2／T3；给了就只认 T1、T2（V01 收窄）
    same_writing: Callable[[str, str], bool] | None = None
    lib_split: Callable[[str], tuple[int, int]] | None = None
    lib_own: Callable[[str], int] | None = None
    near_pairs: frozenset = frozenset()
    glyph_pending: frozenset[str] = frozenset()


def _page(cid: str) -> str:
    return ":".join(cid.split(":")[:-2])


def _col(cid: str) -> str:
    return ":".join(cid.split(":")[:-1])


def build_context(cells: list[Cell], **kw) -> Context:
    ctx = Context(**kw)
    for c in cells:
        if not c.has_ref and not c.ref_by_design:
            if c.ref is None or not ref_missing(c.ref):
                ctx.page_noref[_page(c.id)] += 1
                ctx.col_noref[_col(c.id)] += 1
        elif c.char != c.ref and not c.group and "occluded" not in c.codes \
                and (c.col_agree is None or c.col_agree < COL_AGREE_MAX):
            ctx.page_weak[_page(c.id)] += 1
    return ctx


# ── 判法（搬自 manager review/reasons.py）──────────────────────────────

def _denied(c: Cell) -> bool:
    if not c.ref:
        return False
    return any(x and x != c.ref and frozenset((c.ref, x)) in NOT_VARIANT_PAIRS for x in (c.top, c.char))


def _variant_with_ref(c: Cell, ctx: Context) -> bool:
    if _denied(c):
        return False
    if c.codes & _VARIANT:
        return True
    if not (ctx.are_variants and c.has_ref and c.top and c.top != c.ref):
        return False
    for x in {c.top, c.char}:
        if not x or x == c.ref or not ctx.are_variants(c.ref, x):
            continue
        if ctx.edge_tier is None or ctx.edge_tier(c.ref, x) in VARIANT_TIERS:
            return True
    return False


def lib_own_n(c: Cell, ctx: Context) -> int | None:
    if not c.has_ref:
        return None
    return ctx.lib_own(c.ref) if ctx.lib_own is not None else None


def _sparse(c: Cell, ctx: Context) -> bool:
    n = lib_own_n(c, ctx)
    return n is not None and n <= LIB_SPARSE


def _fold_fn(x: Context | None):
    return (x.same_writing or x.are_variants) if x else None


def _distinct(sol: set, x: Context | None) -> list[str]:
    fold = _fold_fn(x)
    out: list[str] = []
    for ch in sorted(sol):
        if not any(ch == o or (fold and fold(o, ch)) for o in out):
            out.append(ch)
    return out


def _group_kind(c: Cell, x: Context | None = None) -> str | None:
    g = c.group
    if not g or "form_open" in c.codes:
        return None
    why, dec = g.get("why"), g.get("decision")
    if dec in GROUP_SETTLED:
        return None
    chars = _distinct({s.get("char") for s in g.get("solvers") or [] if s.get("char")}, x)
    if why in ("ref_dissent", "coord_dissent"):
        return None if ref_missing(c.ref) else "group_ref_dissent"
    if why in ("ref_missing", "solo_weak"):
        return None
    if not chars:
        return "group_abstain"
    if len(chars) >= 2:
        return "group_conflict"
    if dec == "demote":
        return "group_ref_dissent" if "group_flow_ref_dissent" in c.codes else "group_demoted"
    if why in ("weak", "joint"):
        return "group_unconfirmed"
    return "group_abstain"


def _occluded(c: Cell) -> bool:
    return "occluded" in c.codes or bool(c.evidence.get("occluded"))


def _occluded_hard_ref(c: Cell) -> bool:
    return _occluded(c) and c.has_ref and c.ref in HARD_CHARS and (not c.char or c.char in HARD_CHARS)


def _hard_pair(c: Cell, x: Context) -> bool:
    if _occluded_hard_ref(c):
        return True
    s = {v for v in (c.ref, c.char, c.top) if v}
    if not s or not s <= HARD_CHARS:
        return False
    if len(s) >= 2:
        return True
    gid = (c.group or {}).get("id")
    top2 = [cd[0] for cd in c.cands[:2] if cd]
    return gid in HARD_GROUPS or (len(top2) == 2 and set(top2) <= HARD_CHARS)


def _near_form(c: Cell, x: Context) -> bool:
    if c.evidence.get("guard") in ("conflict", "never_match"):
        return True
    if not c.has_ref:
        return False
    others = {c.char, *(cd[0] for cd in c.cands[:3] if cd)}
    return any(o and o != c.ref and tuple(sorted((c.ref, o))) in x.near_pairs for o in others)


RULES: dict[str, Callable[[Cell, Context], bool]] = {
    "ruling_conflict": lambda c, x: "src_code_conflict" in c.codes,
    "vision_flagged": lambda c, x: "vision_flag" in c.codes,
    # 复审类（machine_changed／recheck）只在待审单上有字段（recheck／note），收尾产物里没有：永不中
    "machine_changed": lambda c, x: False,
    "recheck": lambda c, x: False,
    "manual_cells_remapped": lambda c, x: PIN_REMAPPED_DOUBT in c.codes,
    "seg_defect": lambda c, x: c.src == SELFCHECK_SRC or bool(c.codes & {"seg_defect", JIAZHU_UNEVEN, EVICT_REVIEW})
        or (c.frag and not c.ref),
    "occluded_with_ref": lambda c, x: _occluded(c) and c.has_ref and not _occluded_hard_ref(c),
    "occluded_no_ref": lambda c, x: _occluded(c) and not _occluded_hard_ref(c),
    "seg_page_unaligned": lambda c, x: c.page_kind is None and not c.ref_by_design and (
        (not c.has_ref and not ref_missing(c.ref) and x.page_noref[_page(c.id)] >= PAGE_MIN)
        or (c.has_ref and c.char != c.ref and not c.group and (c.col_agree is None or c.col_agree < COL_AGREE_MAX)
            and x.page_weak[_page(c.id)] >= PAGE_MIN)),
    "seg_col_unaligned": lambda c, x: not c.ref and not c.ref_by_design and x.col_noref[_col(c.id)] >= COL_MIN,
    "hard_pair": _hard_pair,
    "group_abstain": lambda c, x: _group_kind(c, x) == "group_abstain",
    "group_conflict": lambda c, x: _group_kind(c, x) == "group_conflict",
    "group_demoted": lambda c, x: _group_kind(c, x) == "group_demoted",
    "group_ref_dissent": lambda c, x: _group_kind(c, x) == "group_ref_dissent",
    "group_unconfirmed": lambda c, x: _group_kind(c, x) == "group_unconfirmed",
    "group_weak": lambda c, x: False,
    "variant_form_open": lambda c, x: "form_open" in c.codes,
    "glyph_pending": lambda c, x: bool(c.pua_code) and c.pua_code in x.glyph_pending,
    "ref_lacuna": lambda c, x: ref_missing(c.ref),
    "lib_missing": lambda c, x: c.lib_miss,
    "garble_gate": lambda c, x: bool(c.codes & _GARBLE) and c.has_ref,
    "ref_gap": lambda c, x: not c.ref and not c.ref_by_design,
    "variant_pair": _variant_with_ref,
    "near_form_guard": _near_form,
    "lib_sparse_agree": lambda c, x: False,
    "lib_sparse_dissent": lambda c, x: _sparse(c, x),
    "ref_ocr_diff": lambda c, x: c.ref_op == "replace" or "replace_align" in c.codes,
    "lib_unrecognized": lambda c, x: (c.has_ref and c.char == c.ref) or (c.ref_by_design and not c.has_ref),
    "ref_final_diff": lambda c, x: c.has_ref and c.char != c.ref,
}


def lib_missing_kind(c: Cell, ctx: Context | None) -> str:
    if not c.has_ref:
        return "ref_blank" if not c.ref else ""
    if ctx is None or ctx.lib_split is None:
        return ""
    own, borrowed = ctx.lib_split(c.ref)
    return "own_has" if own else ("own_zero_borrow_has" if borrowed else "all_zero")


def lib_unrecognized_kind(c: Cell, ctx: Context | None = None) -> str:
    if c.lib_miss:
        return "lib_diff"
    if c.ref_by_design and not c.has_ref:
        h = (c.evidence or {}).get("human_unbound") or {}
        return "human_unbound" if "human_unbound" in c.codes and h.get("char") and h.get("char") != c.char else "no_ref"
    if not c.cands or c.top != c.ref:
        return "lib_other"
    h = (c.evidence or {}).get("human_unbound") or {}
    if "human_unbound" in c.codes and h.get("char") and h.get("char") != c.char:
        return "human_unbound"
    if c.codes - REF_LIB_COORD_OK_CODES:
        return "doubt_blocked"
    top = float(c.cands[0][1])
    if top < LIB_UNREC_COV:
        return "low_cov"
    same = (ctx.are_variants if ctx is not None and ctx.are_variants else (lambda a, b: False))
    if any(x and x != c.ref and not same(c.ref, x) and top - float(v) < LIB_UNREC_GAP for x, v, *_ in c.cands[1:6]):
        return "near_rival"
    return "clear"


def detail_of(reason: str, c: Cell, ctx: Context | None = None) -> str:
    """给人看的一点细节（字对、组 id），不是判定依据；格式同 manager `detail_of`（只含第四步名下的原因）。
    读者要的依据（命中哪条通道／护栏、原标注、事件 id）在格的 `evidence`／`doubts` 里，这里只写这一格落在哪。"""
    if reason == "lib_missing":
        k = lib_missing_kind(c, ctx)
        return f"{k}:{c.ref or ''}" if k else (c.ref or "")
    if reason.startswith("group_") and c.group:
        mode = c.group.get("mode")
        return f"{c.group.get('id') or ''}:{mode}" if mode in GROUP_SCENES else str(c.group.get("id") or "")
    if reason in ("hard_pair", "near_form_guard", "variant_pair"):
        return "/".join(sorted({v for v in (c.ref, c.char, c.top) if v}))
    if reason in ("ref_ocr_diff", "ref_final_diff"):
        return f"{c.ref or ''}>{c.char or ''}"
    if reason == "glyph_pending":
        return c.pua_code or ""
    if reason == "ref_lacuna" and c.ref and any(0xE000 <= ord(x) <= 0xF8FF or ord(x) >= 0xF0000 for x in c.ref):
        return "/".join(f"U+{ord(x):04X}" for x in c.ref)
    if reason == "ruling_conflict" and "human_unbound" in c.codes:
        h = (c.evidence or {}).get("human_unbound") or {}
        return f"human_unbound:{h.get('char') or ''}>{c.char or ''}"
    return ""


def classify(c: Cell, ctx: Context) -> str:
    """一格 → 原因名（按 priority 第一个命中的）；都不中 `unknown`。逐句同 manager `classify`。"""
    for r in _ordered():
        rule = RULES.get(r)
        if not (rule and rule(c, ctx)):
            continue
        if r == "lib_sparse_dissent" and lib_own_n(c, ctx) == 0:
            return "lib_missing"
        if r == "lib_missing":
            if not c.has_ref:
                continue
            n = lib_own_n(c, ctx)
            if n is not None and n >= 1:
                if n <= LIB_SPARSE:
                    return "lib_sparse_dissent"
                if c.codes & _GARBLE:
                    return "garble_gate"
                r = "lib_unrecognized"
        if r == "lib_unrecognized" and lib_unrecognized_kind(c, ctx) == "human_unbound":
            return "ruling_conflict"
        if r == "lib_unrecognized" and c.bleed and lib_unrecognized_kind(c, ctx) == "lib_diff":
            return "seg_defect"
        return r
    return "unknown"


# ── 读本页的层 ────────────────────────────────────────────────────────

def _dump(ctx, kind: str, page: int) -> dict | None:
    from .decide import _opt
    pr = _opt(ctx, kind, page)
    if pr is None:
        return None
    return pr.model_dump(mode="json") if hasattr(pr, "model_dump") else pr


def _align_for_seed(alt_cols, align: dict | None) -> dict | None:
    """史記 `alt_cut`：改用备选切法的列，格号与现役对位不对应，这些列改读 align_ref `alt_draft`（同 manager `align_for_seed`）。"""
    if not align:
        return align
    cols = set(alt_cols or align.get("alt_cols") or [])
    draft = align.get("alt_draft") or {}
    if not cols or not draft:
        return align
    col_of = lambda cid: int(cid.split(":")[2])  # noqa: E731
    out = dict(align)
    out["chars"] = [c for c in align.get("chars", []) if col_of(c["id"]) not in cols]
    out["coord"] = [c for c in align.get("coord") or [] if col_of(c["id"]) not in cols] + \
                   [c for c in draft.get("coord") or [] if col_of(c["id"]) in cols]
    return out


def _page_kind(ctx, page: int) -> str | None:
    bg = _dump(ctx, "border_detect_gate_manifest", page) or {}
    if bg.get("page_type") and bg["page_type"] != "body":
        return str(bg["page_type"])
    rs = _dump(ctx, "cells", page) or {}
    if any("roster" in (c.get("flags") or []) for c in rs.get("columns") or []):
        return "roster"
    return None


def _ref_by_design(align: dict | None) -> bool:
    ar = align or {}
    if ar.get("ref_kind") == "none":
        return True
    return any(n in str(ar.get("note") or "") for n in NOREF_NOTES)


def _shrink_sets(shr: dict | None) -> tuple[set[str], set[str]]:
    """(碎片格 id, boundary_ink 旗的格 id)。"""
    shr = shr or {}
    bleed = {ch["id"] for key in ("columns", "alt_columns") for col in shr.get(key) or []
             for ch in col.get("chars") or [] if "boundary_ink" in (ch.get("flags") or [])}
    boxes: dict[str, tuple[float, float, bool]] = {}
    for key in ("columns", "alt_columns"):
        for col in shr.get(key) or []:
            for ch in col.get("chars") or []:
                w, h = ch.get("width"), ch.get("height")
                if w and h and ch.get("id") not in boxes:
                    boxes[ch["id"]] = (float(w), float(h), ch.get("step3_kind") == "jiazhu")
    med: dict[bool, float] = {}
    for jz in (False, True):
        v = sorted((w * h) ** .5 for w, h, j in boxes.values() if j == jz)
        if len(v) >= 5:
            med[jz] = v[len(v) // 2]
    frag = set()
    for cid, (w, h, jz) in boxes.items():
        if jz in med and ((w * h) ** .5 < FRAG_REL * med[jz] or min(w, h) / max(w, h) < FRAG_ASPECT):
            frag.add(cid)
    return frag, bleed


def page_cells(ctx, page: int, page_admit) -> dict[str, Cell]:
    """本页没放行的格（排除名单除外）→ `Cell`。读法同 manager `book_cells`，只是 `seed` 取刚算出的 `page_admit`。"""
    seed = page_admit.model_dump(mode="json") if hasattr(page_admit, "model_dump") else page_admit
    align = _align_for_seed(seed.get("alt_cols"), _dump(ctx, "align_ref", page)) or {}
    gm = _dump(ctx, "glyph_match", page) or {}
    ref = {c["id"]: (c.get("align_char"), c.get("align_op")) for c in align.get("chars", [])}
    for c in align.get("coord") or []:
        if c.get("ref_char") and c["id"] not in ref:
            ref[c["id"]] = (c["ref_char"], "coord")
    cands = {c["id"]: c.get("candidates") or [] for col in gm.get("columns", []) for c in col.get("chars", [])}
    kind = _page_kind(ctx, page)
    by_design = _ref_by_design(align)
    frags, bleeds = _shrink_sets(_dump(ctx, "char_index", page))
    rs = _dump(ctx, "cells", page) or {}
    remap_cols = {int(c["col"]) for c in rs.get("columns") or [] if PIN_REMAPPED_DOUBT in (c.get("flags") or [])}
    out: dict[str, Cell] = {}
    for col in seed.get("columns", []):
        hit = [ch.get("char") == ref[ch["id"]][0] for ch in col.get("chars", [])
               if "excluded" not in (ch.get("doubts") or []) and ref.get(ch["id"], (None,))[0]
               and not ref_missing(ref[ch["id"]][0])]
        agree = sum(hit) / len(hit) if hit else None
        remap = int(col.get("col", -1)) in remap_cols
        for ch in col.get("chars", []):
            if (ch.get("admit") and not remap) or "excluded" in (ch.get("doubts") or []):
                continue
            cid = ch["id"]
            r, op = ref.get(cid, (None, None))
            out[cid] = Cell(id=cid, char=ch.get("char"), ref=r, ref_op=op, cands=cands.get(cid, []),
                            doubts=list(ch.get("doubts") or []) + ([PIN_REMAPPED_DOUBT] if remap else []),
                            evidence=dict(ch.get("evidence") or {}),
                            pua_code=(ch.get("evidence") or {}).get("pua_code") or ch.get("pua_code"),
                            col_agree=agree, page_kind=kind, ref_by_design=by_design,
                            frag=cid in frags, bleed=cid in bleeds)
    return out


# ── 书级查表（字形库刻例数、异体表、形近表、待收字）──────────────────────

def _db_ro(p: Path):
    if not p.exists() or p.stat().st_size == 0:
        return None
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)


@lru_cache(maxsize=4)
def lib_own_counts(glyph_db: str) -> Callable[[str], int] | None:
    """字形库 → 每字**本书版本**刻例数（`glyphs.n_confirmed`，`edition_tag`＝`meta.book_edition`；老库求和）。同 manager `lib_own_counts`。"""
    con = _db_ro(Path(glyph_db))
    if con is None:
        return None
    n: Counter = Counter()
    try:
        row = None
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone():
            row = con.execute("SELECT value FROM meta WHERE key='book_edition'").fetchone()
        if row and row[0]:
            q = con.execute("select char, sum(n_confirmed) from glyphs where edition_tag=? group by char", (row[0],))
        else:
            q = con.execute("select char, sum(n_confirmed) from glyphs group by char")
        for ch, k in q:
            n[ch] += k or 0
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return lambda ch: n.get(ch, 0)


@lru_cache(maxsize=4)
def lib_split_counts(glyph_db: str) -> Callable[[str], tuple[int, int]] | None:
    """字形库 → 字 → (本书刻例数, 借来刻例数)，按 exemplars 数。同 manager `lib_split_counts`。"""
    con = _db_ro(Path(glyph_db))
    if con is None:
        return None
    own: Counter = Counter()
    bor: Counter = Counter()
    try:
        has_b = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='borrowed'").fetchone()
        flag = ("e.instance_id IN (SELECT instance_id FROM borrowed)" if has_b else "0")
        for ch, b, k in con.execute(
                f"""SELECT g.char, {flag} AS b, count(*) FROM exemplars e JOIN glyphs g USING(glyph_id)
                    JOIN instances i USING(instance_id) JOIN sources s USING(source_id)
                    WHERE s.kind != 'font' GROUP BY g.char, b"""):
            (bor if b else own)[ch] += k
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return lambda ch: (own.get(ch, 0), bor.get(ch, 0))


@lru_cache(maxsize=1)
def _same_writing() -> Callable[[str, str], bool] | None:
    try:
        from ..groups import registry as groups_registry
        sets = [frozenset(p.forms) for p in groups_registry.PROVISIONAL.values()] + list(_EXTRA_SAME_WRITING)
    except Exception:  # noqa: BLE001
        return None
    return lambda a, b: a == b or any(a in f and b in f for f in sets)


@lru_cache(maxsize=1)
def _near_pairs() -> frozenset:
    try:
        from ..clustering.confusable import registry_pairs
        pairs = registry_pairs("hand")
    except Exception:  # noqa: BLE001
        try:
            from ..clustering.match import NEVER_MATCH_FAMILIES
            pairs = NEVER_MATCH_FAMILIES
        except Exception:  # noqa: BLE001
            return frozenset()
    return frozenset(tuple(sorted(p)) for p in pairs if len(p) == 2)


@lru_cache(maxsize=1)
def _edge_tier():
    try:
        from ..variants import edge_tier
        return edge_tier
    except Exception:  # noqa: BLE001
        return None


@lru_cache(maxsize=1)
def _are_variants():
    try:
        from ..variants import are_variants
        return are_variants
    except Exception:  # noqa: BLE001
        return None


def _glyph_pending() -> frozenset[str]:
    try:
        from ..core.workspace import data_root
        f = Path(data_root()).joinpath("config", "pua", "glyph_pending_codes.json")
        return frozenset(json.loads(f.read_text(encoding="utf-8")).get("codes") or [])
    except Exception:  # noqa: BLE001
        return frozenset()


# ── 对外 ──────────────────────────────────────────────────────────────

def form_src_of(rec) -> str | None:
    """选形来源：`human`（人裁）｜`code_table`（私用码表改字）｜`group`（字组流程）｜`ref`（整理本字）｜`lib`（字形库）；没放字的格 None。"""
    if not getattr(rec, "char", None) or rec.char == "□":
        return None
    ev = rec.evidence or {}
    ch = rec.channel or ""
    if rec.provenance == "human" or ch == "human":
        return "human"
    if ch == "code_table" or "code_table" in ev:
        return "code_table"
    if rec.admit and ("group" in ev or "group" in ch or "fold" in ch):
        return "group"
    if rec.admit and (rec.provenance in ("align", "context") or "ref" in ch or "align" in ch):
        return "ref"
    return "lib"


def stamp_page(ctx, page: int, page_admit, *, glyph_db: str | None = None) -> Counter:
    """给本页每格写 `pending_reason`／`pending_reason_detail`／`form_src`（就地改 `page_admit`），返回计数。

    只写第四步名下的原因，别的 None（见模块头）。`glyph_db` 缺省取工作区现行字形库。"""
    n: Counter = Counter()
    if glyph_db is None:
        from ..core.workspace import glyph_db_path
        glyph_db = str(glyph_db_path())
    cells = page_cells(ctx, page, page_admit)
    own = final_reasons_set()
    gc = _glyph_pending()
    x = build_context(list(cells.values()), are_variants=_are_variants(), edge_tier=_edge_tier(), same_writing=_same_writing(),
                      lib_split=lib_split_counts(glyph_db), lib_own=lib_own_counts(glyph_db),
                      near_pairs=_near_pairs(), glyph_pending=gc)
    for col in page_admit.columns:
        for rec in col.chars:
            rec.form_src = form_src_of(rec)
            c = cells.get(rec.id)
            if c is None:
                continue
            r = classify(c, x)
            n[r] += 1
            if r in own:
                rec.pending_reason = r
                rec.pending_reason_detail = detail_of(r, c, x) or None
    return n
