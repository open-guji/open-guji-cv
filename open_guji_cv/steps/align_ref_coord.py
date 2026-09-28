"""Step5-d 按坐标对位（`align: coord`，2026-09-28，D 道 overview#195）。

## 为什么要有这一路

`align_ref` 的现役对位是「整页定字串 8-gram 锚定 + `difflib`」：拿**认出来的字**去
对整理本。整页认字烂掉的地方——用户点名的 vol03 p3，一枚大印章压住半页，背景满是
噪点——锚定串全是错字，整页锚不上，那一块的格就一个整理本字都拿不到，人裁只能对着
噪点一格一格猜。

四庫總目的整理本（光盘版 `zongmu_wenyuange_wikisource.txt`，以及 P 道正在导的
daizhige 逐列本）是**逐行分开**的：一行 = 刻本一列，版式 21 格/列。所以只要
①知道这一列对的是整理本哪一行、②Step3 切出来的格与这一行的字数对得上，就可以
**按位置**把整理本的字一格一格配上去，不依赖这一格认得出认不出。

## 算法

1. **行表**：整理本逐行解析成「单元」序列——正文一字一单元；`<…>` 双行小注按
   阅读顺序切成右行 a（前一半，向上取整）/左行 b（后一半），每一行（a,b）是一个
   单元，与 Step3 的夹注格 `slot a/b` 同构。标点、空白丢掉。
2. **定窗**：先用现役 8-gram 投票（`_raw_vote_clusters`，不设票数下限）找页在语料
   里的大致位置；一票都没有就退到 4-gram 直接在语料里 `find`（只在锚不上的少数
   页走，4-gram 在全文里 `find` 几十次，毫秒级）。偏移换算成行号，前后各留十几行。
3. **页内列→行**：窗内每一行与每一列的锚定载体（`slots_from_evidence` 同一口径）
   算字对（bigram）重合数，按「第 i 个非空列 ↔ 第 d+i 行」对整页投 d。最高票要
   ≥ `COORD_MIN_PAGE_VOTES`、且压过次高票 1.5 倍，才认这一页的列行对应。
4. **列内按坐标配字**：这一列的格按阅读顺序排成单元（正文格一单元、同一 slot 的
   夹注 a/b 合一单元），**几何行号** `g = 格中心 y / period + 0.5`（1 起）。在格序列
   里找一段**长度正好等于该行单元数、类型逐个对得上**（正文↔正文、夹注↔夹注）的连续
   格，要求这段格的几何行号逐格递增 1（残差 ≤ `COORD_MAX_RESID` 行），段外多出来的
   格（印章/污点切出来的假格）几何上必须落在这段文字的**范围之外**——它们对的是
   整理本的空格位，记 `ref_char=""`。满足的段不止一个时（假格与字格混在一起），
   用载体字与整理本字的吻合数挑，最高者要比次高者多 ≥1，否则判「有歧义」退回。
5. **格数对不上的列退回现有锚定**（`coord_fallback` 记原因），本路不给任何字。

几何上逐格配位只用格的位置；载体字只用来 (a) 定页在语料里的位置 (b) 在几个几何上
都成立的配法里挑一个。所以印章把字压得认不出时，只要这一列有两三个字认得出、
或者这一列根本没有假格，就能配上。

## 与现役对位的关系

**不改现役 `chars`**（8-gram + difflib 的结果逐字节不变），坐标对位另记在
`PageAlignRef.coord`。下游只有三处读它：
- `seed_admit` 的 `occluded`（印章污损）格：默认字取坐标对位的字（没有才退到
  现役对位字）；
- 人审卡 `ref`：现役对位没给字的格，用坐标对位的字补上显示；
- 本模块的对照报告（坐标对位 vs 现役对位 一致/不一致格数）。

**不进任何准入通道**——`admission_decision` 读的仍然只是现役 `chars`。所以打开这一路
不会让任何一格从「待审」变成「放行」（验收口径：其余册 admit 只许减少）。
"""

from __future__ import annotations

