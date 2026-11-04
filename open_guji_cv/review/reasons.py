"""判一格的待审原因 `PendingReason`（A31，sheldon 2026-11-03 定）：出单时算好、写进待审单的 `pending_reason`。

取代 `review/causes.py` 的成因码（A1…I）与 `review/cards.py` 的卡片类别（`cls`）作为「为什么待审」的口径；
那两样过渡期照旧出（双写），两轮后停。判法搬自 A31 统计用的分类 v2（ai-team `按包统计人审率/classify_v2.py`），
按 `pending_reasons.yaml` 里的 `priority` 从小到大逐条试，第一条命中的就是这一格的原因；都不中＝`unknown`。

**这里只判原因，不放行、不改字、不碰任何 Step**：读 seed_admit／align_ref／glyph_match 三层产物和待审单上已有的字段，
不在任何 Step 的 `code_deps` 里，产物指纹不变。判定依据（证据）照旧是 `why[]`，不在这里。

缺事实时不猜：比如没给字形库样本数（`lib_n`），「刻例太少」这两条就判不了，落到后面的规则或 `unknown`。
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .cards import doubt_codes
from .pending_reason import PendingReason as R, specs

#: 极难形近：机器字、整理本字、库首选全落在这几个字里（sheldon 11-03：留到标点、专名阶段）
HARD_CHARS = frozenset("日曰己已巳")
#: 整理本字在字形库的刻例 ≤ 这个数算「刻例太少」
LIB_SPARSE = 2
#: 同页无对位（或弱证据）格 ≥ PAGE_MIN 算整页对不上；同列无对位 ≥ COL_MIN 算整列对不上
PAGE_MIN, COL_MIN = 10, 5
#: 「机器改判」复审格：待审单上 recheck=true 且说明以此开头（auto_cycle 出的复审清单）
MACHINE_CHANGED_NOTE = "机器改判"

_GARBLE = {"ctx_garble_shape", "shadow_veto", "ctx_garble_rare"}
_NEAR = {"near_form", "solo_confusable", "iron_confusable_ref"}
_VARIANT = {"ref_lib_variant", "variant_indirect", "replace_form", "channel_off"}


def ref_missing(ch: str | None) -> bool:
    """整理本这位是〓或缅甸文占位（没码位的生僻字）。"""
    return bool(ch) and (ch == "〓" or any(0x1000 <= ord(c) <= 0x109F for c in ch))


@dataclass
class Cell:
    """判原因要用的一格事实（都从产物或待审单来，缺就是 None／空）。"""
    id: str
    char: str | None = None
    ref: str | None = None
    ref_op: str | None = None
    cands: list = field(default_factory=list)          # 库候选 [[字, 分], …]
    doubts: list = field(default_factory=list)         # seed_admit doubts 原样
    evidence: dict = field(default_factory=dict)
    recheck: bool = False
    note: str = ""
    cls: str | None = None                             # 待审单上的旧卡片类别（老单的 seg_defect 只有这里有；11-04 起不出单）
    seg_kind: str | None = None                        # 切坏细分（单上同名字段；产物里在 evidence.seg_kind），见 SEG_KINDS

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
    """整册（或整单）层面的事实。"""
    page_noref: Counter = field(default_factory=Counter)
    page_weak: Counter = field(default_factory=Counter)
    col_noref: Counter = field(default_factory=Counter)
    lib_n: Callable[[str], int] | None = None
    are_variants: Callable[[str, str], bool] | None = None
    lib_split: Callable[[str], tuple[int, int]] | None = None   # 字 → (本书刻例数, 借来刻例数)，给 lib_missing 细分


def _page(cid: str) -> str:
    return ":".join(cid.split(":")[:-2])


def _col(cid: str) -> str:
    return ":".join(cid.split(":")[:-1])


def build_context(cells: list[Cell], lib_n=None, are_variants=None, lib_split=None) -> Context:
    ctx = Context(lib_n=lib_n, are_variants=are_variants, lib_split=lib_split)
    for c in cells:
        if not c.has_ref:
            ctx.page_noref[_page(c.id)] += 1
            if c.ref is None or not ref_missing(c.ref):
                ctx.col_noref[_col(c.id)] += 1
        elif c.char != c.ref and not c.group and "occluded" not in c.codes:
            ctx.page_weak[_page(c.id)] += 1
    return ctx


def _variant_with_ref(c: Cell, ctx: Context) -> bool:
    if c.codes & _VARIANT:
        return True
    if not (ctx.are_variants and c.has_ref and c.top and c.top != c.ref):
        return False
    return any(x and x != c.ref and ctx.are_variants(c.ref, x) for x, *_ in c.cands[:5])


def _sparse(c: Cell, ctx: Context) -> bool:
    return bool(ctx.lib_n and c.has_ref and ctx.lib_n(c.ref) <= LIB_SPARSE)


def _group_kind(c: Cell) -> R | None:
    g = c.group
    if not g:
        return None
    if "form_open" in c.codes:
        return R.GROUP_FORM_OPEN
    sol = {s.get("char") for s in g.get("solvers") or [] if s.get("char")}
    why, dec = g.get("why"), g.get("decision")
    if not sol:
        return R.GROUP_ABSTAIN
    if why in ("ref_dissent", "coord_dissent", "ref_dissent_follow"):
        return R.GROUP_REF_DISSENT
    if len(sol) > 1 or why in ("conflict", "joint"):
        return R.GROUP_CONFLICT
    if dec == "demote":
        return R.GROUP_DEMOTED
    return R.GROUP_WEAK


#: 每条原因的判法；按 yaml 的 priority 依次试。没有判法的原因（如 col_width_out_of_band 还没接）永远不中。
RULES: dict[R, Callable[[Cell, Context], bool]] = {
    R.RULING_CONFLICT: lambda c, x: "src_code_conflict" in c.codes,
    R.VISION_FLAGGED: lambda c, x: "vision_flag" in c.codes,
    R.MACHINE_CHANGED: lambda c, x: c.recheck and c.note.startswith(MACHINE_CHANGED_NOTE),
    R.RECHECK: lambda c, x: c.recheck,
    R.SEG_DEFECT: lambda c, x: c.cls == "seg_defect" or bool(c.codes & {"seg_defect", JIAZHU_UNEVEN}),
    R.OCCLUDED_WITH_REF: lambda c, x: ("occluded" in c.codes or bool(c.evidence.get("occluded"))) and c.has_ref,
    R.OCCLUDED_NO_REF: lambda c, x: "occluded" in c.codes or bool(c.evidence.get("occluded")),
    R.SEG_PAGE_UNALIGNED: lambda c, x: (not c.has_ref and x.page_noref[_page(c.id)] >= PAGE_MIN)
        or (c.has_ref and c.char != c.ref and not c.group and x.page_weak[_page(c.id)] >= PAGE_MIN),
    R.SEG_COL_UNALIGNED: lambda c, x: not c.ref and x.col_noref[_col(c.id)] >= COL_MIN,
    R.HARD_PAIR: lambda c, x: (lambda s: len(s) >= 2 and s <= HARD_CHARS)({v for v in (c.ref, c.char, c.top) if v}),
    R.GROUP_ABSTAIN: lambda c, x: _group_kind(c) is R.GROUP_ABSTAIN,
    R.GROUP_CONFLICT: lambda c, x: _group_kind(c) is R.GROUP_CONFLICT,
    R.GROUP_DEMOTED: lambda c, x: _group_kind(c) is R.GROUP_DEMOTED,
    R.GROUP_REF_DISSENT: lambda c, x: _group_kind(c) is R.GROUP_REF_DISSENT,
    R.GROUP_WEAK: lambda c, x: _group_kind(c) is R.GROUP_WEAK,
    R.GROUP_FORM_OPEN: lambda c, x: _group_kind(c) is R.GROUP_FORM_OPEN or "form_open" in c.codes,
    R.REF_LACUNA: lambda c, x: ref_missing(c.ref),
    R.LIB_MISSING: lambda c, x: c.lib_miss,
    R.GARBLE_GATE: lambda c, x: bool(c.codes & _GARBLE),
    R.REF_GAP: lambda c, x: not c.ref,
    R.VARIANT_PAIR: _variant_with_ref,
    R.NEAR_FORM_GUARD: lambda c, x: c.evidence.get("guard") in ("conflict", "never_match") or bool(c.codes & _NEAR),
    R.LIB_SPARSE_AGREE: lambda c, x: _sparse(c, x) and c.char == c.ref,
    R.LIB_SPARSE_DISSENT: lambda c, x: _sparse(c, x) and c.char != c.ref,
    R.REF_REPLACED: lambda c, x: c.ref_op == "replace" or "replace_align" in c.codes,
    R.LIB_UNRECOGNIZED: lambda c, x: c.has_ref and c.char == c.ref,
    R.REF_MISMATCH: lambda c, x: c.has_ref and c.char != c.ref,
}


def _ordered() -> list[R]:
    return sorted((r for r in R if r is not R.UNKNOWN), key=lambda r: specs()[r].priority)


#: 切坏格细分（SJ 史記第 8 轮切坏检测，11-04 定）：作 seg_defect 的 pending_reason_detail，不新增取值。
#: merged 两字并一格；clipped 字被切掉一边或半截；bleed 邻格笔画溢入；frame_residue 框线残笔当成笔画。
#: jiazhu_uneven（史記雙行小注逐步切 cv#1011，11-04 A31 定）：夹注两行分法不是 ⌈N/2⌉／⌊N/2⌋、按整理本切的格，要人核；
#: 格上带 doubt 码 `jiazhu_uneven`（或 seg_kind=jiazhu_uneven）即归 seg_defect，细分记 jiazhu_uneven。
JIAZHU_UNEVEN = "jiazhu_uneven"
SEG_KINDS = ("merged", "clipped", "bleed", "frame_residue", JIAZHU_UNEVEN)


def seg_kind_of(c: Cell) -> str:
    """切坏细分：单上的 `seg_kind` 优先，其次产物 evidence.seg_kind，再次 doubt 码 jiazhu_uneven；不在 SEG_KINDS 里的不认。"""
    k = c.seg_kind or (c.evidence or {}).get("seg_kind")
    if k in SEG_KINDS:
        return k
    return JIAZHU_UNEVEN if JIAZHU_UNEVEN in c.codes else ""


#: 「少见的字」细分（A23，sheldon 11-04 定本书字样标注归书 Project）：作 lib_missing 的 pending_reason_detail，
#: 写成 ``<细分>:<整理本字>``，不新增取值。lib_missing 的意思是「库里没有像这一格的刻例」（glyph_match verdict=diff），
#: 不等于库里没有这个字；按整理本字在本书库、借来库里各有几例分开派单：
#:   ref_blank           整理本这一位没字（语料漏字／对位问题，不是字形库的事，转 A24／书 Project）
#:   all_zero            本书、借来库都没有这个字（真缺字：首例人裁入库）
#:   own_zero_borrow_has 本书没有、借来库有（借来的字样不像这本：本书字样标注，归书 Project）
#:   own_has             本书已有这个字的刻例，这一格仍不像（多半淡印、切坏或形近：看图）
LIB_MISSING_KINDS = ("ref_blank", "all_zero", "own_zero_borrow_has", "own_has")


def lib_missing_kind(c: Cell, ctx: Context | None) -> str:
    """lib_missing 细分；没给库（``ctx.lib_split``）就不分（空串）。"""
    if not c.has_ref:
        return "ref_blank" if not c.ref else ""
    if ctx is None or ctx.lib_split is None:
        return ""
    own, borrowed = ctx.lib_split(c.ref)
    return "own_has" if own else ("own_zero_borrow_has" if borrowed else "all_zero")


def detail_of(reason: R, c: Cell, ctx: Context | None = None) -> str:
    """给人看的一点细节（字对、组 id、页号），不是判定依据。"""
    if reason is R.SEG_DEFECT:
        return seg_kind_of(c)
    if reason is R.LIB_MISSING:
        k = lib_missing_kind(c, ctx)
        return f"{k}:{c.ref or ''}" if k else (c.ref or "")
    if reason in (R.SEG_PAGE_UNALIGNED,):
        return _page(c.id)
    if reason in (R.SEG_COL_UNALIGNED,):
        return _col(c.id)
    if reason.name.startswith("GROUP_") and c.group:
        return str(c.group.get("id") or "")
    if reason in (R.HARD_PAIR, R.NEAR_FORM_GUARD, R.VARIANT_PAIR):
        return "/".join(sorted({v for v in (c.ref, c.char, c.top) if v}))
    if reason in (R.REF_REPLACED, R.REF_MISMATCH, R.LIB_SPARSE_DISSENT):
        return f"{c.ref or ''}>{c.char or ''}"
    if reason in (R.LIB_SPARSE_AGREE, R.LIB_UNRECOGNIZED):
        return c.ref or ""
    return ""


def classify(c: Cell, ctx: Context) -> R:
    """一格 → 原因。按 priority 第一个命中的；都不中 `UNKNOWN`。"""
    for r in _ordered():
        rule = RULES.get(r)
        if rule and rule(c, ctx):
            return r
    return R.UNKNOWN


# ── 读产物 ─────────────────────────────────────────────────────────────

def _load_layer(path: Path, key: str) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))[key]
    except (OSError, KeyError, ValueError):
        return None


def book_cells(products_dir, book: str) -> dict[str, Cell]:
    """全册没放行的格（排除名单除外）→ `Cell`。格号不带册前缀（同 `causes.book_causes`）。"""
    root = Path(products_dir) / book
    out: dict[str, Cell] = {}
    for f in sorted((root / "seed_admit").glob("p*.json")):
        seed = _load_layer(f, "seed_admit")
        if not seed:
            continue
        align = _load_layer(root / "align_ref" / f.name, "align_ref") or {}
        gm = _load_layer(root / "glyph_match" / f.name, "glyph_match") or {}
        ref = {c["id"]: (c.get("align_char"), c.get("align_op")) for c in align.get("chars", [])}
        for c in align.get("coord") or []:
            if c.get("ref_char") and c["id"] not in ref:
                ref[c["id"]] = (c["ref_char"], "coord")
        cands = {c["id"]: c.get("candidates") or [] for col in gm.get("columns", []) for c in col.get("chars", [])}
        for col in seed.get("columns", []):
            for ch in col.get("chars", []):
                if ch.get("admit") or "excluded" in (ch.get("doubts") or []):
                    continue
                cid = ch["id"]
                r, op = ref.get(cid, (None, None))
                out[cid.split(":", 1)[1]] = Cell(id=cid, char=ch.get("char"), ref=r, ref_op=op, cands=cands.get(cid, []),
                                                 doubts=list(ch.get("doubts") or []), evidence=dict(ch.get("evidence") or {}))
    return out


def lib_counts(glyph_db) -> Callable[[str], int] | None:
    """字形库 SQLite（`output/glyph.db`）→ 每字刻例数（`glyphs.n_confirmed` 求和）。库不在就返回 None（不猜）。"""
    import sqlite3
    p = Path(glyph_db)
    if not p.exists() or p.stat().st_size == 0:
        return None
    n: Counter = Counter()
    con = sqlite3.connect(str(p))
    try:
        for ch, k in con.execute("select char, sum(n_confirmed) from glyphs group by char"):
            n[ch] += k or 0
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return lambda ch: n.get(ch, 0)


def lib_split_counts(glyph_db) -> Callable[[str], tuple[int, int]] | None:
    """字形库 SQLite → 字 → (本书刻例数, 借来刻例数)。按 exemplars 数，借来的看 ``borrowed`` 表，字体域不算。
    库不在或读不了返回 None（不猜）。"""
    import sqlite3
    p = Path(glyph_db)
    if not p.exists() or p.stat().st_size == 0:
        return None
    own: Counter = Counter()
    bor: Counter = Counter()
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
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


def _default_are_variants():
    try:
        from ..variants import are_variants as _av
        return _av
    except Exception:  # noqa: BLE001 —— 异体表读不到就不判异体，落到后面的规则
        return None


def reasons_for_pending(doc: dict, products_dir, book: str, *, glyph_db=None, are_variants=None) -> dict[str, tuple[R, str]]:
    """待审单 `doc` 的每格 → (原因, 细节)。产物里找不到的格（如复审格）只用单上的字段判，判不出就 `unknown`。"""
    if are_variants is None:
        are_variants = _default_are_variants()
    prod = book_cells(products_dir, book)
    cells: list[Cell] = []
    for x in doc.get("cells", []):
        key = x["cell"].split(":", 1)[1] if x["cell"].count(":") >= 3 else x["cell"]
        c = prod.get(key) or Cell(id=f"{book}:{key}", char=None, ref=((x.get("ref") or {}).get("c") or x.get("refc")),
                                  doubts=list(x.get("why") or []))
        c.recheck, c.note, c.cls = bool(x.get("recheck")), str(x.get("note") or ""), x.get("cls")
        if x.get("seg_kind"):
            c.seg_kind = str(x["seg_kind"])
        cells.append(c)
    ctx = build_context(cells, lib_n=lib_counts(glyph_db) if glyph_db else None, are_variants=are_variants,
                        lib_split=lib_split_counts(glyph_db) if glyph_db else None)
    out = {}
    for x, c in zip(doc.get("cells", []), cells):
        r = classify(c, ctx)
        out[x["cell"]] = (r, detail_of(r, c, ctx))
    return out


def stamp(doc: dict, reasons: dict[str, tuple[R, str]]) -> Counter:
    """把原因写进待审单每格：`pending_reason`（必有，判不出 `unknown`）、`pending_reason_detail`（有才写）。返回计数。"""
    n: Counter = Counter()
    for x in doc.get("cells", []):
        r, d = reasons.get(x["cell"], (R.UNKNOWN, ""))
        x["pending_reason"] = r.value
        if d:
            x["pending_reason_detail"] = d
        else:
            x.pop("pending_reason_detail", None)
        n[r.value] += 1
    return n


def stamp_cards(cards: list[dict], cells: list[Cell], *, glyph_db=None, are_variants=None) -> None:
    """控制台待审卡（`review/cards.py`）每张带 `pending_reason`／`pending_reason_detail`，与出单同一套判法。

    `cells` 与 `cards` 一一对应；整页／整列对不上按这批卡自己数（与待审单按整单数同口径）。"""
    if are_variants is None:
        are_variants = _default_are_variants()
    ctx = build_context(cells, lib_n=lib_counts(glyph_db) if glyph_db else None, are_variants=are_variants,
                        lib_split=lib_split_counts(glyph_db) if glyph_db else None)
    for card, c in zip(cards, cells):
        r = classify(c, ctx)
        card["pending_reason"] = r.value
        d = detail_of(r, c, ctx)
        if d:
            card["pending_reason_detail"] = d