import bisect
import math
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

#: 与 `align_ref._NON_HAN_RE` 同一口径：8-gram 索引/`_corpus_text` 只留这一段汉字，
#: 偏移 → 行号的换算必须按同一把尺子数。
_HAN_RE = re.compile(r"[一-鿿]")
_NOTE_OPEN, _NOTE_CLOSE = "<", ">"

COORD_MIN_PAGE_VOTES = 6       # 页级列→行投票的最低票数（字对重合总数）
COORD_PAGE_DOMINANCE = 1.5     # 最高票 / 次高票
COORD_MAX_RESID = 0.45         # 列内几何行号的最大残差（单位：行）
COORD_OUTSIDE_MARGIN = 0.5     # 段外假格离文字范围至少多远（行）
COORD_WINDOW_LINES = 14        # 定窗时锚点前后各留几行
COORD_MAX_CANDIDATE_RUNS = 64  # 一列里几何上都成立的配法上限（防病态列）


def is_text_char(ch: str) -> bool:
    """整理本里算「一个字位」的字符：CJK/字母类、数字类（〇）、私用区、`□`（阙字）。"""
    if ch == "□":
        return True
    cat = unicodedata.category(ch)
    return cat[0] in ("L", "N") or cat == "Co"


@dataclass(frozen=True)
class Unit:
    """整理本一行里的一个字位单元。`kind="c"` 正文一字；`kind="n"` 夹注一行（a 右、b 左）。"""
    kind: str
    a: str
    b: str = ""


@dataclass
class RefLine:
    idx: int                 # 在非空行表里的序号
    units: list[Unit]
    han_start: int           # 本行在 `_corpus_text`（只留 [一-鿿]）里的起始偏移
    text: str = ""           # 本行全部字（正文 + 夹注 a + 夹注 b，阅读顺序），算重合用

    @property
    def n(self) -> int:
        return len(self.units)


def parse_lines(raw: str) -> list[RefLine]:
    """整理本原文 → 非空行表。跨行的 `<…>`（夹注跨列）按行各自切 a/b。"""
    out: list[RefLine] = []
    han = 0
    in_note = False
    for line in raw.splitlines():
        units: list[Unit] = []
        note: list[str] = []
        text: list[str] = []

        def flush_note():
            k = math.ceil(len(note) / 2)
            a, b = note[:k], note[k:]
            for i in range(k):
                units.append(Unit("n", a[i], b[i] if i < len(b) else ""))
            text.extend(note)
            note.clear()

        for ch in line:
            if ch == _NOTE_OPEN:
                in_note = True
                continue
            if ch == _NOTE_CLOSE:
                flush_note()
                in_note = False
                continue
            if not is_text_char(ch):
                continue
            if in_note:
                note.append(ch)
            else:
                units.append(Unit("c", ch))
                text.append(ch)
        if note:
            flush_note()
        n_han = len(_HAN_RE.findall(line))
        if units:
            out.append(RefLine(idx=len(out), units=units, han_start=han, text="".join(text)))
        han += n_han
    return out


@lru_cache(maxsize=4)
def ref_lines(path: str) -> tuple[list[RefLine], list[int]]:
    p = Path(path)
    if not p.exists():
        return [], []
    lines = parse_lines(p.read_text(encoding="utf-8"))
    return lines, [ln.han_start for ln in lines]


def line_at(starts: list[int], offset: int) -> int:
    return max(0, bisect.bisect_right(starts, offset) - 1)


# ── 定窗 ────────────────────────────────────────────────────────────────
def scan_offset(query: str, text: str, gram: int = 4, step: int = 2,
                max_hits: int = 40, pool: int = 8) -> tuple[int | None, int]:
    """n-gram 直接在语料里 `find` 投票（锚不上的页才走）。返回 (偏移, 峰簇票数)。

    常见 n-gram（命中超过 `max_hits` 处）不投票——套语到处都是，只会把票摊平。"""
    from collections import Counter
    votes: Counter[int] = Counter()
    for i in range(0, max(0, len(query) - gram + 1), step):
        g = query[i:i + gram]
        hits: list[int] = []
        pos = text.find(g)
        while pos >= 0 and len(hits) <= max_hits:
            hits.append(pos)
            pos = text.find(g, pos + 1)
        if not hits or len(hits) > max_hits:
            continue
        for h in hits:
            votes[h - i] += 1
    if not votes:
        return None, 0
    best, best_v = None, 0
    for o in votes:
        v = sum(votes[o2] for o2 in range(o - pool, o + pool + 1) if o2 in votes)
        if v > best_v or (v == best_v and best is not None and o < best):
            best, best_v = o, v
    return best, best_v


# ── 页内列 → 行 ─────────────────────────────────────────────────────────
def _bigrams(s: str) -> set[str]:
    return {s[i:i + 2] for i in range(len(s) - 1)}


def line_sim(carrier: str, line: RefLine) -> int:
    """列载体串与整理本一行的字对（bigram）重合数。"""
    if len(carrier) < 2 or line.n == 0:
        return 0
    return len(_bigrams(carrier) & _bigrams(line.text))


@dataclass
class PageMap:
    base: int | None                          # 第 0 个非空列对应的行号（`lines` 下标）
    votes: int = 0
    runner_up: int = 0
    col_line: dict[int, int] = field(default_factory=dict)
    note: str = ""


def map_columns(carriers: list[tuple[int, str]], lines: list[RefLine],
                lo: int, hi: int) -> PageMap:
    """`carriers`：[(列号, 该列载体串)]，只含非空列、按列号升序（= 阅读顺序）。"""
    if not carriers:
        return PageMap(None, note="没有非空列")
    lo, hi = max(0, lo), min(len(lines), hi)
    sims = {(ci, li): line_sim(c, lines[li])
            for ci, (_col, c) in enumerate(carriers) for li in range(lo, hi)}
    scores: list[tuple[int, int]] = []
    for d in range(lo, hi):
        s = sum(sims.get((ci, d + ci), 0) for ci in range(len(carriers)))
        scores.append((s, d))
    if not scores:
        return PageMap(None, note="窗口内没有整理本行")
    scores.sort(key=lambda t: (-t[0], t[1]))
    best_s, best_d = scores[0]
    second = next((s for s, d in scores[1:] if d != best_d), 0)
    pm = PageMap(best_d, best_s, second)
    if best_s < COORD_MIN_PAGE_VOTES:
        pm.base, pm.note = None, f"列行投票太少（{best_s}）"
        return pm
    if second and best_s < COORD_PAGE_DOMINANCE * second:
        pm.base, pm.note = None, f"列行投票无优势（{best_s} vs {second}）"
        return pm
    for ci, (col, _c) in enumerate(carriers):
        li = best_d + ci
        if li >= len(lines):
            continue
        # 这一列自己明显更像别的行 → 不认（光盘版与刻本分行不一致时的保险）
        own = sims.get((ci, li), 0)
        other = max((sims.get((ci, l2), 0) for l2 in range(lo, hi) if l2 != li), default=0)
        if other >= own + 3 and other >= 2 * max(own, 1):
            continue
        pm.col_line[col] = li
    return pm


# ── 列内按坐标配字 ──────────────────────────────────────────────────────
@dataclass
class CellUnit:
    """列内一个格单元：正文格一个；同一 slot 的夹注 a/b 合成一个。"""
    kind: str                 # "c" | "n"
    slot: int
    g: float                  # 几何行号（1 起）
    ids: dict[str, str]       # {"": id} 或 {"a": id, "b": id}
    carrier: dict[str, str]   # 同上，载体字


@dataclass
class ColumnCoord:
    ok: bool
    note: str = ""
    recs: list[tuple[str, int, str | None, str, float]] = field(default_factory=list)
    """[(id, slot, sub, ref_char, g)]；`ref_char=""` = 整理本这一位是空格（假格）。"""
    agree: int = 0


def _agree(u: CellUnit, ref: Unit) -> int:
    if u.kind == "c":
        return int(u.carrier.get("", "") == ref.a)
    return int(u.carrier.get("a", "") == ref.a) + int(bool(ref.b) and u.carrier.get("b", "") == ref.b)


def coord_column(units: list[CellUnit], line: RefLine) -> ColumnCoord:
    L = line.n
    if L == 0:
        return ColumnCoord(False, "整理本行为空")
    if len(units) < L:
        return ColumnCoord(False, f"格数少于整理本字数（{len(units)} < {L}）")
    kinds = [r.kind for r in line.units]
    cands: list[tuple[int, int, float]] = []   # (吻合数, j, b)
    for j in range(0, len(units) - L + 1):
        run = units[j:j + L]
        if [u.kind for u in run] != kinds:
            continue
        resid = sorted(u.g - i for i, u in enumerate(run))
        b = resid[len(resid) // 2]
        if max(abs(r - b) for r in resid) > COORD_MAX_RESID:
            continue
        top, bot = b - COORD_OUTSIDE_MARGIN, b + (L - 1) + COORD_OUTSIDE_MARGIN
        extras = units[:j] + units[j + L:]
        if any(top < u.g < bot for u in extras):
            continue
        cands.append((sum(_agree(u, r) for u, r in zip(run, line.units)), j, b))
        if len(cands) > COORD_MAX_CANDIDATE_RUNS:
            return ColumnCoord(False, "几何上成立的配法太多")
    if not cands:
        return ColumnCoord(False, f"格与整理本 {L} 字对不上（格数/类型/几何）")
    cands.sort(key=lambda t: (-t[0], t[1]))
    if len(cands) > 1 and cands[0][0] - cands[1][0] < 1:
        return ColumnCoord(False, f"有歧义（{len(cands)} 种配法，载体吻合 {cands[0][0]} vs {cands[1][0]}）")
    agree, j, _b = cands[0]
    recs: list[tuple[str, int, str | None, str, float]] = []
    for i, u in enumerate(units):
        ref = line.units[i - j] if j <= i < j + L else None
        if u.kind == "c":
            recs.append((u.ids[""], u.slot, None, ref.a if ref else "", u.g))
        else:
            for sub in ("a", "b"):
                if sub in u.ids:
                    ch = (ref.a if sub == "a" else ref.b) if ref else ""
                    recs.append((u.ids[sub], u.slot, sub, ch, u.g))
    return ColumnCoord(True, recs=recs, agree=agree)


def column_units(book: str, page: int, col: int, match_col, cells_col,
                 carrier_of) -> list[CellUnit]:
    """`glyph_match` 的一列（字格）+ `cells` 的一列（几何）→ 阅读顺序的格单元。

    只收 `glyph_match` 里有的格（Step3 判 blank 的格不在里面）；几何取 `cells`
    同 (slot, sub) 的 y 中心。查不到几何的格让整列放弃（返回空）。"""
    if cells_col is None or not cells_col.period:
        return []
    per = float(cells_col.period)
    top = float(cells_col.border_top or 0.0)
    geo = {(c.slot, c.sub or ""): ((c.y0 + c.y1) / 2.0 - top) / per + 0.5
           for c in cells_col.cells}
    by_slot: dict[int, CellUnit] = {}
    order: list[int] = []
    for r in match_col.chars:
        sub = r.sub or ""
        g = geo.get((r.slot, sub))
        if g is None:
            return []
        if sub:
            u = by_slot.get(r.slot)
            if u is None:
                u = CellUnit("n", r.slot, g, {}, {})
                by_slot[r.slot] = u
                order.append(r.slot)
            u.ids[sub] = r.id
            u.carrier[sub] = carrier_of(r.id) or ""
        else:
            by_slot[r.slot] = CellUnit("c", r.slot, g, {"": r.id}, {"": carrier_of(r.id) or ""})
            order.append(r.slot)
    units = [by_slot[s] for s in order]
    units.sort(key=lambda u: u.g)
    return units
